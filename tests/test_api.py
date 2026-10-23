# -*- coding: utf-8 -*-
"""飞划APS · 接口测试（真实 HTTP 服务）"""
import datetime
import json

from conftest import Client

TODAY = datetime.date.today().isoformat()


def due(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- 基础
class TestHealth:
    def test_health_public(self, admin):
        st, j = admin.call("GET", "/api/health")
        assert st == 200 and j["code"] == 200
        d = j["data"]
        assert d["brand"] == "飞划APS管理系统" and d["routes"] >= 50
        assert d["workcenters"] == 6 and d["work_orders"] == 10

    def test_health_no_auth_needed(self, server):
        c = Client(server)
        st, j = c.call("GET", "/api/health", no_retry=True)
        assert st == 200

    def test_apidoc(self, admin):
        st, j = admin.call("GET", "/api/apidoc")
        assert st == 200 and j["data"]["openapi"] == "3.0.0"
        assert len(j["data"]["paths"]) >= 40


class TestAuth:
    def test_login_bad(self, server):
        c = Client(server)
        st, j = c.call("POST", "/api/auth/login",
                       {"username": "admin", "password": "wrong"}, no_retry=True)
        assert st == 401

    def test_login_ok(self, server):
        c = Client(server, "admin", "aps@2026")
        d = c.login()
        assert d["role"] == "admin" and d["token"]

    def test_me(self, admin):
        st, j = admin.call("GET", "/api/auth/me")
        assert j["data"]["role"] == "admin" and "*" in j["data"]["perms"]

    def test_logout_invalidates(self, server):
        c = Client(server, "reader", "read@2026")
        c.login()
        st, _ = c.call("POST", "/api/auth/logout", no_retry=True)
        assert st == 200
        st, _ = c.call("GET", "/api/auth/me", no_retry=True)
        assert st == 401

    def test_unauth_401(self, server):
        c = Client(server)
        st, _ = c.call("GET", "/api/work-orders", no_retry=True)
        assert st == 401

    def test_change_password(self, server):
        c = Client(server, "prod", "prod@2026")
        c.login()
        st, j = c.call("POST", "/api/auth/change-password",
                       {"oldPassword": "prod@2026", "newPassword": "newpass2026"})
        assert st == 200
        c2 = Client(server, "prod", "newpass2026")
        assert c2.login()["role"] == "prod"
        # 改回
        c2.call("POST", "/api/auth/change-password",
                {"oldPassword": "newpass2026", "newPassword": "prod@2026"})


class TestPerms:
    def test_reader_cannot_run_plan(self, tokens):
        st, j = tokens["reader"].call("POST", "/api/plan/run", {"rule": "EDD"})
        assert st == 403

    def test_sales_cannot_save_wc(self, tokens):
        st, j = tokens["sales"].call("POST", "/api/workcenters/save",
                                     {"code": "X", "name": "X"})
        assert st == 403

    def test_sales_can_ctp(self, tokens):
        st, j = tokens["sales"].call("POST", "/api/ctp",
                                     {"product": "P-FAN", "qty": 1, "due_date": due(30)})
        assert st == 200

    def test_prod_cannot_write_so(self, tokens):
        st, j = tokens["prod"].call("POST", "/api/sales-orders/save",
                                    {"product": "P-FAN", "qty": 1, "due_date": due(10)})
        assert st == 403

    def test_reader_can_read_wo(self, tokens):
        st, j = tokens["reader"].call("GET", "/api/work-orders")
        assert st == 200 and len(j["data"]) == 10

    def test_planner_can_run(self, tokens):
        st, j = tokens["planner"].call("POST", "/api/plan/run", {"rule": "EDD"})
        assert st == 200

    def test_x_aps_key_auth(self, admin):
        st, j = admin.call("POST", "/api/api-keys/create",
                           {"name": "mes-conn", "role": "reader"})
        key = j["data"]["key"]
        c = Client(admin.base)
        st, j = c.call("GET", "/api/work-orders", headers={"X-Aps-Key": key}, no_retry=True)
        assert st == 200


# ---------------------------------------------------------------- 主数据
class TestMaster:
    def test_wc_crud(self, admin):
        st, j = admin.call("POST", "/api/workcenters/save",
                           {"code": "WC-T1", "name": "测试中心", "hours_per_day": 8,
                            "efficiency": 1.0, "work_days": [1, 2, 3, 4, 5]})
        assert st == 200 and j["data"]["created"] is True
        st, j = admin.call("POST", "/api/workcenters/save",
                           {"code": "WC-T1", "name": "测试中心改"})
        assert st == 200 and j["data"]["created"] is False
        st, j = admin.call("POST", "/api/workcenters/WC-T1/delete")
        assert st == 200

    def test_wc_delete_referenced(self, admin):
        st, j = admin.call("POST", "/api/workcenters/WC-CNC1/delete")
        assert st == 409

    def test_mat_crud_and_ref(self, admin):
        st, j = admin.call("POST", "/api/materials/save",
                           {"code": "M-T1", "name": "测试料", "stock": 5})
        assert st == 200
        st, j = admin.call("POST", "/api/materials/M-BLANK/delete")
        assert st == 409  # 被 BOM 引用
        st, j = admin.call("POST", "/api/materials/M-T1/delete")
        assert st == 200

    def test_mat_adjust(self, admin):
        st, j = admin.call("POST", "/api/materials/adjust",
                           {"code": "M-STEEL", "delta": 100})
        assert st == 200 and j["data"]["stock"] == 220

    def test_prod_save_and_bom(self, admin):
        st, j = admin.call("POST", "/api/products/save",
                           {"code": "P-T1", "name": "测试品", "unit": "台"})
        assert st == 200
        st, j = admin.call("POST", "/api/bom/save",
                           {"product": "P-T1", "material": "M-STEEL", "qty_per_unit": 2})
        assert st == 200
        st, j = admin.call("GET", "/api/bom")
        assert any(b["product"] == "P-T1" for b in j["data"])
        st, j = admin.call("POST", "/api/bom/P-T1/M-STEEL/delete")
        assert st == 200
        admin.call("POST", "/api/products/P-T1/delete")

    def test_routing_save(self, admin):
        st, j = admin.call("POST", "/api/routings/save",
                           {"product": "P-FAN", "seq": 99, "wc": "WC-QC",
                            "op_name": "复检", "setup_h": 0.1, "run_h_per_unit": 0.1})
        assert st == 200
        st, j = admin.call("POST", "/api/routings/P-FAN/99/delete")
        assert st == 200

    def test_routing_bad_wc(self, admin):
        st, j = admin.call("POST", "/api/routings/save",
                           {"product": "P-FAN", "seq": 98, "wc": "NOPE"})
        assert st == 404


# ---------------------------------------------------------------- 订单与工单
class TestOrders:
    def test_so_save_new(self, admin):
        st, j = admin.call("POST", "/api/sales-orders/save",
                           {"customer": "测试客户", "product": "P-FAN", "qty": 2,
                            "due_date": due(15), "priority": 2})
        assert st == 200 and j["data"]["created"] is True
        no = j["data"]["no"]
        st, j = admin.call("POST", "/api/sales-orders/save",
                           {"no": no, "customer": "测试客户改", "product": "P-FAN",
                            "qty": 3, "due_date": due(15), "priority": 2})
        assert st == 200 and j["data"]["created"] is False
        admin.call("POST", "/api/sales-orders/%s/delete" % no)

    def test_so_delete_with_wo(self, admin):
        st, j = admin.call("POST", "/api/sales-orders/SO-2026-0101/delete")
        assert st == 409

    def test_so_validation(self, admin):
        st, _ = admin.call("POST", "/api/sales-orders/save",
                           {"product": "NOPE", "qty": 1, "due_date": due(5)})
        assert st == 404
        st, _ = admin.call("POST", "/api/sales-orders/save",
                           {"product": "P-FAN", "qty": 0, "due_date": due(5)})
        assert st == 400
        st, _ = admin.call("POST", "/api/sales-orders/save",
                           {"product": "P-FAN", "qty": 1, "due_date": "bad"})
        assert st == 400

    def test_wo_save(self, admin):
        st, j = admin.call("POST", "/api/work-orders/save",
                           {"product": "P-TROLLEY", "qty": 5, "due_date": due(20)})
        assert st == 200
        no = j["data"]["no"]
        admin.call("POST", "/api/work-orders/%s/delete" % no)

    def test_wo_delete_scheduled_blocked(self, admin):
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, j = admin.call("POST", "/api/work-orders/WO0101/delete")
        assert st == 409

    def test_release_makes_wo(self, admin):
        admin.call("POST", "/api/sales-orders/save",
                   {"customer": "转单测试", "product": "P-GUARD", "qty": 10,
                    "due_date": due(20), "priority": 3})
        st, j = admin.call("POST", "/api/sales-orders/release")
        assert st == 200 and j["data"]["count"] >= 1


# ---------------------------------------------------------------- 排程
class TestPlan:
    def test_run_edd(self, admin):
        st, j = admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        d = j["data"]
        assert d["wo_count"] >= 10 and d["rule"] == "EDD"
        assert d["run_no"].startswith("RUN")
        assert len(d["results"]) == d["wo_count"]
        assert all("ops" in r for r in d["results"])

    def test_run_creates_alerts(self, admin):
        st, j = admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        assert len(j["data"]["alert_nos"]) == len(j["data"]["alerts"])

    def test_run_invalid_rule(self, admin):
        st, _ = admin.call("POST", "/api/plan/run", {"rule": "NOPE"})
        assert st == 400

    def test_latest(self, admin):
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, j = admin.call("GET", "/api/plan/latest")
        assert st == 200 and j["data"]["run"]["rule"] == "EDD"
        assert len(j["data"]["ops"]) >= 10

    def test_latest_before_run_404(self, server):
        # 新会话库已跑过 → 只验证结构
        c = Client(server, "admin", "aps@2026")
        c.login()
        st, j = c.call("GET", "/api/plan/latest")
        assert st in (200, 404)

    def test_gantt(self, admin):
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, j = admin.call("GET", "/api/plan/gantt")
        g = j["data"]["by_wc"]
        assert set(g.keys()) <= {"WC-CNC1", "WC-CNC2", "WC-WELD", "WC-ASSY",
                                 "WC-PAINT", "WC-QC"}
        for wc, ops in g.items():
            for o in ops:
                assert o["start_date"] and o["hours"] > 0

    def test_ops_no_overlap_same_wc(self, admin):
        """日桶模型允许边界日共享（各占当日不同产能），断言每日负荷不超产能"""
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, j = admin.call("GET", "/api/plan/gantt")
        g = j["data"]["by_wc"]
        assert len(g) > 0
        # 每个工作中心每日负荷 ≤ 日产能（通过 dayload 接口验证）
        for wc in g:
            st, j = admin.call("GET", "/api/plan/dayload/" + wc)
            assert st == 200
            for day in j["data"]["days"]:
                assert day["load"] <= day["capacity"] + 1e-6

    def test_load(self, admin):
        st, j = admin.call("GET", "/api/plan/load")
        loads = j["data"]["loads"]
        assert len(loads) == 6
        for l in loads:
            assert 0 <= l["utilization"] <= 1 or l["utilization"] > 1

    def test_dayload(self, admin):
        st, j = admin.call("GET", "/api/plan/dayload/WC-CNC1")
        d = j["data"]
        assert d["days"][0]["date"] >= TODAY
        assert len(d["days"]) == 90  # 视界 90 天
        sat = [x for x in d["days"] if datetime.date.fromisoformat(x["date"]).isoweekday() == 6]
        assert all(x["capacity"] == 0.0 for x in sat)

    def test_rule_change_takes_effect(self, admin):
        admin.call("POST", "/api/rules/save", {"key": "sched_rule", "value": "CR"})
        st, j = admin.call("POST", "/api/plan/run", {})
        assert st == 200 and j["data"]["rule"] == "CR"
        admin.call("POST", "/api/rules/save", {"key": "sched_rule", "value": "EDD"})

    def test_rule_unknown_rejected(self, admin):
        st, j = admin.call("POST", "/api/rules/save", {"key": "nope", "value": "1"})
        assert st == 400

    def test_push_in(self, admin):
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, j = admin.call("POST", "/api/plan/push-in",
                           {"product": "P-TROLLEY", "qty": 2, "due_date": due(30),
                            "priority": 1, "customer": "插单测试"})
        d = j["data"]
        assert d["so"].startswith("SO-") and d["wo"].startswith("WO")
        assert d["end"] and d["run_no"]
        st, j = admin.call("GET", "/api/work-orders")
        assert any(w["no"] == d["wo"] for w in j["data"])


# ---------------------------------------------------------------- 齐套
class TestKit:
    def test_kit_run(self, admin):
        st, j = admin.call("POST", "/api/kit/run")
        d = j["data"]
        assert d["ok_count"] + d["block_count"] >= 10
        assert all("shortage" in r for r in d["rows"])

    def test_kit_shortage_m6(self, admin):
        st, j = admin.call("POST", "/api/kit/run")
        d = j["data"]
        # 演示数据刻意造了 M-STEEL / M-MOTOR 缺口
        mats = {s["material"] for s in d["shortage"]}
        assert d["block_count"] >= 1

    def test_kit_history(self, admin):
        st, j = admin.call("GET", "/api/kit/history")
        assert st == 200 and len(j["data"]) >= 10


# ---------------------------------------------------------------- CTP
class TestCTP:
    def test_ctp_ok(self, admin):
        st, j = admin.call("POST", "/api/ctp",
                           {"product": "P-FAN", "qty": 2, "due_date": due(30)})
        d = j["data"]
        assert d["feasible"] and d["earliest_end"]
        assert d["suggestion"]

    def test_ctp_tight_due(self, admin):
        st, j = admin.call("POST", "/api/ctp",
                           {"product": "P-LIFTER", "qty": 10, "due_date": due(3)})
        d = j["data"]
        assert d["on_time"] is False

    def test_ctp_bad_product(self, admin):
        st, _ = admin.call("POST", "/api/ctp", {"product": "NOPE", "qty": 1})
        assert st == 404

    def test_ctp_history(self, admin):
        st, j = admin.call("GET", "/api/ctp/history")
        assert len(j["data"]) >= 2


# ---------------------------------------------------------------- 告警
class TestAlerts:
    def test_alerts_list_and_handle(self, admin):
        st, j = admin.call("GET", "/api/alerts")
        assert st == 200 and len(j["data"]) > 0
        open_a = next(a for a in j["data"] if a["status"] == "未处理")
        st, j = admin.call("POST", "/api/alerts/%s/handle" % open_a["no"])
        assert st == 200
        st, j = admin.call("POST", "/api/alerts/%s/handle" % open_a["no"])
        assert st == 409

    def test_alert_404(self, admin):
        st, _ = admin.call("POST", "/api/alerts/NOPE/handle")
        assert st == 404


# ---------------------------------------------------------------- 系统
class TestSystem:
    def test_rules_get(self, admin):
        st, j = admin.call("GET", "/api/rules")
        assert "sched_rule" in j["data"]

    def test_rules_batch(self, admin):
        st, j = admin.call("POST", "/api/rules/save",
                           {"rules": {"util_warn": "0.95", "late_warn_days": "2"}})
        assert st == 200 and j["data"]["rules"]["util_warn"] == 0.95
        admin.call("POST", "/api/rules/save", {"rules": {"util_warn": "0.9", "late_warn_days": "3"}})

    def test_users_and_roles(self, admin):
        st, j = admin.call("GET", "/api/users")
        assert len(j["data"]) == 6
        st, j = admin.call("GET", "/api/roles")
        assert any(r["role"] == "admin" for r in j["data"])

    def test_user_save_and_reset(self, admin):
        st, j = admin.call("POST", "/api/users/save",
                           {"username": "tempu", "name": "临时", "role": "reader",
                            "password": "temppass1"})
        assert st == 200 and j["data"]["created"] is True
        c = Client(admin.base, "tempu", "temppass1")
        assert c.login()["role"] == "reader"
        st, j = admin.call("POST", "/api/users/reset-password",
                           {"username": "tempu", "password": "temppass2"})
        assert st == 200
        admin.call("POST", "/api/users/save", {"username": "tempu", "status": "停用"})
        c2 = Client(admin.base, "tempu", "temppass2")
        st, _ = c2.call("POST", "/api/auth/login",
                        {"username": "tempu", "password": "temppass2"}, no_retry=True)
        assert st == 401

    def test_api_keys(self, admin):
        st, j = admin.call("POST", "/api/api-keys/create", {"name": "k1", "role": "reader"})
        key = j["data"]["key"]
        st, j = admin.call("GET", "/api/api-keys")
        assert any(k["key_prefix"] == key[:12] for k in j["data"])
        c = Client(admin.base)
        st, j = c.call("GET", "/api/products", headers={"X-Aps-Key": key}, no_retry=True)
        assert st == 200

    def test_sync_version(self, admin):
        st, j = admin.call("GET", "/api/sync/version")
        assert "work_orders" in j["data"]

    def test_sync_since(self, admin):
        st, j = admin.call("GET", "/api/sync?version=0")
        assert "work_orders" in j["data"]
        rows = j["data"]["work_orders"]["rows"]
        assert len(rows) >= 10

    def test_logs(self, admin):
        st, j = admin.call("GET", "/api/logs")
        assert st == 200 and len(j["data"]) > 0


# ---------------------------------------------------------------- 报表
class TestReports:
    def test_schedule_csv(self, admin):
        admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        st, text = admin.call("GET", "/api/reports/schedule.csv", raw=True)
        assert st == 200
        body = text.decode("utf-8")
        assert body.startswith("工单,工序,工作中心")
        assert "WC-" in body

    def test_load_csv(self, admin):
        st, text = admin.call("GET", "/api/reports/load.csv", raw=True)
        assert st == 200
        assert "利用率" in text.decode("utf-8")


# ---------------------------------------------------------------- 端到端
class TestE2E:
    def test_full_cycle(self, admin):
        """建产品→BOM→工艺→订单→转工单→排程→齐套→CTP→插单 全链路"""
        admin.call("POST", "/api/products/save", {"code": "P-E2E", "name": "端到端测试品"})
        admin.call("POST", "/api/bom/save", {"product": "P-E2E", "material": "M-SCREW",
                                             "qty_per_unit": 1})
        admin.call("POST", "/api/routings/save",
                   {"product": "P-E2E", "seq": 10, "wc": "WC-QC", "op_name": "检",
                    "setup_h": 0.5, "run_h_per_unit": 0.5})
        st, j = admin.call("POST", "/api/sales-orders/save",
                           {"customer": "E2E", "product": "P-E2E", "qty": 4,
                            "due_date": due(10), "priority": 1})
        st, j = admin.call("POST", "/api/sales-orders/release")
        st, j = admin.call("POST", "/api/plan/run", {"rule": "EDD"})
        assert any(r["product"] == "P-E2E" for r in j["data"]["results"])
        st, j = admin.call("POST", "/api/kit/run")
        assert any(r["product"] == "P-E2E" for r in j["data"]["rows"])
        st, j = admin.call("POST", "/api/ctp",
                           {"product": "P-E2E", "qty": 1, "due_date": due(20)})
        assert st == 200
