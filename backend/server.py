# -*- coding: utf-8 -*-
"""飞划 APS 管理系统 · HTTP 服务（零第三方依赖）

环境变量：APS_PORT（默认 8022）、APS_PREFIX（nginx 子路径，默认空）、APS_DB
鉴权五通道：Authorization: Bearer / X-Aps-Token / Cookie(aps_token) / ?token= / X-Aps-Key
"""
import datetime
import json
import os
import re
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aps
import db
import seed as seedmod

PORT = int(os.environ.get("APS_PORT") or 8022)
PREFIX = os.environ.get("APS_PREFIX", "").rstrip("/")
BRAND = "飞划APS管理系统"
VERSION = "1.0.0"
_root = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(os.path.dirname(_root), "frontend")


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def log(u, action, detail=""):
    db.run("INSERT INTO logs(username,action,detail,at) VALUES(?,?,?,?)",
           (u or "", action, detail, db.now()))


def rules():
    return {r["key"]: _cast(r["value"]) for r in db.rows("SELECT * FROM rules")}


def _cast(v):
    for cast in (int, float):
        try:
            return cast(v)
        except (TypeError, ValueError):
            pass
    if v in ("true", "false"):
        return v == "true"
    return v


def gen_alarm_no(cn):
    return db.gen_no(cn, "alarms", "AL", col="no")


def raise_alarm(atype, level, target, message, value=0, threshold=0):
    cn = db.connect()
    no = gen_alarm_no(cn)
    cn.execute("INSERT INTO alarms(no,atype,level,target,message,value,threshold,status,period,created_at) "
               "VALUES(?,?,?,?,?,?,?,'未处理',?,?)",
               (no, atype, level, target, message, value, threshold,
                datetime.date.today().isoformat(), db.now()))
    cn.commit()
    return {"no": no, "atype": atype, "level": level, "target": target,
            "message": message, "value": value, "threshold": threshold,
            "status": "未处理", "period": datetime.date.today().isoformat()}


def _load_context():
    """从库中装载排程上下文"""
    resources = [dict(r, work_days=[int(x) for x in (r["work_days"] or "1,2,3,4,5").split(",") if x],
                      hours_per_day=r["hours_per_day"] or aps.DEFAULT_RULES["default_hours_per_day"],
                      efficiency=r["efficiency"] or 1.0)
                 for r in db.rows("SELECT * FROM workcenters WHERE status='运行'")]
    routings = {}
    for r in db.rows("SELECT * FROM routing_ops ORDER BY product,seq"):
        routings.setdefault(r["product"], []).append(
            {"seq": r["seq"], "wc": r["wc"], "op_name": r["op_name"],
             "setup_h": r["setup_h"], "run_h_per_unit": r["run_h_per_unit"],
             "transfer_h": r["transfer_h"]})
    boms = db.rows("SELECT product,material,qty_per_unit,loss_pct FROM bom")
    materials = db.rows("SELECT code,name,stock FROM materials")
    return resources, routings, boms, materials


def _load_wos(statuses=("已下达", "排产中")):
    return [{"no": w["no"], "product": w["product"], "qty": w["qty"],
             "due_date": db.today() if isinstance(w["due_date"], str) and not w["due_date"] else
             (datetime.date.fromisoformat(w["due_date"]) if isinstance(w["due_date"], str) else w["due_date"]),
             "priority": w["priority"] or 3, "status": w["status"],
             "release_date": datetime.date.fromisoformat(w["release_date"] or db.today().isoformat()),
             "std_days": max(1.0, aps.wo_hours(_ROUTING_CACHE, w["product"], w["qty"]) /
                             max(1.0, sum(r["hours_per_day"] for r in _RES_CACHE) / max(1, len(_RES_CACHE)))),
             "created_date": w["created_date"]}
            for w in db.rows("SELECT * FROM work_orders WHERE status IN (%s)"
                             % ",".join("?" * len(statuses)), statuses)]


_RES_CACHE, _ROUTING_CACHE = [], {}


def refresh_context():
    global _RES_CACHE, _ROUTING_CACHE
    _RES_CACHE, _ROUTING_CACHE, _, _ = _load_context()
    for w in db.rows("SELECT * FROM work_orders WHERE status IN ('已下达','排产中')"):
        pass


# ================================================================ 业务 API
def api_health(u, body, q):
    return {"brand": BRAND, "version": VERSION,
            "routes": len(ROUTES),
            "workcenters": db.val("SELECT COUNT(*) FROM workcenters", (), 0),
            "materials": db.val("SELECT COUNT(*) FROM materials", (), 0),
            "products": db.val("SELECT COUNT(*) FROM products", (), 0),
            "sales_orders": db.val("SELECT COUNT(*) FROM sales_orders", (), 0),
            "work_orders": db.val("SELECT COUNT(*) FROM work_orders", (), 0),
            "time": db.now()}


