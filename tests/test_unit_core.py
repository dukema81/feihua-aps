# -*- coding: utf-8 -*-
"""飞划APS · 业务内核单元测试（纯函数，不起服务）"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import aps  # noqa: E402
import pytest  # noqa: E402

D = date(2026, 10, 19)  # 周一


def wc(code, hpd=8.0, eff=1.0, wd="1,2,3,4,5"):
    return {"code": code, "name": code, "hours_per_day": hpd, "efficiency": eff,
            "work_days": [int(x) for x in wd.split(",")]}


def wo(no, prod, qty, due, prio=3, rel=None):
    return {"no": no, "product": prod, "qty": qty, "due_date": due, "priority": prio,
            "release_date": rel or D, "std_days": 1.0}


R1 = [wc("A"), wc("B")]
RT1 = {"P": [{"seq": 10, "wc": "A", "setup_h": 1.0, "run_h_per_unit": 1.0, "transfer_h": 0},
             {"seq": 20, "wc": "B", "setup_h": 0.5, "run_h_per_unit": 0.5, "transfer_h": 0}]}


# ---------------------------------------------------------------- 日历与工时
class TestCalendar:
    def test_workday_mon(self):
        assert aps.is_workday(date(2026, 10, 19))

    def test_workday_sat(self):
        assert not aps.is_workday(date(2026, 10, 24))

    def test_custom_workdays(self):
        assert aps.is_workday(date(2026, 10, 24), (6,))
        assert not aps.is_workday(date(2026, 10, 19), (6,))

    def test_capacity_normal(self):
        assert aps.workday_capacity(wc("A", 8, 1.0), date(2026, 10, 19)) == 8.0

    def test_capacity_efficiency(self):
        assert aps.workday_capacity(wc("A", 8, 0.75), date(2026, 10, 19)) == 6.0

    def test_capacity_restday_zero(self):
        assert aps.workday_capacity(wc("A"), date(2026, 10, 24)) == 0.0

    def test_op_hours(self):
        assert aps.op_hours({"setup_h": 2, "run_h_per_unit": 1.5}, 10) == 17.0

    def test_op_hours_zero_qty(self):
        assert aps.op_hours({"setup_h": 2, "run_h_per_unit": 1.5}, 0) == 2.0

    def test_wo_hours_sum(self):
        assert aps.wo_hours(RT1, "P", 10) == 1 + 10 + 0.5 + 5


# ---------------------------------------------------------------- 优先规则
class TestRules:
    def test_edd_sorts_by_due(self):
        wos = [wo("W2", "P", 1, D + timedelta(days=5)),
               wo("W1", "P", 1, D + timedelta(days=2))]
        out = aps.sort_workorders(wos, D, "EDD")
        assert [w["no"] for w in out] == ["W1", "W2"]

    def test_prio_first(self):
        wos = [wo("W1", "P", 1, D + timedelta(days=2), 3),
               wo("W2", "P", 1, D + timedelta(days=9), 1)]
        out = aps.sort_workorders(wos, D, "PRIO")
        assert [w["no"] for w in out] == ["W2", "W1"]

    def test_edd_overrides_priority(self):
        wos = [wo("W1", "P", 1, D + timedelta(days=2), 3),
               wo("W2", "P", 1, D + timedelta(days=9), 1)]
        out = aps.sort_workorders(wos, D, "EDD")
        assert [w["no"] for w in out] == ["W1", "W2"]

    def test_fifo(self):
        wos = [wo("W2", "P", 1, D + timedelta(days=2)),
               wo("W1", "P", 1, D + timedelta(days=9))]
        wos[0]["created_date"] = "2026-10-20"
        wos[1]["created_date"] = "2026-10-10"
        out = aps.sort_workorders(wos, D, "FIFO")
        assert [w["no"] for w in out] == ["W1", "W2"]

    def test_cr_urgent_first(self):
        wos = [wo("W1", "P", 1, D + timedelta(days=30)),
               wo("W2", "P", 1, D + timedelta(days=1))]
        wos[0]["std_days"] = 1
        wos[1]["std_days"] = 1
        out = aps.sort_workorders(wos, D, "CR")
        assert out[0]["no"] == "W2"

    def test_unknown_rule_raises(self):
        with pytest.raises(ValueError):
            aps.sort_key(wo("W", "P", 1, D), D, "XXX")


# ---------------------------------------------------------------- 排程
class TestSchedule:
    def test_single_wo_two_ops(self):
        st, res = aps.schedule([wo("W1", "P", 5, D + timedelta(days=10))], RT1, R1, D)
        r = res[0]
        assert r["feasible"] and not r["late"]
        assert r["total_hours"] == 9.0  # (1+5) + (0.5+2.5)
        assert r["ops"][0]["start"] == "2026-10-19"
        # 工序 20 在工序 10 完成后开始（同日或之后）
        assert r["ops"][1]["start"] >= r["ops"][0]["end"]

    def test_capacity_respected(self):
        # 16h 工序 1 在 8h/日 的 A 上需 2 天
        st, res = aps.schedule([wo("W1", "P", 15, D + timedelta(days=20))], RT1, R1, D)
        assert res[0]["ops"][0]["end"] == "2026-10-20"  # 16h: 周一8+周二8
        assert res[0]["ops"][1]["start"] >= "2026-10-20"

    def test_wo_second_waits(self):
        # W1 占满 A 两天；W2 的工序 10 必须从周三开始
        wos = [wo("W1", "P", 15, D + timedelta(days=20)),
               wo("W2", "P", 1, D + timedelta(days=20))]
        st, res = aps.schedule(wos, RT1, R1, D)
        w2 = next(r for r in res if r["wo"] == "W2")
        assert w2["ops"][0]["start"] == "2026-10-21"

    def test_edd_late_flag(self):
        # 交期早于完工
        st, res = aps.schedule([wo("W1", "P", 15, D)], RT1, R1, D)
        assert res[0]["late"] and res[0]["late_days"] >= 1

    def test_priority_changes_winner(self):
        # 紧急单（PRIO 规则）先排
        wos = [wo("W1", "P", 15, D + timedelta(days=2), 3),
               wo("W2", "P", 1, D + timedelta(days=2), 1)]
        st, res = aps.schedule(wos, RT1, R1, D, "PRIO")
        w2 = next(r for r in res if r["wo"] == "W2")
        assert w2["ops"][0]["start"] == "2026-10-19"

    def test_transfer_delays_next_op(self):
        rt = {"P": [{"seq": 10, "wc": "A", "setup_h": 0, "run_h_per_unit": 1.0, "transfer_h": 8},
                    {"seq": 20, "wc": "B", "setup_h": 0, "run_h_per_unit": 1.0, "transfer_h": 0}]}
        st, res = aps.schedule([wo("W1", "P", 8, D + timedelta(days=10))], rt, R1, D)
        # 工序 10 周一完成，转移 8h → 工序 20 从周二开始
        assert res[0]["ops"][1]["start"] == "2026-10-20"

    def test_infeasible_when_horizon_short(self):
        st, res = aps.schedule([wo("W1", "P", 5000, D + timedelta(days=10))], RT1, R1, D,
                               horizon=5)
        assert not res[0]["feasible"]

    def test_efficiency_slows_wc(self):
        r2 = [wc("A", 8, 0.5), wc("B")]
        st, res = aps.schedule([wo("W1", "P", 4, D + timedelta(days=10))], RT1, r2, D)
        # A 4h/日：工序10 = 1+4=5h → 两天
        assert res[0]["ops"][0]["end"] == "2026-10-20"

    def test_release_date_delays(self):
        st, res = aps.schedule([wo("W1", "P", 1, D + timedelta(days=10),
                                   rel=D + timedelta(days=3))], RT1, R1, D)
        assert res[0]["ops"][0]["start"] == "2026-10-22"

    def test_ops_never_overlap_on_same_wc(self):
        st, res = aps.schedule([wo("W%d" % i, "P", 3, D + timedelta(days=30))
                                for i in range(5)], RT1, R1, D)
        for r in res:
            a = next(o for o in r["ops"] if o["wc"] == "A")
            for r2 in res:
                if r2["wo"] == r["wo"]:
                    continue
                a2 = next(o for o in r2["ops"] if o["wc"] == "A")
                if a["start"] <= a2["start"]:
                    assert a["end"] <= a2["start"]
                else:
                    assert a2["end"] <= a["start"]


# ---------------------------------------------------------------- 负荷与瓶颈
class TestLoad:
    def test_load_sum(self):
        st, res = aps.schedule([wo("W1", "P", 10, D + timedelta(days=10))], RT1, R1, D)
        rows = aps.load_report(st)
        m = {r["wc"]: r for r in rows}
        assert m["A"]["load_h"] == 11.0
        assert m["B"]["load_h"] == 5.5

    def test_utilization_formula(self):
        st, res = aps.schedule([wo("W1", "P", 10, D + timedelta(days=10))], RT1, R1, D)
        rows = aps.load_report(st)
        a = next(r for r in rows if r["wc"] == "A")
        # 视界 90 天：A 产能 = 90 天 - 周末 ≈ 64 工作日 × 8
        assert abs(a["utilization"] - a["load_h"] / a["capacity_h"]) < 1e-3

    def test_rank_desc(self):
        st, res = aps.schedule([wo("W1", "P", 10, D + timedelta(days=10))], RT1, R1, D)
        rows = aps.load_report(st)
        utils = [r["utilization"] for r in rows]
        assert utils == sorted(utils, reverse=True)

    def test_bottleneck_top(self):
        st, res = aps.schedule([wo("W1", "P", 10, D + timedelta(days=10))], RT1, R1, D)
        rows = aps.load_report(st)
        bn = aps.bottleneck(rows)
        assert bn["wc"] == rows[0]["wc"]

    def test_bottleneck_warn_level(self):
        rows = [{"wc": "A", "name": "A", "capacity_h": 100, "load_h": 92,
                 "utilization": 0.92, "free_h": 8, "rank": 1}]
        assert aps.bottleneck(rows)["level"] == "warn"

    def test_bottleneck_over_level(self):
        rows = [{"wc": "A", "name": "A", "capacity_h": 100, "load_h": 105,
                 "utilization": 1.05, "free_h": -5, "rank": 1}]
        assert aps.bottleneck(rows)["level"] == "over"

    def test_day_load_shape(self):
        st, res = aps.schedule([wo("W1", "P", 10, D + timedelta(days=10))], RT1, R1, D)
        dl = aps.day_load(st, "A", horizon=7)
        assert len(dl) == 7
        assert dl[5]["capacity"] == 0.0  # 周六
        assert sum(x["load"] for x in dl) == 11.0


# ---------------------------------------------------------------- 齐套
BOM2 = [{"product": "P", "material": "M1", "qty_per_unit": 2, "loss_pct": 0},
        {"product": "P", "material": "M2", "qty_per_unit": 1, "loss_pct": 0}]
MATS = [{"code": "M1", "name": "甲", "stock": 10}, {"code": "M2", "name": "乙", "stock": 3}]


class TestKit:
    def test_all_ok(self):
        rows, stock = aps.material_check([wo("W1", "P", 3, D)], BOM2, MATS)
        assert rows[0]["kit_ok"] and stock["M1"] == 4 and stock["M2"] == 0

    def test_shortage_recorded(self):
        rows, _ = aps.material_check([wo("W1", "P", 5, D)], BOM2, MATS)
        s = rows[0]["shortage"]
        assert len(s) == 1  # M1 需10 存10 不缺
        assert s[0]["material"] == "M2" and s[0]["gap"] == 2

    def test_first_come_first_served(self):
        # 顺序扣减：W1 拿走 M1 全部 → W2 缺
        wos = [wo("W1", "P", 5, D), wo("W2", "P", 5, D + timedelta(days=2))]
        rows, _ = aps.material_check(wos, BOM2, [{"code": "M1", "name": "甲", "stock": 10},
                                                 {"code": "M2", "name": "乙", "stock": 10}])
        assert rows[0]["kit_ok"] and not rows[1]["kit_ok"]

    def test_short_no_deduction(self):
        rows, stock = aps.material_check([wo("W1", "P", 6, D)], BOM2, MATS)
        assert not rows[0]["kit_ok"] and stock["M1"] == 10  # 缺料不扣

    def test_shortage_summary_agg(self):
        wos = [wo("W1", "P", 5, D), wo("W2", "P", 5, D + timedelta(days=1))]
        rows, _ = aps.material_check(wos, BOM2, MATS)
        agg = aps.shortage_summary(rows)
        m2 = next(x for x in agg if x["material"] == "M2")
        assert m2["total_gap"] == 4  # 缺料不扣减，两张各缺 2
        assert m2["block_wos"] == ["W1", "W2"]


# ---------------------------------------------------------------- CTP
class TestCTP:
    def test_ctp_basic(self):
        st, res = aps.schedule([], RT1, R1, D)
        ans = aps.ctp({"product": "P", "qty": 5, "due_date": D + timedelta(days=30)},
                      RT1, R1, [], start=D)
        assert ans["feasible"] and ans["on_time"]
        assert ans["end"] is not None

    def test_ctp_considers_queue(self):
        # 队列占满 A 两天后，新单最早周三起
        wos = [wo("W1", "P", 15, D + timedelta(days=20))]
        ans = aps.ctp({"product": "P", "qty": 1, "due_date": D + timedelta(days=30)},
                      RT1, R1, wos, start=D)
        st, res = aps.schedule([wo("CTP-SIM", "P", 1, D + timedelta(days=30))], RT1, R1, D)
        sim = res[0]
        assert ans["end"] is not None
        # 与"队列+新单"重排结果一致
        st2, res2 = aps.schedule(wos + [wo("CTP-SIM", "P", 1, D + timedelta(days=30))], RT1, R1, D)
        mine = next(r for r in res2 if r["wo"] == "CTP-SIM")
        assert ans["end"] == mine["end"]

    def test_push_in_reports_late_impact(self):
        wos = [wo("W1", "P", 15, D + timedelta(days=2))]
        st, res, summary = aps.push_in({"no": "W-NEW", "product": "P", "qty": 15,
                                        "due_date": D + timedelta(days=2), "priority": 1},
                                       wos, RT1, R1, D, "EDD")
        assert summary["total"] == 2
        # EDD 同交期时 prio=1 的新单先排，原工单 W1 被挤成迟交
        assert "W1" in summary["late_wos"]
        assert summary["new_wo_end"] is not None


# ---------------------------------------------------------------- 告警
class TestAlerts:
    def test_late_alert(self):
        results = [{"wo": "W1", "end": "2026-10-25", "late": True, "late_days": 3,
                    "due_date": "2026-10-22", "feasible": True}]
        out = aps.build_alerts(results, [], [], {"late_warn_days": 3, "util_warn": 0.9})
        assert any(a["atype"] == "ORDER_LATE" and a["target"] == "W1" for a in out)

    def test_near_due_alert(self):
        results = [{"wo": "W1", "end": "2026-10-20", "late": False, "late_days": 0,
                    "due_date": "2026-10-22", "feasible": True}]
        out = aps.build_alerts(results, [], [], {"late_warn_days": 3, "util_warn": 0.9})
        assert any(a["atype"] == "ORDER_NEAR" for a in out)

    def test_wc_over_alert(self):
        loads = [{"wc": "A", "name": "A", "capacity_h": 100, "load_h": 110,
                  "utilization": 1.10, "free_h": -10, "rank": 1}]
        out = aps.build_alerts([], loads, [], {})
        assert any(a["atype"] == "WC_OVER" and a["level"] == "high" for a in out)

    def test_shortage_alert(self):
        out = aps.build_alerts([], [], [{"material": "M1", "total_gap": 5,
                                         "block_wos": ["W1", "W2"]}], {})
        assert any(a["atype"] == "MAT_SHORT" and len(a["message"]) > 0 for a in out)


# ---------------------------------------------------------------- 权限
class TestPerms:
    def test_admin_all(self):
        assert aps.has_perm("admin", "anything")

    def test_planner_can_run(self):
        assert aps.has_perm("planner", "plan.run")

    def test_sales_cannot_run(self):
        assert not aps.has_perm("sales", "plan.run")

    def test_sales_can_ctp(self):
        assert aps.has_perm("sales", "ctp.read")

    def test_reader_read_only(self):
        assert aps.has_perm("reader", "report.read")
        assert not aps.has_perm("reader", "so.write")
        assert not aps.has_perm("reader", "plan.run")

    def test_prod_no_so_write(self):
        assert not aps.has_perm("prod", "so.write")
        assert aps.has_perm("prod", "check.read")

    def test_all_roles_have_label(self):
        for r in aps.ROLE_PERMS:
            assert r in aps.ROLE_LABEL

    def test_unknown_role_false(self):
        assert not aps.has_perm("nobody", "plan.read")


# ---------------------------------------------------------------- 规则缺省
class TestDefaults:
    def test_default_rule_valid(self):
        assert aps.DEFAULT_RULE in aps.RULES

    def test_default_rules_keys(self):
        for k in ("sched_rule", "late_warn_days", "util_warn", "horizon_days"):
            assert k in aps.DEFAULT_RULES

    def test_q6(self):
        assert aps.q6(1.23456789) == 1.234568
