"""
调拨全生命周期测试。

核心不变量：
- 任意时点系统内总量 = 各保管点四桶之和；除经审批的核销/退出外，总量恒等。
- 在途口径：申请量 = 累计签收 + 短少 + 途中取消退回 + 仍在途。
- 所有台账桶均不得为负（数据库 CHECK 兜底）。
"""
from decimal import Decimal

from django.db import IntegrityError
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.warehouse.models import (
    Category, CustodyLocation, Goods, StockBalance, TransferDifference,
    TransferEvent, TransferRequest, Unit, Variety,
)
from apps.warehouse import transfer_services as svc

D = Decimal


class TransferFixture(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user("transfer-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety, name="执法记录终端", code="DEV-T1",
            quantity=D("100"), warning_threshold=D("5"),
        )
        self.loc_a = CustodyLocation.objects.create(code="A", name="中心监管仓")
        self.loc_b = CustodyLocation.objects.create(code="B", name="东区保管点")
        # A 点初始入库 100
        svc.stock_into_location(self.goods.id, self.loc_a.id, D("100"), self.user)

    def balance(self, location):
        return StockBalance.objects.get(goods=self.goods, location=location)

    def system_total(self):
        total = D("0")
        for b in StockBalance.objects.filter(goods=self.goods):
            total += b.available + b.reserved + b.in_transit + b.investigating
        return total

    def create_ship(self, qty, seal="SEAL-1", carrier="押运员张某", party="押运中队"):
        t = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D(str(qty)), self.user)
        svc.ship_transfer(t.id, self.user, seal, carrier, party)
        return t


class StockBalanceModelTest(TransferFixture):
    def test_buckets_non_negative_constraint(self):
        b = self.balance(self.loc_a)
        b.available = D("-1")
        with self.assertRaises(IntegrityError):
            b.save()

    def test_balance_unique_per_goods_location(self):
        with self.assertRaises(IntegrityError):
            StockBalance.objects.create(goods=self.goods, location=self.loc_a)

    def test_legacy_goods_quantity_mirrors_system_total(self):
        """旧口径 Goods.quantity 始终等于四桶全系统总量（含核销出系统）"""
        t = self.create_ship(10)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, D("100"))  # 桶间转移不变总量
        svc.receive_transfer(t.id, self.user, D("8"), shortage_qty=D("2"))
        diff = t.differences.get()
        svc.resolve_difference(diff.id, self.user, "write_off")
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, D("98"))  # 核销后同步减少


class HappyPathTest(TransferFixture):
    def test_apply_ship_receive_keeps_conservation_and_buckets(self):
        # 1) 申请：可用 -> 已预留
        t = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D("30"), self.user)
        a, b = self.balance(self.loc_a), self.balance(self.loc_b)
        self.assertEqual((a.available, a.reserved, a.in_transit, a.investigating),
                         (D("70"), D("30"), D("0"), D("0")))
        self.assertEqual(t.status, "pending")
        self.assertEqual(self.system_total(), D("100"))

        # 2) 起运：已预留 -> 在途，封签与责任方登记
        svc.ship_transfer(t.id, self.user, "SEAL-001", "押运员张某", "押运中队")
        a = self.balance(self.loc_a)
        self.assertEqual((a.available, a.reserved, a.in_transit), (D("70"), D("0"), D("30")))
        self.assertEqual(self.system_total(), D("100"))

        # 3) 一次性全额签收：在途 -> 终点可用
        svc.receive_transfer(t.id, self.user, D("30"), seal_no="SEAL-001")
        a, b = self.balance(self.loc_a), self.balance(self.loc_b)
        self.assertEqual((a.available, a.in_transit), (D("70"), D("0")))
        self.assertEqual(b.available, D("30"))
        t.refresh_from_db()
        self.assertEqual(t.status, "received")
        self.assertEqual(self.system_total(), D("100"))

        kinds = list(t.events.values_list("event_type", flat=True))
        self.assertEqual(kinds, ["create", "ship", "receive"])
        # 流水快照可解释两边台账
        last = t.events.get(event_type="receive")
        self.assertEqual(last.from_available, D("70"))
        self.assertEqual(last.to_available, D("30"))

    def test_cancel_before_shipment_returns_reserved(self):
        t = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D("20"), self.user)
        svc.cancel_transfer(t.id, self.user)
        a = self.balance(self.loc_a)
        self.assertEqual((a.available, a.reserved), (D("100"), D("0")))
        t.refresh_from_db()
        self.assertEqual(t.status, "cancelled")
        with self.assertRaises(svc.TransferError):
            svc.cancel_transfer(t.id, self.user)

    def test_insufficient_available_rejected(self):
        with self.assertRaises(svc.TransferError):
            svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D("101"), self.user)


