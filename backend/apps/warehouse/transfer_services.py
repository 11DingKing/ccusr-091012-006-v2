"""
调拨领域服务：状态机与库存四桶（可用/已预留/在途/待调查）转移。

所有写操作均在单个事务内完成，且遵守同一守恒口径：

    申请量 = 累计签收 + 短少 + 途中取消退回 + 仍在途
    系统总量 = 各地点四桶之和（差异核销/退回除外，二者是经审批的数量出系统）

每次数量变动写一条 TransferEvent，并附带起讫两点四桶的变动后快照，
差异发生后两边台账都可凭流水解释。
"""
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    CustodyLocation,
    Goods,
    StockBalance,
    StockIn,
    TransferDifference,
    TransferEvent,
    TransferRequest,
    TransferSealChange,
)

ZERO = Decimal("0")


class TransferError(Exception):
    """调拨业务校验失败"""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


class IdempotentReplay(TransferError):
    """携带相同幂等键的重复动作请求"""

    def __init__(self, message, transfer):
        super().__init__(message, code=409)
        self.transfer = transfer


# ==================== 台账辅助 ====================

def _get_balance(goods_id, location_id):
    """取台账行（调用方须已开启事务并持锁），不存在则建零值行"""
    balance, _ = StockBalance.objects.get_or_create(
        goods_id=goods_id, location_id=location_id,
        defaults={
            'available': ZERO, 'reserved': ZERO,
            'in_transit': ZERO, 'investigating': ZERO,
        },
    )
    return balance


def _lock_balances(goods_id, from_location_id, to_location_id):
    """
    按主键顺序锁定起讫两点台账，避免并发下的锁序死锁。
    不存在的台账行先落零值行再锁。
    """
    _get_balance(goods_id, from_location_id)
    _get_balance(goods_id, to_location_id)
    ids = sorted({from_location_id, to_location_id})
    locked = {
        b.location_id: b
        for b in StockBalance.objects.select_for_update().filter(
            goods_id=goods_id, location_id__in=ids
        )
    }
    return locked[from_location_id], locked[to_location_id]


def _record_event(transfer, event_type, quantity, detail, operator,
                  request_id, from_balance, to_balance):
    """写事件流水并记录四桶快照；request_id 非空时由唯一约束兜底幂等"""
    event = TransferEvent(
        transfer=transfer,
        event_type=event_type,
        quantity=quantity or ZERO,
        detail=detail or '',
        request_id=request_id or '',
        operator=operator,
        from_available=from_balance.available if from_balance else ZERO,
        from_reserved=from_balance.reserved if from_balance else ZERO,
        from_in_transit=from_balance.in_transit if from_balance else ZERO,
        from_investigating=from_balance.investigating if from_balance else ZERO,
        to_available=to_balance.available if to_balance else ZERO,
        to_reserved=to_balance.reserved if to_balance else ZERO,
        to_in_transit=to_balance.in_transit if to_balance else ZERO,
        to_investigating=to_balance.investigating if to_balance else ZERO,
    )
    event.save()
    _sync_goods_quantity(transfer.goods_id)
    return event


def _check_replay(transfer, event_type, request_id):
    if request_id:
        existing = TransferEvent.objects.filter(
            transfer=transfer, event_type=event_type, request_id=request_id
        ).first()
        if existing:
            raise IdempotentReplay('重复请求：该动作已处理，请勿重复提交', transfer)


def _generate_code():
    return f"DB{timezone.now():%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"


def _sync_goods_quantity(goods_id):
    """
    将旧口径 Goods.quantity 同步为该货物全系统四桶总量，
    供既有报表/预警 cron 使用；新台账本身才是多地点口径的事实来源。
    """
    agg = StockBalance.objects.filter(goods_id=goods_id).aggregate(
        a=Sum('available'), r=Sum('reserved'),
        t=Sum('in_transit'), i=Sum('investigating'),
    )
    total = ((agg['a'] or ZERO) + (agg['r'] or ZERO)
             + (agg['t'] or ZERO) + (agg['i'] or ZERO))
    Goods.objects.filter(pk=goods_id).update(quantity=total)


