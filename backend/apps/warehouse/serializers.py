"""
仓库管理序列化器
"""
from rest_framework import serializers
from apps.authentication.models import User
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    CustodyLocation, StockBalance, TransferRequest, TransferSealChange,
    TransferDifference, TransferEvent,
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


# ==================== 保管点与库存台账 ====================

class CustodyLocationSerializer(serializers.ModelSerializer):
    """保管点序列化器"""
    manager_name = serializers.CharField(source='manager.username', read_only=True)

    class Meta:
        model = CustodyLocation
        fields = [
            'id', 'code', 'name', 'address', 'manager', 'manager_name',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustodyLocationCreateSerializer(serializers.Serializer):
    """保管点创建/更新序列化器"""
    code = serializers.CharField(min_length=1, max_length=20, required=True,
                                 error_messages={'required': '请输入保管点编码',
                                                 'blank': '保管点编码不能为空'})
    name = serializers.CharField(min_length=1, max_length=50, required=True,
                                 error_messages={'required': '请输入保管点名称',
                                                 'blank': '保管点名称不能为空'})
    address = serializers.CharField(max_length=200, required=False, allow_blank=True)
    manager = serializers.IntegerField(required=False, allow_null=True)

    def validate_code(self, value):
        value = value.strip()
        instance = self.context.get('instance')
        qs = CustodyLocation.objects.filter(code=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('保管点编码已存在')
        return value

    def validate_name(self, value):
        value = value.strip()
        instance = self.context.get('instance')
        qs = CustodyLocation.objects.filter(name=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('保管点名称已存在')
        return value

    def validate_manager(self, value):
        if value:
            if not User.objects.filter(pk=value).exists():
                raise serializers.ValidationError('负责人不存在')
        return value


class StockBalanceSerializer(serializers.ModelSerializer):
    """库存台账序列化器：四桶数量 + 总量"""
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    location_code = serializers.CharField(source='location.code', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = StockBalance
        fields = [
            'id', 'goods', 'goods_code', 'goods_name',
            'location', 'location_code', 'location_name',
            'available', 'reserved', 'in_transit', 'investigating', 'total',
            'updated_at'
        ]


class StockInLocationSerializer(serializers.Serializer):
    """地点入库序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    location = serializers.IntegerField(required=True, error_messages={'required': '请选择保管点'})
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0,
                                        required=True, error_messages={'required': '请输入入库数量'})
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('入库数量必须大于0')
        return value

    def validate(self, data):
        if not Goods.objects.filter(pk=data['goods']).exists():
            raise serializers.ValidationError({'goods': '货物不存在'})
        if not CustodyLocation.objects.filter(pk=data['location']).exists():
            raise serializers.ValidationError({'location': '保管点不存在'})
        return data


# ==================== 调拨 ====================

class TransferCreateSerializer(serializers.Serializer):
    """调拨申请序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    from_location = serializers.IntegerField(required=True, error_messages={'required': '请选择起运点'})
    to_location = serializers.IntegerField(required=True, error_messages={'required': '请选择接收点'})
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2, required=True,
                                        error_messages={'required': '请输入调拨数量'})
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('调拨数量必须大于0')
        return value

    def validate(self, data):
        if data['from_location'] == data['to_location']:
            raise serializers.ValidationError('起运点与接收点不能相同')
        if not Goods.objects.filter(pk=data['goods']).exists():
            raise serializers.ValidationError({'goods': '货物不存在'})
        for field, label in (('from_location', '起运点'), ('to_location', '接收点')):
            if not CustodyLocation.objects.filter(pk=data[field]).exists():
                raise serializers.ValidationError({field: f'{label}不存在'})
        return data


class TransferShipSerializer(serializers.Serializer):
    """起运确认序列化器"""
    seal_no = serializers.CharField(max_length=64, required=True,
                                    error_messages={'required': '请登记封签编号'})
    carrier = serializers.CharField(max_length=100, required=True,
                                    error_messages={'required': '请登记承运/押送人'})
    carrier_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    responsible_party = serializers.CharField(max_length=100, required=True,
                                              error_messages={'required': '请明确在途责任方'})
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)


class TransferSealChangeSerializer(serializers.Serializer):
    """封签变更序列化器"""
    new_seal_no = serializers.CharField(max_length=64, required=True,
                                        error_messages={'required': '请填写新封签编号'})
    reason = serializers.CharField(max_length=200, required=True,
                                   error_messages={'required': '请填写变更原因'})
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True)


class TransferReceiveSerializer(serializers.Serializer):
    """到达签收序列化器（支持部分签收）"""
    received_qty = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0, default=0)
    shortage_qty = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0, default=0)
    overage_qty = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=0, default=0)
    seal_no = serializers.CharField(max_length=64, required=False, allow_blank=True)
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, data):
        total = (data.get('received_qty', 0) + data.get('shortage_qty', 0)
                 + data.get('overage_qty', 0))
        if total <= 0:
            raise serializers.ValidationError('签收、短少、溢余数量不能全部为0')
        return data