class PartialReceiveTest(TransferFixture):
    def test_multiple_partial_receipts(self):
        t = self.create_ship(10)
        svc.receive_transfer(t.id, self.user, D("4"))
        t.refresh_from_db()
        self.assertEqual(t.status, "receiving")
        self.assertEqual(t.remaining_in_transit, D("6"))
        b = self.balance(self.loc_b)
        self.assertEqual(b.available, D("4"))

        svc.receive_transfer(t.id, self.user, D("6"))
        t.refresh_from_db()
        self.assertEqual(t.status, "received")
        self.assertEqual(self.balance(self.loc_b).available, D("10"))
        self.assertEqual(self.system_total(), D("100"))

    def test_receive_cannot_exceed_remaining(self):
        t = self.create_ship(10)
        with self.assertRaises(svc.TransferError):
            svc.receive_transfer(t.id, self.user, D("11"))
        with self.assertRaises(svc.TransferError):
            svc.receive_transfer(t.id, self.user, D("8"), shortage_qty=D("3"))

    def test_duplicate_arrival_after_completion_rejected(self):
        t = self.create_ship(5)
        # 首次签收携带幂等键
        svc.receive_transfer(t.id, self.user, D("5"), request_id="REQ-1")
        # 无幂等键的重复到达：状态守卫拒绝
        with self.assertRaises(svc.TransferError) as ctx:
            svc.receive_transfer(t.id, self.user, D("5"))
        self.assertEqual(ctx.exception.code, 400)
        # 同键重放：明确 409 冲突
        with self.assertRaises(svc.IdempotentReplay):
            svc.receive_transfer(t.id, self.user, D("5"), request_id="REQ-1")
        # 换新键的重复到达同样被状态守卫拦截，不会二次入账
        with self.assertRaises(svc.TransferError):
            svc.receive_transfer(t.id, self.user, D("5"), request_id="REQ-2")
        # 数量纹丝不动
        self.assertEqual(self.balance(self.loc_b).available, D("5"))
        self.assertEqual(self.system_total(), D("100"))

    def test_idempotent_replay_does_not_move_stock(self):
        t = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D("8"), self.user)
        svc.ship_transfer(t.id, self.user, "S", "车", "队", request_id="ship-1")
        with self.assertRaises(svc.IdempotentReplay):
            svc.ship_transfer(t.id, self.user, "S", "车", "队", request_id="ship-1")
        t.refresh_from_db()
        self.assertEqual(t.status, "shipping")
        self.assertEqual(self.balance(self.loc_a).in_transit, D("8"))


class CancelInTransitTest(TransferFixture):
    def test_cancel_after_partial_receipt(self):
        t = self.create_ship(50)
        svc.receive_transfer(t.id, self.user, D("20"))
        svc.cancel_in_transit(t.id, self.user)
        t.refresh_from_db()
        self.assertEqual(t.status, "cancelled_in_transit")
        self.assertEqual(t.cancelled_qty, D("30"))
        a, b = self.balance(self.loc_a), self.balance(self.loc_b)
        self.assertEqual((a.available, a.in_transit), (D("80"), D("0")))
        self.assertEqual(b.available, D("20"))  # 已签收留在终点
        self.assertEqual(self.system_total(), D("100"))
        # 再次途中取消无在途可退
        with self.assertRaises(svc.TransferError):
            svc.cancel_in_transit(t.id, self.user)

    def test_cancel_full_shipment_in_transit(self):
        t = self.create_ship(40)
        svc.cancel_in_transit(t.id, self.user)
        t.refresh_from_db()
        self.assertEqual(t.status, "cancelled_in_transit")
        a = self.balance(self.loc_a)
        self.assertEqual((a.available, a.in_transit), (D("100"), D("0")))


