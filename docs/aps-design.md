# 飞划 APS 高级计划排程系统 · 建设方案与系统设计

| 项 | 内容 |
|---|---|
| 项目名称 | 飞划 APS 高级计划排程系统（FeiHua APS） |
| 版本 | v1.0.0 |
| 编制日期 | 2026-10-23 |
| 文档定位 | 立项建设方案 + 技术设计说明书 + 对外集成契约 |
| 适用读者 | 制造企业计划部/生产部/信息化部门、系统集成方、二次开发人员 |

---

## 1. 项目背景与目标

### 1.1 业务痛点

离散制造车间的排产长期依赖 Excel 与计划员经验，普遍存在五类问题：

| 编号 | 痛点 | 典型表现 | 业务代价 |
|---|---|---|---|
| P1 | 排产靠手工，响应慢 | 插一张急单要重排半天，全凭经验调 | 订单响应周期长，客户流失 |
| P2 | 无限产能假设 | 按标准工时倒排，不看设备实际负荷 | 计划"漂亮"但车间天天加班 |
| P3 | 交期承诺拍脑袋 | 销售问"这单什么时候能交"，只能答"大概两周" | 承诺失真，迟交率高 |
| P4 | 物料不齐套就开工 | 排了产，开工时才发现关键件没到 | 在制品堆积、换线频繁 |
| P5 | 瓶颈不可见 | 不知道哪个工作中心是瓶颈 | 改善无方向，投资没依据 |

### 1.2 建设目标

建设一套**轻量、可落地、可集成**的 APS 系统，核心解决"**有限产能下的可执行排程**"与"**可承诺交期**"两件事：

1. **有限产能正向排程**：以工作中心日产能桶为约束，工序逐日吞占产能，产出任何时点都不超负荷的排程。
2. **多优先规则切换**：EDD / CR / PRIO / FIFO 四规则可选，同一批工单可对比不同策略的迟交结果。
3. **物料齐套校验**：按排程顺序模拟发料，先排先领，缺料工单标阻塞，并给出缺口汇总。
4. **交期承诺 CTP**：把模拟工单插进去重排，回答"最早哪天能完工、能否按期"。
5. **瓶颈与告警可视化**：负荷率排名 + 四类自动告警（迟交/临近/超载/缺料）。

### 1.3 建设原则

- **零第三方依赖**：仅用 Python 标准库（`http.server` + `sqlite3`）+ 原生 JS，单机可跑、内网可部署、无供应链风险。
- **算法与框架解耦**：排程内核 `aps.py` 为纯函数模块，不碰数据库、不碰 HTTP，可单独单测、可换语言重写。
- **接口优先**：全部能力经 REST API 暴露，前端只是 API 的一个消费者，ERP/MES 可等价接入。
- **数据可追溯**：每次排程落一条批次记录（含完整明细 JSON），历史批次可查。

---

## 2. 范围与非目标

### 2.1 本期范围

| 模块 | 能力 |
|---|---|
| 主数据 | 工作中心、物料、产品、BOM、工艺路线、库存调整 |
| 订单 | 销售订单维护、订单转工单、工单维护 |
| 排程 | 有限产能正向排程、插单重排、甘特图、负荷分析、瓶颈识别 |
| 齐套 | 按排程顺序模拟发料、缺口汇总 |
| CTP | 模拟插单交期承诺、查询历史 |
| 告警 | 四类告警自动生成、处理归档 |
| 报表 | 排程明细 CSV、负荷 CSV |
| 系统 | 用户/角色/权限、API 密钥、业务规则参数、审计日志、增量同步 |

### 2.2 明确非目标（本期不做）

- **不做**多工厂/多车间跨组织协同、集团级 APS 网络排程。
- **不做**分钟级有限产能（本系统粒度是"工作中心 × 日"，日内按小时累计，不做设备级时序仿真）。
- **不做**自动采购建议/供应商协同（仅输出缺口，采购在 ERP 侧）。
- **不做**机器学习预测（交期、工时均为确定性计算）。
- **不做**与 PLC/SCADA 直连（经 MES 中转）。

---

## 3. 总体架构

### 3.1 分层结构