# ==================== 入库登记（台账初始化/补入） ====================

def stock_into_location(goods_id, location_id, quantity, operator,
                        batch_no='', supplier='', remark=''):
    """
    入库登记：数量进入指定保管点的可用桶，并同步写传统入库记录。
    这是调拨链之外唯一允许系统总量增加的入口。
    """
    if quantity is None or quantity <= 0:
        raise TransferError('入库数量必须大于0')
    try:
        goods = Goods.objects.get(pk=goods_id)
    except Goods.DoesNotExist:
        raise TransferError('货物不存在', code=404)
    try:
        location = CustodyLocation.objects.get(pk=location_id)
    except CustodyLocation.DoesNotExist:
        raise TransferError('保管点不存在', code=404)
    if not location.is_active:
        raise TransferError('保管点已停用，无法入库')

    with transaction.atomic():
        balance = _get_balance(goods_id, location_id)
        balance.available += quantity
        balance.save()
        StockIn.objects.create(
            goods=goods, operator=operator, quantity=quantity,
            batch_no=batch_no, supplier=supplier, remark=remark,
        )
        _sync_goods_quantity(goods_id)
    return balance


# ==================== 调拨申请 ====================

def create_transfer(goods_id, from_location_id, to_location_id, quantity,
                    applicant, remark=''):
    """申请调拨：起点 可用 -> 已预留，不动其他桶"""
    if quantity is None or quantity <= 0:
        raise TransferError('调拨数量必须大于0')
    if from_location_id == to_location_id:
        raise TransferError('起运点与接收点不能相同')
    try:
        goods = Goods.objects.get(pk=goods_id)
    except Goods.DoesNotExist:
        raise TransferError('货物不存在', code=404)
    try:
        from_location = CustodyLocation.objects.get(pk=from_location_id)
    except CustodyLocation.DoesNotExist:
        raise TransferError('起运点不存在', code=404)
    try:
        to_location = CustodyLocation.objects.get(pk=to_location_id)
    except CustodyLocation.DoesNotExist:
        raise TransferError('接收点不存在', code=404)
    if not (from_location.is_active and to_location.is_active):
        raise TransferError('起运点或接收点已停用')

    with transaction.atomic():
        from_balance = StockBalance.objects.select_for_update().filter(
            goods_id=goods_id, location_id=from_location_id
        ).first()
        if from_balance is None or from_balance.available < quantity:
            raise TransferError('起运点可用库存不足，无法预留')

        transfer = TransferRequest.objects.create(
            code=_generate_code(),
            goods=goods,
            from_location=from_location,
            to_location=to_location,
            quantity=quantity,
            status='pending',
            applicant=applicant,
            remark=remark,
        )
        from_balance.available -= quantity
        from_balance.reserved += quantity
        from_balance.save()

        to_balance = _get_balance(goods_id, to_location_id)
        _record_event(
            transfer, 'create', quantity,
            f'{from_location.name} 预留 {quantity} 待发往 {to_location.name}',
            applicant, '', from_balance, to_balance,
        )
    return transfer


def cancel_transfer(transfer_id, operator, request_id=None, remark=''):
    """起运前取消：起点 已预留 -> 可用"""
    with transaction.atomic():
        transfer = TransferRequest.objects.select_for_update().filter(
            pk=transfer_id
        ).first()
        if transfer is None:
            raise TransferError('调拨单不存在', code=404)
        _check_replay(transfer, 'cancel', request_id)
        if transfer.status != 'pending':
            raise TransferError('仅待起运的调拨单可以取消，当前状态：'
                                + transfer.get_status_display())

        from_balance = StockBalance.objects.select_for_update().get(
            goods_id=transfer.goods_id, location_id=transfer.from_location_id
        )
        from_balance.reserved -= transfer.quantity
        from_balance.available += transfer.quantity
        from_balance.save()

        transfer.status = 'cancelled'
        transfer.save(update_fields=['status', 'updated_at'])

        to_balance = _get_balance(transfer.goods_id, transfer.to_location_id)
        _record_event(
            transfer, 'cancel', transfer.quantity, remark or '起运前取消，预留退回起点',
            operator, request_id, from_balance, to_balance,
        )
    return transfer