class SealChangeTest(TransferFixture):
    def test_seal_change_only_in_transit_and_logged(self):
        t = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                D("10"), self.user)
        # 未起运不能变更封签
        with self.assertRaises(svc.TransferError):
            svc.change_seal(t.id, self.user, "SEAL-2", "途中查验换封")
        svc.ship_transfer(t.id, self.user, "SEAL-1", "车", "队")
        with self.assertRaises(svc.TransferError):
            svc.change_seal(t.id, self.user, "SEAL-1", "重复封签")
        with self.assertRaises(svc.TransferError):
            svc.change_seal(t.id, self.user, "", "缺编号")

        svc.change_seal(t.id, self.user, "SEAL-2", "途中查验换封", request_id="sc-1")
        self.assertEqual(t.current_seal_no, "SEAL-2")
        # 同键重复变更拒绝
        with self.assertRaises(svc.IdempotentReplay):
            svc.change_seal(t.id, self.user, "SEAL-3", "重试", request_id="sc-1")
        t.refresh_from_db()
        self.assertEqual(t.current_seal_no, "SEAL-2")
        # 封签变更不动数量
        a = self.balance(self.loc_a)
        self.assertEqual((a.available, a.in_transit), (D("90"), D("10")))

        # 部分签收后仍有在途，允许继续变更
        svc.receive_transfer(t.id, self.user, D("4"))
        svc.change_seal(t.id, self.user, "SEAL-3", "二次换封")
        self.assertEqual(t.current_seal_no, "SEAL-3")
        # 全部签收后不能再变更
        svc.receive_transfer(t.id, self.user, D("6"))
        with self.assertRaises(svc.TransferError):
            svc.change_seal(t.id, self.user, "SEAL-4", "已到终点")
        self.assertEqual(t.seal_events.count(), 2)


class ShortageTest(TransferFixture):
    def test_shortage_write_off_exits_system_after_approval(self):
        t = self.create_ship(10)
        svc.receive_transfer(t.id, self.user, D("8"), shortage_qty=D("2"),
                             seal_no="SEAL-1")
        t.refresh_from_db()
        self.assertEqual(t.status, "investigating")
        a, b = self.balance(self.loc_a), self.balance(self.loc_b)
        # 短少挂【起点】待调查，终点只入合格签收量
        self.assertEqual((a.in_transit, a.investigating, a.available),
                         (D("0"), D("2"), D("90")))
        self.assertEqual(b.available, D("8"))
        self.assertEqual(self.system_total(), D("100"))  # 待调查仍在系统内

        diff = t.differences.get(kind="shortage")
        svc.resolve_difference(diff.id, self.user, "write_off",
                               liability_party="押运中队")
        a = self.balance(self.loc_a)
        self.assertEqual(a.investigating, D("0"))
        self.assertEqual(a.available, D("90"))
        t.refresh_from_db()
        self.assertEqual(t.status, "resolved")
        # 核销是经审批的数量出系统
        self.assertEqual(self.system_total(), D("98"))

        # 差异不可重复处理
        with self.assertRaises(svc.TransferError):
            svc.resolve_difference(diff.id, self.user, "recover")

    def test_shortage_recover_returns_to_available(self):
        t = self.create_ship(10)
        svc.receive_transfer(t.id, self.user, D("0"), shortage_qty=D("10"))
        diff = t.differences.get()
        svc.resolve_difference(diff.id, self.user, "recover")
        a = self.balance(self.loc_a)
        self.assertEqual((a.available, a.investigating), (D("100"), D("0")))
        self.assertEqual(self.system_total(), D("100"))

    def test_shortage_cannot_use_overage_resolution(self):
        t = self.create_ship(5)
        svc.receive_transfer(t.id, self.user, D("4"), shortage_qty=D("1"))
        diff = t.differences.get()
        with self.assertRaises(svc.TransferError):
            svc.resolve_difference(diff.id, self.user, "confirm")


