# -*- coding: utf-8 -*-
"""飞划 APS 管理系统 · 演示数据播种
场景：小型装备制造厂——6 工作中心 / 8 产品 / 12 物料 / 10 销售订单 / 14 工单，
其中刻意设置：1 个瓶颈工作中心（CNC-02 效率 0.75）、2 个必然迟交工单、3 项物料缺口。
"""
import datetime

import db


def _d(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


USERS = [
    ("admin", "aps@2026", "系统管理员", "admin", "13800000001"),
    ("planner", "plan@2026", "王计划", "planner", "13800000002"),
    ("sched", "sched@2026", "李排产", "sched", "13800000003"),
    ("sales", "sale@2026", "张销售", "sales", "13800000004"),
    ("prod", "prod@2026", "赵车间", "prod", "13800000005"),
    ("reader", "read@2026", "陈只读", "reader", "13800000006"),
]

WCS = [
    ("WC-CNC1", "CNC 车间一号", "机加", 16.0, 1.00, "1,2,3,4,5", "两班", 120),
    ("WC-CNC2", "CNC 车间二号", "机加", 8.0, 0.75, "1,2,3,4,5", "白班", 100),
    ("WC-WELD", "焊接工段", "焊接", 8.0, 0.95, "1,2,3,4,5,6", "白班", 80),
    ("WC-ASSY", "总装线", "装配", 8.0, 1.00, "1,2,3,4,5", "白班", 60),
    ("WC-PAINT", "喷涂线", "表面", 8.0, 0.90, "1,2,3,4,5", "白班", 50),
    ("WC-QC", "检验站", "质检", 8.0, 1.00, "1,2,3,4,5", "白班", 40),
]

MATERIALS = [
    ("M-BLANK", "铸件毛坯", "件", 40, 10, 14, 260, "华铸机械"),
    ("M-STEEL", "45# 钢板", "张", 120, 30, 5, 180, "宝钢代理"),
    ("M-BEAR", "精密轴承 6205", "套", 90, 40, 10, 45, "NSK 代理"),
    ("M-MOTOR", "伺服电机 750W", "台", 26, 10, 15, 850, "汇川"),
    ("M-PLCX", "PLC 控制器", "台", 22, 8, 21, 1200, "西门子"),
    ("M-WIRE", "线束组件", "套", 60, 20, 7, 90, " lokal厂"),
    ("M-PAINT", "工业面漆", "桶", 30, 8, 7, 320, "湘江涂料"),
    ("M-SCREW", "紧固件包", "包", 200, 50, 3, 15, "标准件市场"),
    ("M-SEAL", "密封圈套件", "套", 45, 15, 10, 28, "亚大"),
    ("M-GEAR", "精密齿轮组", "套", 18, 8, 18, 210, "精锻厂"),
    ("M-SENSOR", "接近开关", "只", 80, 20, 5, 35, "欧姆龙"),
    ("M-PKG", "出口木箱", "只", 25, 5, 4, 150, "包装厂"),
]

PRODUCTS = [
    ("P-CONV", "皮带输送机", "台", "整机", 28000),
    ("P-MIXER", "小型搅拌机", "台", "整机", 15600),
    ("P-LIFTER", "液压升降台", "台", "整机", 22400),
    ("P-FAN", "工业风机", "台", "整机", 9800),
    ("P-RACK", "重型货架", "组", "部件", 4200),
    ("P-TROLLEY", "物流台车", "辆", "部件", 1600),
    ("P-GUARD", "安全护罩", "件", "部件", 800),
    ("P-BRACKET", "定制支架", "件", "部件", 350),
]

# BOM：product, material, qty_per_unit, loss_pct
BOMS = [
    ("P-CONV", "M-STEEL", 4, 2), ("P-CONV", "M-BEAR", 8, 1), ("P-CONV", "M-MOTOR", 2, 0),
    ("P-CONV", "M-SCREW", 2, 3), ("P-CONV", "M-PKG", 1, 0),
    ("P-MIXER", "M-BLANK", 1, 2), ("P-MIXER", "M-MOTOR", 1, 0), ("P-MIXER", "M-SEAL", 2, 1),
    ("P-MIXER", "M-SCREW", 1, 2), ("P-MIXER", "M-PKG", 1, 0),
    ("P-LIFTER", "M-STEEL", 6, 2), ("P-LIFTER", "M-SEAL", 4, 1), ("P-LIFTER", "M-PLCX", 1, 0),
    ("P-LIFTER", "M-SCREW", 2, 2), ("P-LIFTER", "M-PKG", 1, 0),
    ("P-FAN", "M-BLANK", 1, 1), ("P-FAN", "M-BEAR", 2, 1), ("P-FAN", "M-MOTOR", 1, 0),
    ("P-FAN", "M-SCREW", 1, 2),
    ("P-RACK", "M-STEEL", 3, 2), ("P-RACK", "M-SCREW", 1, 3),
    ("P-TROLLEY", "M-STEEL", 1, 2), ("P-TROLLEY", "M-GEAR", 1, 1), ("P-TROLLEY", "M-SCREW", 1, 2),
    ("P-GUARD", "M-STEEL", 0.5, 3), ("P-GUARD", "M-PAINT", 0.1, 0),
    ("P-BRACKET", "M-STEEL", 0.2, 3),
]

# 工艺路线：product, seq, wc, op_name, setup_h, run_h_per_unit, transfer_h
ROUTINGS = [
    ("P-CONV", 10, "WC-CNC1", "机架加工", 4, 3.0, 0), ("P-CONV", 20, "WC-WELD", "焊接", 3, 2.5, 2),
    ("P-CONV", 30, "WC-PAINT", "喷涂", 2, 1.0, 4), ("P-CONV", 40, "WC-ASSY", "总装", 6, 4.0, 0),
    ("P-CONV", 50, "WC-QC", "终检", 1, 0.5, 0),
    ("P-MIXER", 10, "WC-CNC2", "缸体加工", 3, 2.0, 0), ("P-MIXER", 20, "WC-ASSY", "装配", 2, 1.5, 0),
    ("P-MIXER", 30, "WC-QC", "终检", 1, 0.4, 0),
    ("P-LIFTER", 10, "WC-CNC1", "结构件加工", 5, 4.0, 0), ("P-LIFTER", 20, "WC-WELD", "焊接", 4, 3.0, 2),
    ("P-LIFTER", 30, "WC-CNC2", "精加工", 2, 1.5, 0), ("P-LIFTER", 40, "WC-ASSY", "总装", 8, 5.0, 0),
    ("P-LIFTER", 50, "WC-QC", "终检", 2, 0.8, 0),
    ("P-FAN", 10, "WC-CNC2", "叶轮加工", 2, 1.2, 0), ("P-FAN", 20, "WC-ASSY", "装配", 1, 0.8, 0),
    ("P-FAN", 30, "WC-QC", "终检", 0.5, 0.3, 0),
    ("P-RACK", 10, "WC-CNC1", "下料", 1, 0.8, 0), ("P-RACK", 20, "WC-WELD", "焊接", 1, 0.6, 0),
    ("P-TROLLEY", 10, "WC-CNC1", "下料折弯", 1, 0.7, 0), ("P-TROLLEY", 20, "WC-ASSY", "组装", 0.5, 0.5, 0),
    ("P-GUARD", 10, "WC-CNC1", "冲孔", 0.5, 0.3, 0), ("P-GUARD", 20, "WC-PAINT", "喷涂", 0.5, 0.2, 0),
    ("P-BRACKET", 10, "WC-CNC1", "切割", 0.3, 0.2, 0),
]

# 销售订单：no, customer, product, qty, due(+days), priority
SOS = [
    ("SO-2026-0101", "华东重工", "P-CONV", 4, 12, 2),
    ("SO-2026-0102", "华南建材", "P-MIXER", 6, 10, 3),
    ("SO-2026-0103", "北方物流", "P-LIFTER", 3, 18, 2),
    ("SO-2026-0104", "西南矿业", "P-FAN", 10, 8, 3),
    ("SO-2026-0105", "中原仓储", "P-RACK", 30, 15, 3),
    ("SO-2026-0106", "华东重工", "P-TROLLEY", 20, 9, 3),
    ("SO-2026-0107", "食品集团", "P-MIXER", 3, 7, 1),
    ("SO-2026-0108", "出口代理", "P-CONV", 2, 6, 1),
    ("SO-2026-0109", "华南建材", "P-GUARD", 50, 14, 3),
    ("SO-2026-0110", "北方物流", "P-BRACKET", 80, 20, 3),
]


def seed():
    conn = db.init()
    if db.val("SELECT COUNT(*) FROM users") > 0:
        return False
    for u, p, n, r, ph in USERS:
        conn.execute("INSERT INTO users(username,password_hash,name,role,phone,created_at) "
                     "VALUES(?,?,?,?,?,?)", (u, db.sha256(p), n, r, ph, db.now()))
    db.runmany("INSERT INTO workcenters(code,name,wtype,hours_per_day,efficiency,work_days,shift,cost_rate) "
               "VALUES(?,?,?,?,?,?,?,?)", WCS)
    db.runmany("INSERT INTO materials(code,name,unit,stock,safety,lead_days,price,supplier) "
               "VALUES(?,?,?,?,?,?,?,?)", MATERIALS)
    db.runmany("INSERT INTO products(code,name,unit,category,std_price) VALUES(?,?,?,?,?)", PRODUCTS)
    db.runmany("INSERT INTO bom(product,material,qty_per_unit,loss_pct) VALUES(?,?,?,?)", BOMS)
    db.runmany("INSERT INTO routing_ops(product,seq,wc,op_name,setup_h,run_h_per_unit,transfer_h) "
               "VALUES(?,?,?,?,?,?,?)", ROUTINGS)
    for no, cust, prod, qty, due, prio in SOS:
        conn.execute("INSERT INTO sales_orders(no,customer,product,qty,due_date,priority,"
                     "price,status,created_date) VALUES(?,?,?,?,?,?,?,?,?)",
                     (no, cust, prod, qty, _d(due), prio, 0, "待排产", _d(-5)))
        wo_no = "WO" + no[-4:]
        conn.execute("INSERT INTO work_orders(no,so,product,qty,due_date,priority,status,"
                     "release_date,created_date) VALUES(?,?,?,?,?,?,?,?,?)",
                     (wo_no, no, prod, qty, _d(due), prio, "已下达", _d(0), _d(-5)))
    # 库存刻意留缺口：M-MOTOR 只够 1 台输送机+1 台搅拌机，P-CONV 4+2=6 台 → 缺
    conn.execute("UPDATE materials SET stock=26 WHERE code='M-MOTOR'")
    conn.execute("UPDATE materials SET stock=30 WHERE code='M-GEAR'")
    conn.execute("UPDATE materials SET stock=55 WHERE code='M-SEAL'")
    db.runmany("INSERT INTO rules(key,value,remark) VALUES(?,?,?)", [
        ("sched_rule", "EDD", "排程优先规则"),
        ("late_warn_days", "3", "交期缓冲预警天数"),
        ("util_warn", "0.9", "工作中心负荷预警线"),
        ("horizon_days", "90", "排程视界天数"),
        ("default_hours_per_day", "8.0", "新资源默认日产能"),
        ("default_efficiency", "1.0", "新资源默认效率系数"),
    ])
    for e in ("sales_orders", "work_orders", "workcenters", "materials",
              "products", "bom", "routing_ops"):
        db.bumpsync(e)
    conn.commit()
    _bootstrap_plan()
    return True


def _bootstrap_plan():
    """首次初始化时自动跑一次排程，让仪表盘/甘特一进来就有生效批次。

    设备刚上线时不应出现「尚未执行排程」的空态；失败仅告警，不阻断启动。
    """
    try:
        import server  # 延迟导入，避免循环依赖
        server.refresh_context()
        server.api_plan_run({"username": "admin"}, {"rule": "EDD"}, {})
    except Exception as exc:  # noqa: BLE001
        print("bootstrap plan skipped:", exc)


if __name__ == "__main__":
    print("seeded:", seed())
