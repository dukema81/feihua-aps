# 飞划 APS 开放接口契约（API Reference）

| 项 | 内容 |
|---|---|
| 系统 | 飞划 APS 高级计划排程系统（FeiHua APS）v1.0.0 |
| 协议 | HTTP/1.1，JSON over UTF-8 |
| 默认端口 | `8022` |
| 反代前缀 | `/aps`（示例：`https://host/aps/api/health`） |
| 路由总数 | 56 |
| 文档版本 | 2026-10-23 |

> 实时机器可读版本：`GET /api/apidoc`（OpenAPI 3.0.0 结构）

---

## 1. 通用约定

### 1.1 统一响应包

**成功**

```json
{ "code": 200, "message": "ok", "data": {} }
```

**失败**

```json
{ "code": 400, "message": "rule 需为 EDD/CR/PRIO/FIFO", "data": null }
```

调用方应以 **HTTP 状态码** 为准，`data` 字段为空数组时表示无记录（非错误）。

### 1.2 状态码表

| HTTP | 语义 | 典型场景 |
|---|---|---|
| 200 | 成功 | 全部正常响应 |
| 400 | 参数错误 | 缺必填、格式不符、枚举越界 |
| 401 | 未认证 | 无 token / token 过期 / 密码错 |
| 403 | 无权限 | 角色权限码不足 |
| 404 | 不存在 | 资源未找到；`/api/plan/latest` 在尚未排程时返回 404 |
| 409 | 冲突 | 单号重复、告警已处理 |
| 500 | 服务端错误 | 未捕获异常（含 traceback 摘要） |

### 1.3 鉴权（五通道，按序尝试）

| 顺序 | 位置 | 示例 |
|---|---|---|
| 1 | `Authorization` | `Authorization: Bearer 3f9c...` |
| 2 | `X-Aps-Token` | `X-Aps-Token: 3f9c...` |
| 3 | Cookie | `Cookie: aps_token=3f9c...` |
| 4 | Query | `?token=3f9c...` |
| 5 | API Key | `X-Aps-Key: apskey_9a8b...` |

**系统间集成推荐用 API Key**（`X-Aps-Key`），与用户 token 完全等价、长期有效、可单独吊销。

**公开端点（免鉴权）**

- `GET /api/health`
- `GET /api/sync/version`

### 1.4 幂等

写接口可带请求头：

```
Idempotency-Key: <调用方生成的唯一串>
```

服务端记录首次结果，重复提交同 key 直接回放首次响应（不重复建单）。建议用于：`/api/sales-orders/save`、`/api/work-orders/save`、`/api/plan/run`、`/api/plan/push-in`。

### 1.5 时间与数值格式

| 类型 | 格式 | 示例 |
|---|---|---|
| 日期 | `YYYY-MM-DD` | `2026-10-23` |
| 日期时间 | `YYYY-MM-DD HH:MM:SS` | `2026-10-23 09:15:17` |
| 小时（日内） | float，班次起点 8.0 起算 | `16.5` |
| 百分比/利用率 | float 小数 | `0.94` |

### 1.6 分页与数量

当前版本列表接口均返回**全量**（数据量在千级以内），部分接口内置 `LIMIT`：

| 接口 | 上限 |
|---|---|
| `/api/alerts` | 300 |
| `/api/logs` | 200 |
| `/api/kit/history` | 200 |
| `/api/ctp/history` | 100 |

---

## 2. 权限码

调用所需权限码写在每个接口后。`—` 表示仅需登录。

| 权限码 | 系统管理员 | 计划员 | 排程员 | 销售 | 生产 | 只读 |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `*` | ✓ | | | | | |
| `master.read/write` | ✓ | ✓ | 读 | | | 读 |
| `so.read/write` | ✓ | ✓ | | ✓ | 读 | 读 |
| `wo.read/write` | ✓ | ✓ | 读 | | ✓ | 读 |
| `plan.read` / `plan.run` | ✓ | ✓ | ✓ / ✓ | 读 | 读 | 读 |
| `check.read` | ✓ | ✓ | ✓ | | ✓ | ✓ |
| `ctp.read` | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `alert.read/write` | ✓ | ✓ | ✓ | | ✓ | 读 |
| `report.read` | ✓ | ✓ | ✓ | | ✓ | ✓ |
| `system.read/write` | ✓ | | | | | |