def api_login(u, body, q):
    un = (body or {}).get("username") or ""
    pw = (body or {}).get("password") or ""
    row = db.one("SELECT * FROM users WHERE username=? AND status='启用'", (un,))
    if not row or row["password_hash"] != db.sha256(pw):
        raise ApiError("用户名或密码错误", 401)
    tok = secrets.token_hex(24)
    exp = (datetime.datetime.now() + datetime.timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    db.run("INSERT INTO tokens(token,username,expire_at,created_at) VALUES(?,?,?,?)",
           (tok, un, exp, db.now()))
    log(un, "登录")
    return {"token": tok, "username": un, "name": row["name"], "role": row["role"],
            "roleLabel": aps.ROLE_LABEL.get(row["role"], row["role"])}


def api_logout(u, body, q):
    if (u or {}).get("_token"):
        db.run("DELETE FROM tokens WHERE token=?", (u["_token"],))
    log(u["username"], "登出")
    return {"ok": True}


def api_me(u, body, q):
    return {"username": u["username"], "name": u["name"], "role": u["role"],
            "roleLabel": aps.ROLE_LABEL.get(u["role"], u["role"]),
            "perms": sorted(aps.ROLE_PERMS.get(u["role"], set()))}


def api_change_pwd(u, body, q):
    old, new = (body or {}).get("oldPassword") or "", (body or {}).get("newPassword") or ""
    row = db.one("SELECT password_hash FROM users WHERE username=?", (u["username"],))
    if not row or row["password_hash"] != db.sha256(old):
        raise ApiError("旧密码错误", 401)
    if len(new) < 8:
        raise ApiError("新密码至少 8 位", 400)
    db.run("UPDATE users SET password_hash=? WHERE username=?",
           (db.sha256(new), u["username"]))
    log(u["username"], "修改密码")
    return {"ok": True}


# ------------------------------------------------ 用户管理
def api_users(u, body, q):
    return db.rows("SELECT username,name,role,phone,status,created_at FROM users ORDER BY username")


def api_user_save(u, body, q):
    un = body.get("username") or ""
    if not un:
        raise ApiError("username 必填")
    if db.one("SELECT 1 FROM users WHERE username=?", (un,)):
        db.run("UPDATE users SET name=?,role=?,phone=?,status=? WHERE username=?",
               (body.get("name") or un, body.get("role") or "reader",
                body.get("phone") or "", body.get("status") or "启用", un))
        log(u["username"], "更新用户", un)
        return {"ok": True, "created": False}
    pw = body.get("password") or "aps@2026"
    db.run("INSERT INTO users(username,password_hash,name,role,phone,created_at) VALUES(?,?,?,?,?,?)",
           (un, db.sha256(pw), body.get("name") or un, body.get("role") or "reader",
            body.get("phone") or "", db.now()))
    log(u["username"], "新增用户", un)
    return {"ok": True, "created": True}


def api_user_reset(u, body, q):
    un = body.get("username") or ""
    if not db.one("SELECT 1 FROM users WHERE username=?", (un,)):
        raise ApiError("用户不存在", 404)
    pw = body.get("password") or "aps@2026"
    db.run("UPDATE users SET password_hash=? WHERE username=?", (db.sha256(pw), un))
    db.run("DELETE FROM tokens WHERE username=?", (un,))
    log(u["username"], "重置密码", un)
    return {"ok": True}


def api_roles(u, body, q):
    return [{"role": r, "label": aps.ROLE_LABEL[r],
             "perms": sorted(aps.ROLE_PERMS[r])} for r in aps.ROLE_PERMS]


# ------------------------------------------------ 主数据：工作中心 / 物料 / 产品 / BOM / 工艺
def _master_list(table, order="code"):
    return db.rows("SELECT * FROM %s ORDER BY %s" % (table, order))


def _master_save(table, key, body, fields, u, label):
    code = body.get(key) or ""
    if not code:
        raise ApiError(key + " 必填")
    old = db.one("SELECT * FROM %s WHERE %s=?" % (table, key), (code,))
    vals = {f: body.get(f) for f in fields}
    if old:
        sets = ",".join(f + "=?" for f in fields)
        db.run("UPDATE %s SET %s WHERE %s=?" % (table, sets, key),
               [vals[f] for f in fields] + [code])
        act = "更新"
    else:
        cols = key + "," + ",".join(fields)
        db.run("INSERT INTO %s(%s) VALUES(%s)" % (table, cols, ",".join("?" * (len(fields) + 1))),
               [code] + [vals[f] for f in fields])
        act = "新增"
    db.bumpsync(table)
    log(u["username"], act + label, code)
    return {"ok": True, "created": not old}


def api_wc_list(u, body, q):
    return _master_list("workcenters")


def api_wc_save(u, body, q):
    if "work_days" in body and isinstance(body["work_days"], list):
        body["work_days"] = ",".join(str(x) for x in body["work_days"])
    return _master_save("workcenters", "code", body,
                        ["name", "wtype", "hours_per_day", "efficiency",
                         "work_days", "shift", "cost_rate", "status", "remark"], u, "工作中心")


def api_wc_del(u, body, q, code):
    if db.one("SELECT 1 FROM routing_ops WHERE wc=?", (code,)):
        raise ApiError("该工作中心被工艺路线引用，不能删除", 409)
    db.run("DELETE FROM workcenters WHERE code=?", (code,))
    db.bumpsync("workcenters")
    log(u["username"], "删除工作中心", code)
    return {"ok": True}


def api_mat_list(u, body, q):
    return _master_list("materials")


def api_mat_save(u, body, q):
    return _master_save("materials", "code", body,
                        ["name", "unit", "stock", "safety", "lead_days",
                         "price", "supplier", "remark"], u, "物料")


def api_mat_del(u, body, q, code):
    if db.one("SELECT 1 FROM bom WHERE material=?", (code,)):
        raise ApiError("该物料被 BOM 引用，不能删除", 409)
    db.run("DELETE FROM materials WHERE code=?", (code,))
    db.bumpsync("materials")
    log(u["username"], "删除物料", code)
    return {"ok": True}


def api_mat_adjust(u, body, q):
    code = body.get("code") or ""
    delta = float(body.get("delta") or 0)
    if not db.one("SELECT 1 FROM materials WHERE code=?", (code,)):
        raise ApiError("物料不存在", 404)
    db.run("UPDATE materials SET stock=ROUND(stock+?,4) WHERE code=?", (delta, code))
    db.bumpsync("materials")
    log(u["username"], "库存调整", "%s %+g" % (code, delta))
    return {"code": code, "stock": db.val("SELECT stock FROM materials WHERE code=?", (code,))}


def api_prod_list(u, body, q):
    return _master_list("products")


def api_prod_save(u, body, q):
    return _master_save("products", "code", body,
                        ["name", "unit", "category", "std_price", "status", "remark"],
                        u, "产品")


def api_prod_del(u, body, q, code):
    if db.one("SELECT 1 FROM work_orders WHERE product=?", (code,)):
        raise ApiError("该产品存在工单，不能删除", 409)
    db.run("DELETE FROM products WHERE code=?", (code,))
    db.run("DELETE FROM bom WHERE product=?", (code,))
    db.run("DELETE FROM routing_ops WHERE product=?", (code,))
    db.bumpsync("products")
    log(u["username"], "删除产品", code)
    return {"ok": True}


def api_bom_list(u, body, q):
    return db.rows("SELECT b.*,m.name mat_name FROM bom b LEFT JOIN materials m "
                   "ON m.code=b.material ORDER BY b.product,b.material")


def api_bom_save(u, body, q):
    prod, mat = body.get("product") or "", body.get("material") or ""
    if not prod or not mat:
        raise ApiError("product/material 必填")
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    if not db.one("SELECT 1 FROM materials WHERE code=?", (mat,)):
        raise ApiError("物料不存在", 404)
    db.run("INSERT INTO bom(product,material,qty_per_unit,loss_pct) VALUES(?,?,?,?) "
           "ON CONFLICT(product,material) DO UPDATE SET qty_per_unit=excluded.qty_per_unit,"
           "loss_pct=excluded.loss_pct",
           (prod, mat, body.get("qty_per_unit") or 1, body.get("loss_pct") or 0))
    db.bumpsync("bom")
    log(u["username"], "保存BOM", prod + "/" + mat)
    return {"ok": True}


def api_bom_del(u, body, q, pid, mid):
    db.run("DELETE FROM bom WHERE product=? AND material=?", (pid, mid))
    db.bumpsync("bom")
    log(u["username"], "删除BOM", pid + "/" + mid)
    return {"ok": True}


def api_rt_list(u, body, q):
    return db.rows("SELECT r.*,w.name wc_name FROM routing_ops r LEFT JOIN workcenters w "
                   "ON w.code=r.wc ORDER BY r.product,r.seq")


def api_rt_save(u, body, q):
    prod, seq = body.get("product") or "", int(body.get("seq") or 0)
    if not prod or not seq:
        raise ApiError("product/seq 必填")
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    if not db.one("SELECT 1 FROM workcenters WHERE code=?", (body.get("wc") or "",)):
        raise ApiError("工作中心不存在", 404)
    db.run("INSERT INTO routing_ops(product,seq,wc,op_name,setup_h,run_h_per_unit,transfer_h) "
           "VALUES(?,?,?,?,?,?,?) ON CONFLICT(product,seq) DO UPDATE SET wc=excluded.wc,"
           "op_name=excluded.op_name,setup_h=excluded.setup_h,"
           "run_h_per_unit=excluded.run_h_per_unit,transfer_h=excluded.transfer_h",
           (prod, seq, body.get("wc"), body.get("op_name") or "", body.get("setup_h") or 0,
            body.get("run_h_per_unit") or 0, body.get("transfer_h") or 0))
    db.bumpsync("routing_ops")
    log(u["username"], "保存工艺", prod + "/" + str(seq))
    return {"ok": True}


def api_rt_del(u, body, q, pid, seq):
    db.run("DELETE FROM routing_ops WHERE product=? AND seq=?", (pid, seq))
    db.bumpsync("routing_ops")
    log(u["username"], "删除工序", pid + "/" + seq)
    return {"ok": True}


# ------------------------------------------------ 订单与工单
def api_so_list(u, body, q):
    status = q.get("status")
    if status:
        return db.rows("SELECT * FROM sales_orders WHERE status=? ORDER BY due_date,no", (status,))
    return db.rows("SELECT * FROM sales_orders ORDER BY due_date,no")


def api_so_save(u, body, q):
    no = body.get("no") or ""
    if not no:
        no = db.gen_no(db.connect(), "sales_orders", "SO-" + db.today().strftime("%Y-"))
    prod = body.get("product") or ""
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    due = body.get("due_date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        raise ApiError("due_date 需 YYYY-MM-DD")
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("qty 必须 > 0")
    old = db.one("SELECT * FROM sales_orders WHERE no=?", (no,))
    if old:
        db.run("UPDATE sales_orders SET customer=?,product=?,qty=?,due_date=?,priority=?,"
               "price=?,status=?,remark=? WHERE no=?",
               (body.get("customer") or "", prod, qty, due, int(body.get("priority") or 3),
                body.get("price") or 0, body.get("status") or old["status"],
                body.get("remark") or "", no))
        created = False
    else:
        db.run("INSERT INTO sales_orders(no,customer,product,qty,due_date,priority,price,"
               "status,created_date,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (no, body.get("customer") or "", prod, qty, due, int(body.get("priority") or 3),
                body.get("price") or 0, "待排产", db.today().isoformat(), body.get("remark") or ""))
        created = True
    db.bumpsync("sales_orders")
    log(u["username"], "保存销售订单", no)
    return {"ok": True, "no": no, "created": created}


def api_so_del(u, body, q, no):
    if db.one("SELECT 1 FROM work_orders WHERE so=?", (no,)):
        raise ApiError("该订单已生成工单，先删工单", 409)
    db.run("DELETE FROM sales_orders WHERE no=?", (no,))
    db.bumpsync("sales_orders")
    log(u["username"], "删除销售订单", no)
    return {"ok": True}


def api_so_release(u, body, q):
    """订单转工单（未生成的生成）"""
    made = []
    for so in db.rows("SELECT * FROM sales_orders WHERE status='待排产'"):
        wo_no = "WO" + so["no"].split("-")[-1]
        if db.one("SELECT 1 FROM work_orders WHERE no=?", (wo_no,)):
            continue
        db.run("INSERT INTO work_orders(no,so,product,qty,due_date,priority,status,"
               "release_date,created_date) VALUES(?,?,?,?,?,?,?,?,?)",
               (wo_no, so["no"], so["product"], so["qty"], so["due_date"], so["priority"],
                "已下达", db.today().isoformat(), db.now()))
        db.run("UPDATE sales_orders SET status='已转工单' WHERE no=?", (so["no"],))
        made.append({"so": so["no"], "wo": wo_no})
    db.bumpsync("work_orders")
    log(u["username"], "订单转工单", "%d 张" % len(made))
    return {"created": made, "count": len(made)}


def api_wo_list(u, body, q):
    return db.rows("SELECT * FROM work_orders ORDER BY due_date,no")


def api_wo_save(u, body, q):
    no = body.get("no") or db.gen_no(db.connect(), "work_orders", "WO")
    prod = body.get("product") or ""
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("qty 必须 > 0")
    due = body.get("due_date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        raise ApiError("due_date 需 YYYY-MM-DD")
    old = db.one("SELECT * FROM work_orders WHERE no=?", (no,))
    if old:
        if old["status"] == "排产中" and body.get("status") != "已下达":
            raise ApiError("工单已排产，先取消排程再改", 409)
        db.run("UPDATE work_orders SET so=?,product=?,qty=?,due_date=?,priority=?,"
               "status=?,remark=? WHERE no=?",
               (body.get("so") or "", prod, qty, due, int(body.get("priority") or 3),
                body.get("status") or old["status"], body.get("remark") or "", no))
        created = False
    else:
        db.run("INSERT INTO work_orders(no,so,product,qty,due_date,priority,status,"
               "release_date,created_date,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (no, body.get("so") or "", prod, qty, due, int(body.get("priority") or 3),
                "已下达", body.get("release_date") or db.today().isoformat(),
                db.now(), body.get("remark") or ""))
        created = True
    db.bumpsync("work_orders")
    log(u["username"], "保存工单", no)
    return {"ok": True, "no": no, "created": created}


def api_wo_del(u, body, q, no):
    w = db.one("SELECT * FROM work_orders WHERE no=?", (no,))
    if not w:
        raise ApiError("工单不存在", 404)
    if w["status"] == "排产中":
        raise ApiError("工单已排产，先取消排程", 409)
    db.run("DELETE FROM work_orders WHERE no=?", (no,))
    db.bumpsync("work_orders")
    log(u["username"], "删除工单", no)
    return {"ok": True}


# ------------------------------------------------ 排程
def api_plan_run(u, body, q):
    body = body or {}
    rule = body.get("rule") or rules().get("sched_rule") or aps.DEFAULT_RULE
    if rule not in aps.RULES:
        raise ApiError("rule 需为 %s" % "/".join(aps.RULES))
    horizon = int(body.get("horizon") or rules().get("horizon_days") or aps.HORIZON_DAYS)
    start = datetime.date.fromisoformat(body.get("start")) if body.get("start") else db.today()
    resources, routings, boms, materials = _load_context()
    if not resources:
        raise ApiError("没有可用的运行状态工作中心")
    wos = _load_wos()
    if not wos:
        raise ApiError("没有待排产工单（状态 已下达/排产中）")
    wos = [w for w in wos if w["due_date"] >= start or w["status"] == "排产中"]
    st, res = aps.schedule(wos, routings, resources, start=start, rule=rule, horizon=horizon)
    loads = aps.load_report(st)
    bn = aps.bottleneck(loads)
    in_order = sort_wo_for_kit(ordered_nos(res), wos)
    kit_rows, stock_after = aps.material_check(in_order, boms, materials)
    short_agg = aps.shortage_summary(kit_rows)
    rls = rules()
    alerts = aps.build_alerts(res, loads, short_agg, rls)
    # 持久化
    run_no = db.gen_no(db.connect(), "schedule_runs", "RUN", col="run_no")
    run_id = db.run("INSERT INTO schedule_runs(run_no,rule,start_date,horizon_days,wo_count,"
                    "late_count,bottleneck_wc,status,run_by,run_at,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (run_no, rule, start.isoformat(), horizon, len(res),
                     sum(1 for r in res if r["late"]), (bn or {}).get("wc", ""),
                     "生效", u["username"], db.now(),
                     json.dumps({"loads": loads, "alerts": alerts,
                                 "kit": kit_rows, "stock_after": stock_after,
                                 "spans": st.spans,
                                 "days": [d.isoformat() for d in st.days]},
                                ensure_ascii=False, default=str)))
    db.run("UPDATE schedule_runs SET status='历史' WHERE id<>? AND status='生效'", (run_id,))
    for r in res:
        for op in r["ops"]:
            if op.get("start"):
                db.run("INSERT INTO schedule_ops(run_id,wo,seq,wc,hours,start_date,start_h,"
                       "end_date,end_h) VALUES(?,?,?,?,?,?,?,?,?)",
                       (run_id, r["wo"], op["seq"], op["wc"], op["hours"], op["start"],
                        op.get("start_h", 0), op.get("end") or "", op.get("end_h", 0)))
        db.run("UPDATE work_orders SET status=? WHERE no=?",
               ("排产中" if r["feasible"] else "排程失败", r["wo"]))
    new_alerts = []
    for a in alerts:
        row = raise_alarm(a["atype"], a["level"], a["target"], a["message"],
                          a.get("value", 0), a.get("threshold", 0))
        new_alerts.append(row["no"])
    log(u["username"], "执行排程", "%s %s %d工单 迟交%d" % (run_no, rule, len(res),
                                                          sum(1 for r in res if r["late"])))
    db.bumpsync("work_orders")
    return {"run_no": run_no, "run_id": run_id, "rule": rule, "start": start.isoformat(),
            "wo_count": len(res), "late_count": sum(1 for r in res if r["late"]),
            "bottleneck": bn, "loads": loads, "results": res,
            "kit": kit_rows, "shortage": short_agg,
            "alerts": alerts, "alert_nos": new_alerts,
            "stock_after": stock_after}