```
┌──────────────────────────────────────────────────────────┐
│  接入层                                                    │
│  浏览器（原生 JS SPA）  │  ERP/MES（REST + API Key）        │
└───────────────┬──────────────────────┬───────────────────┘
                │                      │
┌───────────────▼──────────────────────▼───────────────────┐
│  服务层  server.py（http.server ThreadingHTTPServer）       │
│  ├─ 路由表 ROUTES（56 条，正则匹配 + 权限码校验）             │
│  ├─ 鉴权五通道（Bearer / X-Aps-Token / Cookie / ?token / Key）│
│  ├─ 统一响应封装 {code, message, data}                     │
│  ├─ 幂等键 idem_keys                                      │
│  └─ 审计日志 logs                                         │
└───────────────┬──────────────────────┬───────────────────┘
                │                      │
┌───────────────▼───────────┐  ┌───────▼───────────────────┐
│  算法层  aps.py（纯函数）    │  │  数据层 db.py（sqlite3 WAL）│
│  ├─ SchedState 日桶模型     │  │  19 张表                   │
│  ├─ place() 产能吞噬        │  │  ├─ 主数据 5 表            │
│  ├─ sort_key() 四规则       │  │  ├─ 业务 2 表              │
│  ├─ material_check()       │  │  ├─ 排程结果 3 表           │
│  ├─ ctp() 交期承诺          │  │  ├─ 安全 4 表              │
│  ├─ load_report/bottleneck │  │  └─ 系统 5 表              │
│  └─ build_alerts()         │  │  gen_no() MAX 尾号递增     │
└────────────────────────────┘  └───────────────────────────┘
```

### 3.2 技术选型与理由

| 层次 | 选型 | 理由 |
|---|---|---|
| Web 服务 | Python `http.server.ThreadingHTTPServer` | 标准库，零依赖，内网单机足够；并发量在车间级（<50 用户）完全够用 |
| 数据库 | SQLite（WAL 模式） | 单文件、免运维、备份即拷贝；WAL 支持读写并发 |
| 算法 | 纯 Python 函数 | 无第三方数值库；排程是离散逻辑而非数值优化，纯函数最利于测试 |
| 前端 | 原生 JS + CSS | 无构建链、无 node_modules；打包即部署 |
| 部署 | systemd / nginx 反代 | 前缀 `/aps/` 直接挂到现有门户下 |

### 3.3 部署拓扑

```
                 Internet / 内网
                       │
              ┌────────▼────────┐
              │  nginx :80      │
              │  location /aps/ │──── proxy_pass ──► 127.0.0.1:8022
              └─────────────────┘
                                         │
                              ┌──────────▼───────────┐
                              │  feihua-aps 服务      │
                              │  APS_PORT=8022        │
                              │  APS_DB=/data/feihua.db│
                              └──────────────────────┘
```

**环境变量**

| 变量 | 默认 | 说明 |
|---|---|---|
| `APS_PORT` | 8022 | 监听端口 |
| `APS_DB` | `backend/feihua.db` | 数据库路径 |
| `APS_PREFIX` | 空 | 反代前缀，如 `/aps` |

---

## 4. 排程内核设计（核心）

### 4.1 时间离散化：日桶模型

**为什么是"日"而不是"分钟"？**
离散制造的计划粒度通常是班次/日；分钟级仿真需要精确到每台设备的开机停机、人员上下岗、换模时间，数据可得性差、维护成本高，且计划员本身按天做决策。日桶模型在"可执行性"与"可维护性"之间取得平衡。

**模型定义**

- 排程视界 `HORIZON_DAYS = 90`（可配置），起点 `start`（默认今天）。
- 每个工作中心 `wc` 在每一天 `d` 有一个**可用产能**：

```python
def cap(self, wc, day):
    if day.weekday() not in self.wc["work_days"]:   # 非工作日
        return 0.0
    return self.wc["hours_per_day"] * self.wc["efficiency"]
```

- 状态 `load[wc][d]` 记录该日已占用小时数。**核心不变量：对任意 `wc`、任意 `d`，有 `0 ≤ load[wc][d] ≤ cap(wc, d)`。**

### 4.2 产能吞噬算法 `place()`

一道工序（工时 `dur` 小时）进来后，从最早可开工日 `earliest_day_idx` 开始逐日"吞"产能：