---

## 3. 接口清单总览

| # | 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/health` | 公开 | 健康检查 |
| 2 | GET | `/api/apidoc` | — | OpenAPI 文档 |
| 3 | POST | `/api/auth/login` | — | 登录 |
| 4 | POST | `/api/auth/logout` | — | 登出 |
| 5 | GET | `/api/auth/me` | — | 当前用户 |
| 6 | POST | `/api/auth/change-password` | — | 改密码 |
| 7 | GET | `/api/users` | system.read | 用户列表 |
| 8 | POST | `/api/users/save` | system.write | 保存用户 |
| 9 | POST | `/api/users/reset-password` | system.write | 重置密码 |
| 10 | GET | `/api/roles` | — | 角色与权限矩阵 |
| 11 | GET | `/api/workcenters` | master.read | 工作中心列表 |
| 12 | POST | `/api/workcenters/save` | master.write | 保存工作中心 |
| 13 | POST | `/api/workcenters/{code}/delete` | master.write | 删除工作中心 |
| 14 | GET | `/api/materials` | master.read | 物料列表 |
| 15 | POST | `/api/materials/save` | master.write | 保存物料 |
| 16 | POST | `/api/materials/{code}/delete` | master.write | 删除物料 |
| 17 | POST | `/api/materials/adjust` | master.write | 库存调整 |
| 18 | GET | `/api/products` | master.read | 产品列表 |
| 19 | POST | `/api/products/save` | master.write | 保存产品 |
| 20 | POST | `/api/products/{code}/delete` | master.write | 删除产品 |
| 21 | GET | `/api/bom` | master.read | BOM 查询 |
| 22 | POST | `/api/bom/save` | master.write | 保存 BOM 行 |
| 23 | POST | `/api/bom/{product}/{material}/delete` | master.write | 删除 BOM 行 |
| 24 | GET | `/api/routings` | master.read | 工艺路线查询 |
| 25 | POST | `/api/routings/save` | master.write | 保存工序 |
| 26 | POST | `/api/routings/{product}/{seq}/delete` | master.write | 删除工序 |
| 27 | GET | `/api/sales-orders` | so.read | 销售订单列表 |
| 28 | POST | `/api/sales-orders/save` | so.write | 保存订单 |
| 29 | POST | `/api/sales-orders/{no}/delete` | so.write | 删除订单 |
| 30 | POST | `/api/sales-orders/release` | wo.write | 订单转工单 |
| 31 | GET | `/api/work-orders` | wo.read | 工单列表 |
| 32 | POST | `/api/work-orders/save` | wo.write | 保存工单 |
| 33 | POST | `/api/work-orders/{no}/delete` | wo.write | 删除工单 |
| 34 | POST | `/api/plan/run` | plan.run | **执行排程** |
| 35 | GET | `/api/plan/latest` | plan.read | 最近生效批次 |
| 36 | GET | `/api/plan/overview` | plan.read | **看板聚合**（空态返回 200） |
| 37 | GET | `/api/plan/gantt` | plan.read | 甘特数据 |
| 38 | GET | `/api/plan/load` | plan.read | 负荷榜单 |
| 39 | GET | `/api/plan/dayload/{wc}` | plan.read | 某中心逐日负荷 |
| 40 | POST | `/api/plan/push-in` | plan.run | **插单重排** |
| 41 | POST | `/api/kit/run` | check.read | **齐套检查** |
| 42 | GET | `/api/kit/history` | check.read | 齐套历史 |
| 43 | POST | `/api/ctp` | ctp.read | **交期承诺** |
| 44 | GET | `/api/ctp/history` | ctp.read | CTP 历史 |
| 45 | GET | `/api/alerts` | alert.read | 告警列表 |
| 46 | POST | `/api/alerts/{no}/handle` | alert.write | 处理告警 |
| 47 | GET | `/api/rules` | system.read | 业务规则 |
| 48 | POST | `/api/rules/save` | system.write | 更新规则 |
| 49 | GET | `/api/reports/schedule.csv` | report.read | 排程明细 CSV |
| 50 | GET | `/api/reports/load.csv` | report.read | 负荷 CSV |
| 51 | GET | `/api/logs` | system.read | 审计日志 |
| 52 | GET | `/api/sync` | — | 增量同步数据 |
| 53 | GET | `/api/sync/version` | 公开 | 同步版本号 |
| 54 | GET | `/api/api-keys` | system.read | API Key 列表 |
| 55 | POST | `/api/api-keys/create` | system.write | 创建 API Key |
| 56 | POST | `/api/api-keys/{id}/delete` | system.write | 删除 API Key |

