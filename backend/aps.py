# -*- coding: utf-8 -*-
"""飞划 APS 管理系统 · 纯函数业务内核

域模型（全部为 dict，无副作用，便于单测）：
  资源 workcenter : {code, name, hours_per_day, efficiency, work_days}  work_days=工作日 1-7（ISO 周一=1）
  产品 product    : {code, name, unit}
  工艺路线 op     : {seq, product, wc, setup_h, run_h_per_unit, transfer_h}
  BOM 行 bom      : {product, material, qty_per_unit}
  物料 material   : {code, name, stock}
  销售订单 so     : {no, product, qty, due_date, priority, customer}
  工单 wo         : {no, product, qty, due_date, priority, so}

排程模型（日桶法 · 有限产能正向排程）：
  - 排程视界 N 天；每个工作中心每天产能 = hours_per_day × efficiency（非工作日为 0）
  - 工序按工艺路线顺序、在「最早可开工日」起逐日吞占工作中心日桶剩余产能
  - 工序不重叠（下一道工序最早开工 = 上一道完工日，可加转移时间）
  - 工单排程顺序由规则决定：EDD 最早交期 / CR 关键比率 / PRIO 优先级 / FIFO 先进先出
"""
from datetime import date, timedelta

HORIZON_DAYS = 90          # 排程视界
SHIFT_START_H = 8.0        # 班次起点 08:00
DEFAULT_RULE = "EDD"

RULES = ("EDD", "CR", "PRIO", "FIFO")


# ---------------------------------------------------------------- 日历
def is_workday(d, work_days=(1, 2, 3, 4, 5)):
    return d.isoweekday() in work_days


def workday_capacity(wc, d):
    """工作中心某日可用产能（小时）；非工作日为 0"""
    if not is_workday(d, tuple(wc.get("work_days") or (1, 2, 3, 4, 5))):
        return 0.0
    return round(wc["hours_per_day"] * (wc.get("efficiency") or 1.0), 4)


def op_hours(op, qty):
    """工序总工时 = 准备 + 单件 × 数量"""
    return round((op["setup_h"] or 0.0) + (op["run_h_per_unit"] or 0.0) * qty, 4)


def wo_hours(routing, product, qty):
    """工单总工时 = 各工序之和"""
    return round(sum(op_hours(op, qty) for op in routing.get(product, [])), 4)


# ---------------------------------------------------------------- 优先规则
def sort_key(wo, today, rule=DEFAULT_RULE):
    if rule == "EDD":
        return (wo["due_date"], wo.get("priority", 3), wo["no"])
    if rule == "PRIO":
        return (wo.get("priority", 3), wo["due_date"], wo["no"])
    if rule == "FIFO":
        return (wo.get("created_date") or wo["due_date"], wo["no"])
    if rule == "CR":
        # 关键比率 = 剩余天数 / 剩余标准工时天数；<1 必迟
        remain_days = max((wo["due_date"] - today).days, 0.001)
        return (round(remain_days / max(wo.get("std_days", 1.0), 0.001), 4), wo["no"])
    raise ValueError("unknown rule: %s" % rule)


def sort_workorders(wos, today, rule=DEFAULT_RULE):
    return sorted(wos, key=lambda w: sort_key(w, today, rule))


