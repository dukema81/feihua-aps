# -*- coding: utf-8 -*-
"""飞划APS · 部署后端到端冒烟（28 项）

用法：
  python tools/smoke_api.py                        # 本地 127.0.0.1:8022
  python tools/smoke_api.py --base http://42.193.158.63/aps
"""
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8022"
for i, a in enumerate(sys.argv):
    if a == "--base" and i + 1 < len(sys.argv):
        BASE = sys.argv[i + 1].rstrip("/")

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = ""
OK = FAIL = 0
TODAY = datetime.date.today()


def call(method, path, body=None, token=None, raw=False, headers=None):
    url = BASE + path
    if not raw:
        url = BASE + urllib.parse.quote(path, safe="/?:=&%+,.[]{}")
    data = json.dumps(body).encode("utf-8") if (method == "POST" and body is not None) else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    t = token if token is not None else TOKEN
    if t:
        req.add_header("Authorization", "Bearer " + t)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with OP.open(req, timeout=60) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload.decode("utf-8")))
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload
        try:
            return e.code, json.loads(payload.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, {}


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def due(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def main():
    global TOKEN
    print("== 飞划APS 冒烟 · %s ==" % BASE)

    st, j = call("GET", "/api/health")
    d = j.get("data") or {}
    check("健康检查", st == 200 and d.get("brand") == "飞划APS管理系统", str(j)[:120])
    check("路由数 ≥50", d.get("routes", 0) >= 50, d.get("routes"))
    check("工作中心 6", d.get("workcenters") == 6, d.get("workcenters"))
    check("工单 10", d.get("work_orders") == 10, d.get("work_orders"))

    st, j = call("POST", "/api/auth/login", {"username": "admin", "password": "aps@2026"})
    TOKEN = (j.get("data") or {}).get("token", "")
    check("登录", st == 200 and TOKEN, str(j)[:120])

    st, j = call("GET", "/api/auth/me")
    check("当前用户", st == 200 and j["data"]["role"] == "admin")

    st, j = call("GET", "/api/workcenters")
    check("工作中心列表", st == 200 and len(j["data"]) == 6)
    st, j = call("GET", "/api/materials")
    check("物料列表", st == 200 and len(j["data"]) == 12)
    st, j = call("GET", "/api/products")
    check("产品列表", st == 200 and len(j["data"]) == 8)
    st, j = call("GET", "/api/bom")
    check("BOM 列表", st == 200 and len(j["data"]) >= 20)
    st, j = call("GET", "/api/routings")
    check("工艺路线", st == 200 and len(j["data"]) >= 20)
    st, j = call("GET", "/api/sales-orders")
    check("销售订单", st == 200 and len(j["data"]) == 10)
    st, j = call("GET", "/api/work-orders")
    check("生产工单", st == 200 and len(j["data"]) == 10)

    st, j = call("POST", "/api/plan/run", {"rule": "EDD"})
    pd = j.get("data") or {}
    check("执行排程", st == 200 and pd.get("wo_count") == 10, str(j)[:160])
    check("排程产生序号", str(pd.get("run_no", "")).startswith("RUN"), pd.get("run_no"))
    check("负荷覆盖 6 中心", len(pd.get("loads") or []) == 6, len(pd.get("loads") or []))
    check("瓶颈已识别", bool((pd.get("bottleneck") or {}).get("wc")))
    check("告警已生成", len(pd.get("alerts") or []) > 0, len(pd.get("alerts") or []))

    st, j = call("GET", "/api/plan/latest")
    check("最近排程", st == 200 and j["data"]["run"]["rule"] == "EDD")
    check("工序明细非空", len(j["data"].get("ops") or []) >= 10)

    st, j = call("GET", "/api/plan/gantt")
    g = (j.get("data") or {}).get("by_wc") or {}
    check("甘特数据", st == 200 and sum(len(v) for v in g.values()) >= 10)

    st, j = call("GET", "/api/plan/dayload/WC-CNC1")
    days = (j.get("data") or {}).get("days") or []
    check("日负荷曲线", st == 200 and len(days) == 90, len(days))
    check("日负荷不超产能", all(x["load"] <= x["capacity"] + 1e-6 for x in days))

    st, j = call("POST", "/api/kit/run")
    kd = j.get("data") or {}
    check("齐套检查", st == 200 and len(kd.get("rows") or []) == 10)
    check("缺料识别", kd.get("block_count", 0) >= 1, kd.get("block_count"))

    st, j = call("POST", "/api/ctp", {"product": "P-FAN", "qty": 2, "due_date": due(30)})
    check("CTP 查询", st == 200 and (j.get("data") or {}).get("earliest_end"), str(j)[:150])

    st, j = call("POST", "/api/plan/push-in",
                 {"product": "P-TROLLEY", "qty": 1, "due_date": due(25), "priority": 1})
    check("插单重排", st == 200 and (j.get("data") or {}).get("wo"), str(j)[:150])

    st, j = call("GET", "/api/alerts")
    check("告警列表", st == 200 and len(j["data"]) > 0)

    st, j = call("GET", "/api/rules")
    check("业务规则", st == 200 and "sched_rule" in j["data"])

    st, j = call("GET", "/api/users")
    check("用户列表", st == 200 and len(j["data"]) == 6)
    st, j = call("GET", "/api/roles")
    check("角色矩阵", st == 200 and len(j["data"]) == 6)
    st, j = call("GET", "/api/sync/version")
    check("增量同步版本", st == 200 and "work_orders" in (j.get("data") or {}))
    st, j = call("GET", "/api/apidoc")
    check("OpenAPI", st == 200 and len((j.get("data") or {}).get("paths") or {}) >= 40)

    st, body = call("GET", "/api/reports/schedule.csv", raw=True)
    text = body.decode("utf-8", "ignore") if isinstance(body, bytes) else ""
    check("排程 CSV", st == 200 and text.startswith("工单,工序"))
    check("CSV 中文表头", "工作中心" in text)

    st, j = call("GET", "/api/work-orders", token="")
    check("未认证 401", st == 401)

    print("\n结果：通过 %d / 失败 %d" % (OK, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
