# -*- coding: utf-8 -*-
"""飞划APS · 生成离线单文件 DEMO

思路：用真实后端算出一整套业务数据（排程结果、负荷、齐套、CTP、告警），
再把前端 style.css / app.js / pages.js 内联进一个 HTML，并把 GET 请求拦截为
读取内置的 MOCK 数据 —— 于是双击这个 HTML 就能看到与线上完全一致的真实界面，
不需要服务器、不需要网络。

用法：
    python tools/build_demo.py
产物：
    demo/飞划APS系统Demo.html
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

DEMO_DB = os.path.join(ROOT, "demo", "_demo.db")
for suffix in ("", "-wal", "-shm"):
    p = DEMO_DB + suffix
    if os.path.exists(p):
        os.remove(p)
os.environ["APS_DB"] = DEMO_DB
os.environ["APS_PORT"] = "0"

import aps          # noqa: E402
import db           # noqa: E402
import seed as seedmod   # noqa: E402
import server       # noqa: E402

OUT = os.path.join(ROOT, "demo", "飞划APS系统Demo.html")
ADMIN = {"username": "admin", "name": "系统管理员", "role": "admin",
         "roleLabel": "系统管理员", "perms": ["*"]}


def build_mock():
    """在临时库里跑一遍真实业务，把响应快照成 GET 数据源。"""
    db.init()
    seedmod.seed()
    server.refresh_context()

    run = server.api_plan_run(ADMIN, {"rule": "EDD"}, {})
    kit = server.api_kit_run(ADMIN, {}, {})
    latest = server.api_plan_latest(ADMIN, {}, {})
    overview = server.api_plan_overview(ADMIN, {}, {})
    gantt = server.api_plan_gantt(ADMIN, {}, {})
    load = server.api_plan_load(ADMIN, {}, {})

    wcs = server.api_wc_list(ADMIN, {}, {})
    dayload = {}
    for w in wcs:
        dayload[w["code"]] = server.api_plan_dayload(ADMIN, {}, {"days": "30"}, w["code"])

    products = server.api_prod_list(ADMIN, {}, {})
    ctp = {}
    for p in products[:3]:
        ctp[p["code"]] = server.api_ctp(ADMIN, {"product": p["code"], "qty": 5,
                                                "due_date": (db.today() + datetime.timedelta(days=30)).isoformat()}, {})

    return {
        "/api/health": server.api_health(ADMIN, {}, {}),
        "/api/auth/me": ADMIN,
        "/api/alerts": server.api_alerts(ADMIN, {}, {}),
        "/api/plan/latest": latest,
        "/api/plan/overview": overview,
        "/api/plan/gantt": gantt,
        "/api/plan/load": load,
        "/api/plan/run": run,
        "/api/kit/run": kit,
        "/api/kit/history": server.api_kit_history(ADMIN, {}, {}),
        "/api/ctp/history": server.api_ctp_history(ADMIN, {}, {}),
        "/api/sales-orders": server.api_so_list(ADMIN, {}, {}),
        "/api/work-orders": server.api_wo_list(ADMIN, {}, {}),
        "/api/workcenters": wcs,
        "/api/materials": server.api_mat_list(ADMIN, {}, {}),
        "/api/products": products,
        "/api/bom": server.api_bom_list(ADMIN, {}, {}),
        "/api/routings": server.api_rt_list(ADMIN, {}, {}),
        "/api/rules": server.api_rules(ADMIN, {}, {}),
        "/api/roles": server.api_roles(ADMIN, {}, {}),
        "/api/users": server.api_users(ADMIN, {}, {}),
        "/api/logs": server.api_logs(ADMIN, {}, {}),
        "/api/api-keys": server.api_keys_list(ADMIN, {}, {}),
        "/api/apidoc": server.api_apidoc(ADMIN, {}, {}),
        "__dayload__": dayload,
        "__ctp__": ctp,
    }


def read(name):
    with open(os.path.join(ROOT, "frontend", name), encoding="utf-8") as f:
        return f.read()


SHIM = """
/* ============ 离线 DEMO 运行时 ============ */
var MOCK = __MOCK__;
var DEMO = {
  /* 前端用的 get 兜底：按路径取内置快照 */
  get: function (path) {
    var p = path.split('?')[0];
    if (MOCK[p] !== undefined) return MOCK[p];
    if (p.indexOf('/api/plan/dayload/') === 0)
      return MOCK.__dayload__[p.split('/').pop()] || [];
    return [];
  },
  post: function (path, body) {
    var p = path.split('?')[0];
    if (p === '/api/ctp') {
      var d = MOCK.__ctp__[(body || {}).product];
      if (d) return d;
      return {product: (body || {}).product, qty: (body || {}).qty,
              earliest_end: null, on_time: false, feasible: false, late_days: 0,
              suggestion: 'DEMO 中仅预置了部分产品的 CTP 结果'};
    }
    if (p === '/api/plan/run') return MOCK['/api/plan/run'];
    if (p === '/api/plan/push-in') return {so: 'SO-DEMO', wo: 'WO-DEMO', end: null,
      late_count: 0, late_wos: [], run_no: MOCK['/api/plan/run'].run_no};
    if (p === '/api/kit/run') return MOCK['/api/kit/run'];
    return {ok: true};
  }
};
"""


def main():
    mock = build_mock()
    css = read("style.css")
    appjs = read("app.js")
    pagesjs = read("pages.js")

    # 1) app.js：把 fetch 换成读内置数据
    appjs = appjs.replace(
        """function api(method, path, body, raw) {
  return fetch(path, {""",
        """function api(method, path, body, raw) {
  /* DEMO：不发请求，直接读内置数据 */
  if (method === 'POST') return Promise.resolve(DEMO.post(path, body));
  var _d = DEMO.get(path);
  return Promise.resolve(raw ? DEMO.csvOf(path) : {code: 200, message: 'ok', data: _d});
}
function _apiReal(method, path, body, raw) {
  return fetch(path, {""")

    # 2) CSV 导出在 DEMO 中生成示意文本
    appjs += """
DEMO.csvOf = function (path) {
  if (path.indexOf('schedule') >= 0) {
    var ops = (DEMO.get('/api/plan/latest') || {}).ops || [];
    return '工单,工序,工作中心,工时(h),开始日,开始时,结束日,结束时\\n' +
      ops.map(function (o) { return [o.wo, o.seq, o.wc, o.hours, o.start_date,
        o.start_h, o.end_date, o.end_h].join(','); }).join('\\n');
  }
  var ls = (DEMO.get('/api/plan/load') || {}).loads || [];
  return '工作中心,名称,可用产能(h),负荷(h),利用率,剩余(h)\\n' +
    ls.map(function (l) { return [l.wc, l.name, l.capacity_h, l.load_h,
      l.utilization, l.free_h].join(','); }).join('\\n');
};
"""

    # 3) boot：DEMO 里跳过登录校验，直接进主界面
    appjs = appjs.replace(
        """function boot() {
  if (!TOKEN) { location.href = 'login.html'; return; }
  GET('/api/auth/me').then(function (j) {""",
        """function boot() {
  TOKEN = TOKEN || 'demo';   /* DEMO：免登录 */
  GET('/api/auth/me').then(function (j) {""")

    # 4) 退出按钮在 DEMO 中不做跳转
    appjs = appjs.replace(
        """    document.getElementById('btn-logout').onclick = function () {
      POST('/api/auth/logout').then(function () {
        localStorage.clear(); location.href = 'login.html';
      });
    };""",
        """    document.getElementById('btn-logout').onclick = function () {
      toast('离线 DEMO 无登录态，退出不生效');
    };
    if (window.__DEMO_BANNER__) document.body.classList.add('demo-mode');""")

    # 5) 写操作在 DEMO 中给出提示，不静默失败
    appjs = appjs.replace(
        """function POST(p, b) { return api('POST', p, b); }""",
        """function POST(p, b) {
  if (p.indexOf('/save') > 0 || p.indexOf('/delete') > 0 || p.indexOf('/adjust') > 0) {
    toast('离线 DEMO：写操作已禁用'); 
    return Promise.resolve({code: 200, data: {ok: true}});
  }
  return api('POST', p, b);
}""")

    shim = SHIM.replace("__MOCK__", json.dumps(mock, ensure_ascii=False, default=str))

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>飞划APS管理系统 · 离线DEMO</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%E2%9A%A1%3C/text%3E%3C/svg%3E" />
<style>
__CSS__
.demo-tip { position:fixed; right:18px; bottom:18px; z-index:99; background:#1f2733; color:#fff;
  padding:10px 14px; border-radius:10px; font-size:12.5px; box-shadow:0 6px 20px rgba(0,0,0,.2);
  max-width:280px; line-height:1.6; }
.demo-tip b { color:#ffd666; }
</style>
</head>
<body>
<div id="sidebar">
  <div class="brand">⚡ 飞划APS</div>
  <div class="brand-sub">高级计划与排程</div>
  <nav id="nav"></nav>
  <div class="side-foot">
    <span id="who"></span>
    <button id="btn-logout" class="btn ghost sm">退出</button>
  </div>
</div>
<main id="main"><div class="empty">加载中…</div></main>
<div id="modal-mask" class="modal-mask hidden"><div id="modal" class="modal"></div></div>
<div id="toast" class="toast hidden"></div>
<div class="demo-tip"><b>离线 DEMO</b><br/>数据为真实排程结果快照，交互可点，写操作已禁用。</div>
<script>
__SHIM__
</script>
<script>
__APPJS__
</script>
<script>
__PAGESJS__
</script>
<script>boot();</script>
</body>
</html>
"""
    html = (html.replace("__CSS__", css)
                .replace("__SHIM__", shim)
                .replace("__APPJS__", appjs)
                .replace("__PAGESJS__", pagesjs))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(OUT)
    print("DEMO 生成完成：%s（%.1f KB）" % (OUT, size / 1024.0))
    print("内置数据：%d 个接口快照；排程批次 %s（%d 工单 / 迟交 %d）"
          % (len(mock), mock["/api/plan/run"]["run_no"],
             mock["/api/plan/run"]["wo_count"], mock["/api/plan/run"]["late_count"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