# ==================== 起运确认 ====================

def ship_transfer(transfer_id, operator, seal_no, carrier,
                  responsible_party, carrier_phone='', request_id=None, remark=''):
    """起运确认：起点 已预留 -> 在途，登记封签与在途责任方"""
    if not seal_no or not str(seal_no).strip():
        raise TransferError('起运必须登记封签编号')
    if not carrier or not str(carrier).strip():
        raise TransferError('起运必须登记承运/押送人')
    if not responsible_party or not str(responsible_party).strip():
        raise TransferError('起运必须明确在途责任方')

    with transaction.atomic():
        transfer = TransferRequest.objects.select_for_update().filter(
            pk=transfer_id
        ).first()
        if transfer is None:
            raise TransferError('调拨单不存在', code=404)
        _check_replay(transfer, 'ship', request_id)
        if transfer.status != 'pending':
            raise TransferError('仅待起运的调拨单可以起运确认，当前状态：'
                                + transfer.get_status_display())

        from_balance, to_balance = _lock_balances(
            transfer.goods_id, transfer.from_location_id, transfer.to_location_id
        )
        if from_balance.reserved < transfer.quantity:
            raise TransferError('起点预留数量异常，无法起运')

        from_balance.reserved -= transfer.quantity
        from_balance.in_transit += transfer.quantity
        from_balance.save()

        transfer.seal_no = str(seal_no).strip()
        transfer.carrier = carrier
        transfer.carrier_phone = carrier_phone or ''
        transfer.responsible_party = responsible_party
        transfer.shipped_by = operator
        transfer.shipped_at = timezone.now()
        transfer.status = 'shipping'
        transfer.save()

        _record_event(
            transfer, 'ship', transfer.quantity,
            f'封签 {seal_no}，承运人 {carrier}，在途责任方 {responsible_party}。{remark}'.strip(),
            operator, request_id, from_balance, to_balance,
        )
    return transfer


# ==================== 封签变更 ====================

def change_seal(transfer_id, operator, new_seal_no, reason, request_id=None):
    """在途封签变更：只留痕，不动任何数量桶"""
    if not new_seal_no or not str(new_seal_no).strip():
        raise TransferError('必须填写新封签编号')
    if not reason or not str(reason).strip():
        raise TransferError('必须填写封签变更原因')

    with transaction.atomic():
        transfer = TransferRequest.objects.select_for_update().filter(
            pk=transfer_id
        ).first()
        if transfer is None:
            raise TransferError('调拨单不存在', code=404)
        _check_replay(transfer, 'seal_change', request_id)
        if transfer.status not in ('shipping', 'receiving'):
            raise TransferError('仅在途物资可以变更封签，当前状态：'
                                + transfer.get_status_display())

        old_seal = transfer.current_seal_no
        if str(new_seal_no).strip() == old_seal:
            raise TransferError('新封签编号与当前封签相同')

        seal_change = TransferSealChange.objects.create(
            transfer=transfer,
            old_seal_no=old_seal,
            new_seal_no=str(new_seal_no).strip(),
            reason=reason,
            changed_by=operator,
        )
        from_balance = StockBalance.objects.get(
            goods_id=transfer.goods_id, location_id=transfer.from_location_id
        )
        to_balance = _get_balance(transfer.goods_id, transfer.to_location_id)
        _record_event(
            transfer, 'seal_change', ZERO,
            f'封签 {old_seal} 变更为 {seal_change.new_seal_no}，原因：{reason}',
            operator, request_id, from_balance, to_balance,
        )
    return transfer


# ==================== 到达签收 ====================

