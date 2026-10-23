# -*- coding: utf-8 -*-
"""飞划APS · UI 巡检（Playwright）：逐页渲染 + 控制台错误 + 截图 + 移动端

用法：python tools/ui_check.py [--base http://127.0.0.1:8022] [--debug-net]
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8022"
DEBUG_NET = False
for i, a in enumerate(sys.argv):
    if a == "--base" and i + 1 < len(sys.argv):
        BASE = sys.argv[i + 1].rstrip("/")
    if a == "--debug-net":
        DEBUG_NET = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dash", "仪表盘", ["最近排程序号", "迟交工单", "工作中心负荷"]),
    ("plan", "排程与甘特", ["执行排程", "甘特"]),
    ("orders", "销售订单", ["订单号", "SO-2026"]),
    ("wos", "生产工单", ["工单号", "WO"]),
    ("kit", "物料齐套", ["执行齐套检查"]),
    ("ctp", "交期承诺", ["可承诺", "历史查询"]),
    ("master", "主数据", ["工作中心", "CNC"]),
    ("alerts", "告警中心", ["告警"]),
    ("system", "系统管理", ["业务规则", "API 密钥", "审计日志"]),
]

# 可忽略的控制台噪声：favicon 兜底请求、CTP/排程等业务 4xx 的浏览器通用文案
IGNORE_MARKS = ("favicon",)

OK = FAIL = 0
ERRORS = []
NET_BAD = []


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s  %s" % (name, extra))


def real_errors():
    """过滤掉 favicon 与「资源加载失败」这类无 URL 线索的浏览器文案。"""
    out = []
    for e in ERRORS:
        low = e.lower()
        if any(m in low for m in IGNORE_MARKS):
            continue
        if "failed to load resource" in low:
            continue
        out.append(e)
    return out


def main():
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: ERRORS.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: ERRORS.append(str(e)))
        pg.on("response", lambda r: NET_BAD.append((r.status, r.url))
              if r.status >= 400 else None)

        print("== 飞划APS UI 巡检 · %s ==" % BASE)
        pg.goto(BASE + "/login.html", wait_until="networkidle")
        check("登录页加载", pg.locator("#username").count() == 1)
        pg.screenshot(path=os.path.join(SHOTS, "01-login.png"))
        pg.fill("#username", "admin")
        pg.fill("#password", "aps@2026")
        pg.click("#btn-login")
        pg.wait_for_url("**/index.html", timeout=15000)
        pg.wait_for_timeout(1600)
        check("登录跳转成功", "index.html" in pg.url)

        for i, (key, name, must) in enumerate(PAGES, 2):
            pg.goto("%s/index.html#/%s" % (BASE, key), wait_until="networkidle")
            pg.wait_for_timeout(1200)
            body = pg.inner_text("#main")
            check("%s：主区渲染" % name, len(body.strip()) > 80, len(body))
            miss = [m for m in must if m not in body]
            check("%s：关键文案" % name, not miss, "缺 " + ",".join(miss))
            pg.screenshot(path=os.path.join(SHOTS, "%02d-%s.png" % (i, key)), full_page=True)

        # 排程交互：点执行排程
        pg.goto(BASE + "/index.html#/plan", wait_until="networkidle")
        pg.wait_for_timeout(900)
        btn = pg.locator("#btn-run")
        if btn.count():
            btn.click()
            pg.wait_for_timeout(2600)
            check("执行排程按钮可用", "排程完成" in pg.inner_text("body") or
                  "生效批次" in pg.inner_text("#main"))
            pg.screenshot(path=os.path.join(SHOTS, "11-plan-after-run.png"), full_page=True)

        # 插单弹层
        pg.goto(BASE + "/index.html#/plan", wait_until="networkidle")
        pg.wait_for_timeout(900)
        pi = pg.locator("#btn-pushin")
        if pi.count():
            pi.click()
            pg.wait_for_timeout(700)
            check("插单弹层打开", pg.locator("#pi-prod").count() == 1)
            pg.screenshot(path=os.path.join(SHOTS, "12-pushin-modal.png"))
            pg.keyboard.press("Escape")
            pg.evaluate("closeModal()")

        # CTP 查询
        pg.goto(BASE + "/index.html#/ctp", wait_until="networkidle")
        pg.wait_for_timeout(900)
        if pg.locator("#c-go").count():
            pg.click("#c-go")
            pg.wait_for_timeout(1500)
            out = pg.inner_text("#c-out")
            check("CTP 查询返回结果", "完工" in out or "承诺" in out, out[:60])
            pg.screenshot(path=os.path.join(SHOTS, "13-ctp-result.png"), full_page=True)

        # 齐套
        pg.goto(BASE + "/index.html#/kit", wait_until="networkidle")
        pg.wait_for_timeout(800)
        if pg.locator("#btn-kit").count():
            pg.click("#btn-kit")
            pg.wait_for_timeout(2200)
            txt = pg.inner_text("#kit-body")
            check("齐套检查返回明细", "齐套" in txt or "缺" in txt, txt[:60])
            pg.screenshot(path=os.path.join(SHOTS, "14-kit-result.png"), full_page=True)

        # 移动端
        m = br.new_context(viewport={"width": 390, "height": 844})
        mp = m.new_page()
        mp.goto(BASE + "/login.html", wait_until="networkidle")
        mp.fill("#username", "admin")
        mp.fill("#password", "aps@2026")
        mp.click("#btn-login")
        mp.wait_for_timeout(2200)
        overflow = mp.evaluate("document.body.scrollWidth > window.innerWidth + 4")
        check("移动端 390px 无横向溢出", not overflow)
        mp.screenshot(path=os.path.join(SHOTS, "15-mobile.png"), full_page=True)

        bad = [(s, u) for s, u in NET_BAD if "favicon" not in u.lower()]
        err = real_errors()
        check("控制台无 JS 错误", not err and not bad,
              str(err[:3]) + " | 异常请求 " + str(bad[:3]))
        if DEBUG_NET and bad:
            print("\n-- 异常请求明细 --")
            seen = set()
            for s, u in bad:
                if u in seen:
                    continue
                seen.add(u)
                print("   %s %s" % (s, u))
        br.close()

    print("\n结果：通过 %d / 失败 %d ｜ 截图 %d 张 → reports/screenshots/"
          % (OK, FAIL, len(os.listdir(SHOTS))))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
