"""
库房管理模型
"""
from django.db import models
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


class CustodyPoint(models.Model):
    """保管点模型（同一机构下的多个物资保管地点）"""
    name = models.CharField('保管点名称', max_length=50, unique=True)
    code = models.CharField('保管点编码', max_length=20, unique=True)
    address = models.CharField('地址', max_length=200, blank=True)
    keeper_name = models.CharField('负责人', max_length=50, blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_custody_points', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_custody_point'
        verbose_name = '保管点'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class StockBalance(models.Model):
    """保管点库存余额：同一货物在每个保管点分为可用与已预留两桶"""
    custody_point = models.ForeignKey(
        CustodyPoint, on_delete=models.CASCADE,
        related_name='balances', verbose_name='保管点'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='balances', verbose_name='货物'
    )
    available_quantity = models.DecimalField('可用数量', max_digits=12, decimal_places=2, default=0)
    reserved_quantity = models.DecimalField('已预留数量', max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_stock_balance'
        verbose_name = '库存余额'
        verbose_name_plural = verbose_name
        unique_together = ['custody_point', 'goods']

    def __str__(self):
        return f"{self.custody_point.name} - {self.goods.name}"


class TransferOrder(models.Model):
    """调拨单模型"""
    STATUS_CHOICES = [
        ('pending', '待起运'),
        ('in_transit', '在途'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    ]

    transfer_no = models.CharField('调拨单号', max_length=30, unique=True)
    origin_point = models.ForeignKey(
        CustodyPoint, on_delete=models.PROTECT,
        related_name='origin_transfers', verbose_name='起点保管点'
    )
    destination_point = models.ForeignKey(
        CustodyPoint, on_delete=models.PROTECT,
        related_name='destination_transfers', verbose_name='终点保管点'
    )
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    applicant = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='transfer_applications', verbose_name='申请人'
    )
    carrier_name = models.CharField('承运押运人', max_length=50, blank=True)
    carrier_phone = models.CharField('承运人电话', max_length=20, blank=True)
    vehicle_no = models.CharField('运输工具', max_length=50, blank=True)
    seal_no = models.CharField('当前封签号', max_length=50, blank=True)
    dispatched_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dispatched_transfers', verbose_name='起运确认人'
    )
    dispatched_at = models.DateTimeField('起运时间', null=True, blank=True)
    completed_at = models.DateTimeField('完结时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_transfer_order'
        verbose_name = '调拨单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.transfer_no


class TransferItem(models.Model):
    """调拨明细模型

    数量守恒恒等式：
        applied = cancelled + pending_shipment + shipped
        shipped = in_transit + disputed + received + returned + lost
    其中 pending_shipment / in_transit 为派生量，见下方属性。
    """
    transfer = models.ForeignKey(
        TransferOrder, on_delete=models.CASCADE,
        related_name='items', verbose_name='调拨单'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='transfer_items', verbose_name='货物'
    )
    applied_quantity = models.DecimalField('申请数量', max_digits=12, decimal_places=2)
    cancelled_quantity = models.DecimalField('已取消数量', max_digits=12, decimal_places=2, default=0)
    shipped_quantity = models.DecimalField('已起运数量', max_digits=12, decimal_places=2, default=0)
    received_quantity = models.DecimalField('已签收数量', max_digits=12, decimal_places=2, default=0)
    returned_quantity = models.DecimalField('已退回数量', max_digits=12, decimal_places=2, default=0)
    lost_quantity = models.DecimalField('已核销数量', max_digits=12, decimal_places=2, default=0)
    disputed_quantity = models.DecimalField('待调查数量', max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'wh_transfer_item'
        verbose_name = '调拨明细'
        verbose_name_plural = verbose_name
        unique_together = ['transfer', 'goods']

    def __str__(self):
        return f"{self.transfer.transfer_no} - {self.goods.name}"

    @property
    def pending_shipment_quantity(self):
        """待起运数量（仍预留于起点）"""
        return self.applied_quantity - self.cancelled_quantity - self.shipped_quantity

    @property
    def in_transit_quantity(self):
        """在途数量"""
        return (
            self.shipped_quantity - self.received_quantity - self.returned_quantity
            - self.lost_quantity - self.disputed_quantity
        )


class SealChange(models.Model):
    """封签变更记录模型"""
    transfer = models.ForeignKey(
        TransferOrder, on_delete=models.CASCADE,
        related_name='seal_changes', verbose_name='调拨单'
    )
    old_seal_no = models.CharField('原封签号', max_length=50)
    new_seal_no = models.CharField('新封签号', max_length=50)
    reason = models.TextField('变更原因', blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='seal_changes', verbose_name='变更人'
    )
    created_at = models.DateTimeField('变更时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_seal_change'
        verbose_name = '封签变更记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transfer.transfer_no}: {self.old_seal_no} -> {self.new_seal_no}"


class Discrepancy(models.Model):
    """差异记录模型（在途/签收差异的待调查案件）"""
    STATUS_CHOICES = [
        ('open', '待调查'),
        ('resolved', '已结案'),
    ]

    transfer = models.ForeignKey(
        TransferOrder, on_delete=models.CASCADE,
        related_name='discrepancies', verbose_name='调拨单'
    )
    item = models.ForeignKey(
        TransferItem, on_delete=models.CASCADE,
        related_name='discrepancies', verbose_name='调拨明细'
    )
    quantity = models.DecimalField('差异数量', max_digits=12, decimal_places=2)
    delivered_quantity = models.DecimalField('补交终点数量', max_digits=12, decimal_places=2, default=0)
    returned_quantity = models.DecimalField('退回起点数量', max_digits=12, decimal_places=2, default=0)
    lost_quantity = models.DecimalField('核销损失数量', max_digits=12, decimal_places=2, default=0)
    reason = models.TextField('差异原因')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='open')
    raised_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='raised_discrepancies', verbose_name='登记人'
    )
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_discrepancies', verbose_name='处理人'
    )
    remark = models.TextField('处理说明', blank=True)
    created_at = models.DateTimeField('登记时间', auto_now_add=True)
    resolved_at = models.DateTimeField('结案时间', null=True, blank=True)

    class Meta:
        db_table = 'wh_discrepancy'
        verbose_name = '差异记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transfer.transfer_no} - {self.item.goods.name} - {self.quantity}"

    @property
    def remaining_quantity(self):
        """剩余待调查数量"""
        return (
            self.quantity - self.delivered_quantity
            - self.returned_quantity - self.lost_quantity
        )


class TransferEvent(models.Model):
    """调拨事件台账模型（每一步状态变更留痕，用于解释数量去向）"""
    EVENT_CHOICES = [
        ('apply', '调拨申请'),
        ('dispatch', '起运确认'),
        ('receive', '到达签收'),
        ('cancel', '取消调拨'),
        ('seal_change', '封签变更'),
        ('dispute_raise', '差异登记'),
        ('dispute_resolve', '差异处理'),
    ]

    transfer = models.ForeignKey(
        TransferOrder, on_delete=models.CASCADE,
        related_name='events', verbose_name='调拨单'
    )
    event_type = models.CharField('事件类型', max_length=20, choices=EVENT_CHOICES)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='transfer_events', verbose_name='操作人'
    )
    detail = models.JSONField('事件明细', default=dict, blank=True)
    created_at = models.DateTimeField('发生时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_event'
        verbose_name = '调拨事件'
        verbose_name_plural = verbose_name
        ordering = ['created_at']

    def __str__(self):
        return f"{self.transfer.transfer_no} - {self.get_event_type_display()}"


class IdempotencyRecord(models.Model):
    """幂等记录模型（防止重复请求重复入账）"""
    key = models.CharField('幂等键', max_length=64, unique=True)
    scope = models.CharField('业务范围', max_length=50)
    response = models.JSONField('已存响应', default=dict)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_idempotency_record'
        verbose_name = '幂等记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.scope} - {self.key}"