```python
def place(self, wc, earliest_day_idx, dur, wo_no, seq, transfer_h=0.0):
    remaining = dur
    idx = earliest_day_idx
    while idx < len(self.days) and remaining > 1e-9:
        d = self.days[idx]
        free = round(self.cap(wc, d) - self.load[wc][d], 6)
        if free > 1e-6:                       # 当天还有余量
            if s_idx is None:                 # 记录工序开始
                s_idx, s_hour = idx, SHIFT_START_H + self.load[wc][d]
            take = min(free, remaining)       # 能吞多少吞多少
            self.load[wc][d] = round(self.load[wc][d] + take, 6)
            self.spans.append({"wc": wc, "wo": wo_no, "seq": seq,
                               "day_idx": idx, "hours": round(take, 4)})
            remaining = round(remaining - take, 6)
            e_idx, e_hour = idx, SHIFT_START_H + self.load[wc][d]
        idx += 1
    return s_idx, e_idx
```

**关键设计点**

1. **可跨日拆分**：一道 20h 工序在 8h/天的中心上会横跨 3 天，`spans` 记录每天实际占用小时，甘特图与日负荷图都直接读这份明细——**不存在"负荷按平均分摊"导致的失真**。
2. **产能溢出到次日**：当天余量不足时，剩余工时自然流到次日，无需回溯。
3. **不可行标记**：若 `idx` 走完视界仍有 `remaining > 0`，该工序排不进视界，工单置 `feasible = False`。

### 4.3 工艺约束：工序不可重叠

同一工单的工序必须串行：下一工序的最早开工日 = 上一工序的完工日；若工艺路线标了转移时间 `transfer_h > 0`，再顺延一天。

```python
earliest = prev_end_idx + (1 if op["transfer_h"] > 0 else 0)
```

**注意**：日桶模型允许相邻工序在**同一天的不同时段**衔接（前工序上午完工、后工序下午开工），因此校验口径是"**每日总负荷不超产能**"，而不是"工序时间段不重叠"。

### 4.4 四种优先规则

排程前对所有可排工单排序，`sort_key()` 返回排序键：

| 规则 | 排序键 | 适用场景 | 业务含义 |
|---|---|---|---|
| **EDD** | `due_date` 升序 | 默认。追求准时交付 | 最早交期先做，最直观 |
| **CR** | 关键比率升序 | 交期松紧混杂时 | `CR = 剩余天数 ÷ 标准工时折算天数`，CR 越小越紧急；自动让"时间紧、活量大"的单插队 |
| **PRIO** | `priority` 升序，再 due | 有明确客户分级 | 战略客户/急单优先 |
| **FIFO** | `created_date` / 单号 | 追求公平、减少换线 | 先到先做 |

CR 计算：

```python
days_left = (due - today).days
work_days = total_hours / 8.0        # 折算成标准工时天数
cr = days_left / max(work_days, 0.01)
```

### 4.5 负荷分析 `load_report()`

对每个工作中心汇总：

```
capacity_h = Σ 视界内每日产能（工作日）
load_h     = Σ spans 中该中心的占用小时
utilization = load_h / capacity_h
```

按 `utilization` 降序给出 `rank`，并按阈值分级：

| 级别 | 条件 | 含义 |
|---|---|---|
| `over` | `utilization > 1.0` | 超载（理论上日桶模型不会超，出现即说明有手工干预） |
| `warn` | `utilization ≥ 0.9` | 接近饱和，需关注 |
| `ok` | 其他 | 正常 |

### 4.6 瓶颈识别 `bottleneck()`

取 `rank == 1` 且 `utilization ≥ 0.9` 的中心作为瓶颈；若最高负荷也未达 0.9，则认为当前无显著瓶颈。

### 4.7 物料齐套 `material_check()`

**逻辑**：按排程顺序（先排先领）逐单核对 BOM：

```python
for wo in 按排程顺序:
    for 每行 BOM:
        need = qty_per_unit × wo.qty × (1 + loss_pct)
        if stock[material] >= need:
            stock[material] -= need          # 齐套才扣减
            该行齐套
        else:
            gap = need - stock[material]
            记录缺口；**不扣减库存**
```

**为什么缺料不扣减？**
如果缺料也照扣，会把库存扣成负数，后续工单会因为"库存已被前面订单吃掉"而全部判缺，产生**虚假齐套失败**——实际上那批料根本没发出去。缺料不扣减保证库存账实一致，缺口只在真正被阻塞的工单上体现。

`shortage_summary()` 按物料聚合总缺口与被阻塞工单列表。

### 4.8 交期承诺 CTP

把模拟工单（产品、数量、期望交期）作为一个新工单插入当前排程，**完整重排一次**，取其完工日作为可承诺日：