---

## 4. 接口详情

### 4.1 健康与文档

#### GET /api/health — 健康检查（公开）

响应 `data`：

```json
{
  "brand": "飞划APS管理系统",
  "version": "1.0.0",
  "routes": 56,
  "workcenters": 6,
  "materials": 12,
  "products": 8,
  "sales_orders": 10,
  "work_orders": 10,
  "time": "2026-10-23 09:15:17"
}
```

#### GET /api/apidoc — OpenAPI 文档

返回 `{openapi, info:{title,version}, paths:{...}}`，每个 `operation` 含 `operationId`、`permission`、`summary`。可用于自动生成客户端或做接口契约测试。

---

### 4.2 认证

#### POST /api/auth/login — 登录

**请求**

```json
{ "username": "admin", "password": "aps@2026" }
```

**响应 data**

```json
{
  "token": "3f9c8a...",
  "username": "admin",
  "name": "系统管理员",
  "role": "admin",
  "roleLabel": "系统管理员"
}
```

**错误**：`401 用户名或密码错误`

Token 有效期 12 小时。

#### POST /api/auth/logout — 登出

注销当前 token。响应 `{ok: true}`。

#### GET /api/auth/me — 当前用户

```json
{
  "username": "admin",
  "name": "系统管理员",
  "role": "admin",
  "roleLabel": "系统管理员",
  "perms": ["*"]
}
```

#### POST /api/auth/change-password — 修改密码

```json
{ "oldPassword": "aps@2026", "newPassword": "NewPass@2026" }
```

**约束**：新密码 ≥ 8 位。**错误**：`401 旧密码错误`、`400 新密码至少 8 位`

---

### 4.3 用户与角色

#### GET /api/users — 用户列表 · `system.read`

返回 `username,name,role,phone,status,created_at`。

#### POST /api/users/save — 保存用户 · `system.write`

```json
{ "username": "pln01", "password": "12345678", "name": "张计划", "role": "planner", "phone": "13800000002" }
```

有 `username` 即更新（`password` 可省略），无则新建（`password` 必填）。

#### POST /api/users/reset-password — 重置密码 · `system.write`

```json
{ "username": "pln01", "password": "Reset@2026" }
```

#### GET /api/roles — 角色与权限矩阵

```json
[
  { "role": "admin", "label": "系统管理员", "perms": ["*"] },
  { "role": "planner", "label": "计划员", "perms": ["master.read", "master.write", "..."] }
]
```

---

### 4.4 主数据

#### GET /api/workcenters — 工作中心 · `master.read`

```json
[{
  "code": "WC-CNC1", "name": "CNC 加工中心一", "wtype": "机加",
  "hours_per_day": 8.0, "efficiency": 1.0, "work_days": "1,2,3,4,5",
  "shift": "白班", "cost_rate": 120.0, "status": "运行", "remark": ""
}]
```

> `work_days` 用 `0=周一 … 6=周日` 表示。`efficiency` 直接乘入日产能，是模拟"设备新旧/稼动率差异"的手段。

#### POST /api/workcenters/save · `master.write`

同上字段；`code` 为唯一键。

#### POST /api/workcenters/{code}/delete · `master.write`

**冲突**：被工艺路线引用时返回 409。

#### GET /api/materials — 物料 · `master.read`

```json
[{ "code": "M-MOTOR", "name": "伺服电机", "unit": "台", "stock": 26,
   "safety": 5, "lead_days": 20, "price": 1800, "supplier": "..." }]
```

#### POST /api/materials/save · `master.write`

#### POST /api/materials/{code}/delete · `master.write`

#### POST /api/materials/adjust — 库存调整 · `master.write`

```json
{ "code": "M-MOTOR", "qty": 10, "reason": "到货入库" }
```

`qty` 正数入库、负数出库。会写审计日志。