class OverageTest(TransferFixture):
    def test_overage_confirm_then_reject_duplicate(self):
        t = self.create_ship(10)
        svc.receive_transfer(t.id, self.user, D("10"), overage_qty=D("1"))
        t.refresh_from_db()
        self.assertEqual(t.status, "investigating")
        b = self.balance(self.loc_b)
        # 溢余挂【终点】待调查，确认前不计可用
        self.assertEqual((b.available, b.investigating), (D("10"), D("1")))

        diff = t.differences.get(kind="overage")
        svc.resolve_difference(diff.id, self.user, "confirm")
        b = self.balance(self.loc_b)
        self.assertEqual((b.available, b.investigating), (D("11"), D("0")))
        t.refresh_from_db()
        self.assertEqual(t.status, "resolved")
        self.assertEqual(self.system_total(), D("101"))

    def test_overage_return_exits_system(self):
        t = self.create_ship(10)
        svc.receive_transfer(t.id, self.user, D("10"), overage_qty=D("2"))
        diff = t.differences.get()
        svc.resolve_difference(diff.id, self.user, "return")
        b = self.balance(self.loc_b)
        self.assertEqual((b.available, b.investigating), (D("10"), D("0")))
        self.assertEqual(self.system_total(), D("100"))


class MixedLifecycleTest(TransferFixture):
    def test_partial_then_shortage_then_cancel_then_resolve(self):
        """部分签收 + 短少 + 途中取消并存，差异处理后单据关闭，全程守恒"""
        t = self.create_ship(100)
        # 先签收 60
        svc.receive_transfer(t.id, self.user, D("60"))
        t.refresh_from_db()
        self.assertEqual(t.status, "receiving")
        # 再到货：短少 10，其余 30 仍在途
        svc.receive_transfer(t.id, self.user, D("0"), shortage_qty=D("10"))
        t.refresh_from_db()
        self.assertEqual(t.status, "receiving")  # 还有 30 在途
        self.assertEqual(t.remaining_in_transit, D("30"))
        # 途中取消剩余 30
        svc.cancel_in_transit(t.id, self.user)
        t.refresh_from_db()
        self.assertEqual(t.status, "cancelled_in_transit")
        a, b = self.balance(self.loc_a), self.balance(self.loc_b)
        self.assertEqual((a.available, a.investigating), (D("30"), D("10")))
        self.assertEqual(b.available, D("60"))
        self.assertEqual(self.system_total(), D("100"))
        # 处理短少（核销）后单据关闭
        diff = t.differences.get()
        svc.resolve_difference(diff.id, self.user, "write_off")
        t.refresh_from_db()
        self.assertEqual(t.status, "resolved")
        # 守恒核对：签收60 + 退回30 + 核销10 = 100
        self.assertEqual(
            t.received_qty + t.cancelled_qty + t.shortage_qty, t.quantity
        )


class BalanceQueryTest(TransferFixture):
    def test_four_buckets_distinguished_at_every_stage(self):
        # 布置：一张在途单 + 一张待起运单 + 一笔待调查
        t1 = self.create_ship(10)                       # 10 在途
        t2 = svc.create_transfer(self.goods.id, self.loc_a.id, self.loc_b.id,
                                 D("5"), self.user)     # 5 已预留
        svc.receive_transfer(t1.id, self.user, D("7"), shortage_qty=D("3"))
        a = self.balance(self.loc_a)
        self.assertEqual(
            {"available": a.available, "reserved": a.reserved,
             "in_transit": a.in_transit, "investigating": a.investigating},
            {"available": D("85"), "reserved": D("5"),
             "in_transit": D("0"), "investigating": D("3")},
        )
        b = self.balance(self.loc_b)
        self.assertEqual(b.available, D("7"))


class LocationAPITest(TransferFixture):
    def test_location_crud_and_deactivate_with_balance(self):
        created = self.client.post("/api/locations/",
                                   {"code": "C", "name": "西区保管点"}, format="json")
        self.assertEqual(created.status_code, 200)
        # 有台账的地点删除 -> 停用
        resp = self.client.delete(f"/api/locations/{self.loc_a.id}/")
        self.assertEqual(resp.status_code, 200)
        self.loc_a.refresh_from_db()
        self.assertFalse(self.loc_a.is_active)

    def test_duplicate_location_code(self):
        resp = self.client.post("/api/locations/",
                                {"code": "A", "name": "别的仓"}, format="json")
        self.assertEqual(resp.status_code, 400)


