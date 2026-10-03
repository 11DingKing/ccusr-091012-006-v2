# 既有库存迁入默认保管点的数据迁移
from django.db import migrations


DEFAULT_POINT_CODE = 'DEFAULT'
DEFAULT_POINT_NAME = '默认保管点'


def migrate_stock_to_default_point(apps, schema_editor):
    """将既有 Goods.quantity 全部落入默认保管点的可用数量。"""
    CustodyPoint = apps.get_model('warehouse', 'CustodyPoint')
    StockBalance = apps.get_model('warehouse', 'StockBalance')
    Goods = apps.get_model('warehouse', 'Goods')

    point, _ = CustodyPoint.objects.get_or_create(
        code=DEFAULT_POINT_CODE,
        defaults={'name': DEFAULT_POINT_NAME},
    )
    for goods in Goods.objects.all():
        StockBalance.objects.get_or_create(
            custody_point=point,
            goods=goods,
            defaults={'available_quantity': goods.quantity, 'reserved_quantity': 0},
        )


def reverse_stock_migration(apps, schema_editor):
    """回滚：仅当默认保管点未发生任何调拨时，清除迁移生成的余额与保管点。"""
    CustodyPoint = apps.get_model('warehouse', 'CustodyPoint')
    StockBalance = apps.get_model('warehouse', 'StockBalance')

    try:
        point = CustodyPoint.objects.get(code=DEFAULT_POINT_CODE)
    except CustodyPoint.DoesNotExist:
        return
    if point.origin_transfers.exists() or point.destination_transfers.exists():
        return
    StockBalance.objects.filter(custody_point=point).delete()
    point.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0002_custodypoint_idempotencyrecord_transferorder_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_stock_to_default_point, reverse_stock_migration),
    ]