#### GET /api/products — 产品 · `master.read`

#### POST /api/products/save · `master.write` / POST `/api/products/{code}/delete` · `master.write`

#### GET /api/bom — BOM · `master.read`

查询参数：`?product=P-CONV`（可选，不传返回全部）

```json
[{ "product": "P-CONV", "material": "M-MOTOR", "qty_per_unit": 2, "loss_pct": 0.02 }]
```

#### POST /api/bom/save · `master.write`

```json
{ "product": "P-CONV", "material": "M-MOTOR", "qty_per_unit": 2, "loss_pct": 0.02 }
```

同 `product + material` 存在则覆盖。

#### POST /api/bom/{product}/{material}/delete · `master.write`

#### GET /api/routings — 工艺路线 · `master.read`

查询参数：`?product=P-CONV`

```json
[{ "product": "P-CONV", "seq": 10, "wc": "WC-CNC1", "op_name": "粗加工",
   "setup_h": 0.5, "run_h_per_unit": 0.8, "transfer_h": 0 }]
```

> 单工序总工时 = `setup_h + run_h_per_unit × qty`。`transfer_h > 0` 表示需等待转运，后序再顺延一天。

#### POST /api/routings/save · `master.write` / POST `/api/routings/{product}/{seq}/delete` · `master.write`

---

### 4.5 销售订单与工单

#### GET /api/sales-orders — 订单列表 · `so.read`

查询参数：`?status=待排产`

```json
[{
  "no": "SO-2026-0011", "customer": "华东重工", "product": "P-CONV",
  "qty": 2, "due_date": "2026-11-10", "priority": 1, "price": 0,
  "status": "待排产", "created_date": "2026-10-18", "remark": ""
}]
```

**status 枚举**：`待排产` / `已转工单`

#### POST /api/sales-orders/save — 保存订单 · `so.write`

```json
{ "no": "", "customer": "华东重工", "product": "P-CONV", "qty": 2,
  "due_date": "2026-11-10", "priority": 1 }
```

- `no` 留空自动生成 `SO-<年>-<4位序号>`
- `due_date` 必须 `YYYY-MM-DD`
- `qty > 0`
- `product` 必须在 products 中存在（否则 404）
- 相同 `no` 视为更新

#### POST /api/sales-orders/{no}/delete — 删除订单 · `so.write`

#### POST /api/sales-orders/release — 订单转工单 · `wo.write`

把全部 `待排产` 订单批量生成工单（`WO` + 订单尾号）。

**响应 data**

```json
{ "count": 3, "wos": ["WO0011", "WO0012", "WO0013"] }
```

#### GET /api/work-orders — 工单列表 · `wo.read`

```json
[{
  "no": "WO0011", "so": "SO-2026-0011", "product": "P-CONV", "qty": 2,
  "due_date": "2026-11-10", "priority": 1, "status": "已下达",
  "release_date": "2026-10-20", "created_date": "2026-10-18"
}]
```

**status 枚举**：`已下达` / `排产中` / `排程失败` / `完工`

#### POST /api/work-orders/save — 保存工单 · `wo.write`

字段同上；`no` 留空自动生成。已处于 `排产中` 的工单不允许直接改回 `已下达`（防止绕过排程）。

#### POST /api/work-orders/{no}/delete — 删除工单 · `wo.write`

---

### 4.6 排程（核心）

#### POST /api/plan/run — 执行排程 · `plan.run`

**请求**

```json
{
  "rule": "EDD",
  "start": "2026-10-23",
  "horizon": 90
}
```

| 字段 | 可选 | 默认 | 说明 |
|---|---|---|---|
| `rule` | 是 | rules 表 `sched_rule` | `EDD` / `CR` / `PRIO` / `FIFO` |
| `start` | 是 | 今天 | 排程起点 |
| `horizon` | 是 | 90 | 视界天数 |

**响应 data（裁剪）**

