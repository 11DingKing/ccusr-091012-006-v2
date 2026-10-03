"""
保管点与调拨视图。

所有写操作委托 transfer_services 中的状态机完成，视图只负责
入参校验、异常翻译与响应封装。
"""
import logging
from functools import wraps

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db import IntegrityError
from django.db.models import Q

from apps.core.response import success_response, error_response
from .models import (
    CustodyLocation, StockBalance, TransferRequest, TransferDifference,
)
from .serializers import (
    CustodyLocationSerializer, CustodyLocationCreateSerializer,
    StockBalanceSerializer, StockInLocationSerializer,
    TransferCreateSerializer, TransferListSerializer, TransferDetailSerializer,
    TransferShipSerializer, TransferSealChangeSerializer,
    TransferReceiveSerializer, TransferCancelSerializer,
    TransferDifferenceSerializer, TransferResolveSerializer,
)
from . import transfer_services as svc

logger = logging.getLogger('apps')


def _first_error(errors):
    """从序列化器错误中提取第一条人类可读信息"""
    value = list(errors.values())[0]
    if isinstance(value, dict):
        return _first_error(value)
    if isinstance(value, list):
        return str(value[0])
    return str(value)


def _handle_service(func):
    """装饰器：统一处理领域服务异常与幂等冲突"""
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        try:
            return func(self, request, *args, **kwargs)
        except svc.IdempotentReplay as exc:
            logger.warning(
                '重复请求被拒绝 user=%s transfer=%s',
                request.user, exc.transfer.code
            )
            return error_response(message=exc.message, code=409,
                                  data={'transfer': TransferListSerializer(exc.transfer).data})
        except svc.TransferError as exc:
            return error_response(message=exc.message, code=exc.code)
        except IntegrityError:
            # 幂等唯一约束兜底（并发同键请求）
            return error_response(message='重复请求：该动作已处理，请勿重复提交', code=409)
    return wrapper


# ==================== 保管点 ====================

class LocationListView(APIView):
    """保管点列表/创建"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = CustodyLocation.objects.all().order_by('code')
        code = request.query_params.get('code')
        name = request.query_params.get('name')
        if code:
            queryset = queryset.filter(code__icontains=code)
        if name:
            queryset = queryset.filter(name__icontains=name)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        locations = queryset[(page - 1) * page_size: page * page_size]
        return success_response(data={
            'list': CustodyLocationSerializer(locations, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    @_handle_service
    def post(self, request):
        serializer = CustodyLocationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        manager_id = data.get('manager')
        location = CustodyLocation.objects.create(
            code=data['code'], name=data['name'],
            address=data.get('address', ''),
            manager_id=manager_id if manager_id else None,
        )
        logger.info('User %s created location %s', request.user.username, location.code)
        return success_response(data=CustodyLocationSerializer(location).data,
                                message='创建成功')


class LocationAllView(APIView):
    """全部启用保管点（下拉选择）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        locations = CustodyLocation.objects.filter(is_active=True).order_by('code')
        return success_response(data=CustodyLocationSerializer(locations, many=True).data)


class LocationDetailView(APIView):
    """保管点更新/停用"""
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        try:
            location = CustodyLocation.objects.get(pk=pk)
        except CustodyLocation.DoesNotExist:
            return error_response(message='保管点不存在', code=404)
        serializer = CustodyLocationCreateSerializer(
            data=request.data, context={'instance': location})
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        location.code = data['code']
        location.name = data['name']
        location.address = data.get('address', '')
        manager_id = data.get('manager')
        location.manager_id = manager_id if manager_id else None
        location.save()
        logger.info('User %s updated location %s', request.user.username, location.code)
        return success_response(data=CustodyLocationSerializer(location).data,
                                message='更新成功')

    def delete(self, request, pk):
        """停用保管点（已有台账时不物理删除，保证历史台账可解释）"""
        try:
            location = CustodyLocation.objects.get(pk=pk)
        except CustodyLocation.DoesNotExist:
            return error_response(message='保管点不存在', code=404)
        if StockBalance.objects.filter(location=location).exists():
            location.is_active = False
            location.save(update_fields=['is_active', 'updated_at'])
            logger.info('User %s deactivated location %s', request.user.username, location.code)
            return success_response(message='该保管点已有台账记录，已停用而非删除')
        location.delete()
        logger.info('User %s deleted location %s', request.user.username, location.code)
        return success_response(message='删除成功')


# ==================== 库存台账与地点入库 ====================

class StockBalanceListView(APIView):
    """库存台账查询：任意时点区分可用/已预留/在途/待调查"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = StockBalance.objects.select_related(
            'goods', 'location').all().order_by('location_id', 'goods_id')
        goods_id = request.query_params.get('goods')
        location_id = request.query_params.get('location')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if location_id:
            queryset = queryset.filter(location_id=location_id)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))
        total = queryset.count()
        rows = queryset[(page - 1) * page_size: page * page_size]
        data = StockBalanceSerializer(rows, many=True).data
        return success_response(data={
            'list': data, 'total': total, 'page': page, 'page_size': page_size,
        })


class StockInLocationView(APIView):
    """入库到指定保管点（台账初始化/补入）"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request):
        serializer = StockInLocationSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        balance = svc.stock_into_location(
            goods_id=data['goods'], location_id=data['location'],
            quantity=data['quantity'], operator=request.user,
            batch_no=data.get('batch_no', ''), supplier=data.get('supplier', ''),
            remark=data.get('remark', ''),
        )
        logger.info(
            'User %s stocked %s of goods %s into location %s',
            request.user.username, data['quantity'], data['goods'], data['location']
        )
        return success_response(data=StockBalanceSerializer(balance).data,
                                message='入库成功')


