"""
仓库管理序列化器
"""
from decimal import Decimal

from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    CustodyPoint, Discrepancy, SealChange, TransferEvent, TransferItem,
    TransferOrder,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 保管点 ====================

class CustodyPointSerializer(serializers.ModelSerializer):
    """保管点序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = CustodyPoint
        fields = [
            'id', 'name', 'code', 'address', 'keeper_name', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustodyPointCreateSerializer(serializers.Serializer):
    """保管点创建/更新序列化器"""
    name = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入保管点名称',
        'blank': '保管点名称不能为空',
        'max_length': '保管点名称最多50个字',
    })
    code = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入保管点编码',
        'blank': '保管点编码不能为空',
        'max_length': '保管点编码最多20个字',
    })
    address = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    keeper_name = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')

    def validate_name(self, value):
        instance = self.context.get('instance')
        queryset = CustodyPoint.objects.filter(name=value)
        if instance:
            queryset = queryset.exclude(pk=instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('保管点名称已存在')
        return value

    def validate_code(self, value):
        instance = self.context.get('instance')
        queryset = CustodyPoint.objects.filter(code=value)
        if instance:
            queryset = queryset.exclude(pk=instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('保管点编码已存在')
        return value


# ==================== 调拨 ====================

class QuantityLineSerializer(serializers.Serializer):
    """数量行序列化器（起运/签收/退回通用）"""
    item_id = serializers.IntegerField(required=True, error_messages={
        'required': '请指定调拨明细',
    })
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        min_value=Decimal('0.01'),
        error_messages={'required': '请填写数量'},
    )


class TransferItemSerializer(serializers.ModelSerializer):
    """调拨明细序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    unit_name = serializers.CharField(source='goods.variety.category.unit.name', read_only=True)
    pending_shipment_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    in_transit_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = TransferItem
        fields = [
            'id', 'goods', 'goods_name', 'goods_code', 'unit_name',
            'applied_quantity', 'cancelled_quantity', 'shipped_quantity',
            'received_quantity', 'returned_quantity', 'lost_quantity',
            'disputed_quantity', 'pending_shipment_quantity', 'in_transit_quantity',
        ]