```json
{
  "run_no": "RUN0001",
  "run_id": 1,
  "rule": "EDD",
  "start": "2026-10-23",
  "wo_count": 10,
  "late_count": 2,
  "bottleneck": { "wc": "WC-ASSY", "utilization": 0.94, "level": "warn" },
  "loads": [
    { "wc": "WC-ASSY", "name": "总装线", "capacity_h": 512.0,
      "load_h": 96.0, "utilization": 0.1875, "free_h": 416.0,
      "rank": 1, "level": "ok" }
  ],
  "results": [
    {
      "wo": "WO0011", "product": "P-CONV", "qty": 2, "due": "2026-11-10",
      "start": "2026-10-23", "end": "2026-10-30",
      "late": false, "late_days": 0, "feasible": true,
      "ops": [
        { "seq": 10, "wc": "WC-CNC1", "hours": 2.1,
          "start": "2026-10-23", "start_h": 8.0,
          "end": "2026-10-23", "end_h": 10.1 }
      ]
    }
  ],
  "kit": [ /* 齐套明细，同 /api/kit/run.rows */ ],
  "shortage": [ { "material": "M-MOTOR", "total_gap": 4, "block_wos": ["WO0013"] } ],
  "alerts": [ { "atype": "ORDER_LATE", "level": "high", "target": "WO0015", "message": "..." } ],
  "alert_nos": ["AL0001", "AL0002"],
  "stock_after": { "M-MOTOR": 22, "M-GEAR": 28 }
}
```

**副作用**（一次性事务）：

1. 新批次 `schedule_runs` 置为 `生效`，旧生效批次置 `历史`
2. 写 `schedule_ops` 工序明细
3. 更新工单状态（`排产中` / `排程失败`）
4. 写告警到 `alarms`
5. 写审计日志
6. 递增 `work_orders` 同步版本

**错误**：`400 rule 需为 ...`、`400 没有待排产工单`、`400 没有可用的运行状态工作中心`

#### GET /api/plan/latest — 最近生效批次 · `plan.read`

```json
{
  "run": { "run_no": "RUN0001", "rule": "EDD", "start_date": "2026-10-23",
           "horizon_days": 90, "wo_count": 10, "late_count": 2,
           "bottleneck_wc": "WC-ASSY", "run_by": "admin", "run_at": "..." },
  "ops": [ { "wo": "WO0011", "seq": 10, "wc": "WC-CNC1", "hours": 2.1,
             "start_date": "2026-10-23", "start_h": 8.0,
             "end_date": "2026-10-23", "end_h": 10.1 } ],
  "loads": [ /* 同 run.loads */ ],
  "kit": [ /* 齐套明细 */ ],
  "shortage": { "M-MOTOR": 22 }
}
```

**404**：尚未执行任何排程。若需空态友好，请改用 `/api/plan/overview`。

#### GET /api/plan/overview — 看板聚合 · `plan.read`

**推荐给仪表盘/大屏使用**：一次请求拿齐最近批次 + 负荷，且**未排程时返回 200 空结构**。

```json
{
  "run": { "run_no": "RUN0001", "rule": "EDD", "start_date": "2026-10-23",
           "horizon_days": 90, "wo_count": 10, "late_count": 2,
           "bottleneck_wc": "WC-ASSY", "run_by": "admin", "run_at": "..." },
  "loads": [ /* ... */ ],
  "bottleneck": { "wc": "WC-ASSY" }
}
```

未排程时：

```json
{ "run": null, "loads": [], "bottleneck": null, "hint": "尚未排程" }
```

#### GET /api/plan/gantt — 甘特数据 · `plan.read`

```json
{
  "run_no": "RUN0001",
  "start_date": "2026-10-23",
  "horizon_days": 90,
  "by_wc": {
    "WC-CNC1": [ { "wo": "WO0011", "seq": 10, "hours": 2.1,
                   "start_date": "...", "end_date": "..." } ]
  },
  "work_orders": {
    "WO0011": { "no": "WO0011", "product": "P-CONV", "qty": 2,
                "due_date": "2026-11-10", "status": "排产中" }
  }
}
```

前端渲染方式：横轴为 `[start_date, start_date + horizon_days)`，每个工作中心一行，条的位置 = `(工序开始日 - start_date) / horizon`，宽度 = 跨天数 / horizon。

#### GET /api/plan/load — 负荷榜单 · `plan.read`

```json
{
  "run_no": "RUN0001",
  "loads": [ { "wc": "WC-ASSY", "name": "总装线", "capacity_h": 512.0,
               "load_h": 96.0, "utilization": 0.1875, "free_h": 416.0,
               "rank": 1, "level": "ok" } ],
  "bottleneck": { "wc": "WC-ASSY" }
}
```

