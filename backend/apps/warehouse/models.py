"""
库房管理模型
"""
from decimal import Decimal

from django.db import models
from django.db.models import Q
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


# ==================== 保管点与库存台账 ====================

class CustodyLocation(models.Model):
    """保管点：同一机构内多个相互调拨的实物保管地点"""

    code = models.CharField('保管点编码', max_length=20, unique=True)
    name = models.CharField('保管点名称', max_length=50, unique=True)
    address = models.CharField('地点', max_length=200, blank=True)
    manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='managed_locations', verbose_name='负责人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_custody_location'
        verbose_name = '保管点'
        verbose_name_plural = verbose_name
        ordering = ['code']

    def __str__(self):
        return self.name


class StockBalance(models.Model):
    """
    库存台账：货物在单个保管点上的数量始终拆分为四个互斥的桶，
    任意时点四桶之和即为该地点该货物的全部实物口径，
    桶间只做转移，不允许凭空增减（CHECK 约束保证不为负）。

    - available     可用：可对外发放或用于新调拨申请
    - reserved      已预留：已被调拨申请占用但尚未起运
    - in_transit    在途：已起运离开本点、尚未在终点签收
    - investigating 待调查：发生差异后等待定责/处理的数量
    """

    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='balances', verbose_name='货物'
    )
    location = models.ForeignKey(
        CustodyLocation, on_delete=models.PROTECT,
        related_name='balances', verbose_name='保管点'
    )
    available = models.DecimalField('可用数量', max_digits=14, decimal_places=2, default=0)
    reserved = models.DecimalField('已预留数量', max_digits=14, decimal_places=2, default=0)
    in_transit = models.DecimalField('在途数量', max_digits=14, decimal_places=2, default=0)
    investigating = models.DecimalField('待调查数量', max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_stock_balance'
        verbose_name = '库存台账'
        verbose_name_plural = verbose_name
        unique_together = ['goods', 'location']
        constraints = [
            models.CheckConstraint(
                check=Q(available__gte=0) & Q(reserved__gte=0)
                & Q(in_transit__gte=0) & Q(investigating__gte=0),
                name='stock_balance_buckets_non_negative',
            ),
        ]

    def __str__(self):
        return f"{self.goods.name}@{self.location.name}"

    @property
    def total(self):
        return self.available + self.reserved + self.in_transit + self.investigating


# ==================== 调拨 ====================

class TransferRequest(models.Model):
    """
    调拨申请及其全生命周期单据。守恒口径：

        quantity = 累计签收 + 短少 + 途中取消退回 + 仍在途待签收
    短少/溢余经差异处理后全部计入 resolved_qty，任何处理都不改变
    “签收 + 短少 + 退回 + 在途 = 申请量”这一在途口径。

    状态机：
        pending   已申请，起点数量已从可用转为已预留
        shipping  已起运确认，数量在途，封签与在途责任方已登记
        receiving 部分签收后仍有在途余量，可继续签收或途中取消
        received  全部数量签收完毕（无差异的一次性签收）
        cancelled 起运前整单取消，预留数量全部回到起点可用
        cancelled_in_transit 途中取消：在途余量退回起点，已签收部分留在终点
        investigating 到达差异待调查，差异数量已分别挂入起/终点待调查桶
        resolved  差异全部处理完毕，单据关闭
    """

    STATUS_CHOICES = [
        ('pending', '待起运'),
        ('shipping', '在途'),
        ('receiving', '部分签收'),
        ('received', '已签收'),
        ('cancelled', '已取消'),
        ('cancelled_in_transit', '途中取消'),
        ('investigating', '差异待调查'),
        ('resolved', '差异已处理'),
    ]

    code = models.CharField('调拨单号', max_length=32, unique=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='transfers', verbose_name='货物'
    )
    from_location = models.ForeignKey(
        CustodyLocation, on_delete=models.PROTECT,
        related_name='outbound_transfers', verbose_name='起运点'
    )
    to_location = models.ForeignKey(
        CustodyLocation, on_delete=models.PROTECT,
        related_name='inbound_transfers', verbose_name='接收点'
    )
    quantity = models.DecimalField('申请数量', max_digits=14, decimal_places=2)
    status = models.CharField('状态', max_length=24, choices=STATUS_CHOICES, default='pending')

    applicant = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='applied_transfers', verbose_name='申请人'
    )
    remark = models.TextField('申请备注', blank=True)

    # 起运确认：封签与在途责任
    seal_no = models.CharField('封签编号', max_length=64, blank=True)
    carrier = models.CharField('承运/押送人', max_length=100, blank=True)
    carrier_phone = models.CharField('承运人联系电话', max_length=20, blank=True)
    responsible_party = models.CharField('在途责任方', max_length=100, blank=True)
    shipped_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipped_transfers', verbose_name='起运确认人'
    )
    shipped_at = models.DateTimeField('起运时间', null=True, blank=True)

    # 到达签收（累计口径，支持多次部分签收）
    received_qty = models.DecimalField('累计签收数量', max_digits=14, decimal_places=2, default=0)
    shortage_qty = models.DecimalField('累计短少数量', max_digits=14, decimal_places=2, default=0)
    overage_qty = models.DecimalField('累计溢余数量', max_digits=14, decimal_places=2, default=0)
    resolved_qty = models.DecimalField('已处理差异数量', max_digits=14, decimal_places=2, default=0)
    cancelled_qty = models.DecimalField('途中取消退回数量', max_digits=14, decimal_places=2, default=0)
    last_received_at = models.DateTimeField('最近签收时间', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_transfer_request'
        verbose_name = '调拨申请'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=Q(quantity__gt=0),
                name='transfer_quantity_positive',
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.goods.name} {self.from_location_id}->{self.to_location_id}"

    @property
    def remaining_in_transit(self):
        """当前仍在途、尚未签收或退回的数量"""
        accounted = self.received_qty + self.shortage_qty + self.cancelled_qty
        remaining = self.quantity - accounted
        return remaining if remaining > 0 else Decimal('0')

    @property
    def unresolved_difference(self):
        """尚未处理完结的差异数量（短少+溢余-已处理）"""
        pending = self.shortage_qty + self.overage_qty - self.resolved_qty
        return pending if pending > 0 else Decimal('0')

    @property
    def current_seal_no(self):
        """当前有效封签：取最近一条封签变更记录，缺省回退到起运封签"""
        seal = self.seal_events.order_by('-sealed_at', '-id').first()
        return seal.new_seal_no if seal else self.seal_no


