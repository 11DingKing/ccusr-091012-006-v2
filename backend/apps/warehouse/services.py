"""
调拨与库存台账服务

数量守恒约定（针对每一条调拨明细 TransferItem）：
    applied = cancelled + pending_shipment + shipped
    shipped = in_transit + disputed + received + returned + lost
其中：
    pending_shipment = applied - cancelled - shipped   （仍预留于起点）
    in_transit       = shipped - received - returned - lost - disputed

库存账本约定：
    StockBalance.available_quantity  可用数量
    StockBalance.reserved_quantity   已预留数量（调拨申请占用）
    在途与待调查数量不隶属于任何保管点，记录在调拨明细上；
    Goods.quantity 为全机构在册总量 = Σ(available+reserved) + 在途 + 待调查，
    调拨本身不改变它，仅差异核销（lost）会使其减少。
"""
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import BusinessException, NotFoundException
from .models import (
    Discrepancy, Goods, IdempotencyRecord, SealChange, StockBalance,
    TransferEvent, TransferItem, TransferOrder,
)

logger = logging.getLogger('apps')

RECEIVE_IDEMPOTENCY_SCOPE = 'transfer-receive'


def _get_balance(point, goods):
    """获取（必要时创建）保管点库存余额行。"""
    balance, _ = StockBalance.objects.get_or_create(
        custody_point=point, goods=goods,
        defaults={'available_quantity': Decimal('0'), 'reserved_quantity': Decimal('0')},
    )
    return balance


def _record_event(order, event_type, actor, detail):
    """写入调拨事件台账。detail 中的数量须已转为字符串。"""
    TransferEvent.objects.create(
        transfer=order, event_type=event_type, actor=actor, detail=detail,
    )


def _refresh_status(order):
    """根据明细数量重算调拨单状态。"""
    items = list(order.items.all())
    shipped_total = sum((i.shipped_quantity for i in items), Decimal('0'))
    settled = all(
        i.pending_shipment_quantity == 0
        and i.in_transit_quantity == 0
        and i.disputed_quantity == 0
        for i in items
    )
    if settled:
        if shipped_total == 0:
            order.status = 'cancelled'
        else:
            order.status = 'completed'
            if order.completed_at is None:
                order.completed_at = timezone.now()
    else:
        order.status = 'in_transit' if shipped_total > 0 else 'pending'


def _get_order(order_id):
    try:
        return TransferOrder.objects.select_for_update().get(pk=order_id)
    except TransferOrder.DoesNotExist:
        raise NotFoundException('调拨单不存在')


def _resolve_lines(order, lines, max_quantity_getter, empty_message, exceed_message):
    """将请求行解析为 (item, quantity) 列表并校验上限。

    lines 为空时默认取全部可处理数量。
    """
    item_map = {item.pk: item for item in order.items.all()}
    if not lines:
        resolved = [
            (item, max_quantity_getter(item))
            for item in item_map.values()
            if max_quantity_getter(item) > 0
        ]
        if not resolved:
            raise BusinessException(empty_message)
        return resolved

    resolved = []
    for line in lines:
        item = item_map.get(line['item_id'])
        if item is None:
            raise BusinessException('调拨明细不属于该调拨单')
        quantity = line['quantity']
        if quantity <= 0:
            raise BusinessException('数量必须大于0')
        if quantity > max_quantity_getter(item):
            raise BusinessException(f'货物「{item.goods.name}」{exceed_message}')
        resolved.append((item, quantity))
    return resolved


def _generate_transfer_no():
    prefix = 'TR' + timezone.now().strftime('%Y%m%d')
    count = TransferOrder.objects.filter(transfer_no__startswith=prefix).count()
    return f'{prefix}-{count + 1:04d}'