#### GET /api/plan/dayload/{wc} — 逐日负荷 · `plan.read`

查询参数：`?days=30`（可选，默认 30）

```json
[ { "date": "2026-10-23", "capacity_h": 8.0, "load_h": 6.5, "utilization": 0.8125 },
  { "date": "2026-10-24", "capacity_h": 0.0, "load_h": 0.0, "utilization": 0.0 } ]
```

> 数据来自批次快照里的每日占用明细（`detail.spans`），非均摊估算，可直接用于画日负荷柱状图。

#### POST /api/plan/push-in — 插单重排 · `plan.run`

一步完成：建销售订单 → 建工单 → 全量重排。

**请求**

```json
{
  "product": "P-CONV", "qty": 3, "due_date": "2026-11-05",
  "priority": 1, "customer": "急单客户", "no": ""
}
```

**响应 data**

```json
{
  "so": "SO-2026-0011",
  "wo": "WO0011",
  "end": "2026-11-08",
  "late_count": 3,
  "late_wos": ["WO0011", "WO0015"],
  "run_no": "RUN0002"
}
```

`late_wos` 用于向销售展示"插这张单会让哪几张单变迟"，是谈判依据。

**错误**：`404 产品不存在`、`400 qty 必须 > 0`、`400 due_date 需 YYYY-MM-DD`、`409 订单号已存在`

---

### 4.7 物料齐套

#### POST /api/kit/run — 执行齐套检查 · `check.read`

无请求体。按当前排程顺序（`sched_rule`）模拟发料。

**响应 data**

```json
{
  "check_no": "KIT0001",
  "rows": [{
    "wo": "WO0011", "product": "P-CONV", "kit_ok": true,
    "need": { "M-MOTOR": 4, "M-GEAR": 2 },
    "shortage": []
  }, {
    "wo": "WO0013", "product": "P-CONV", "kit_ok": false,
    "need": { "M-MOTOR": 4 },
    "shortage": [ { "material": "M-MOTOR", "need": 4, "stock": 2, "gap": 2 } ]
  }],
  "shortage": [ { "material": "M-MOTOR", "total_gap": 4, "block_wos": ["WO0013"] } ],
  "stock_after": { "M-MOTOR": 22, "M-GEAR": 28 },
  "ok_count": 8,
  "block_count": 2
}
```

**语义要点**：

- `kit_ok = false` 的工单**不扣减库存**，因此 `stock_after` 是"真正会被消耗后"的库存，不会出现负数。
- `shortage[].total_gap` 是该物料全部阻塞工单的缺口之和。

#### GET /api/kit/history — 齐套历史 · `check.read`

```json
[ { "check_no": "KIT0001", "wo": "WO0011", "product": "P-CONV",
    "kit_ok": 1, "checked_at": "2026-10-23 09:20:11" } ]
```

---

### 4.8 交期承诺 CTP

#### POST /api/ctp — 交期承诺查询 · `ctp.read`

**请求**

```json
{ "product": "P-CONV", "qty": 5, "due_date": "2026-11-20", "priority": 2 }
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `product` | 是 | 产品编码，不存在返回 404 |
| `qty` | 是 | `> 0` |
| `due_date` | 否 | 不传/格式错则默认今天 +30 天 |
| `priority` | 否 | 默认 3 |

**响应 data**

```json
{
  "product": "P-CONV",
  "qty": 5,
  "requested_due": "2026-11-20",
  "earliest_end": "2026-11-14",
  "on_time": true,
  "feasible": true,
  "late_days": 0,
  "suggestion": "可按期承诺"
}
```

**三种话术分支**

| 情形 | `feasible` | `on_time` | `suggestion` |
|---|---|---|---|
| 视界内排得下且按期 | true | true | 可按期承诺 |
| 视界内排得下但晚于交期 | true | false | 最早 X 完工，比交期晚 N 天，建议协商交期或插单 |
| 视界内排不下 | false | false | 视界内排不下，建议拆单/外协 |

> **实现说明**：CTP 是把模拟工单插入当前工单集后**完整重排一次**取完工日，因此结果与真实排产严格一致（同样的算法、同样的产能约束）。

#### GET /api/ctp/history — CTP 历史 · `ctp.read`

```json
[ { "product": "P-CONV", "qty": 5, "due_date": "2026-11-20",
    "answer_end": "2026-11-14", "on_time": 1, "feasible": 1,
    "queried_by": "sales01", "queried_at": "2026-10-23 10:02:33" } ]