```python
def ctp(wos, routings, resources, product, qty, start, rule):
    sim = wos + [模拟工单]
    st, res = schedule(sim, routings, resources, start=start, rule=rule)
    mine = [r for r in res if r["wo"] == SIM_NO][0]
    可承诺日 = mine["end"]
    可接受   = 可承诺日 <= 期望交期
```

返回：`earliest_date`（最早完工日）、`on_time`（是否按期）、`late_days`、`bottleneck`、建议话术。

**代价**：一次 CTP = 一次全量重排。工单规模在数百级时（本算法复杂度约为 `O(工单数 × 工序数 × 平均跨天数)`）响应时间在百毫秒级，可接受；若未来到数千工单，需引入增量重排或缓存。

### 4.9 告警生成 `build_alerts()`

| 类型 | 触发条件 | 级别 |
|---|---|---|
| `ORDER_LATE` | 工单完工日 > 交期 | high |
| `ORDER_NEAR` | `0 ≤ 交期 - 完工日 ≤ late_warn_days` | mid |
| `WC_OVER` | `utilization > 1.0` | high |
| `WC_BUSY` | `utilization ≥ util_warn`（默认 0.9） | mid |
| `MAT_SHORT` | 存在物料缺口 | high/mid（按缺口量） |

阈值来自 `rules` 表，可在系统管理中调整，无需改代码。

---

## 5. 数据模型

### 5.1 表清单（19 张）

**主数据（5）**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `workcenters` | code(PK), name, wtype, hours_per_day, efficiency, work_days, shift, cost_rate, status | 工作中心；`work_days` 如 `1,2,3,4,5` 表示周一至周五 |
| `materials` | code(PK), name, unit, stock, safety, lead_days, price, supplier | 物料 |
| `products` | code(PK), name, unit, category, std_price, status | 产品 |
| `bom` | id, product, material, qty_per_unit, loss_pct | 产品 BOM |
| `routing_ops` | id, product, seq, wc, op_name, setup_h, run_h_per_unit, transfer_h | 工艺路线 |

**业务（2）**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sales_orders` | no(PK), customer, product, qty, due_date, priority, price, status, created_date | 销售订单；status: 待排产/已转工单 |
| `work_orders` | no(PK), so, product, qty, due_date, priority, status, release_date | 生产工单；status: 已下达/排产中/排程失败/完工 |

**排程结果（3）**

| 表 | 关键字段 | 说明 |
|---|---|---|
| `schedule_runs` | id, run_no, rule, start_date, horizon_days, wo_count, late_count, bottleneck_wc, status, run_by, run_at, **detail(JSON)** | 每次排程一个批次；`detail` 存 loads / alerts / kit / stock_after / **spans** / days |
| `schedule_ops` | id, run_id, wo, seq, wc, hours, start_date, start_h, end_date, end_h | 工序级排程结果 |
| `kit_checks`, `ctp_queries` | — | 齐套/CTP 查询历史 |

> **设计要点**：`detail` 里冗余保存了完整快照（含 spans 与工作日序列），使得**历史批次可以被完整复盘**，不依赖当时的排程代码与主数据状态。

**安全（4）**：`users`、`tokens`、`api_keys`、`logs`
**系统（5）**：`alarms`、`rules`、`idem_keys`、`sync_state`（+ 预留）

### 5.2 单号生成 `gen_no()`

```python
gen_no(conn, "schedule_runs", "RUN", col="run_no")   # → RUN0001, RUN0002 ...
```

规则：取该列 `MAX` 值，解析尾号 +1，补零到 4 位；同时探测空号（删除后产生的空洞）优先复用。

### 5.3 并发与一致性

- WAL 模式：读不阻塞写。
- 每次写操作单事务提交。
- 排程写库顺序：先插 `schedule_runs`（生效）→ 更新旧批次为 `历史` → 插 `schedule_ops` → 更新工单状态 → 写告警。任一步失败整体回滚。

---

## 6. 权限模型

### 6.1 六个角色

| 角色 | 权限码 | 职责 |
|---|---|---|
| `admin` 系统管理员 | `*` | 全部权限 |
| `planner` 计划员 | `master.*`, `so.*`, `wo.*`, `plan.*`, `check.*`, `ctp.*`, `alert.*`, `report.*` | 主数据维护 + 排程执行 |
| `sched` 排程员 | `plan.read`, `plan.run`, `check.*`, `ctp.*`, `alert.*`, `report.*` | 只跑排程，不改主数据 |
| `sales` 销售 | `so.read`, `so.write`, `ctp.*`, `plan.read` | 查交期、建订单 |
| `prod` 生产 | `wo.read`, `wo.write`, `plan.read`, `check.*`, `alert.*`, `report.*` | 执行侧 |
| `reader` 只读 | `*.read` | 看板/查询 |

### 6.2 权限校验点

路由表的第三列即权限码，`_dispatch()` 在调用业务函数前统一校验：

```python
if perm and not has_perm(user, perm):
    raise ApiError("无权限：%s" % perm, 403)