def ordered_nos(res):
    return [r["wo"] for r in res]


def sort_wo_for_kit(nos, wos):
    m = {w["no"]: w for w in wos}
    return [m[n] for n in nos if n in m]


def _latest_run():
    r = db.one("SELECT * FROM schedule_runs WHERE status='生效' ORDER BY id DESC LIMIT 1")
    if not r:
        raise ApiError("尚未执行排程，请先 POST /api/plan/run", 404)
    return r


def api_plan_latest(u, body, q):
    r = _latest_run()
    ops = db.rows("SELECT * FROM schedule_ops WHERE run_id=? ORDER BY wo,seq", (r["id"],))
    detail = json.loads(r["detail"]) if r["detail"] else {}
    return {"run": {k: r[k] for k in ("run_no", "rule", "start_date", "horizon_days",
                                      "wo_count", "late_count", "bottleneck_wc", "run_by", "run_at")},
            "ops": ops, "loads": detail.get("loads", []),
            "kit": detail.get("kit", []), "shortage": detail.get("stock_after", {})}


def api_plan_overview(u, body, q):
    """看板聚合：一次拿齐最近生效批次 + 负荷，未排程时返回空结构而非 404。"""
    r = db.one("SELECT * FROM schedule_runs WHERE status='生效' ORDER BY id DESC LIMIT 1")
    if not r:
        return {"run": None, "loads": [], "bottleneck": None, "hint": "尚未排程"}
    detail = json.loads(r["detail"]) if r["detail"] else {}
    return {"run": {k: r[k] for k in ("run_no", "rule", "start_date", "horizon_days",
                                      "wo_count", "late_count", "bottleneck_wc",
                                      "run_by", "run_at")},
            "loads": detail.get("loads", []),
            "bottleneck": ({"wc": r["bottleneck_wc"]} if r["bottleneck_wc"] else None)}