```

---

### 4.9 告警

#### GET /api/alerts — 告警列表 · `alert.read`

查询参数：`?status=未处理`

```json
[{
  "no": "AL0001", "atype": "ORDER_LATE", "level": "high",
  "target": "WO0015", "message": "工单 WO0015 预计 2026-11-12 完工，晚于交期 2026-11-08 共 4 天",
  "value": 4, "threshold": 0, "status": "未处理", "created_at": "2026-10-23 09:15:17"
}]
```

**atype 枚举**

| 值 | 含义 | 默认 level |
|---|---|---|
| `ORDER_LATE` | 工单迟交 | high |
| `ORDER_NEAR` | 交期临近（余量 ≤ `late_warn_days`） | mid |
| `WC_OVER` | 工作中心超载（>1.0） | high |
| `WC_BUSY` | 工作中心繁忙（≥`util_warn`） | mid |
| `MAT_SHORT` | 物料缺口 | high / mid |

#### POST /api/alerts/{no}/handle — 处理告警 · `alert.write`

**响应** `{ok: true}`。**错误**：`404 告警不存在`、`409 告警已处理`

---

### 4.10 系统

#### GET /api/rules — 业务规则 · `system.read`

```json
{
  "sched_rule": "EDD",
  "late_warn_days": "3",
  "util_warn": "0.9",
  "horizon_days": "90",
  "default_hours_per_day": "8.0",
  "default_efficiency": "1.0"
}
```

| key | 含义 | 影响 |
|---|---|---|
| `sched_rule` | 默认排程规则 | `plan/run` 不传 rule 时使用 |
| `late_warn_days` | 交期预警天数 | `ORDER_NEAR` 告警阈值 |
| `util_warn` | 负荷预警线 | `WC_BUSY` 告警阈值、瓶颈判定 |
| `horizon_days` | 排程视界 | 默认 90 天 |
| `default_hours_per_day` | 新资源默认日产能 | 新建工作中心默认值 |
| `default_efficiency` | 新资源默认效率 | 同上 |

#### POST /api/rules/save — 更新规则 · `system.write`

两种写法二选一：

```json
{ "key": "util_warn", "value": "0.85" }
```

```json
{ "rules": { "util_warn": "0.85", "late_warn_days": "2" } }
```

只接受已知 key，未知返回 400。修改立即生效（下次排程）。

#### GET /api/reports/schedule.csv — 排程明细 CSV · `report.read`

`Content-Type: text/csv; charset=utf-8`，UTF-8 无 BOM（前端下载时自行加 `\ufeff`）。

表头：`工单,工序,工作中心,工时(h),开始日,开始时,结束日,结束时`

#### GET /api/reports/load.csv — 负荷 CSV · `report.read`

表头：`工作中心,名称,可用产能(h),负荷(h),利用率,剩余(h)`

#### GET /api/logs — 审计日志 · `system.read`

```json
[ { "username": "admin", "action": "执行排程",
    "detail": "RUN0001 EDD 10工单 迟交2", "created_at": "2026-10-23 09:15:17" } ]
```

#### GET /api/sync/version — 同步版本号（公开）

```json
{ "sales_orders": 12, "work_orders": 15, "workcenters": 3, "materials": 4,
  "products": 2, "bom": 5, "routing_ops": 6 }
```

#### GET /api/sync — 增量同步数据

查询参数：`?entities=work_orders,sales_orders&version=12`

```json
{
  "work_orders": { "version": 15, "rows": [ /* 全量行 */ ] }
}
```

只返回 `version` 大于入参的实体。`entities` 不传或含 `*` 表示全部。

#### GET /api/api-keys — API Key 列表 · `system.read`

```json
[ { "id": 1, "name": "MES 集成", "key_prefix": "apskey_9a8b",
    "role": "prod", "status": "启用",
    "created_at": "...", "last_used": "..." } ]