# ==================== 调拨申请 ====================

class TransferListView(APIView):
    """调拨单列表/创建"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = TransferRequest.objects.select_related(
            'goods', 'from_location', 'to_location', 'applicant').all()
        status = request.query_params.get('status')
        goods_id = request.query_params.get('goods')
        location_id = request.query_params.get('location')
        code = request.query_params.get('code')
        if status:
            queryset = queryset.filter(status=status)
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        if location_id:
            queryset = queryset.filter(
                Q(from_location_id=location_id)
                | Q(to_location_id=location_id)
            )
        if code:
            queryset = queryset.filter(code__icontains=code)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        transfers = queryset[(page - 1) * page_size: page * page_size]
        return success_response(data={
            'list': TransferListSerializer(transfers, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    @_handle_service
    def post(self, request):
        serializer = TransferCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.create_transfer(
            goods_id=data['goods'],
            from_location_id=data['from_location'],
            to_location_id=data['to_location'],
            quantity=data['quantity'],
            applicant=request.user,
            remark=data.get('remark', ''),
        )
        logger.info('User %s created transfer %s',
                    request.user.username, transfer.code)
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message='调拨申请已提交')


class TransferDetailView(APIView):
    """调拨单详情：含封签变更、差异、完整事件流水"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            transfer = TransferRequest.objects.select_related(
                'goods', 'from_location', 'to_location', 'applicant'
            ).prefetch_related('seal_events', 'differences', 'events').get(pk=pk)
        except TransferRequest.DoesNotExist:
            return error_response(message='调拨单不存在', code=404)
        return success_response(data=TransferDetailSerializer(transfer).data)


class TransferCancelView(APIView):
    """起运前取消申请"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.cancel_transfer(
            pk, operator=request.user,
            request_id=data.get('request_id') or None,
            remark=data.get('remark', ''),
        )
        logger.info('User %s cancelled transfer %s before shipment',
                    request.user.username, transfer.code)
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message='调拨单已取消，预留数量已退回')


class TransferShipView(APIView):
    """起运确认"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferShipSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.ship_transfer(
            pk, operator=request.user,
            seal_no=data['seal_no'], carrier=data['carrier'],
            responsible_party=data['responsible_party'],
            carrier_phone=data.get('carrier_phone', ''),
            request_id=data.get('request_id') or None,
            remark=data.get('remark', ''),
        )
        logger.info('User %s shipped transfer %s seal=%s',
                    request.user.username, transfer.code, transfer.seal_no)
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message='起运已确认，物资进入在途')


class TransferSealChangeView(APIView):
    """在途封签变更"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferSealChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.change_seal(
            pk, operator=request.user,
            new_seal_no=data['new_seal_no'], reason=data['reason'],
            request_id=data.get('request_id') or None,
        )
        logger.info('User %s changed seal on transfer %s',
                    request.user.username, transfer.code)
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message='封签变更已登记')


class TransferReceiveView(APIView):
    """到达签收（支持部分签收、短少、溢余登记）"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferReceiveSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.receive_transfer(
            pk, operator=request.user,
            received_qty=data.get('received_qty', 0),
            shortage_qty=data.get('shortage_qty', 0),
            overage_qty=data.get('overage_qty', 0),
            seal_no=data.get('seal_no', ''),
            request_id=data.get('request_id') or None,
            remark=data.get('remark', ''),
        )
        logger.info('User %s received transfer %s status=%s',
                    request.user.username, transfer.code, transfer.status)
        message = '签收完成'
        if transfer.status == 'receiving':
            message = '部分签收成功，剩余物资仍在途'
        elif transfer.status == 'investigating':
            message = '签收完成，存在差异，数量已挂待调查'
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message=message)


class TransferCancelInTransitView(APIView):
    """途中取消：在途余量退回起点"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        transfer = svc.cancel_in_transit(
            pk, operator=request.user,
            request_id=data.get('request_id') or None,
            remark=data.get('remark', ''),
        )
        logger.info('User %s cancelled transfer %s in transit, returned %s',
                    request.user.username, transfer.code, transfer.cancelled_qty)
        return success_response(data=TransferDetailSerializer(transfer).data,
                                message='途中取消成功，在途余量已退回起点')


# ==================== 差异处理 ====================

class TransferDifferenceListView(APIView):
    """差异记录列表"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = TransferDifference.objects.select_related('transfer').all()
        kind = request.query_params.get('kind')
        resolution = request.query_params.get('resolution')
        transfer_id = request.query_params.get('transfer')
        if kind:
            queryset = queryset.filter(kind=kind)
        if resolution:
            queryset = queryset.filter(resolution=resolution)
        if transfer_id:
            queryset = queryset.filter(transfer_id=transfer_id)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        rows = queryset[(page - 1) * page_size: page * page_size]
        return success_response(data={
            'list': TransferDifferenceSerializer(rows, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


class TransferDifferenceResolveView(APIView):
    """差异定责处理"""
    permission_classes = [IsAuthenticated]

    @_handle_service
    def post(self, request, pk):
        serializer = TransferResolveSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        difference = svc.resolve_difference(
            pk, operator=request.user,
            resolution=data['resolution'],
            liability_party=data.get('liability_party', ''),
            request_id=data.get('request_id') or None,
            remark=data.get('remark', ''),
        )
        logger.info('User %s resolved difference %s as %s',
                    request.user.username, difference.id, difference.resolution)
        difference.refresh_from_db()
        return success_response(
            data=TransferDifferenceSerializer(difference).data,
            message=f'差异已按「{difference.get_resolution_display()}」处理')