# ---------------------------------------------------------------- 排程
class SchedState(object):
    """排程状态：工作中心 × 日期 的产能占用桶"""

    def __init__(self, resources, start, horizon=HORIZON_DAYS):
        self.start = start
        self.days = [start + timedelta(days=i) for i in range(horizon)]
        self.res = {r["code"]: r for r in resources}
        self.load = {r["code"]: {d: 0.0 for d in self.days} for r in resources}
        self.assigned = {}   # (wo, seq) -> op schedule result
        self.spans = []      # 每日占用明细 [{wc, wo, seq, day_idx, hours}]

    def cap(self, wc, d):
        r = self.res[wc]
        return workday_capacity(r, d)

    def place(self, wc, earliest_day_idx, dur, wo_no, seq, transfer_h=0.0):
        """从 earliest_day_idx 起找工作中心产能放置 dur 小时，返回 (start_day_idx,
        start_hour, end_day_idx, end_hour)；产能不足返回 None"""
        remaining = dur
        s_idx = s_hour = e_idx = e_hour = None
        idx = earliest_day_idx
        while idx < len(self.days) and remaining > 1e-9:
            d = self.days[idx]
            cap = self.cap(wc, d)
            free = round(cap - self.load[wc][d], 6)
            if free > 1e-6:
                if s_idx is None:
                    s_idx, s_hour = idx, SHIFT_START_H + self.load[wc][d]
                take = min(free, remaining)
                self.load[wc][d] = round(self.load[wc][d] + take, 6)
                self.spans.append({"wc": wc, "wo": wo_no, "seq": seq,
                                   "day_idx": idx, "hours": round(take, 4)})
                remaining = round(remaining - take, 6)
                e_idx, e_hour = idx, SHIFT_START_H + self.load[wc][d]
            idx += 1
        if remaining > 1e-6:
            return None
        self.assigned[(wo_no, seq)] = {"wc": wc, "start_day": self.days[s_idx],
                                       "start_h": round(s_hour, 2),
                                       "end_day": self.days[e_idx],
                                       "end_h": round(e_hour, 2)}
        return s_idx, e_idx


def schedule(wos, routings, resources, start=None, rule=DEFAULT_RULE,
             horizon=HORIZON_DAYS, preassigned=None):
    """有限产能正向排程。
    wos: 工单列表；routings: {product: [op,...]}；resources: [workcenter,...]
    preassigned: {(wo_no, seq): (start_day_idx,)} 已锁定工序（重排保留），本版简化为忽略锁定。
    返回 state + 工单结果。"""
    start = start or date.today()
    st = SchedState(resources, start, horizon)
    ordered = sort_workorders(wos, start, rule)
    results = []
    for wo in ordered:
        ops = sorted(routings.get(wo["product"], []), key=lambda o: o["seq"])
        earliest = 0 if (wo.get("release_date") or start) <= start else \
            (wo["release_date"] - start).days
        op_rows, ok = [], True
        for op in ops:
            dur = op_hours(op, wo["qty"])
            placed = st.place(op["wc"], earliest, dur, wo["no"], op["seq"],
                              op.get("transfer_h", 0.0))
            if placed is None:
                ok = False
                op_rows.append({"seq": op["seq"], "wc": op["wc"], "hours": dur,
                                "start": None, "end": None, "note": "视界内产能不足"})
                break
            s_idx, e_idx = placed
            op_rows.append({"seq": op["seq"], "wc": op["wc"], "hours": dur,
                            "start": st.days[s_idx].isoformat(),
                            "start_h": st.assigned[(wo["no"], op["seq"])]["start_h"],
                            "end": st.days[e_idx].isoformat(),
                            "end_h": st.assigned[(wo["no"], op["seq"])]["end_h"]})
            earliest = e_idx + (1 if op.get("transfer_h") else 0)
        last = op_rows[-1] if op_rows else None
        end_date = date.fromisoformat(last["end"]) if last and last["end"] else None
        late_days = (end_date - wo["due_date"]).days if end_date else None
        results.append({
            "wo": wo["no"], "product": wo["product"], "qty": wo["qty"],
            "due_date": wo["due_date"].isoformat(),
            "priority": wo.get("priority", 3),
            "total_hours": wo_hours(routings, wo["product"], wo["qty"]),
            "start": op_rows[0]["start"] if op_rows and op_rows[0]["start"] else None,
            "end": last["end"] if last else None,
            "late_days": late_days if late_days and late_days > 0 else 0,
            "late": bool(late_days and late_days > 0),
            "feasible": ok,
            "ops": op_rows,
        })
    return st, results