class TransferSealChange(models.Model):
    """封签变更记录：仅在途可变更，原封签为何被替换必须留痕"""

    transfer = models.ForeignKey(
        TransferRequest, on_delete=models.CASCADE,
        related_name='seal_events', verbose_name='调拨单'
    )
    old_seal_no = models.CharField('原封签编号', max_length=64, blank=True)
    new_seal_no = models.CharField('新封签编号', max_length=64)
    reason = models.CharField('变更原因', max_length=200)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='seal_changes', verbose_name='变更操作人'
    )
    sealed_at = models.DateTimeField('变更时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_seal_change'
        verbose_name = '封签变更'
        verbose_name_plural = verbose_name
        ordering = ['-sealed_at', '-id']

    def __str__(self):
        return f"{self.transfer.code} {self.old_seal_no}->{self.new_seal_no}"


class TransferDifference(models.Model):
    """
    到达差异处理单：每条对应一次差异登记（短少/溢余）及其处理结论。

    短少(shortage)：起运数量 > 实到数量，差异先挂【起运点】待调查；
    溢余(overage)：实到数量 > 起运数量，差异先挂【接收点】待调查。
    """

    KIND_CHOICES = [
        ('shortage', '短少'),
        ('overage', '溢余'),
    ]
    # 短少：write_off 核销（报损，数量出系统）/ recover 追回（实物回起点可用）
    # 溢余：confirm 确认入库（转入终点可用）/ return 退回（数量出系统）
    RESOLUTION_CHOICES = [
        ('pending', '待处理'),
        ('write_off', '核销'),
        ('recover', '追回'),
        ('confirm', '确认入库'),
        ('return', '退回'),
    ]

    transfer = models.ForeignKey(
        TransferRequest, on_delete=models.CASCADE,
        related_name='differences', verbose_name='调拨单'
    )
    kind = models.CharField('差异类型', max_length=10, choices=KIND_CHOICES)
    quantity = models.DecimalField('差异数量', max_digits=14, decimal_places=2)
    seal_no_at_arrival = models.CharField('签收时封签编号', max_length=64, blank=True)
    resolution = models.CharField(
        '处理结论', max_length=20, choices=RESOLUTION_CHOICES, default='pending'
    )
    liability_party = models.CharField('责任方认定', max_length=100, blank=True)
    handled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handled_differences', verbose_name='处理人'
    )
    handled_at = models.DateTimeField('处理时间', null=True, blank=True)
    remark = models.TextField('处理说明', blank=True)
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_difference'
        verbose_name = '调拨差异'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=Q(quantity__gt=0),
                name='transfer_difference_quantity_positive',
            ),
        ]

    def __str__(self):
        return f"{self.transfer.code} {self.get_kind_display()} {self.quantity}"


