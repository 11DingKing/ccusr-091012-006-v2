"""
调拨与库存台账测试

覆盖：调拨申请、起运确认、在途责任、到达签收（含幂等）、差异处理、
部分签收、途中取消、封签变更、重复到达请求，以及任意时点的数量守恒。
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Category, CustodyPoint, Discrepancy, Goods, SealChange, StockBalance,
    TransferEvent, TransferItem, TransferOrder, Unit, Variety,
)

ZERO = Decimal('0')


class TransferFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("transfer-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")

        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="TR-DEV-001",
            quantity=Decimal("100"),
            warning_threshold=Decimal("5"),
        )
        self.point_a = CustodyPoint.objects.create(
            name="起点库房", code="PA", keeper_name="保管员甲", created_by=self.user
        )
        self.point_b = CustodyPoint.objects.create(
            name="终点库房", code="PB", keeper_name="保管员乙", created_by=self.user
        )
        self.balance_a = StockBalance.objects.create(
            custody_point=self.point_a, goods=self.goods,
            available_quantity=Decimal("100"), reserved_quantity=ZERO,
        )

    # ---------- 辅助方法 ----------

    def balance(self, point):
        return StockBalance.objects.filter(custody_point=point, goods=self.goods).first()

    def quantities(self, point):
        balance = self.balance(point)
        if balance is None:
            return ZERO, ZERO
        return balance.available_quantity, balance.reserved_quantity

    def assert_conservation(self, physical_total=Decimal("100")):
        """数量守恒：账面 + 在途 + 待调查 + 已核销 = 物理总量；
        在册总量(Goods.quantity) = 账面 + 在途 + 待调查。"""
        balances = StockBalance.objects.filter(goods=self.goods)
        on_points = sum(b.available_quantity + b.reserved_quantity for b in balances)
        items = TransferItem.objects.filter(goods=self.goods)
        in_transit = sum(i.in_transit_quantity for i in items)
        disputed = sum(i.disputed_quantity for i in items)
        lost = sum(i.lost_quantity for i in items)
        self.assertEqual(on_points + in_transit + disputed + lost, physical_total)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, on_points + in_transit + disputed)

    def create_transfer(self, quantity="20", **overrides):
        payload = {
            "origin_point": self.point_a.id,
            "destination_point": self.point_b.id,
            "items": [{"goods": self.goods.id, "quantity": quantity}],
        }
        payload.update(overrides)
        response = self.client.post("/api/transfers/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()["data"]

    def dispatch(self, order_id, items=None, **overrides):
        payload = {"carrier_name": "押运员丙", "vehicle_no": "警A-0001", "seal_no": "SL-001"}
        if items is not None:
            payload["items"] = items
        payload.update(overrides)
        return self.client.post(f"/api/transfers/{order_id}/dispatch/", payload, format="json")

    def receive(self, order_id, items=None, key=None):
        payload = {}
        if items is not None:
            payload["items"] = items
        if key:
            payload["idempotency_key"] = key
        return self.client.post(f"/api/transfers/{order_id}/receive/", payload, format="json")

    def first_item_id(self, order):
        return order["items"][0]["id"]


class CustodyPointAPITest(TransferFixture):
    def test_create_and_list_points(self):
        response = self.client.post(
            "/api/custody-points/",
            {"name": "证物室", "code": "EV1", "keeper_name": "保管员丁"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["name"], "证物室")

        listing = self.client.get("/api/custody-points/")
        self.assertEqual(listing.status_code, 200)
        names = [row["name"] for row in listing.json()["data"]["list"]]
        self.assertIn("证物室", names)

    def test_reject_duplicate_name_and_code(self):
        dup_name = self.client.post(
            "/api/custody-points/", {"name": "起点库房", "code": "PX"}, format="json"
        )
        dup_code = self.client.post(
            "/api/custody-points/", {"name": "另一个点", "code": "PA"}, format="json"
        )
        self.assertEqual(dup_name.status_code, 400)
        self.assertEqual(dup_code.status_code, 400)

    def test_delete_point_with_stock_is_blocked(self):
        blocked = self.client.delete(f"/api/custody-points/{self.point_a.id}/")
        self.assertEqual(blocked.status_code, 400)

        empty = CustodyPoint.objects.create(name="空闲点", code="PE", created_by=self.user)
        allowed = self.client.delete(f"/api/custody-points/{empty.id}/")
        self.assertEqual(allowed.status_code, 200)

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/custody-points/")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(APIClient().get("/api/stock/").status_code, 401)
        self.assertEqual(APIClient().get("/api/transfers/").status_code, 401)


class TransferApplyTest(TransferFixture):
    def test_apply_reserves_stock(self):
        order = self.create_transfer("20")
        self.assertEqual(order["status"], "pending")
        self.assertTrue(order["transfer_no"].startswith("TR"))

        available, reserved = self.quantities(self.point_a)
        self.assertEqual(available, Decimal("80"))
        self.assertEqual(reserved, Decimal("20"))
        # 在册总量不因调拨申请变化
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("100"))
        self.assert_conservation()

        event = TransferEvent.objects.get(transfer_id=order["id"], event_type="apply")
        self.assertEqual(event.actor, self.user)

    def test_apply_rejects_same_point(self):
        response = self.client.post("/api/transfers/", {
            "origin_point": self.point_a.id,
            "destination_point": self.point_a.id,
            "items": [{"goods": self.goods.id, "quantity": "1"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_apply_rejects_insufficient_stock(self):
        response = self.client.post("/api/transfers/", {
            "origin_point": self.point_a.id,
            "destination_point": self.point_b.id,
            "items": [{"goods": self.goods.id, "quantity": "101"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("100"), ZERO))

    def test_apply_rejects_duplicate_goods_and_bad_quantity(self):
        dup = self.client.post("/api/transfers/", {
            "origin_point": self.point_a.id,
            "destination_point": self.point_b.id,
            "items": [
                {"goods": self.goods.id, "quantity": "1"},
                {"goods": self.goods.id, "quantity": "2"},
            ],
        }, format="json")
        self.assertEqual(dup.status_code, 400)

        zero = self.client.post("/api/transfers/", {
            "origin_point": self.point_a.id,
            "destination_point": self.point_b.id,
            "items": [{"goods": self.goods.id, "quantity": "0"}],
        }, format="json")
        self.assertEqual(zero.status_code, 400)


class TransferDispatchTest(TransferFixture):
    def test_dispatch_moves_reserved_to_in_transit(self):
        order = self.create_transfer("20")
        response = self.dispatch(order["id"])
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertEqual(data["status"], "in_transit")
        self.assertEqual(data["carrier_name"], "押运员丙")
        self.assertEqual(data["seal_no"], "SL-001")

        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("80"), ZERO))
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.in_transit_quantity, Decimal("20"))
        self.assert_conservation()

    def test_partial_dispatch_twice(self):
        order = self.create_transfer("20")
        item_id = self.first_item_id(order)

        first = self.dispatch(order["id"], items=[{"item_id": item_id, "quantity": "5"}])
        self.assertEqual(first.status_code, 200)
        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("80"), Decimal("15")))

        second = self.dispatch(
            order["id"],
            items=[{"item_id": item_id, "quantity": "15"}],
            seal_no="SL-002",
        )
        self.assertEqual(second.status_code, 200)
        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("80"), ZERO))
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.in_transit_quantity, Decimal("20"))
        # 最近一次起运的封签号为当前封签
        self.assertEqual(second.json()["data"]["seal_no"], "SL-002")
        self.assert_conservation()

    def test_dispatch_rejects_over_quantity_and_wrong_state(self):
        order = self.create_transfer("10")
        item_id = self.first_item_id(order)
        over = self.dispatch(order["id"], items=[{"item_id": item_id, "quantity": "11"}])
        self.assertEqual(over.status_code, 400)

        cancelled = self.create_transfer("5")
        self.client.post(f"/api/transfers/{cancelled['id']}/cancel/", {}, format="json")
        rejected = self.dispatch(cancelled["id"])
        self.assertEqual(rejected.status_code, 400)
        self.assert_conservation()

    def test_dispatch_requires_carrier_and_seal(self):
        order = self.create_transfer("10")
        missing_seal = self.dispatch(order["id"], seal_no="")
        self.assertEqual(missing_seal.status_code, 400)
        missing_carrier = self.dispatch(order["id"], carrier_name="")
        self.assertEqual(missing_carrier.status_code, 400)


class TransferReceiveTest(TransferFixture):
    def test_partial_receive_then_receive_all(self):
        order = self.create_transfer("20")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)

        first = self.receive(order["id"], items=[{"item_id": item_id, "quantity": "8"}])
        self.assertEqual(first.status_code, 200, first.json())
        b_available, _ = self.quantities(self.point_b)
        self.assertEqual(b_available, Decimal("8"))
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.in_transit_quantity, Decimal("12"))

        # 不带明细则签收全部剩余在途
        second = self.receive(order["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["status"], "completed")
        b_available, _ = self.quantities(self.point_b)
        self.assertEqual(b_available, Decimal("20"))
        self.assert_conservation()

    def test_duplicate_receive_with_same_key_is_applied_once(self):
        order = self.create_transfer("20")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)

        first = self.receive(order["id"], items=[{"item_id": item_id, "quantity": "5"}], key="rcpt-1")
        second = self.receive(order["id"], items=[{"item_id": item_id, "quantity": "5"}], key="rcpt-1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["data"], second.json()["data"])
        self.assertIn("重复", second.json()["message"])

        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.received_quantity, Decimal("5"))
        b_available, _ = self.quantities(self.point_b)
        self.assertEqual(b_available, Decimal("5"))
        self.assert_conservation()

    def test_duplicate_receive_via_header_key(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])

        headers = {"HTTP_IDEMPOTENCY_KEY": "rcpt-header-1"}
        first = self.client.post(f"/api/transfers/{order['id']}/receive/", {}, format="json", **headers)
        second = self.client.post(f"/api/transfers/{order['id']}/receive/", {}, format="json", **headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        b_available, _ = self.quantities(self.point_b)
        self.assertEqual(b_available, Decimal("10"))
        self.assert_conservation()

    def test_over_receive_is_rejected_without_side_effects(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)

        response = self.receive(order["id"], items=[{"item_id": item_id, "quantity": "11"}])
        self.assertEqual(response.status_code, 400)
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.received_quantity, ZERO)
        self.assertIsNone(self.balance(self.point_b))
        self.assert_conservation()

    def test_receive_rejected_when_not_in_transit(self):
        order = self.create_transfer("10")
        response = self.receive(order["id"])
        self.assertEqual(response.status_code, 400)


class TransferCancelTest(TransferFixture):
    def test_cancel_before_dispatch_releases_reservation(self):
        order = self.create_transfer("20")
        response = self.client.post(f"/api/transfers/{order['id']}/cancel/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "cancelled")

        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("100"), ZERO))
        self.assert_conservation()

        # 已取消单据不可再起运、再签收
        self.assertEqual(self.dispatch(order["id"]).status_code, 400)
        self.assertEqual(self.receive(order["id"]).status_code, 400)

    def test_cancel_in_transit_returns_goods_and_releases_unshipped(self):
        order = self.create_transfer("20")
        item_id = self.first_item_id(order)
        # 先起运 12，剩余 8 仍预留
        self.dispatch(order["id"], items=[{"item_id": item_id, "quantity": "12"}])

        # 途中取消：退回 5，其余 7 仍在途
        response = self.client.post(f"/api/transfers/{order['id']}/cancel/", {
            "reason": "运输途中召回",
            "returns": [{"item_id": item_id, "quantity": "5"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertEqual(data["status"], "in_transit")

        # 起点：80 + 释放的 8 + 退回的 5 = 93 可用，0 预留
        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("93"), ZERO))
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.in_transit_quantity, Decimal("7"))
        self.assertEqual(item.cancelled_quantity, Decimal("8"))
        self.assertEqual(item.returned_quantity, Decimal("5"))
        self.assert_conservation()

        # 剩余在途仍可正常签收
        rest = self.receive(order["id"])
        self.assertEqual(rest.status_code, 200)
        self.assertEqual(rest.json()["data"]["status"], "completed")
        self.assert_conservation()

    def test_cancel_rejects_return_over_in_transit(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)
        response = self.client.post(f"/api/transfers/{order['id']}/cancel/", {
            "returns": [{"item_id": item_id, "quantity": "11"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assert_conservation()

    def test_completed_order_cannot_be_cancelled(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])
        self.receive(order["id"])
        response = self.client.post(f"/api/transfers/{order['id']}/cancel/", {}, format="json")
        self.assertEqual(response.status_code, 400)


class SealChangeTest(TransferFixture):
    def test_seal_change_recorded_without_quantity_effect(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])

        response = self.client.post(f"/api/transfers/{order['id']}/seal-changes/", {
            "new_seal_no": "SL-002",
            "reason": "途中查验后重新封签",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["data"]["old_seal_no"], "SL-001")
        self.assertEqual(response.json()["data"]["new_seal_no"], "SL-002")

        order_obj = TransferOrder.objects.get(pk=order["id"])
        self.assertEqual(order_obj.seal_no, "SL-002")
        self.assertEqual(SealChange.objects.filter(transfer_id=order["id"]).count(), 1)
        self.assertTrue(
            TransferEvent.objects.filter(transfer_id=order["id"], event_type="seal_change").exists()
        )
        self.assert_conservation()

        listing = self.client.get(f"/api/transfers/{order['id']}/seal-changes/")
        self.assertEqual(len(listing.json()["data"]), 1)

    def test_seal_change_rejected_when_not_in_transit_or_same_seal(self):
        order = self.create_transfer("10")
        not_in_transit = self.client.post(f"/api/transfers/{order['id']}/seal-changes/", {
            "new_seal_no": "SL-002",
        }, format="json")
        self.assertEqual(not_in_transit.status_code, 400)

        self.dispatch(order["id"])
        same_seal = self.client.post(f"/api/transfers/{order['id']}/seal-changes/", {
            "new_seal_no": "SL-001",
        }, format="json")
        self.assertEqual(same_seal.status_code, 400)


class DiscrepancyTest(TransferFixture):
    def test_raise_and_resolve_discrepancy_split(self):
        order = self.create_transfer("20")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)

        # 到达时发现 6 件差异，登记待调查
        raised = self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id,
            "quantity": "6",
            "reason": "封签破损，短少 6 件",
        }, format="json")
        self.assertEqual(raised.status_code, 200, raised.json())
        discrepancy_id = raised.json()["data"]["id"]

        item = TransferItem.objects.get(pk=item_id)
        self.assertEqual(item.disputed_quantity, Decimal("6"))
        self.assertEqual(item.in_transit_quantity, Decimal("14"))
        # 差异登记不动任何保管点库存
        available, reserved = self.quantities(self.point_a)
        self.assertEqual((available, reserved), (Decimal("80"), ZERO))
        self.assert_conservation()

        # 正常签收无争议的 14
        self.receive(order["id"], items=[{"item_id": item_id, "quantity": "14"}])

        # 差异处理：2 找回补交终点、1 退回起点、3 核销损失
        resolved = self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "delivered_quantity": "2",
            "returned_quantity": "1",
            "lost_quantity": "3",
            "remark": "找回 2 件，1 件退回，3 件灭失核销",
        }, format="json")
        self.assertEqual(resolved.status_code, 200, resolved.json())
        self.assertEqual(resolved.json()["data"]["status"], "resolved")

        item.refresh_from_db()
        self.assertEqual(item.disputed_quantity, ZERO)
        self.assertEqual(item.received_quantity, Decimal("16"))
        self.assertEqual(item.returned_quantity, Decimal("1"))
        self.assertEqual(item.lost_quantity, Decimal("3"))

        a_available, _ = self.quantities(self.point_a)
        b_available, _ = self.quantities(self.point_b)
        self.assertEqual(a_available, Decimal("81"))
        self.assertEqual(b_available, Decimal("16"))

        # 在册总量仅因核销减少 3
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("97"))
        self.assert_conservation()

        order_obj = TransferOrder.objects.get(pk=order["id"])
        self.assertEqual(order_obj.status, "completed")

    def test_partial_resolve_keeps_open_until_fully_allocated(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)
        raised = self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "4", "reason": "到货短少",
        }, format="json")
        discrepancy_id = raised.json()["data"]["id"]

        first = self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "delivered_quantity": "1",
        }, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["status"], "open")
        self.assertEqual(first.json()["data"]["remaining_quantity"], "3.00")

        over = self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "lost_quantity": "4",
        }, format="json")
        self.assertEqual(over.status_code, 400)

        second = self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "lost_quantity": "3",
        }, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["status"], "resolved")

        again = self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "lost_quantity": "1",
        }, format="json")
        self.assertEqual(again.status_code, 400)
        self.assert_conservation()

    def test_dispute_rejects_over_in_transit_and_wrong_state(self):
        order = self.create_transfer("10")
        item_id = self.first_item_id(order)
        not_in_transit = self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "1", "reason": "测试",
        }, format="json")
        self.assertEqual(not_in_transit.status_code, 400)

        self.dispatch(order["id"])
        over = self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "11", "reason": "测试",
        }, format="json")
        self.assertEqual(over.status_code, 400)
        self.assertEqual(Discrepancy.objects.count(), 0)
        self.assert_conservation()

    def test_disputed_quantity_cannot_be_returned_by_cancel(self):
        order = self.create_transfer("10")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)
        self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "4", "reason": "途中盘点短少",
        }, format="json")

        # 途中取消只能退回仍在途的 6，待调查的 4 必须走差异处理
        over = self.client.post(f"/api/transfers/{order['id']}/cancel/", {
            "returns": [{"item_id": item_id, "quantity": "7"}],
        }, format="json")
        self.assertEqual(over.status_code, 400)

        ok = self.client.post(f"/api/transfers/{order['id']}/cancel/", {
            "returns": [{"item_id": item_id, "quantity": "6"}],
        }, format="json")
        self.assertEqual(ok.status_code, 200)
        item = TransferItem.objects.get(pk=item_id)
        self.assertEqual(item.disputed_quantity, Decimal("4"))
        self.assertEqual(TransferOrder.objects.get(pk=order["id"]).status, "in_transit")
        self.assert_conservation()


class StockQueryTest(TransferFixture):
    def test_stock_query_distinguishes_four_buckets_mid_flight(self):
        order = self.create_transfer("20")
        item_id = self.first_item_id(order)
        self.dispatch(order["id"], items=[{"item_id": item_id, "quantity": "12"}])
        self.receive(order["id"], items=[{"item_id": item_id, "quantity": "3"}])
        self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "2", "reason": "到货短少",
        }, format="json")

        response = self.client.get("/api/stock/", {"goods_id": self.goods.id})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["list"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # 起点 80 可用 + 8 预留；终点 3 可用；在途 7；待调查 2
        self.assertEqual(row["available"], "83.00")
        self.assertEqual(row["reserved"], "8.00")
        self.assertEqual(row["in_transit"], "7.00")
        self.assertEqual(row["under_investigation"], "2.00")
        self.assertEqual(row["lost"], "0.00")
        self.assertEqual(row["on_hand"], "100.00")

        points = {p["point_id"]: p for p in row["points"]}
        self.assertEqual(points[self.point_a.id]["available"], "80.00")
        self.assertEqual(points[self.point_a.id]["reserved"], "8.00")
        self.assertEqual(points[self.point_a.id]["in_transit_out"], "7.00")
        self.assertEqual(points[self.point_a.id]["under_investigation"], "2.00")
        self.assertEqual(points[self.point_b.id]["available"], "3.00")
        self.assertEqual(points[self.point_b.id]["in_transit_in"], "7.00")

        # 按保管点过滤
        filtered = self.client.get("/api/stock/", {
            "goods_id": self.goods.id, "point_id": self.point_b.id,
        })
        filtered_points = filtered.json()["data"]["list"][0]["points"]
        self.assertEqual(len(filtered_points), 1)
        self.assertEqual(filtered_points[0]["point_id"], self.point_b.id)

    def test_stock_query_after_lost_write_off(self):
        order = self.create_transfer("5")
        self.dispatch(order["id"])
        item_id = self.first_item_id(order)
        raised = self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "5", "reason": "整车灭失",
        }, format="json")
        discrepancy_id = raised.json()["data"]["id"]
        self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "lost_quantity": "5",
        }, format="json")

        row = self.client.get("/api/stock/", {"goods_id": self.goods.id}).json()["data"]["list"][0]
        self.assertEqual(row["lost"], "5.00")
        self.assertEqual(row["on_hand"], "95.00")
        self.assertEqual(row["in_transit"], "0.00")
        self.assertEqual(row["under_investigation"], "0.00")
        self.assert_conservation()


class TransferEventTrailTest(TransferFixture):
    def test_full_lifecycle_event_trail(self):
        order = self.create_transfer("20")
        item_id = self.first_item_id(order)
        self.dispatch(order["id"], items=[{"item_id": item_id, "quantity": "12"}])
        self.client.post(f"/api/transfers/{order['id']}/seal-changes/", {
            "new_seal_no": "SL-009", "reason": "重新封签",
        }, format="json")
        self.receive(order["id"], items=[{"item_id": item_id, "quantity": "10"}], key="evt-rcpt")
        self.client.post(f"/api/transfers/{order['id']}/discrepancies/", {
            "item_id": item_id, "quantity": "2", "reason": "短少",
        }, format="json")
        discrepancy_id = Discrepancy.objects.get(transfer_id=order["id"]).id
        self.client.post(f"/api/discrepancies/{discrepancy_id}/resolve/", {
            "lost_quantity": "2",
        }, format="json")
        self.client.post(f"/api/transfers/{order['id']}/cancel/", {}, format="json")

        response = self.client.get(f"/api/transfers/{order['id']}/events/")
        self.assertEqual(response.status_code, 200)
        event_types = [e["event_type"] for e in response.json()["data"]]
        self.assertEqual(
            event_types,
            ["apply", "dispatch", "seal_change", "receive",
             "dispute_raise", "dispute_resolve", "cancel"],
        )
        # 全部完结：申请 20 = 签收 10 + 核销 2 + 取消释放 8
        order_obj = TransferOrder.objects.get(pk=order["id"])
        self.assertEqual(order_obj.status, "completed")
        item = TransferItem.objects.get(transfer_id=order["id"])
        self.assertEqual(item.received_quantity, Decimal("10"))
        self.assertEqual(item.lost_quantity, Decimal("2"))
        self.assertEqual(item.cancelled_quantity, Decimal("8"))
        self.assert_conservation()


class TransferListAndDetailTest(TransferFixture):
    def test_list_filter_and_detail(self):
        first = self.create_transfer("10")
        second = self.create_transfer("5")
        self.dispatch(first["id"])

        in_transit = self.client.get("/api/transfers/", {"status": "in_transit"})
        self.assertEqual(in_transit.json()["data"]["total"], 1)
        pending = self.client.get("/api/transfers/", {"status": "pending"})
        self.assertEqual(pending.json()["data"]["total"], 1)

        by_point = self.client.get("/api/transfers/", {"destination_point": self.point_b.id})
        self.assertEqual(by_point.json()["data"]["total"], 2)

        detail = self.client.get(f"/api/transfers/{first['id']}/")
        self.assertEqual(detail.status_code, 200)
        data = detail.json()["data"]
        self.assertEqual(data["transfer_no"], first["transfer_no"])
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["in_transit_quantity"], "10.00")
        self.assertIn("discrepancies", data)
        self.assertIn("seal_changes", data)

        missing = self.client.get("/api/transfers/99999/")
        self.assertEqual(missing.status_code, 404)