def create_transfer(*, user, origin_point, destination_point, items, remark=''):
    """调拨申请：在起点冻结库存（可用 -> 已预留）。"""
    if origin_point.pk == destination_point.pk:
        raise BusinessException('起点与终点不能是同一保管点')
    if not items:
        raise BusinessException('调拨明细不能为空')

    seen_goods = set()
    goods_lines = []
    for line in items:
        goods_id = line['goods']
        quantity = line['quantity']
        if goods_id in seen_goods:
            raise BusinessException('同一货物在一张调拨单中只能出现一次')
        seen_goods.add(goods_id)
        try:
            goods = Goods.objects.get(pk=goods_id, is_active=True)
        except Goods.DoesNotExist:
            raise BusinessException('货物不存在或已停用')
        if quantity <= 0:
            raise BusinessException('调拨数量必须大于0')
        goods_lines.append((goods, quantity))

    # SQLite 写事务串行化，以下校验与扣减在同一事务中原子完成
    for attempt in range(3):
        try:
            with transaction.atomic():
                balances = []
                for goods, quantity in goods_lines:
                    balance = _get_balance(origin_point, goods)
                    if balance.available_quantity < quantity:
                        raise BusinessException(
                            f'货物「{goods.name}」在保管点「{origin_point.name}」可用库存不足'
                        )
                    balances.append((balance, quantity))

                order = TransferOrder.objects.create(
                    transfer_no=_generate_transfer_no(),
                    origin_point=origin_point,
                    destination_point=destination_point,
                    applicant=user,
                    remark=remark,
                )
                event_items = []
                for (goods, quantity), (balance, _) in zip(goods_lines, balances):
                    balance.available_quantity -= quantity
                    balance.reserved_quantity += quantity
                    balance.save()
                    item = TransferItem.objects.create(
                        transfer=order, goods=goods, applied_quantity=quantity,
                    )
                    event_items.append({
                        'item_id': item.pk,
                        'goods_id': goods.pk,
                        'goods_name': goods.name,
                        'quantity': str(quantity),
                    })
                _record_event(order, 'apply', user, {
                    'origin_point_id': origin_point.pk,
                    'destination_point_id': destination_point.pk,
                    'items': event_items,
                })
                logger.info(f"User {user.username} created transfer {order.transfer_no}")
                return order
        except IntegrityError:
            # 调拨单号并发冲突，重试
            if attempt == 2:
                raise


def dispatch_transfer(*, user, order_id, lines, carrier_name, seal_no,
                      carrier_phone='', vehicle_no=''):
    """起运确认：起点已预留 -> 在途，并记录在途责任人与封签号。"""
    with transaction.atomic():
        order = _get_order(order_id)
        if order.status not in ('pending', 'in_transit'):
            raise BusinessException('当前状态不可起运')
        if not carrier_name:
            raise BusinessException('请填写承运押运人')
        if not seal_no:
            raise BusinessException('请填写封签号')

        resolved = _resolve_lines(
            order, lines,
            lambda item: item.pending_shipment_quantity,
            '没有可起运的数量',
            '可起运数量不足',
        )
        event_lines = []
        for item, quantity in resolved:
            balance = _get_balance(order.origin_point, item.goods)
            balance.reserved_quantity -= quantity
            balance.save()
            item.shipped_quantity += quantity
            item.save()
            event_lines.append({
                'item_id': item.pk,
                'goods_id': item.goods_id,
                'goods_name': item.goods.name,
                'quantity': str(quantity),
            })

        order.carrier_name = carrier_name
        order.carrier_phone = carrier_phone
        order.vehicle_no = vehicle_no
        order.seal_no = seal_no
        order.dispatched_by = user
        order.dispatched_at = timezone.now()
        _refresh_status(order)
        order.save()
        _record_event(order, 'dispatch', user, {
            'lines': event_lines,
            'carrier_name': carrier_name,
            'carrier_phone': carrier_phone,
            'vehicle_no': vehicle_no,
            'seal_no': seal_no,
        })
        logger.info(f"User {user.username} dispatched transfer {order.transfer_no}")
        return order