class TransferAPITest(TransferFixture):
    def _detail(self, resp):
        return resp.json()["data"]

    def test_full_flow_api(self):
        r = self.client.post("/api/transfers/", {
            "goods": self.goods.id,
            "from_location": self.loc_a.id,
            "to_location": self.loc_b.id,
            "quantity": "10",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        tid = self._detail(r)["id"]
        self.assertEqual(self._detail(r)["status"], "pending")

        r = self.client.post(f"/api/transfers/{tid}/ship/", {
            "seal_no": "S1", "carrier": "张某", "responsible_party": "中队",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        r = self.client.post(f"/api/transfers/{tid}/seal-change/", {
            "new_seal_no": "S2", "reason": "查验换封",
        }, format="json")
        self.assertEqual(r.status_code, 200)

        r = self.client.post(f"/api/transfers/{tid}/receive/", {
            "received_qty": "4",
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._detail(r)["status"], "receiving")

        r = self.client.post(f"/api/transfers/{tid}/cancel-in-transit/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._detail(r)["status"], "cancelled_in_transit")

    def test_api_duplicate_receive_conflict(self):
        r = self.client.post("/api/transfers/", {
            "goods": self.goods.id,
            "from_location": self.loc_a.id,
            "to_location": self.loc_b.id,
            "quantity": "5",
        }, format="json")
        tid = r.json()["data"]["id"]
        self.client.post(f"/api/transfers/{tid}/ship/",
                         {"seal_no": "S", "carrier": "车", "responsible_party": "队",
                          "request_id": "ship-x"}, format="json")
        # 同键重放起运
        replay = self.client.post(f"/api/transfers/{tid}/ship/",
                                  {"seal_no": "S", "carrier": "车",
                                   "responsible_party": "队", "request_id": "ship-x"},
                                  format="json")
        self.assertEqual(replay.status_code, 409)

        recv = self.client.post(f"/api/transfers/{tid}/receive/",
                                {"received_qty": "5", "request_id": "recv-1"},
                                format="json")
        self.assertEqual(recv.status_code, 200)
        replay = self.client.post(f"/api/transfers/{tid}/receive/",
                                  {"received_qty": "5", "request_id": "recv-1"},
                                  format="json")
        self.assertEqual(replay.status_code, 409)

    def test_api_shortage_resolve(self):
        r = self.client.post("/api/transfers/", {
            "goods": self.goods.id,
            "from_location": self.loc_a.id,
            "to_location": self.loc_b.id,
            "quantity": "10",
        }, format="json")
        tid = r.json()["data"]["id"]
        self.client.post(f"/api/transfers/{tid}/ship/",
                         {"seal_no": "S", "carrier": "车", "responsible_party": "队"},
                         format="json")
        r = self.client.post(f"/api/transfers/{tid}/receive/",
                             {"received_qty": "8", "shortage_qty": "2"}, format="json")
        self.assertEqual(r.status_code, 200)
        diff_id = r.json()["data"]["differences"][0]["id"]

        resolve = self.client.post(f"/api/transfer-differences/{diff_id}/resolve/",
                                   {"resolution": "write_off",
                                    "liability_party": "押运中队"}, format="json")
        self.assertEqual(resolve.status_code, 200, resolve.content)
        detail = self.client.get(f"/api/transfers/{tid}/").json()["data"]
        self.assertEqual(detail["status"], "resolved")

    def test_api_balance_query(self):
        self.create_ship(10)
        r = self.client.get("/api/stock-balances/")
        self.assertEqual(r.status_code, 200)
        rows = {row["location_code"]: row for row in r.json()["data"]["list"]}
        self.assertEqual(rows["A"]["in_transit"], "10.00")
        self.assertEqual(rows["A"]["available"], "90.00")

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get("/api/transfers/").status_code, 401)

    def test_same_location_rejected(self):
        r = self.client.post("/api/transfers/", {
            "goods": self.goods.id,
            "from_location": self.loc_a.id,
            "to_location": self.loc_a.id,
            "quantity": "1",
        }, format="json")
        self.assertEqual(r.status_code, 400)
