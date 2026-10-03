# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 调拨与在途台账

同一机构下的多个保管点通过调拨单流转物资，全程数量守恒：

- **调拨申请** `POST /api/transfers/`：起点库存由「可用」转为「已预留」。
- **起运确认** `POST /api/transfers/<id>/dispatch/`：「已预留」转为「在途」，记录承运押运人、运输工具与封签号（在途责任）。
- **到达签收** `POST /api/transfers/<id>/receive/`：「在途」转为终点「可用」，支持部分签收；携带 `idempotency_key`（或 `Idempotency-Key` 请求头）的重复到达请求只入账一次。
- **取消调拨** `POST /api/transfers/<id>/cancel/`：释放全部待起运预留，可将在途数量退回起点（途中取消）。
- **封签变更** `POST /api/transfers/<id>/seal-changes/`：仅在途可变更，全程留痕，不影响数量。
- **差异登记** `POST /api/transfers/<id>/discrepancies/`：「在途」转为「待调查」。
- **差异处理** `POST /api/discrepancies/<id>/resolve/`：「待调查」按补交终点 / 退回起点 / 核销损失分配，可分批结案。
- **库存查询** `GET /api/stock/`：任意时点区分可用、已预留、在途、待调查与已核销数量（货物汇总 + 按保管点明细）。
- **事件台账** `GET /api/transfers/<id>/events/`：申请、起运、签收、取消、封签变更、差异登记与处理的完整留痕。

每条调拨明细满足守恒恒等式：`申请 = 已取消 + 待起运 + 已起运`，`已起运 = 在途 + 待调查 + 已签收 + 已退回 + 已核销`。`Goods.quantity` 为全机构在册总量（= Σ各点可用与预留 + 在途 + 待调查），仅因差异核销而减少。

保管点维护：`GET/POST /api/custody-points/`、`PUT/DELETE /api/custody-points/<id>/`。既有库存在迁移时落入「默认保管点」。

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