def receive_transfer(*, user, order_id, lines, idempotency_key=None):
    """到达签收：在途 -> 终点可用。幂等键保证重复请求只入账一次。

    返回 (响应数据, 是否重复请求)。
    """
    try:
        with transaction.atomic():
            if idempotency_key:
                existing = IdempotencyRecord.objects.filter(
                    key=idempotency_key, scope=RECEIVE_IDEMPOTENCY_SCOPE,
                ).first()
                if existing:
                    return existing.response, True

            order = _get_order(order_id)
            if order.status != 'in_transit':
                raise BusinessException('当前状态不可签收')

            resolved = _resolve_lines(
                order, lines,
                lambda item: item.in_transit_quantity,
                '没有在途数量可签收',
                '在途数量不足，无法签收',
            )
            event_lines = []
            for item, quantity in resolved:
                item.received_quantity += quantity
                item.save()
                balance = _get_balance(order.destination_point, item.goods)
                balance.available_quantity += quantity
                balance.save()
                event_lines.append({
                    'item_id': item.pk,
                    'goods_id': item.goods_id,
                    'goods_name': item.goods.name,
                    'quantity': str(quantity),
                })

            _refresh_status(order)
            order.save()
            _record_event(order, 'receive', user, {
                'lines': event_lines,
                'idempotency_key': idempotency_key or '',
            })
            payload = {
                'transfer_id': order.pk,
                'transfer_no': order.transfer_no,
                'status': order.status,
                'received': event_lines,
            }
            if idempotency_key:
                IdempotencyRecord.objects.create(
                    key=idempotency_key,
                    scope=RECEIVE_IDEMPOTENCY_SCOPE,
                    response=payload,
                )
            logger.info(f"User {user.username} received transfer {order.transfer_no}")
            return payload, False
    except IntegrityError:
        # 并发下同键请求已入账，返回已存响应
        if idempotency_key:
            existing = IdempotencyRecord.objects.filter(
                key=idempotency_key, scope=RECEIVE_IDEMPOTENCY_SCOPE,
            ).first()
            if existing:
                return existing.response, True
        raise


def cancel_transfer(*, user, order_id, returns=None, reason=''):
    """取消调拨：释放全部待起运预留，并可将在途数量退回起点。"""
    with transaction.atomic():
        order = _get_order(order_id)
        if order.status in ('completed', 'cancelled'):
            raise BusinessException('调拨单已完结，不可取消')

        released = []
        for item in order.items.all():
            pending = item.pending_shipment_quantity
            if pending > 0:
                balance = _get_balance(order.origin_point, item.goods)
                balance.reserved_quantity -= pending
                balance.available_quantity += pending
                balance.save()
                item.cancelled_quantity += pending
                item.save()
                released.append({
                    'item_id': item.pk,
                    'goods_id': item.goods_id,
                    'goods_name': item.goods.name,
                    'quantity': str(pending),
                })

        returned = []
        if returns:
            item_map = {item.pk: item for item in order.items.all()}
            for line in returns:
                item = item_map.get(line['item_id'])
                if item is None:
                    raise BusinessException('调拨明细不属于该调拨单')
                quantity = line['quantity']
                if quantity <= 0:
                    raise BusinessException('退回数量必须大于0')
                if quantity > item.in_transit_quantity:
                    raise BusinessException(f'货物「{item.goods.name}」在途数量不足，无法退回')
                item.returned_quantity += quantity
                item.save()
                balance = _get_balance(order.origin_point, item.goods)
                balance.available_quantity += quantity
                balance.save()
                returned.append({
                    'item_id': item.pk,
                    'goods_id': item.goods_id,
                    'goods_name': item.goods.name,
                    'quantity': str(quantity),
                })

        _refresh_status(order)
        order.save()
        _record_event(order, 'cancel', user, {
            'released': released,
            'returned': returned,
            'reason': reason,
        })
        logger.info(f"User {user.username} cancelled transfer {order.transfer_no}")
        return order


def change_seal(*, user, order_id, new_seal_no, reason=''):
    """封签变更：仅记录台账，不影响数量。"""
    with transaction.atomic():
        order = _get_order(order_id)
        if order.status != 'in_transit':
            raise BusinessException('仅在途调拨单可变更封签')
        if not new_seal_no:
            raise BusinessException('请填写新封签号')
        if new_seal_no == order.seal_no:
            raise BusinessException('新封签号与当前封签号相同')

        change = SealChange.objects.create(
            transfer=order,
            old_seal_no=order.seal_no,
            new_seal_no=new_seal_no,
            reason=reason,
            changed_by=user,
        )
        order.seal_no = new_seal_no
        order.save(update_fields=['seal_no', 'updated_at'])
        _record_event(order, 'seal_change', user, {
            'old_seal_no': change.old_seal_no,
            'new_seal_no': change.new_seal_no,
            'reason': reason,
        })
        logger.info(f"User {user.username} changed seal of transfer {order.transfer_no}")
        return change