def api_plan_gantt(u, body, q):
    r = _latest_run()
    ops = db.rows("SELECT * FROM schedule_ops WHERE run_id=? ORDER BY start_date,wc,wo",
                  (r["id"],))
    g = {}
    for o in ops:
        g.setdefault(o["wc"], []).append(o)
    wos = db.rows("SELECT no,product,qty,due_date,status FROM work_orders")
    return {"run_no": r["run_no"], "start_date": r["start_date"],
            "horizon_days": r["horizon_days"], "by_wc": g,
            "work_orders": {w["no"]: w for w in wos}}


def api_plan_load(u, body, q):
    r = _latest_run()
    detail = json.loads(r["detail"]) if r["detail"] else {}
    return {"run_no": r["run_no"], "loads": detail.get("loads", []),
            "bottleneck": ({"wc": r["bottleneck_wc"]} if r["bottleneck_wc"] else None)}


def api_plan_dayload(u, body, q, wc):
    r = _latest_run()
    detail = json.loads(r["detail"]) if r["detail"] else {}
    days = detail.get("days") or []
    spans = detail.get("spans") or []
    if not db.one("SELECT 1 FROM workcenters WHERE code=?", (wc,)):
        raise ApiError("工作中心不存在", 404)
    resources, _, _, _ = _load_context()
    wc_obj = next((x for x in resources if x["code"] == wc), None)
    buckets = {}
    for sp in spans:
        if sp["wc"] == wc:
            buckets[sp["day_idx"]] = round(buckets.get(sp["day_idx"], 0.0) + sp["hours"], 4)
    out = []
    for i, ds in enumerate(days):
        d = datetime.date.fromisoformat(ds)
        out.append({"date": ds,
                    "capacity": aps.workday_capacity(wc_obj, d) if wc_obj else 0.0,
                    "load": buckets.get(i, 0.0)})
    return {"wc": wc, "run_no": r["run_no"], "days": out,
            "total_load": round(sum(x["load"] for x in out), 2),
            "total_cap": round(sum(x["capacity"] for x in out), 2)}