```

`perm=None` 的仅登录可访问；公开白名单（`/api/health`、`/api/sync/version`）免登录。

---

## 7. 鉴权设计（对外集成关键）

为了让 ERP、MES、BI、自动化脚本都能接入，鉴权支持**五条通道**，按优先级依次尝试：

| 顺序 | 通道 | 格式 | 适用 |
|---|---|---|---|
| 1 | Bearer Token | `Authorization: Bearer <token>` | 前端、常规客户端 |
| 2 | 自定义头 | `X-Aps-Token: <token>` | 不便改 Authorization 的网关 |
| 3 | Cookie | `aps_token=<token>` | 浏览器同源 |
| 4 | 查询参数 | `?token=<token>` | 下载链接、iframe（**仅建议内网**） |
| 5 | API Key | `X-Aps-Key: <key>` | **系统间集成，推荐** |

**API Key 机制**

- 创建时返回完整 key（仅此一次），库里只存 `sha256(key)` + 前缀（用于展示辨识）。
- Key 绑定角色，等价于该角色的用户权限。
- 记录 `last_used`，便于审计与清理僵尸 Key。
- 删除即失效。

**Token 机制**

- 登录后颁发随机 token，落 `tokens` 表带过期时间。
- 401 统一响应，前端收到后清本地态跳登录页。

---

## 8. 接口设计规范

### 8.1 统一响应

```json
{ "code": 200, "message": "ok", "data": { ... } }
```

错误：

```json
{ "code": 400, "message": "rule 需为 EDD/CR/PRIO/FIFO", "data": null }
```

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未认证 / token 失效 |
| 403 | 无权限 |
| 404 | 资源不存在（如尚未排程） |
| 409 | 冲突（重复单号） |
| 500 | 服务端异常 |

### 8.2 命名与风格

- 资源集合用复数名词：`/api/sales-orders`、`/api/workcenters`
- 动作型端点用动词后缀：`/api/plan/run`、`/api/sales-orders/release`
- 保存统一 `POST /xxx/save`（有 id 即更新，无 id 即新增）
- 删除统一 `POST /xxx/{id}/delete`（不用 DELETE 方法，兼容老旧网关）
- 时间一律 `YYYY-MM-DD`，日期时间 `YYYY-MM-DD HH:MM:SS`

### 8.3 幂等

写接口支持 `Idempotency-Key` 请求头。服务端以 key 记录首次结果，重复请求直接返回首次结果，避免网络重试造成重复下单/重复排程。

### 8.4 增量同步

供 MES/BI 拉增量：

- `GET /api/sync/version` → 各实体当前版本号（免登录）
- `GET /api/sync?entities=work_orders,sales_orders&since=<ts>` → 只返回版本变化的实体数据

---

## 9. 非功能设计

| 维度 | 设计 |
|---|---|
| 性能 | 10 工单 / 23 工序全量排程 < 200ms；100 工单约 1~2s |
| 并发 | ThreadingHTTPServer，车间级 50 并发足够；写操作单事务 |
| 可用性 | 单机无状态崩溃重启即可；DB 为单文件，备份 = 拷文件 |
| 备份 | `sqlite3 feihua.db ".backup bak.db"`（WAL 安全备份） |
| 安全 | 密码 sha256 加盐存储；API Key 只存哈希；权限逐接口校验；审计日志记录关键写操作 |
| 可观测 | `/api/health` 返回版本、路由数、各实体计数；`logs` 表可查操作轨迹 |
| 可移植 | 纯标准库，Linux/Windows 均可跑，Python 3.9+ |

---

## 10. 实施计划

| 阶段 | 内容 | 交付物 | 建议工期 |
|---|---|---|---|
| S1 立项与设计 | 需求梳理、方案设计、接口契约 | 本方案 + API 契约 | 3 天 |
| S2 内核开发 | 数据层、排程内核、单元测试 | db.py / aps.py / 55 单测 | 5 天 |
| S3 接口与前端 | 56 路由、9 页面、权限 | server.py / frontend 6 文件 | 6 天 |
| S4 测试 | 接口测试、冒烟、UI 巡检 | 61 接口测 / 36 冒烟 / 26 巡检 | 2 天 |
| S5 上线 | 部署、反代、初始化、培训 | 运行环境 + 用户手册 | 2 天 |
| S6 集成 | 与 ERP/MES 联调 | 集成验收报告 | 3 天 |

---

## 11. 验收标准

| 编号 | 验收项 | 判定标准 |
|---|---|---|
| A1 | 排程正确性 | 任意时点、任意工作中心的日负荷 ≤ 日产能 |
| A2 | 工序顺序 | 同工单工序严格串行，后序不早于前序完工 |
| A3 | 规则生效 | 同一批工单在 EDD/PRIO 下迟交清单明显不同，符合规则语义 |
| A4 | 齐套逻辑 | 缺料工单标阻塞，缺口汇总数量与明细一致；库存不出现负数 |
| A5 | CTP 一致性 | CTP 承诺日 ≥ 重排后实际可行完工日 |
| A6 | 权限隔离 | reader 角色调用写接口一律 403 |
| A7 | 接口契约 | 56 条路由与文档一一对应，apidoc 可自动导出 |
| A8 | 测试门禁 | pytest 全绿、冒烟全绿、UI 巡检全绿 |
| A9 | 部署 | 经 nginx `/aps/` 前缀访问全功能可用 |
| A10 | 数据可追溯 | 每次排程可在历史批次中完整复盘（含每日占用明细） |

---

## 12. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 主数据不准（工时、BOM 偏差） | 排程结果不可信 | 上线前主数据治理；系统提供实际工时回填（后续版本） |
| 日粒度过粗 | 日内冲突无法表达 | 明确适用边界；日内细化交 MES 执行排程 |
| 全量重排性能 | 工单数上千后变慢 | 引入增量重排 / 分车间滚动排程（v2.0） |
| 计划员不信任算法 | 落地失败 | 提供四规则对比、可手工插单、透明展示每日占用 |
| 与 ERP 数据口径不一 | 集成困难 | API 契约先行，字段口径在文档中固化 |

---

## 13. 后续演进（v2.0 设想）

1. **多车间/多工厂**：资源池分层，跨车间转序建模。
2. **滚动排程**：只重排变动窗口内工单，锁定已开工区间。
3. **模具与人员约束**：把工装、班组作为二级资源加入日桶。
4. **实际工时回填与偏差分析**：闭环校准标准工时。
5. **图形化排程板**：甘特拖拽调整 + 自动校验可行性。

---

## 附录 A：目录结构

```
feihua-aps/
├── backend/
│   ├── aps.py          # 排程内核（纯函数，无 IO）
│   ├── db.py           # 数据层（sqlite3 WAL，19 表）
│   ├── seed.py         # 种子数据 + 首次自动排程
│   └── server.py       # HTTP 服务（56 路由）
├── frontend/
│   ├── index.html      # SPA 主框架
│   ├── login.html      # 登录页
│   ├── app.js          # 框架层：api/toast/table/modal/go
│   ├── pages.js        # 页面层：9 个页面
│   ├── style.css       # 样式（含移动端适配）
│   └── favicon.svg
├── tests/
│   ├── conftest.py     # 临时库 + 随机端口真实服务
│   ├── test_unit_core.py  # 55 条内核单测
│   └── test_api.py        # 61 条接口测试
├── tools/
│   ├── smoke_api.py    # 36 项线上冒烟
│   └── ui_check.py     # 26 项 UI 巡检（含 15 张截图）
├── demo/               # 离线单文件 DEMO
├── docs/               # 本方案 + API 契约 + 用户手册
└── reports/            # 巡检截图与测试报告
```

## 附录 B：核心公式汇总

| 公式 | 表达式 |
|---|---|
| 日产能 | `cap(wc, d) = workday(d) ? hours_per_day × efficiency : 0` |
| 利用率 | `utilization = load_h / capacity_h` |
| 关键比率 | `CR = (due - today).days ÷ (total_hours / 8)` |
| BOM 需求 | `need = qty_per_unit × qty × (1 + loss_pct)` |
| 缺口 | `gap = need - stock`（仅当 `need > stock`） |
| 工序最早开工 | `earliest = prev_end_day + (transfer_h > 0 ? 1 : 0)` |