class TransferEvent(models.Model):
    """
    调拨事件流水：每一次数量/状态变动都记录一行，含起运点与接收点
    各桶的变动后快照，差异发生后两边台账都可凭此解释。
    """

    EVENT_CHOICES = [
        ('create', '申请'),
        ('cancel', '取消申请'),
        ('ship', '起运确认'),
        ('receive', '到达签收'),
        ('cancel_in_transit', '途中取消'),
        ('seal_change', '封签变更'),
        ('difference', '差异登记'),
        ('resolve', '差异处理'),
    ]

    transfer = models.ForeignKey(
        TransferRequest, on_delete=models.CASCADE,
        related_name='events', verbose_name='调拨单'
    )
    event_type = models.CharField('事件类型', max_length=20, choices=EVENT_CHOICES)
    quantity = models.DecimalField('涉及数量', max_digits=14, decimal_places=2, default=0)
    detail = models.CharField('事件说明', max_length=500, blank=True)
    # 动作幂等键：同一调拨单同一动作携带相同键的重试只生效一次
    request_id = models.CharField('请求幂等键', max_length=64, blank=True, default='')
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='transfer_events', verbose_name='操作人'
    )
    # 变动后四桶快照，便于任意时点核对
    from_available = models.DecimalField('起点可用', max_digits=14, decimal_places=2, default=0)
    from_reserved = models.DecimalField('起点预留', max_digits=14, decimal_places=2, default=0)
    from_in_transit = models.DecimalField('起点在途', max_digits=14, decimal_places=2, default=0)
    from_investigating = models.DecimalField('起点待调查', max_digits=14, decimal_places=2, default=0)
    to_available = models.DecimalField('终点可用', max_digits=14, decimal_places=2, default=0)
    to_reserved = models.DecimalField('终点预留', max_digits=14, decimal_places=2, default=0)
    to_in_transit = models.DecimalField('终点在途', max_digits=14, decimal_places=2, default=0)
    to_investigating = models.DecimalField('终点待调查', max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField('发生时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_event'
        verbose_name = '调拨事件流水'
        verbose_name_plural = verbose_name
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['transfer', 'event_type', 'request_id'],
                condition=~Q(request_id=''),
                name='transfer_event_idempotency_unique',
            ),
        ]

    def __str__(self):
        return f"{self.transfer.code} {self.get_event_type_display()} {self.quantity}"
