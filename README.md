# 飞划 APS 高级计划排程系统

有限产能正向排程 + 物料齐套 + 交期承诺，面向离散制造车间的轻量级 APS。

零第三方依赖：Python 标准库（`http.server` + `sqlite3`）+ 原生 JS，单机即可运行。

## 快速开始

```bash
cd backend
python server.py            # 默认 8022 端口
# 打开 http://127.0.0.1:8022/login.html
```

默认账号：`admin` / `aps@2026`

首次启动会自动建库、灌种子数据，并**自动跑一次排程**（批次 RUN0001），所以一进去仪表盘就是有数据的。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `APS_PORT` | `8022` | 监听端口 |
| `APS_DB` | `backend/feihua.db` | 数据库路径 |
| `APS_PREFIX` | 空 | 反代前缀（如 `/aps`） |

## 目录

```
backend/    aps.py 排程内核 · db.py 数据层 · seed.py 种子 · server.py 服务（56 路由）
frontend/   index/login/app/pages/style/favicon
tests/      116 条 pytest（55 内核单测 + 61 接口）
tools/      smoke_api.py 冒烟 · ui_check.py UI 巡检 · build_demo.py 生成离线 DEMO
docs/       aps-design.md 方案 · api.md 接口契约 · user-guide.md 用户手册
demo/       离线单文件 DEMO（双击即看）
```

## 测试

```bash
python -m pytest -q                     # 116 条
python tools/smoke_api.py               # 36 项（可加 --base 打线上）
python tools/ui_check.py --debug-net    # 26 项 UI 巡检 + 15 张截图
```

## 排程内核

日桶法有限产能正向排程：工作中心 × 日 为产能单元，工序逐日吞占产能、可跨日拆分，工艺路线保证工序串行。

四种优先规则：`EDD` 最早交期 / `CR` 关键比率 / `PRIO` 优先级 / `FIFO` 先到先做。

详见 `docs/aps-design.md`。

## 集成

全部能力经 REST API 暴露，56 条路由，支持 API Key（`X-Aps-Key`）系统间对接。详见 `docs/api.md`。

## 角色

`admin` 系统管理员 / `planner` 计划员 / `sched` 排程员 / `sales` 销售 / `prod` 生产 / `reader` 只读
