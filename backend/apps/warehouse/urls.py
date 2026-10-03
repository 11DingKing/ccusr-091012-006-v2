"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, StockInListView, StockOutListView,
    WarningListView, ApprovalListView
)
from .transfer_views import (
    LocationListView, LocationAllView, LocationDetailView,
    StockBalanceListView, StockInLocationView,
    TransferListView, TransferDetailView, TransferCancelView,
    TransferShipView, TransferSealChangeView, TransferReceiveView,
    TransferCancelInTransitView,
    TransferDifferenceListView, TransferDifferenceResolveView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # 保管点管理
    path('locations/', LocationListView.as_view(), name='location-list'),
    path('locations/all/', LocationAllView.as_view(), name='location-all'),
    path('locations/<int:pk>/', LocationDetailView.as_view(), name='location-detail'),

    # 库存台账（四桶数量查询）与地点入库
    path('stock-balances/', StockBalanceListView.as_view(), name='stock-balance-list'),
    path('stock-in-location/', StockInLocationView.as_view(), name='stock-in-location'),

    # 调拨全生命周期
    path('transfers/', TransferListView.as_view(), name='transfer-list'),
    path('transfers/<int:pk>/', TransferDetailView.as_view(), name='transfer-detail'),
    path('transfers/<int:pk>/cancel/', TransferCancelView.as_view(), name='transfer-cancel'),
    path('transfers/<int:pk>/ship/', TransferShipView.as_view(), name='transfer-ship'),
    path('transfers/<int:pk>/seal-change/', TransferSealChangeView.as_view(), name='transfer-seal-change'),
    path('transfers/<int:pk>/receive/', TransferReceiveView.as_view(), name='transfer-receive'),
    path('transfers/<int:pk>/cancel-in-transit/', TransferCancelInTransitView.as_view(), name='transfer-cancel-in-transit'),

    # 调拨差异
    path('transfer-differences/', TransferDifferenceListView.as_view(), name='transfer-difference-list'),
    path('transfer-differences/<int:pk>/resolve/', TransferDifferenceResolveView.as_view(), name='transfer-difference-resolve'),
]