def receive_transfer(transfer_id, operator, received_qty, shortage_qty=None,
                     overage_qty=None, seal_no='', request_id=None, remark=''):
    """
    到达签收（支持多次部分签收）。显式三数量口径：
      received_qty  本次合格签收，终点 在途对应量 -> 可用
      shortage_qty  本次确认短少，起点 在途 -> 待调查（挂起运点）
      overage_qty   本次溢余，终点挂 待调查（确认入库前不计可用）

    守恒约束：received + shortage 不得超过当前仍在途量。
    """
    received_qty = received_qty if received_qty is not None else ZERO
    shortage_qty = shortage_qty if shortage_qty is not None else ZERO
    overage_qty = overage_qty if overage_qty is not None else ZERO
    for name, value in (('签收数量', received_qty), ('短少数量', shortage_qty),
                        ('溢余数量', overage_qty)):
        if value < 0:
            raise TransferError(f'{name}不能为负')
    if received_qty + shortage_qty + overage_qty == 0:
        raise TransferError('签收、短少、溢余数量不能全部为0')

    with transaction.atomic():
        transfer = TransferRequest.objects.select_for_update().filter(
            pk=transfer_id
        ).first()
        if transfer is None:
            raise TransferError('调拨单不存在', code=404)
        _check_replay(transfer, 'receive', request_id)
        if transfer.status not in ('shipping', 'receiving', 'investigating'):
            raise TransferError('当前状态不允许签收：' + transfer.get_status_display())

        remaining = transfer.remaining_in_transit
        if received_qty + shortage_qty > remaining:
            raise TransferError(
                f'本次签收({received_qty})+短少({shortage_qty}) '
                f'超过仍在途数量({remaining})'
            )

        from_balance, to_balance = _lock_balances(
            transfer.goods_id, transfer.from_location_id, transfer.to_location_id
        )
        actual_seal = seal_no or transfer.current_seal_no

        # 正常签收：起点在途出清，终点可用增加
        if received_qty > 0:
            from_balance.in_transit -= received_qty
            to_balance.available += received_qty
        # 短少：起点在途 -> 起点待调查
        if shortage_qty > 0:
            from_balance.in_transit -= shortage_qty
            from_balance.investigating += shortage_qty
            TransferDifference.objects.create(
                transfer=transfer, kind='shortage', quantity=shortage_qty,
                seal_no_at_arrival=actual_seal,
            )
        # 溢余：终点待调查（实物多出来，确认前不得计入可用）
        if overage_qty > 0:
            to_balance.investigating += overage_qty
            TransferDifference.objects.create(
                transfer=transfer, kind='overage', quantity=overage_qty,
                seal_no_at_arrival=actual_seal,
            )
        from_balance.save()
        to_balance.save()

        transfer.received_qty += received_qty
        transfer.shortage_qty += shortage_qty
        transfer.overage_qty += overage_qty
        transfer.last_received_at = timezone.now()
        transfer.status = _status_after_receive(transfer)
        transfer.save()

        detail = (f'签收 {received_qty}'
                  + (f'，短少 {shortage_qty}' if shortage_qty > 0 else '')
                  + (f'，溢余 {overage_qty}' if overage_qty > 0 else '')
                  + (f'，到货封签 {actual_seal}' if actual_seal else '')
                  + (f'。{remark}' if remark else ''))
        _record_event(
            transfer, 'receive', received_qty, detail,
            operator, request_id, from_balance, to_balance,
        )
    return transfer


def _status_after_receive(transfer):
    """签收后状态：仍有在途 -> 部分签收；全部到齐后看差异是否结清"""
    if transfer.remaining_in_transit > 0:
        return 'receiving'
    if transfer.unresolved_difference > 0:
        return 'investigating'
    return 'received'


# ==================== 途中取消 ====================

