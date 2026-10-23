# -*- coding: utf-8 -*-
"""飞划 APS 管理系统 · 数据层（sqlite3 WAL，18 表）"""
import os
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("APS_DB") or os.path.join(BASE_DIR, "feihua.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  phone TEXT DEFAULT '',
  status TEXT DEFAULT '启用',
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tokens (
  token TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  expire_at TEXT NOT NULL,
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  key_prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT DEFAULT '启用',
  created_at TEXT DEFAULT '',
  last_used TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workcenters (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  wtype TEXT DEFAULT '机加',
  hours_per_day REAL DEFAULT 8.0,
  efficiency REAL DEFAULT 1.0,
  work_days TEXT DEFAULT '1,2,3,4,5',
  shift TEXT DEFAULT '白班',
  cost_rate REAL DEFAULT 0,
  status TEXT DEFAULT '运行',
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS materials (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit TEXT DEFAULT '件',
  stock REAL DEFAULT 0,
  safety REAL DEFAULT 0,
  lead_days INTEGER DEFAULT 7,
  price REAL DEFAULT 0,
  supplier TEXT DEFAULT '',
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS products (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit TEXT DEFAULT '件',
  category TEXT DEFAULT '',
  std_price REAL DEFAULT 0,
  status TEXT DEFAULT '启用',
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bom (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product TEXT NOT NULL,
  material TEXT NOT NULL,
  qty_per_unit REAL NOT NULL,
  loss_pct REAL DEFAULT 0,
  UNIQUE(product, material)
);

CREATE TABLE IF NOT EXISTS routing_ops (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product TEXT NOT NULL,
  seq INTEGER NOT NULL,
  wc TEXT NOT NULL,
  op_name TEXT DEFAULT '',
  setup_h REAL DEFAULT 0,
  run_h_per_unit REAL DEFAULT 0,
  transfer_h REAL DEFAULT 0,
  UNIQUE(product, seq)
);

CREATE TABLE IF NOT EXISTS sales_orders (
  no TEXT PRIMARY KEY,
  customer TEXT DEFAULT '',
  product TEXT NOT NULL,
  qty REAL NOT NULL,
  due_date TEXT NOT NULL,
  priority INTEGER DEFAULT 3,
  price REAL DEFAULT 0,
  status TEXT DEFAULT '待排产',
  created_date TEXT DEFAULT '',
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS work_orders (
  no TEXT PRIMARY KEY,
  so TEXT DEFAULT '',
  product TEXT NOT NULL,
  qty REAL NOT NULL,
  due_date TEXT NOT NULL,
  priority INTEGER DEFAULT 3,
  status TEXT DEFAULT '已下达',
  release_date TEXT DEFAULT '',
  created_date TEXT DEFAULT '',
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedule_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_no TEXT NOT NULL,
  rule TEXT NOT NULL,
  start_date TEXT NOT NULL,
  horizon_days INTEGER NOT NULL,
  wo_count INTEGER DEFAULT 0,
  late_count INTEGER DEFAULT 0,
  bottleneck_wc TEXT DEFAULT '',
  status TEXT DEFAULT '生效',
  run_by TEXT DEFAULT '',
  run_at TEXT DEFAULT '',
  detail TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedule_ops (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  wo TEXT NOT NULL,
  seq INTEGER NOT NULL,
  wc TEXT NOT NULL,
  hours REAL DEFAULT 0,
  start_date TEXT DEFAULT '',
  start_h REAL DEFAULT 0,
  end_date TEXT DEFAULT '',
  end_h REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kit_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_no TEXT NOT NULL,
  wo TEXT NOT NULL,
  product TEXT NOT NULL,
  kit_ok INTEGER DEFAULT 1,
  shortage TEXT DEFAULT '[]',
  need TEXT DEFAULT '{}',
  checked_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ctp_queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product TEXT NOT NULL,
  qty REAL NOT NULL,
  due_date TEXT NOT NULL,
  answer_end TEXT DEFAULT '',
  on_time INTEGER DEFAULT 0,
  feasible INTEGER DEFAULT 1,
  queried_by TEXT DEFAULT '',
  queried_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alarms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  no TEXT NOT NULL,
  atype TEXT NOT NULL,
  level TEXT DEFAULT 'mid',
  target TEXT DEFAULT '',
  message TEXT NOT NULL,
  value REAL DEFAULT 0,
  threshold REAL DEFAULT 0,
  status TEXT DEFAULT '未处理',
  period TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rules (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  remark TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT DEFAULT '',
  action TEXT DEFAULT '',
  detail TEXT DEFAULT '',
  at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS idem_keys (
  key TEXT PRIMARY KEY,
  endpoint TEXT DEFAULT '',
  response TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_state (
  entity TEXT PRIMARY KEY,
  version INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_sops_run ON schedule_ops(run_id, wo, seq);
CREATE INDEX IF NOT EXISTS ix_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS ix_so_status ON sales_orders(status);
CREATE INDEX IF NOT EXISTS ix_alarms_status ON alarms(status, level);
CREATE INDEX IF NOT EXISTS ix_logs_at ON logs(at);
"""

_local = threading.local()


def connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def close_thread_conns():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        _local.conn = None


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def rows(sql, args=()):
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = connect().execute(sql, args).fetchone()
    return dict(r) if r else None


def val(sql, args=(), default=None):
    r = connect().execute(sql, args).fetchone()
    if r is None:
        return default
    v = r[0]
    return default if v is None else v


def run(sql, args=()):
    conn = connect()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def runmany(sql, seq):
    conn = connect()
    conn.executemany(sql, seq)
    conn.commit()


def bumpsync(entity):
    import datetime
    conn = connect()
    v = val("SELECT version FROM sync_state WHERE entity=?", (entity,), 0) or 0
    conn.execute("INSERT INTO sync_state(entity, version, updated_at) VALUES(?,?,?) "
                 "ON CONFLICT(entity) DO UPDATE SET version=version+1, updated_at=excluded.updated_at",
                 (entity, v + 1, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()


def sha256(s):
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    import datetime
    return datetime.date.today()


def gen_no(cn, table, prefix, col="no"):
    """编号：MAX 尾号递增 + 空号探测，避免 COUNT+1 冲突"""
    r = cn.execute("SELECT %s FROM %s WHERE %s LIKE ? ORDER BY %s DESC LIMIT 1"
                   % (col, table, col, col), (prefix + "%",)).fetchone()
    tail = 0
    if r:
        try:
            tail = int(str(r[0])[len(prefix):].lstrip("0") or 0)
        except ValueError:
            tail = 0
    for i in range(tail + 1, tail + 1000):
        cand = "%s%04d" % (prefix, i)
        if not cn.execute("SELECT 1 FROM %s WHERE %s=?" % (table, col), (cand,)).fetchone():
            return cand
    raise RuntimeError("编号耗尽")