```

> 列表**不返回** key 明文，只返回前缀。

#### POST /api/api-keys/create — 创建 API Key · `system.write`

```json
{ "name": "MES 集成", "role": "prod" }
```

**响应 data**

```json
{
  "key": "apskey_9a8b7c6d5e4f3a2b1c0d...",
  "prefix": "apskey_9a8b",
  "role": "prod",
  "note": "仅此一次返回完整 key，请妥善保存"
}
```

**错误**：`400 name 必填`、`400 角色不存在`

#### POST /api/api-keys/{id}/delete — 删除 API Key · `system.write`

---

## 5. 集成场景示例

### 5.1 ERP 下推订单 → APS 排程 → 回读结果

```bash
# 0. 准备：ERP 侧创建 API Key（role=planner），得到 apskey_xxx
KEY="apskey_xxx"
BASE="http://42.193.158.63/aps"

# 1. 推订单
curl -s -X POST "$BASE/api/sales-orders/save" \
  -H "X-Aps-Key: $KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: erp-so-20261023-001" \
  -d '{"customer":"华东重工","product":"P-CONV","qty":2,
       "due_date":"2026-11-10","priority":1}'

# 2. 订单转工单
curl -s -X POST "$BASE/api/sales-orders/release" -H "X-Aps-Key: $KEY"

# 3. 执行排程（EDD）
curl -s -X POST "$BASE/api/plan/run" -H "X-Aps-Key: $KEY" \
  -H "Content-Type: application/json" -d '{"rule":"EDD"}'

# 4. 回读排程明细
curl -s "$BASE/api/plan/latest" -H "X-Aps-Key: $KEY"

# 5. 导出 CSV 归档
curl -s "$BASE/api/reports/schedule.csv" -H "X-Aps-Key: $KEY" -o sched.csv
```

### 5.2 销售端口内嵌 CTP 查询

```bash
curl -s -X POST "$BASE/api/ctp" -H "X-Aps-Key: $SALES_KEY" \
  -H "Content-Type: application/json" \
  -d '{"product":"P-CONV","qty":5,"due_date":"2026-11-20"}'
```

返回 `earliest_end` 直接填进销售合同交期栏；`suggestion` 可直接展示给销售。

### 5.3 MES 拉增量工单

```bash
# 先取当前版本
curl -s "$BASE/api/sync/version"
# → {"work_orders":15,...}

# 只拉变动的工单（上次 version=12）
curl -s "$BASE/api/sync?entities=work_orders&version=12" -H "X-Aps-Key: $MES_KEY"
```

### 5.4 BI 大屏看板

```bash
# 一次拿齐：批次摘要 + 负荷榜
curl -s "$BASE/api/plan/overview" -H "X-Aps-Key: $BI_KEY"

# 未处理告警数
curl -s "$BASE/api/alerts?status=未处理" -H "X-Aps-Key: $BI_KEY"
```

### 5.5 日负荷柱状图数据

```bash
curl -s "$BASE/api/plan/dayload/WC-CNC1?days=14" -H "X-Aps-Key: $KEY"
```

---

## 6. 错误码速查

| code | message 示例 | 排查方向 |
|---|---|---|
| 400 | `rule 需为 EDD/CR/PRIO/FIFO` | 枚举值拼写 |
| 400 | `due_date 需 YYYY-MM-DD` | 日期格式 |
| 400 | `qty 必须 > 0` | 数量校验 |
| 400 | `没有待排产工单（状态 已下达/排产中）` | 工单是否已下达 |
| 400 | `未知规则 key: xxx` | rules 表键名 |
| 401 | `用户名或密码错误` | 凭据 |
| 401 | `未认证或登录已过期` | token 过期（12h） |
| 403 | `无权限：plan.run` | API Key 角色权限不足 |
| 404 | `产品不存在` | 产品编码 |
| 404 | `尚未执行排程，请先 POST /api/plan/run` | 用 `/api/plan/overview` 代替 |
| 409 | `订单号已存在` | 单号冲突 |
| 409 | `告警已处理` | 重复处理 |
| 500 | 任意 | 查服务日志与 `/api/logs` |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0.0 | 2026-10-23 | 首版，56 条路由全量契约；新增 `/api/plan/overview` 看板聚合接口（空态 200） |
