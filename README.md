# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 多保管点与相互调拨

同一机构的多个保管点由本服务统一建账，不依赖任何外部系统。库存按
「货物 × 保管点」记一行台账 `StockBalance`，数量始终拆分为四个互斥的桶：

| 桶 | 含义 |
|---|---|
| `available` 可用 | 可对外发放或用于新调拨申请 |
| `reserved` 已预留 | 已被调拨申请占用但尚未起运 |
| `in_transit` 在途 | 已起运离开本点、尚未在接收点签收 |
| `investigating` 待调查 | 到达差异（短少/溢余）挂账待处理 |

任意时点查询台账都能区分四种数量；桶间只做转移，数据库 CHECK 约束保证
不出现负数，系统四桶总量除经审批的核销/退回外恒定。

### 调拨生命周期与守恒口径

```
申请 pending ──起运确认──▶ shipping ──部分签收──▶ receiving
   │                         │                      │
   │                         └──全额签收──────────▶ received
取消(cancel)                  │                      │
   ▼                          └──短少/溢余────────▶ investigating ──差异处理──▶ resolved
cancelled                     │
                           途中取消
                               ▼
                     cancelled_in_transit（在途余量退回起点，已签收留在终点）
```

- **申请**：起点 `可用 → 已预留`，不动其他桶。
- **起运确认**：起点 `已预留 → 在途`，必须登记封签编号、承运/押送人、在途责任方与起运时间。
- **到达签收**：起点在途出清、终点 `→ 可用`；支持多次部分签收，累计口径。
  - 短少：起点 `在途 → 待调查`（挂起运点）；
  - 溢余：终点挂 `待调查`，确认入库前不计可用。
- **途中取消**：当前在途余量 `起点在途 → 起点可用`，已签收部分留在终点，
  已登记差异仍挂待调查。
- **封签变更**：仅在途可做，原封签/新封签/原因/操作人全程留痕，不动数量。
- **差异处理**：短少可「核销（报损出系统）/追回（回起点可用）」；
  溢余可「确认入库（转终点可用）/退回（出系统）」，可登记责任方。
- **重复请求**：状态守卫拒绝跨状态的重复动作；关键动作支持 `request_id`
  幂等键，同键重放返回 409 且不发生第二次数量变动。

守恒恒等式：`申请量 = 累计签收 + 短少 + 途中取消退回 + 仍在途`，
每次数量变动都写一条 `TransferEvent`，附起讫两点四桶的变动后快照，差异后两边台账均可解释。

### 主要接口

| 方法/路径 | 说明 |
|---|---|
| `GET/POST /api/locations/` | 保管点列表/创建（有台账后删除为停用） |
| `GET /api/stock-balances/` | 四桶台账查询（可按 goods/location 过滤） |
| `POST /api/stock-in-location/` | 入库到指定保管点（进入可用桶） |
| `GET/POST /api/transfers/` | 调拨单列表/申请 |
| `GET /api/transfers/{id}/` | 单据详情（封签变更、差异、事件流水） |
| `POST /api/transfers/{id}/cancel/` | 起运前取消 |
| `POST /api/transfers/{id}/ship/` | 起运确认（封签/责任方） |
| `POST /api/transfers/{id}/seal-change/` | 在途封签变更 |
| `POST /api/transfers/{id}/receive/` | 到达签收（received_qty/shortage_qty/overage_qty） |
| `POST /api/transfers/{id}/cancel-in-transit/` | 途中取消 |
| `GET /api/transfer-differences/` | 差异记录列表 |
| `POST /api/transfer-differences/{id}/resolve/` | 差异定责处理 |

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```