# ---------------------------------------------------------------- 负荷与瓶颈
def load_report(st, horizon=None):
    """工作中心负荷：horizon 天内 负荷小时 / 可用产能 → 利用率"""
    days = st.days[:horizon] if horizon else st.days
    rows = []
    for code, r in st.res.items():
        cap = sum(st.cap(code, d) for d in days)
        used = round(sum(st.load[code][d] for d in days), 2)
        util = round(used / cap, 4) if cap > 0 else 0.0
        rows.append({"wc": code, "name": r["name"],
                     "capacity_h": round(cap, 2), "load_h": used,
                     "utilization": util, "free_h": round(cap - used, 2)})
    rows.sort(key=lambda x: -x["utilization"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def bottleneck(rows, warn=0.85):
    """瓶颈 = 利用率最高；≥warn 预警，>1.0 超载"""
    if not rows:
        return None
    top = rows[0]
    top["level"] = "over" if top["utilization"] > 1.0 else (
        "warn" if top["utilization"] >= warn else "ok")
    return top


def day_load_from_spans(st, wc, horizon=None):
    """直接用排程时的每日占用明细出图，无需重算"""
    days = st.days[:horizon] if horizon else st.days
    buckets = {i: 0.0 for i in range(len(days))}
    for sp in st.spans:
        if sp["wc"] == wc and sp["day_idx"] < len(days):
            buckets[sp["day_idx"]] = round(buckets[sp["day_idx"]] + sp["hours"], 4)
    return [{"date": d.isoformat(), "capacity": st.cap(wc, d),
             "load": buckets[i]} for i, d in enumerate(days)]


def day_load(st, wc, horizon=None):
    days = st.days[:horizon] if horizon else st.days
    return [{"date": d.isoformat(),
             "capacity": st.cap(wc, d),
             "load": round(st.load[wc][d], 2)} for d in days]


# ---------------------------------------------------------------- 物料齐套
def material_check(wos_in_order, boms, materials):
    """按排程顺序模拟发料：返回每工单齐套结果 + 物料余量。
    wos_in_order: 已按排程顺序排序的工单（dict 列表）
    boms: [ {product, material, qty_per_unit} ] ; materials: {code: {stock,...}}"""
    stock = {m["code"]: float(m.get("stock") or 0) for m in materials}
    rows = []
    for wo in wos_in_order:
        need, short = {}, []
        for b in boms:
            if b["product"] != wo["product"]:
                continue
            q = round(b["qty_per_unit"] * wo["qty"], 4)
            need[b["material"]] = round(need.get(b["material"], 0) + q, 4)
        for code, q in need.items():
            have = stock.get(code, 0.0)
            if have < q - 1e-9:
                short.append({"material": code, "need": q, "stock": have,
                              "gap": round(q - have, 4)})
        # 有缺料不扣减（缺多少记多少），够则全额扣减
        if not short:
            for code, q in need.items():
                stock[code] = round(stock[code] - q, 6)
        rows.append({"wo": wo["no"], "product": wo["product"],
                     "kit_ok": not short, "shortage": short, "need": need})
    return rows, stock


def shortage_summary(check_rows):
    """物料维度缺口汇总"""
    agg = {}
    for r in check_rows:
        for s in r["shortage"]:
            a = agg.setdefault(s["material"], {"material": s["material"],
                                               "total_gap": 0.0, "block_wos": []})
            a["total_gap"] = round(a["total_gap"] + s["gap"], 4)
            a["block_wos"].append(r["wo"])
    return sorted(agg.values(), key=lambda x: -x["total_gap"])


# ---------------------------------------------------------------- 交期承诺 CTP
def ctp(candidate, routings, resources, wos, start=None, rule=DEFAULT_RULE,
        horizon=HORIZON_DAYS):
    """可承诺量：模拟插入新订单后排程，返回最早完工日与是否迟到。
    candidate: {product, qty, due_date, priority}"""
    start = start or date.today()
    wo = {"no": candidate.get("no") or "CTP-SIM", "product": candidate["product"],
          "qty": candidate["qty"], "due_date": candidate["due_date"],
          "priority": candidate.get("priority", 3), "std_days": candidate.get("std_days", 1.0),
          "release_date": start}
    st, res = schedule(list(wos) + [wo], routings, resources, start, rule, horizon)
    mine = next(r for r in res if r["wo"] == wo["no"])
    # 可用日期：去掉候选单本身再逐日外推太贵，直接给模拟结果
    return {"feasible": mine["feasible"],
            "end": mine["end"], "late": mine["late"], "late_days": mine["late_days"],
            "on_time": bool(mine["end"] and not mine["late"]),
            "queue_len": len(wos) + 1}


def push_in(so, wos, routings, resources, start=None, rule=DEFAULT_RULE):
    """插单重排：把新销售订单对应工单插入队列重排，返回整体结果与受影响工单"""
    wo = dict(so)
    wo.setdefault("no", "WO-NEW")
    st, res = schedule(list(wos) + [wo], routings, resources, start, rule)
    late = [r for r in res if r["late"]]
    return st, res, {"total": len(res), "late_count": len(late),
                     "late_wos": [r["wo"] for r in late],
                     "new_wo_end": next(r["end"] for r in res if r["wo"] == wo["no"])}


# ---------------------------------------------------------------- 告警
def build_alerts(results, loads, shortage_rows, rules):
    """rules: {late_warn_days, util_warn, shortage_block} → 告警列表"""
    out = []
    lw = rules.get("late_warn_days", 3)
    uw = rules.get("util_warn", 0.9)
    for r in results:
        if r["late"]:
            out.append({"atype": "ORDER_LATE", "target": r["wo"], "level": "high",
                        "message": "工单 %s 预计 %s 完工，迟于交期 %d 天"
                                   % (r["wo"], r["end"], r["late_days"]),
                        "value": r["late_days"], "threshold": 0})
        elif r["end"]:
            remain = (date.fromisoformat(r["due_date"]) -
                      date.fromisoformat(r["end"])).days
            if remain <= lw:
                out.append({"atype": "ORDER_NEAR", "target": r["wo"], "level": "mid",
                            "message": "工单 %s 距交期缓冲仅 %d 天" % (r["wo"], remain),
                            "value": remain, "threshold": lw})
        if not r["feasible"]:
            out.append({"atype": "WO_INFEASIBLE", "target": r["wo"], "level": "high",
                        "message": "工单 %s 在 %d 天视界内排不下" % (r["wo"], HORIZON_DAYS),
                        "value": 0, "threshold": 0})
    for l in loads:
        if l["utilization"] > 1.0:
            out.append({"atype": "WC_OVER", "target": l["wc"], "level": "high",
                        "message": "工作中心 %s 超载 %.1f%%" % (l["wc"], l["utilization"] * 100 - 100),
                        "value": l["utilization"], "threshold": 1.0})
        elif l["utilization"] >= uw:
            out.append({"atype": "WC_BUSY", "target": l["wc"], "level": "mid",
                        "message": "工作中心 %s 负荷 %.1f%%" % (l["wc"], l["utilization"] * 100),
                        "value": l["utilization"], "threshold": uw})
    for s in shortage_rows:
        out.append({"atype": "MAT_SHORT", "target": s["material"], "level": "high",
                    "message": "物料 %s 缺口 %s，阻塞 %d 个工单"
                               % (s["material"], s["total_gap"], len(s["block_wos"])),
                    "value": s["total_gap"], "threshold": 0})
    return out


# ---------------------------------------------------------------- 权限
ROLE_PERMS = {
    "admin":    {"*"},
    "planner":  {"plan.read", "plan.run", "plan.unlock", "so.read", "so.write",
                 "wo.read", "wo.write", "master.read", "master.write",
                 "mat.read", "ctp.read", "report.read", "alert.read", "check.read"},
    "sched":    {"plan.read", "plan.run", "so.read", "wo.read", "wo.write",
                 "master.read", "mat.read", "ctp.read", "report.read",
                 "alert.read", "check.read"},
    "sales":    {"so.read", "so.write", "plan.read", "ctp.read", "wo.read", "alert.read"},
    "prod":     {"wo.read", "plan.read", "mat.read", "check.read", "alert.read"},
    "reader":   {"plan.read", "so.read", "wo.read", "master.read", "mat.read",
                 "ctp.read", "report.read", "alert.read", "check.read"},
}
ROLE_LABEL = {"admin": "管理员", "planner": "计划员", "sched": "排产员",
              "sales": "销售", "prod": "生产", "reader": "只读"}


def has_perm(role, perm):
    p = ROLE_PERMS.get(role, set())
    return "*" in p or perm in p


DEFAULT_RULES = {
    "sched_rule": "EDD",
    "late_warn_days": 3,
    "util_warn": 0.9,
    "horizon_days": 90,
    "default_hours_per_day": 8.0,
    "default_efficiency": 1.0,
    "transfer_default_h": 0.0,
    "max_orders_per_run": 500,
}


def q6(x):
    return round(x, 6)