def api_plan_pushin(u, body, q):
    """插单：body {product,qty,due_date,priority,customer,no} → 创建 SO+WO 并重排"""
    body = body or {}
    prod = body.get("product") or ""
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("qty 必须 > 0")
    due = body.get("due_date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        raise ApiError("due_date 需 YYYY-MM-DD")
    prio = int(body.get("priority") or 1)
    cn = db.connect()
    so_no = body.get("no") or db.gen_no(cn, "sales_orders", "SO-" + db.today().strftime("%Y-"))
    if db.one("SELECT 1 FROM sales_orders WHERE no=?", (so_no,)):
        raise ApiError("订单号已存在", 409)
    wo_no = "WO" + so_no.split("-")[-1]
    db.run("INSERT INTO sales_orders(no,customer,product,qty,due_date,priority,status,created_date,remark) "
           "VALUES(?,?,?,?,?,?,?,?,?)",
           (so_no, body.get("customer") or "插单", prod, qty, due, prio, "已转工单",
            db.today().isoformat(), "插单"))
    db.run("INSERT INTO work_orders(no,so,product,qty,due_date,priority,status,release_date,created_date,remark) "
           "VALUES(?,?,?,?,?,?,?,?,?,?)",
           (wo_no, so_no, prod, qty, due, prio, "已下达", db.today().isoformat(), db.now(), "插单"))
    db.bumpsync("sales_orders")
    db.bumpsync("work_orders")
    # 重排
    result = api_plan_run(u, {"rule": rules().get("sched_rule") or aps.DEFAULT_RULE}, q)
    new_end = None
    for r in result.get("results", []):
        if r["wo"] == wo_no:
            new_end = r["end"]
    late = [r["wo"] for r in result.get("results", []) if r["late"]]
    log(u["username"], "插单重排", "%s → %s 完工 %s" % (so_no, wo_no, new_end))
    return {"so": so_no, "wo": wo_no, "end": new_end,
            "late_count": len(late), "late_wos": late,
            "run_no": result["run_no"]}


# ------------------------------------------------ 齐套
def api_kit_run(u, body, q):
    resources, routings, boms, materials = _load_context()
    wos = _load_wos(("已下达", "排产中"))
    if not wos:
        raise ApiError("没有待检查工单")
    rule = rules().get("sched_rule") or aps.DEFAULT_RULE
    ordered = aps.sort_workorders(wos, db.today(), rule)
    rows, stock_after = aps.material_check(ordered, boms, materials)
    short = aps.shortage_summary(rows)
    check_no = db.gen_no(db.connect(), "kit_checks", "KIT", col="check_no")
    for r in rows:
        db.run("INSERT INTO kit_checks(check_no,wo,product,kit_ok,shortage,need,checked_at) "
               "VALUES(?,?,?,?,?,?,?)",
               (check_no, r["wo"], r["product"], 1 if r["kit_ok"] else 0,
                json.dumps(r["shortage"], ensure_ascii=False),
                json.dumps(r["need"], ensure_ascii=False), db.now()))
    log(u["username"], "齐套检查", check_no)
    return {"check_no": check_no, "rows": rows, "shortage": short,
            "stock_after": stock_after,
            "ok_count": sum(1 for r in rows if r["kit_ok"]),
            "block_count": sum(1 for r in rows if not r["kit_ok"])}


def api_kit_history(u, body, q):
    return db.rows("SELECT check_no,wo,product,kit_ok,checked_at FROM kit_checks "
                   "ORDER BY id DESC LIMIT 200")


# ------------------------------------------------ CTP
def api_ctp(u, body, q):
    body = body or {}
    prod = body.get("product") or ""
    if not db.one("SELECT 1 FROM products WHERE code=?", (prod,)):
        raise ApiError("产品不存在", 404)
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("qty 必须 > 0")
    due_s = body.get("due_date") or ""
    due = (datetime.date.fromisoformat(due_s) if re.match(r"^\d{4}-\d{2}-\d{2}$", due_s)
           else db.today() + datetime.timedelta(days=30))
    resources, routings, boms, materials = _load_context()
    wos = _load_wos()
    rls = rules()
    ans = aps.ctp({"product": prod, "qty": qty, "due_date": due,
                   "priority": int(body.get("priority") or 3)},
                  routings, resources, wos, rule=rls.get("sched_rule") or aps.DEFAULT_RULE,
                  horizon=int(rls.get("horizon_days") or aps.HORIZON_DAYS))
    db.run("INSERT INTO ctp_queries(product,qty,due_date,answer_end,on_time,feasible,"
           "queried_by,queried_at) VALUES(?,?,?,?,?,?,?,?)",
           (prod, qty, due.isoformat(), ans.get("end") or "", 1 if ans["on_time"] else 0,
            1 if ans["feasible"] else 0, u["username"], db.now()))
    log(u["username"], "CTP 查询", "%s x%g" % (prod, qty))
    return {"product": prod, "qty": qty, "requested_due": due.isoformat(),
            "earliest_end": ans.get("end"), "on_time": ans["on_time"],
            "feasible": ans["feasible"], "late_days": ans.get("late_days", 0),
            "suggestion": ("可按期承诺" if ans["on_time"] else
                           ("视界内排不下，建议拆单/外协" if not ans["feasible"]
                            else "最早 %s 完工，比交期晚 %d 天，建议协商交期或插单"
                            % (ans.get("end"), ans.get("late_days", 0))))}


def api_ctp_history(u, body, q):
    return db.rows("SELECT * FROM ctp_queries ORDER BY id DESC LIMIT 100")


# ------------------------------------------------ 告警
def api_alerts(u, body, q):
    st = q.get("status")
    if st:
        return db.rows("SELECT * FROM alarms WHERE status=? ORDER BY id DESC LIMIT 300", (st,))
    return db.rows("SELECT * FROM alarms ORDER BY id DESC LIMIT 300")


def api_alert_handle(u, body, q, no):
    a = db.one("SELECT * FROM alarms WHERE no=?", (no,))
    if not a:
        raise ApiError("告警不存在", 404)
    if a["status"] == "已处理":
        raise ApiError("告警已处理", 409)
    db.run("UPDATE alarms SET status='已处理' WHERE no=?", (no,))
    log(u["username"], "处理告警", no)
    return {"ok": True}


# ------------------------------------------------ 规则 / 报表 / 系统
def api_rules(u, body, q):
    return rules()


def api_rule_save(u, body, q):
    body = body or {}
    if "rules" in body and isinstance(body["rules"], dict):
        items = body["rules"].items()
    elif body.get("key") is not None:
        items = [(body["key"], body.get("value"))]
    else:
        raise ApiError("需提供 {key,value} 或 {rules:{...}}")
    known = set(aps.DEFAULT_RULES)
    for k, v in items:
        if k not in known:
            raise ApiError("未知规则 key: %s" % k)
        db.run("INSERT INTO rules(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    log(u["username"], "更新规则", ",".join(items and [k for k, _ in items] or []))
    return {"ok": True, "rules": rules()}


def api_rep_schedule_csv(u, body, q):
    r = _latest_run()
    ops = db.rows("SELECT * FROM schedule_ops WHERE run_id=? ORDER BY wo,seq", (r["id"],))
    lines = ["工单,工序,工作中心,工时(h),开始日,开始时,结束日,结束时"]
    for o in ops:
        lines.append(",".join(str(x) for x in (o["wo"], o["seq"], o["wc"], o["hours"],
                                               o["start_date"], o["start_h"],
                                               o["end_date"], o["end_h"])))
    return _csv("\n".join(lines))


def api_rep_load_csv(u, body, q):
    r = _latest_run()
    detail = json.loads(r["detail"]) if r["detail"] else {}
    lines = ["工作中心,名称,可用产能(h),负荷(h),利用率,剩余(h)"]
    for l in detail.get("loads", []):
        lines.append(",".join(str(x) for x in (l["wc"], l["name"], l["capacity_h"],
                                               l["load_h"], l["utilization"], l["free_h"])))
    return _csv("\n".join(lines))


def _csv(text):
    return text, "text/csv; charset=utf-8"


def api_logs(u, body, q):
    return db.rows("SELECT * FROM logs ORDER BY id DESC LIMIT 200")


def api_sync(u, body, q):
    ents = [x for x in (q.get("entities") or "").split(",") if x]
    since = int(q.get("version") or 0)
    out = {}
    for e in db.rows("SELECT * FROM sync_state WHERE version>?", (since,)):
        if ents and "*" not in ents and e["entity"] not in ents:
            continue
        table = e["entity"]
        if table in ("sales_orders", "work_orders", "workcenters", "materials",
                     "products", "bom", "routing_ops"):
            out[table] = {"version": e["version"], "rows": db.rows("SELECT * FROM %s" % table)}
    return out


def api_sync_version(u, body, q):
    return {r["entity"]: r["version"] for r in db.rows("SELECT * FROM sync_state")}


# ------------------------------------------------ API Key
def api_keys_list(u, body, q):
    return db.rows("SELECT id,name,key_prefix,role,status,created_at,last_used FROM api_keys "
                   "ORDER BY id DESC")


def api_keys_create(u, body, q):
    name = (body or {}).get("name") or ""
    if not name:
        raise ApiError("name 必填")
    role = body.get("role") or "reader"
    if role not in aps.ROLE_PERMS:
        raise ApiError("角色不存在")
    raw = "apskey_" + secrets.token_hex(16)
    prefix = raw[:12]
    db.run("INSERT INTO api_keys(name,key_prefix,key_hash,role,created_at) VALUES(?,?,?,?,?)",
           (name, prefix, db.sha256(raw), role, db.now()))
    log(u["username"], "创建APIKey", name)
    return {"key": raw, "prefix": prefix, "role": role,
            "note": "仅此一次返回完整 key，请妥善保存"}


def api_keys_delete(u, body, q, kid):
    db.run("DELETE FROM api_keys WHERE id=?", (kid,))
    log(u["username"], "删除APIKey", kid)
    return {"ok": True}


# ------------------------------------------------ OpenAPI
def api_apidoc(u, body, q):
    paths = {}
    for m, pat, fn, perm in ROUTES:
        p = re.sub(r"\(\[\^/\]\+\)", "{id}", pat.replace("^/api", "/api").replace("$", ""))
        p = re.sub(r"\(\[\^\ /\]\+\)", "{id}", p)
        p = p.replace("(?P<p1>[^/]+)", "{p1}").replace("(?P<p2>[^/]+)", "{p2}")
        p = re.sub(r"\(\?P<(\w+)>\[\^/\]\+\)", r"{\1}", p)
        p = re.sub(r"\((\[\^/\]\+|[^()]+)\)", "{param}", p) if "(" in p and "{" not in p else p
        node = paths.setdefault(p, {})
        node[m.lower()] = {"operationId": fn.__name__,
                           "permission": perm or "仅登录",
                           "summary": (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""}
    return {"openapi": "3.0.0", "info": {"title": BRAND, "version": VERSION},
            "paths": paths}


# ================================================================ 路由表
ROUTES = [
    ("GET", r"^/api/health$", lambda u, b, q: api_health(u, b, q), None),
    ("GET", r"^/api/apidoc$", lambda u, b, q: api_apidoc(u, b, q), None),
    ("POST", r"^/api/auth/login$", lambda u, b, q: api_login(u, b, q), None),
    ("POST", r"^/api/auth/logout$", api_logout, None),
    ("GET", r"^/api/auth/me$", lambda u, b, q: api_me(u, b, q), None),
    ("POST", r"^/api/auth/change-password$", api_change_pwd, None),

    ("GET", r"^/api/users$", api_users, "system.read"),
    ("POST", r"^/api/users/save$", api_user_save, "system.write"),
    ("POST", r"^/api/users/reset-password$", api_user_reset, "system.write"),
    ("GET", r"^/api/roles$", lambda u, b, q: api_roles(u, b, q), None),

    ("GET", r"^/api/workcenters$", api_wc_list, "master.read"),
    ("POST", r"^/api/workcenters/save$", api_wc_save, "master.write"),
    ("POST", r"^/api/workcenters/([\w\-]+)/delete$", lambda u, b, q, c: api_wc_del(u, b, q, c), "master.write"),
    ("GET", r"^/api/materials$", api_mat_list, "master.read"),
    ("POST", r"^/api/materials/save$", api_mat_save, "master.write"),
    ("POST", r"^/api/materials/([\w\-]+)/delete$", lambda u, b, q, c: api_mat_del(u, b, q, c), "master.write"),
    ("POST", r"^/api/materials/adjust$", api_mat_adjust, "master.write"),
    ("GET", r"^/api/products$", api_prod_list, "master.read"),
    ("POST", r"^/api/products/save$", api_prod_save, "master.write"),
    ("POST", r"^/api/products/([\w\-]+)/delete$", lambda u, b, q, c: api_prod_del(u, b, q, c), "master.write"),
    ("GET", r"^/api/bom$", api_bom_list, "master.read"),
    ("POST", r"^/api/bom/save$", api_bom_save, "master.write"),
    ("POST", r"^/api/bom/([\w\-]+)/([\w\-]+)/delete$",
     lambda u, b, q, p, m: api_bom_del(u, b, q, p, m), "master.write"),
    ("GET", r"^/api/routings$", api_rt_list, "master.read"),
    ("POST", r"^/api/routings/save$", api_rt_save, "master.write"),
    ("POST", r"^/api/routings/([\w\-]+)/(\d+)/delete$",
     lambda u, b, q, p, s: api_rt_del(u, b, q, p, s), "master.write"),

    ("GET", r"^/api/sales-orders$", api_so_list, "so.read"),
    ("POST", r"^/api/sales-orders/save$", api_so_save, "so.write"),
    ("POST", r"^/api/sales-orders/([\w\-]+)/delete$", lambda u, b, q, n: api_so_del(u, b, q, n), "so.write"),
    ("POST", r"^/api/sales-orders/release$", api_so_release, "wo.write"),
    ("GET", r"^/api/work-orders$", api_wo_list, "wo.read"),
    ("POST", r"^/api/work-orders/save$", api_wo_save, "wo.write"),
    ("POST", r"^/api/work-orders/([\w\-]+)/delete$", lambda u, b, q, n: api_wo_del(u, b, q, n), "wo.write"),

    ("POST", r"^/api/plan/run$", api_plan_run, "plan.run"),
    ("GET", r"^/api/plan/latest$", api_plan_latest, "plan.read"),
    ("GET", r"^/api/plan/overview$", api_plan_overview, "plan.read"),
    ("GET", r"^/api/plan/gantt$", api_plan_gantt, "plan.read"),
    ("GET", r"^/api/plan/load$", api_plan_load, "plan.read"),
    ("GET", r"^/api/plan/dayload/([\w\-]+)$", lambda u, b, q, w: api_plan_dayload(u, b, q, w), "plan.read"),
    ("POST", r"^/api/plan/push-in$", api_plan_pushin, "plan.run"),

    ("POST", r"^/api/kit/run$", api_kit_run, "check.read"),
    ("GET", r"^/api/kit/history$", api_kit_history, "check.read"),

    ("POST", r"^/api/ctp$", api_ctp, "ctp.read"),
    ("GET", r"^/api/ctp/history$", api_ctp_history, "ctp.read"),

    ("GET", r"^/api/alerts$", api_alerts, "alert.read"),
    ("POST", r"^/api/alerts/([\w\-]+)/handle$", lambda u, b, q, n: api_alert_handle(u, b, q, n), "alert.read"),

    ("GET", r"^/api/rules$", api_rules, "plan.read"),
    ("POST", r"^/api/rules/save$", api_rule_save, "plan.run"),

    ("GET", r"^/api/reports/schedule.csv$", api_rep_schedule_csv, "report.read"),
    ("GET", r"^/api/reports/load.csv$", api_rep_load_csv, "report.read"),

    ("GET", r"^/api/logs$", api_logs, "system.read"),
    ("GET", r"^/api/sync$", api_sync, None),
    ("GET", r"^/api/sync/version$", api_sync_version, None),

    ("GET", r"^/api/api-keys$", api_keys_list, "system.read"),
    ("POST", r"^/api/api-keys/create$", api_keys_create, "system.write"),
    ("POST", r"^/api/api-keys/(\d+)/delete$", lambda u, b, q, i: api_keys_delete(u, b, q, i), "system.write"),
]


# ================================================================ 鉴权
def auth_user(cn, req_handler, q):
    tok = ""
    h = req_handler.headers
    auth = h.get("Authorization") or ""
    if auth.startswith("Bearer "):
        tok = auth[7:]
    tok = h.get("X-Aps-Token") or tok
    key = h.get("X-Aps-Key") or ""
    if not tok:
        ck = h.get("Cookie") or ""
        m = re.search(r"aps_token=([0-9a-f]+)", ck)
        if m:
            tok = m.group(1)
    if not tok and q.get("token"):
        tok = q["token"]
    if key and not tok:
        row = db.one("SELECT * FROM api_keys WHERE key_hash=? AND status='启用'",
                     (db.sha256(key),))
        if row:
            db.run("UPDATE api_keys SET last_used=? WHERE id=?", (db.now(), row["id"]))
            return {"username": "apikey:" + row["key_prefix"], "name": row["name"],
                    "role": row["role"]}
        raise ApiError("API Key 无效", 401)
    if not tok:
        raise ApiError("未认证", 401)
    t = db.one("SELECT * FROM tokens WHERE token=?", (tok,))
    if not t or t["expire_at"] < db.now():
        raise ApiError("令牌无效或已过期", 401)
    u = db.one("SELECT * FROM users WHERE username=? AND status='启用'", (t["username"],))
    if not u:
        raise ApiError("用户不存在或停用", 401)
    u["_token"] = tok
    return u


def check_perm(u, perm):
    if not perm:
        return
    if not aps.has_perm(u["role"], perm):
        raise ApiError("无权限：%s（角色 %s）" % (perm, u["role"]), 403)


# ================================================================ Handler
class Handler(BaseHTTPRequestHandler):
    server_version = "FeiHuaAPS/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8", raw=None):
        body = raw if raw is not None else json.dumps(data, ensure_ascii=False, default=str).encode()
        if raw is None and isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type,Authorization,X-Aps-Token,X-Aps-Key,Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self._send(204, None, raw=b"")

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if PREFIX and path.startswith(PREFIX):
            path = path[len(PREFIX):] or "/"
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if path == "/" or path == "/index.html":
            return self._static("index.html")
        if path == "/login.html":
            return self._static("login.html")
        if not path.startswith("/api/"):
            if method == "GET" and re.search(r"\.(html|css|js|png|svg|ico|woff2?|jpg|json|map)$", path):
                return self._static(path.lstrip("/"))
            return self._send(404, {"code": 404, "message": "资源不存在"})
        body = self._read_body() if method == "POST" else {}
        if path in ("/api/health", "/api/sync/version"):
            try:
                result = api_health(None, body, q) if path == "/api/health" else api_sync_version(None, body, q)
                return self._send(200, {"code": 200, "message": "ok", "data": result})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"code": 500, "message": str(e)})
        if path == "/api/auth/login":
            try:
                return self._send(200, {"code": 200, "message": "ok",
                                        "data": api_login(None, body, q)})
            except ApiError as e:
                return self._send(e.code, {"code": e.code, "message": str(e)})
        cn = db.connect()
        try:
            u = auth_user(cn, self, q)
        except ApiError as e:
            return self._send(e.code, {"code": e.code, "message": str(e)})
        for m, pat, fn, perm in ROUTES:
            if m != method:
                continue
            mm = re.match(pat, path)
            if not mm:
                continue
            try:
                check_perm(u, perm)
                args = [u, body, q] + list(mm.groups())
                result = fn(*args)
                if isinstance(result, tuple) and len(result) == 2:
                    text, ctype = result
                    return self._send(200, None, ctype=ctype,
                                      raw=text.encode("utf-8"))
                return self._send(200, {"code": 200, "message": "ok", "data": result})
            except ApiError as e:
                return self._send(e.code, {"code": e.code, "message": str(e)})
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                return self._send(500, {"code": 500, "message": "服务器内部错误: %s" % e})
        return self._send(404, {"code": 404, "message": "接口不存在：%s %s" % (method, path)})

    def _static(self, rel):
        safe = os.path.normpath(rel)
        if safe.startswith("..") or os.path.isabs(safe):
            return self._send(403, {"code": 403, "message": "forbidden"})
        full = os.path.join(STATIC_DIR, safe)
        if not os.path.isfile(full):
            return self._send(404, {"code": 404, "message": "静态资源不存在"})
        ext = os.path.splitext(full)[1]
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
                 ".json": "application/json"}.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, None, ctype=ctype, raw=f.read())

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main():
    db.init()
    created = seedmod.seed()
    refresh_context()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("%s v%s | port=%d prefix=%r db=%s seed=%s"
          % (BRAND, VERSION, PORT, PREFIX, db.DB_PATH, created))
    srv.serve_forever()


if __name__ == "__main__":
    main()