def cancel_in_transit(transfer_id, operator, request_id=None, remark=''):
    """
    途中取消：当前仍在途余量 起点在途 -> 起点可用。
    已签收部分留在终点，已登记差异仍挂待调查，数量守恒不受影响。
    """
    with transaction.atomic():
        transfer = TransferRequest.objects.select_for_update().filter(
            pk=transfer_id
        ).first()
        if transfer is None:
            raise TransferError('调拨单不存在', code=404)
        _check_replay(transfer, 'cancel_in_transit', request_id)
        if transfer.status not in ('shipping', 'receiving', 'investigating'):
            raise TransferError('当前状态不允许途中取消：'
                                + transfer.get_status_display())

        remaining = transfer.remaining_in_transit
        if remaining <= 0:
            raise TransferError('在途数量为0，无可取消退回的物资')

        from_balance, to_balance = _lock_balances(
            transfer.goods_id, transfer.from_location_id, transfer.to_location_id
        )
        from_balance.in_transit -= remaining
        from_balance.available += remaining
        from_balance.save()

        transfer.cancelled_qty += remaining
        transfer.status = 'cancelled_in_transit'
        transfer.save()

        _record_event(
            transfer, 'cancel_in_transit', remaining,
            f'途中取消，在途余量 {remaining} 退回起点。{remark}'.strip(),
            operator, request_id, from_balance, to_balance,
        )
    return transfer


# ==================== 差异处理 ====================

# 差异类型 -> 允许的处理结论
VALID_RESOLUTIONS = {
    'shortage': {'write_off', 'recover'},
    'overage': {'confirm', 'return'},
}


def resolve_difference(difference_id, operator, resolution,
                       liability_party='', request_id=None, remark=''):
    """
    差异定责处理：
      短少-核销 write_off：起点待调查出系统（经审批的报损）
      短少-追回 recover  ：起点待调查 -> 起点可用
      溢余-确认 confirm  ：终点待调查 -> 终点可用
      溢余-退回 return   ：终点待调查出系统
    """
    with transaction.atomic():
        difference = TransferDifference.objects.select_for_update().filter(
            pk=difference_id
        ).first()
        if difference is None:
            raise TransferError('差异记录不存在', code=404)
        transfer = TransferRequest.objects.select_for_update().get(
            pk=difference.transfer_id
        )
        _check_replay(transfer, 'resolve', request_id)
        if difference.resolution != 'pending':
            raise TransferError('该差异已处理，不能重复处理')
        if resolution not in VALID_RESOLUTIONS[difference.kind]:
            allowed = '、'.join(
                dict(TransferDifference.RESOLUTION_CHOICES)[r]
                for r in VALID_RESOLUTIONS[difference.kind]
            )
            raise TransferError(f'{difference.get_kind_display()}只能选择：{allowed}')

        qty = difference.quantity
        if difference.kind == 'shortage':
            balance = StockBalance.objects.select_for_update().get(
                goods_id=transfer.goods_id, location_id=transfer.from_location_id
            )
            if balance.investigating < qty:
                raise TransferError('起点待调查数量不足，无法处理')
            balance.investigating -= qty
            if resolution == 'recover':
                balance.available += qty
            balance.save()
        else:
            balance = StockBalance.objects.select_for_update().get(
                goods_id=transfer.goods_id, location_id=transfer.to_location_id
            )
            if balance.investigating < qty:
                raise TransferError('终点待调查数量不足，无法处理')
            balance.investigating -= qty
            if resolution == 'confirm':
                balance.available += qty
            balance.save()

        difference.resolution = resolution
        difference.liability_party = liability_party or ''
        difference.remark = remark or ''
        difference.handled_by = operator
        difference.handled_at = timezone.now()
        difference.save()

        transfer.resolved_qty += qty
        if (transfer.unresolved_difference == 0
                and transfer.remaining_in_transit == 0
                and transfer.status in ('investigating', 'cancelled_in_transit',
                                        'receiving', 'shipping')):
            transfer.status = 'resolved'
        transfer.save()

        from_balance = StockBalance.objects.get(
            goods_id=transfer.goods_id, location_id=transfer.from_location_id
        )
        to_balance, _ = StockBalance.objects.get_or_create(
            goods_id=transfer.goods_id, location_id=transfer.to_location_id,
            defaults={
                'available': ZERO, 'reserved': ZERO,
                'in_transit': ZERO, 'investigating': ZERO,
            },
        )
        _record_event(
            transfer, 'resolve', qty,
            f'{difference.get_kind_display()} {qty} 处理为'
            f'{difference.get_resolution_display()}'
            + (f'，责任方：{liability_party}' if liability_party else '')
            + (f'。{remark}' if remark else ''),
            operator, request_id, from_balance, to_balance,
        )
    return difference