def raise_discrepancy(*, user, order_id, item_id, quantity, reason):
    """差异登记：在途 -> 待调查。"""
    with transaction.atomic():
        order = _get_order(order_id)
        if order.status != 'in_transit':
            raise BusinessException('仅在途调拨单可登记差异')
        item = order.items.filter(pk=item_id).first()
        if item is None:
            raise BusinessException('调拨明细不属于该调拨单')
        if quantity <= 0:
            raise BusinessException('差异数量必须大于0')
        if quantity > item.in_transit_quantity:
            raise BusinessException(f'货物「{item.goods.name}」差异数量不能超过在途数量')

        item.disputed_quantity += quantity
        item.save()
        discrepancy = Discrepancy.objects.create(
            transfer=order, item=item, quantity=quantity,
            reason=reason, raised_by=user,
        )
        _record_event(order, 'dispute_raise', user, {
            'discrepancy_id': discrepancy.pk,
            'item_id': item.pk,
            'goods_id': item.goods_id,
            'goods_name': item.goods.name,
            'quantity': str(quantity),
            'reason': reason,
        })
        logger.info(
            f"User {user.username} raised discrepancy {discrepancy.pk} "
            f"on transfer {order.transfer_no}"
        )
        return discrepancy


def resolve_discrepancy(*, user, discrepancy_id,
                        delivered=Decimal('0'), returned=Decimal('0'),
                        lost=Decimal('0'), remark=''):
    """差异处理：待调查 -> 补交终点 / 退回起点 / 核销损失（可分批结案）。"""
    with transaction.atomic():
        try:
            discrepancy = Discrepancy.objects.select_for_update().get(pk=discrepancy_id)
        except Discrepancy.DoesNotExist:
            raise NotFoundException('差异记录不存在')
        if discrepancy.status == 'resolved':
            raise BusinessException('差异已结案')

        total = delivered + returned + lost
        if total <= 0:
            raise BusinessException('请填写处理数量')
        if min(delivered, returned, lost) < 0:
            raise BusinessException('处理数量不能为负数')
        if total > discrepancy.remaining_quantity:
            raise BusinessException('处理数量超过剩余待调查数量')

        item = discrepancy.item
        order = discrepancy.transfer
        item.disputed_quantity -= total
        if delivered > 0:
            item.received_quantity += delivered
            balance = _get_balance(order.destination_point, item.goods)
            balance.available_quantity += delivered
            balance.save()
        if returned > 0:
            item.returned_quantity += returned
            balance = _get_balance(order.origin_point, item.goods)
            balance.available_quantity += returned
            balance.save()
        if lost > 0:
            item.lost_quantity += lost
            Goods.objects.filter(pk=item.goods_id).update(quantity=F('quantity') - lost)
        item.save()

        discrepancy.delivered_quantity += delivered
        discrepancy.returned_quantity += returned
        discrepancy.lost_quantity += lost
        if remark:
            discrepancy.remark = remark
        if discrepancy.remaining_quantity == 0:
            discrepancy.status = 'resolved'
            discrepancy.resolved_by = user
            discrepancy.resolved_at = timezone.now()
        discrepancy.save()

        _refresh_status(order)
        order.save()
        _record_event(order, 'dispute_resolve', user, {
            'discrepancy_id': discrepancy.pk,
            'item_id': item.pk,
            'goods_id': item.goods_id,
            'goods_name': item.goods.name,
            'delivered': str(delivered),
            'returned': str(returned),
            'lost': str(lost),
            'remark': remark,
        })
        logger.info(
            f"User {user.username} resolved discrepancy {discrepancy.pk} "
            f"(delivered={delivered}, returned={returned}, lost={lost})"
        )
        return discrepancy