class TransferOrderSerializer(serializers.ModelSerializer):
    """调拨单序列化器"""
    items = TransferItemSerializer(many=True, read_only=True)
    origin_point_name = serializers.CharField(source='origin_point.name', read_only=True)
    destination_point_name = serializers.CharField(
        source='destination_point.name', read_only=True
    )
    applicant_name = serializers.CharField(source='applicant.username', read_only=True)
    dispatched_by_name = serializers.CharField(source='dispatched_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = TransferOrder
        fields = [
            'id', 'transfer_no', 'status', 'status_display',
            'origin_point', 'origin_point_name',
            'destination_point', 'destination_point_name',
            'applicant', 'applicant_name',
            'carrier_name', 'carrier_phone', 'vehicle_no', 'seal_no',
            'dispatched_by', 'dispatched_by_name', 'dispatched_at',
            'completed_at', 'remark', 'items', 'created_at', 'updated_at',
        ]


class TransferItemInputSerializer(serializers.Serializer):
    """调拨申请明细行序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={
        'required': '请选择货物',
    })
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        min_value=Decimal('0.01'),
        error_messages={'required': '请填写调拨数量'},
    )


class TransferCreateSerializer(serializers.Serializer):
    """调拨申请序列化器"""
    origin_point = serializers.IntegerField(required=True, error_messages={
        'required': '请选择起点保管点',
    })
    destination_point = serializers.IntegerField(required=True, error_messages={
        'required': '请选择终点保管点',
    })
    remark = serializers.CharField(required=False, allow_blank=True, default='')
    items = TransferItemInputSerializer(many=True)

    def validate_origin_point(self, value):
        if not CustodyPoint.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('起点保管点不存在或已停用')
        return value

    def validate_destination_point(self, value):
        if not CustodyPoint.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('终点保管点不存在或已停用')
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('调拨明细不能为空')
        return value


class DispatchSerializer(serializers.Serializer):
    """起运确认序列化器"""
    carrier_name = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请填写承运押运人',
        'blank': '承运押运人不能为空',
    })
    carrier_phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    vehicle_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    seal_no = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请填写封签号',
        'blank': '封签号不能为空',
    })
    items = QuantityLineSerializer(many=True, required=False)


class ReceiveSerializer(serializers.Serializer):
    """到达签收序列化器"""
    idempotency_key = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=''
    )
    items = QuantityLineSerializer(many=True, required=False)


class CancelSerializer(serializers.Serializer):
    """取消调拨序列化器"""
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    returns = QuantityLineSerializer(many=True, required=False)


class SealChangeCreateSerializer(serializers.Serializer):
    """封签变更序列化器"""
    new_seal_no = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请填写新封签号',
        'blank': '新封签号不能为空',
    })
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class SealChangeSerializer(serializers.ModelSerializer):
    """封签变更记录序列化器"""
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = SealChange
        fields = [
            'id', 'transfer', 'old_seal_no', 'new_seal_no', 'reason',
            'changed_by', 'changed_by_name', 'created_at',
        ]


class DiscrepancyRaiseSerializer(serializers.Serializer):
    """差异登记序列化器"""
    item_id = serializers.IntegerField(required=True, error_messages={
        'required': '请指定调拨明细',
    })
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True,
        min_value=Decimal('0.01'),
        error_messages={'required': '请填写差异数量'},
    )
    reason = serializers.CharField(min_length=1, required=True, error_messages={
        'required': '请填写差异原因',
        'blank': '差异原因不能为空',
    })


class DiscrepancyResolveSerializer(serializers.Serializer):
    """差异处理序列化器"""
    delivered_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        min_value=Decimal('0'), default=Decimal('0'),
    )
    returned_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        min_value=Decimal('0'), default=Decimal('0'),
    )
    lost_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        min_value=Decimal('0'), default=Decimal('0'),
    )
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        total = (
            data['delivered_quantity'] + data['returned_quantity']
            + data['lost_quantity']
        )
        if total <= 0:
            raise serializers.ValidationError('请填写处理数量')
        return data


class DiscrepancySerializer(serializers.ModelSerializer):
    """差异记录序列化器"""
    transfer_no = serializers.CharField(source='transfer.transfer_no', read_only=True)
    goods_name = serializers.CharField(source='item.goods.name', read_only=True)
    goods_code = serializers.CharField(source='item.goods.code', read_only=True)
    raised_by_name = serializers.CharField(source='raised_by.username', read_only=True)
    resolved_by_name = serializers.CharField(source='resolved_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    remaining_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Discrepancy
        fields = [
            'id', 'transfer', 'transfer_no', 'item',
            'goods_name', 'goods_code',
            'quantity', 'delivered_quantity', 'returned_quantity',
            'lost_quantity', 'remaining_quantity',
            'reason', 'status', 'status_display',
            'raised_by', 'raised_by_name', 'resolved_by', 'resolved_by_name',
            'remark', 'created_at', 'resolved_at',
        ]


class TransferEventSerializer(serializers.ModelSerializer):
    """调拨事件序列化器"""
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = TransferEvent
        fields = [
            'id', 'transfer', 'event_type', 'event_type_display',
            'actor', 'actor_name', 'detail', 'created_at',
        ]


class TransferOrderDetailSerializer(TransferOrderSerializer):
    """调拨单详情序列化器（含差异与封签变更记录）"""
    discrepancies = DiscrepancySerializer(many=True, read_only=True)
    seal_changes = SealChangeSerializer(many=True, read_only=True)

    class Meta(TransferOrderSerializer.Meta):
        fields = TransferOrderSerializer.Meta.fields + ['discrepancies', 'seal_changes']