class TransferCancelSerializer(serializers.Serializer):
    """取消（起运前/途中）序列化器"""
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)


class TransferDifferenceSerializer(serializers.ModelSerializer):
    """差异记录序列化器"""
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    resolution_display = serializers.CharField(source='get_resolution_display', read_only=True)
    handled_by_name = serializers.CharField(source='handled_by.username', read_only=True)

    class Meta:
        model = TransferDifference
        fields = [
            'id', 'transfer', 'kind', 'kind_display', 'quantity',
            'seal_no_at_arrival', 'resolution', 'resolution_display',
            'liability_party', 'handled_by', 'handled_by_name',
            'handled_at', 'remark', 'created_at'
        ]


class TransferResolveSerializer(serializers.Serializer):
    """差异处理序列化器"""
    resolution = serializers.ChoiceField(
        choices=['write_off', 'recover', 'confirm', 'return'],
        required=True, error_messages={'required': '请选择处理结论'})
    liability_party = serializers.CharField(max_length=100, required=False, allow_blank=True)
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)


class TransferSealChangeListSerializer(serializers.ModelSerializer):
    """封签变更记录序列化器"""
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = TransferSealChange
        fields = [
            'id', 'old_seal_no', 'new_seal_no', 'reason',
            'changed_by', 'changed_by_name', 'sealed_at'
        ]


class TransferEventSerializer(serializers.ModelSerializer):
    """调拨事件流水序列化器"""
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = TransferEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'quantity', 'detail',
            'operator', 'operator_name',
            'from_available', 'from_reserved', 'from_in_transit', 'from_investigating',
            'to_available', 'to_reserved', 'to_in_transit', 'to_investigating',
            'created_at'
        ]


class TransferListSerializer(serializers.ModelSerializer):
    """调拨单列表序列化器"""
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    from_location_name = serializers.CharField(source='from_location.name', read_only=True)
    to_location_name = serializers.CharField(source='to_location.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    applicant_name = serializers.CharField(source='applicant.username', read_only=True)
    remaining_in_transit = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True)
    unresolved_difference = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True)
    current_seal_no = serializers.CharField(read_only=True)

    class Meta:
        model = TransferRequest
        fields = [
            'id', 'code', 'goods', 'goods_code', 'goods_name',
            'from_location', 'from_location_name',
            'to_location', 'to_location_name',
            'quantity', 'status', 'status_display',
            'received_qty', 'shortage_qty', 'overage_qty',
            'resolved_qty', 'cancelled_qty',
            'remaining_in_transit', 'unresolved_difference',
            'seal_no', 'current_seal_no', 'carrier', 'responsible_party',
            'applicant', 'applicant_name', 'remark',
            'shipped_at', 'last_received_at', 'created_at'
        ]


class TransferDetailSerializer(TransferListSerializer):
    """调拨单详情序列化器：含封签变更、差异、事件流水"""
    seal_events = TransferSealChangeListSerializer(many=True, read_only=True)
    differences = TransferDifferenceSerializer(many=True, read_only=True)
    events = TransferEventSerializer(many=True, read_only=True)

    class Meta(TransferListSerializer.Meta):
        fields = TransferListSerializer.Meta.fields + [
            'seal_events', 'differences', 'events'
        ]
