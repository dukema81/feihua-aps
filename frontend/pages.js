/* 飞划APS · 页面层 */
var PAGES = {};

/* ---------------- 仪表盘 ---------------- */
PAGES.dash = function (main) {
  /* 一次 /api/plan/overview 取全看板数据，避免多请求 + 空态 404 噪声 */
  return Promise.all([GET('/api/health'), GET('/api/alerts'),
                      GET('/api/plan/overview').catch(function () { return {data: null}; })])
    .then(function (rs) {
      var h = rs[0].data, alerts = rs[1].data || [], ov = rs[2] && rs[2].data;
      var loads = (ov && ov.loads) || [];
      var latest = ov && ov.run ? ov : null;
      var pending = alerts.filter(function (a) { return a.status === '未处理'; });
      var late = latest ? latest.run.late_count : '—';
      main.innerHTML =
        '<h2 class="page">仪表盘</h2>' +
        '<div class="kpis">' +
        kpi(latest ? latest.run.run_no : '未排程', '最近排程序号') +
        kpi(h.work_orders, '生产工单') +
        kpi(late, '迟交工单', late && late !== '—' ? 'err' : '') +
        kpi(h.sales_orders, '销售订单') +
        kpi(h.workcenters, '工作中心') +
        kpi(pending.length, '未处理告警', pending.length ? 'err' : 'ok') +
        '</div>' +
        '<div class="card"><h3>工作中心负荷（最近排程）</h3>' +
        (loads.length ? loads.map(function (l) {
          var cls = l.utilization > 1 ? 'over' : (l.utilization >= 0.9 ? 'warn' : '');
          return '<div class="g-row"><div class="g-label">' + esc(l.wc) + ' ' + esc(l.name) +
            '</div><div class="bar" style="flex:1"><i class="' + cls + '" style="width:' +
            Math.min(l.utilization * 100, 100) + '%"></i></div>' +
            '<div style="width:130px;text-align:right;font-size:12px">' + fmtPct(l.utilization) +
            '（' + l.load_h + 'h/' + l.capacity_h + 'h）</div></div>';
        }).join('') : '<div class="empty">尚未排程</div>') + '</div>' +
        '<div class="card"><h3>最新未处理告警</h3>' +
        (pending.length ? table(['级别', '类型', '对象', '消息', '时间'], pending.slice(0, 8),
          function (a) {
            return '<tr><td><span class="tag ' + (a.level === 'high' ? 'err' : 'warn') + '">' +
              esc(a.level) + '</span></td><td>' + esc(a.atype) + '</td><td>' + esc(a.target) +
              '</td><td style="white-space:normal">' + esc(a.message) + '</td><td>' + esc(a.created_at) + '</td></tr>';
          }) : '<div class="empty">无未处理告警 🎉</div>') + '</div>';
    });
};
function kpi(v, t, cls) {
  return '<div class="kpi"><div class="v ' + (cls || '') + '">' + v + '</div><div class="t">' + t + '</div></div>';
}

/* ---------------- 排程与甘特 ---------------- */
PAGES.plan = function (main) {
  return GET('/api/plan/latest').then(function (j) { render(main, j.data); })
    .catch(function () { render(main, null); });
  function render(main, latest) {
    main.innerHTML =
      '<h2 class="page">排程与甘特</h2>' +
      '<div style="color:var(--sub);font-size:12.5px;margin-bottom:10px">' +
      '有限产能正向排程：按优先规则（EDD 最早交期 / CR 关键比率 / PRIO 优先级 / FIFO 先到先做）' +
      '把工单工序逐日放入工作中心日产能桶，产出资源甘特图、负荷率与瓶颈、迟交清单。</div>' +
      '<div class="toolbar">' +
      (perm('plan.run') ? '<select id="rule"><option>EDD</option><option>CR</option><option>PRIO</option><option>FIFO</option></select>' +
        '<button class="btn" id="btn-run">▶ 执行排程</button>' +
        '<button class="btn ghost" id="btn-pushin">⚡ 插单重排</button>' : '') +
      '<button class="btn ghost" id="btn-csv-s">导出排程CSV</button>' +
      '<button class="btn ghost" id="btn-csv-l">导出负荷CSV</button>' +
      '<span class="tag info">' + (latest ? '生效批次 ' + esc(latest.run.run_no) + ' · 规则 ' + esc(latest.run.rule) +
        ' · 迟交 ' + latest.run.late_count + '/' + latest.run.wo_count : '尚未排程') + '</span></div>' +
      '<div id="plan-body"></div>';
    var body = document.getElementById('plan-body');
    if (latest) draw(body, latest);
    else body.innerHTML = '<div class="empty">先执行一次排程</div>';
    var rb = document.getElementById('btn-run');
    if (rb) rb.onclick = function () {
      rb.disabled = true;
      POST('/api/plan/run', {rule: document.getElementById('rule').value}).then(function (j) {
        toast('排程完成：' + j.data.wo_count + ' 工单，迟交 ' + j.data.late_count);
        go('plan');
      }).catch(function (e) { toast(e.message || '排程失败', true); rb.disabled = false; });
    };
    var pb = document.getElementById('btn-pushin');
    if (pb) pb.onclick = pushInModal;
    document.getElementById('btn-csv-s').onclick = function () { dl('/api/reports/schedule.csv'); };
    document.getElementById('btn-csv-l').onclick = function () { dl('/api/reports/load.csv'); };
  }
  function dl(p) { CSV(p).then(function (t) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\ufeff' + t], {type: 'text/csv'}));
    a.download = p.split('/').pop(); a.click();
  }); }
  function draw(el, latest) {
    var total = latest.run.horizon_days;
    var start = latest.run.start_date;
    var d0 = new Date(start + 'T00:00:00');
    el.innerHTML = '<div class="card"><h3>资源甘特图（' + esc(start) + ' 起 ' + total + ' 天，条上为工单号）</h3><div class="gantt" id="gantt"></div></div>' +
      '<div class="card"><h3>工单结果</h3><div id="wores"></div></div>';
    var gt = document.getElementById('gantt');
    var wcs = Object.keys(latest.ops ? groupBy(latest.ops, 'wc') : {});
    if (!wcs.length) wcs = Object.keys(latest.loads || {}).length ? [] : [];
    /* 用 gantt 接口的数据更方便：直接再拉 */
    GET('/api/plan/gantt').then(function (j) {
      var g = j.data.by_wc, wos = j.data.work_orders;
      var html = '';
      Object.keys(g).sort().forEach(function (wc) {
        html += '<div style="font-weight:600;margin:8px 0 4px">' + esc(wc) + '</div>';
        g[wc].forEach(function (o) {
          var idx = Math.round((new Date(o.start_date + 'T00:00:00') - d0) / 86400000);
          var len = Math.max(1, Math.round((new Date((o.end_date || o.start_date) + 'T00:00:00') - new Date(o.start_date + 'T00:00:00')) / 86400000) + 1);
          var wo = wos[o.wo] || {};
          var late = wo.due_date && o.end_date > wo.due_date;
          html += '<div class="g-row"><div class="g-label">' + esc(o.wo) + ' #' + o.seq + '</div>' +
            '<div class="g-track"><div class="g-bar ' + (late ? 'late' : 'ok2') + '" style="left:' +
            (idx / total * 100) + '%;width:' + Math.min(len / total * 100, 100) + '%" title="' +
            esc(o.start_date + ' ' + o.start_h + 'h → ' + o.end_date + ' ' + o.end_h + 'h / ' + o.hours + 'h') + '">' +
            esc(o.wo + ' #' + o.seq + ' ' + o.hours + 'h') + '</div></div></div>';
        });
      });
      gt.innerHTML = html || '<div class="empty">无排程明细</div>';
      var res = [];
      Object.keys(g).forEach(function (wc) {
        g[wc].forEach(function (o) {
          if (!res.find(function (x) { return x.wo === o.wo; })) res.push({wo: o.wo});
        });
      });
    });
    /* 工单结果表 */
    var r0 = latest.ops.length ? latest.ops[0] : null;
    /* 从 latest.run 的 detail 中提取结果不现实，直接聚合 ops */
    var byWo = groupBy(latest.ops, 'wo');
    document.getElementById('wores').innerHTML = table(
      ['工单', '工序数', '首工序开始', '末工序结束', '状态'],
      Object.keys(byWo), function (wo) {
        var ops = byWo[wo];
        var first = ops[0], last = ops[ops.length - 1];
        var woMeta = (latest.kit || []).find(function (k) { return k.wo === wo; });
        var blocked = woMeta && woMeta.kit_ok === false;
        return '<tr><td>' + esc(wo) + '</td><td>' + ops.length + '</td><td>' +
          esc(first.start_date) + '</td><td>' + esc(last.end_date) + '</td><td>' +
          (blocked ? '<span class="tag warn">齐套缺口</span>' : '<span class="tag ok">已排产</span>') +
          '</td></tr>';
      });
  }
  function groupBy(arr, k) {
    var m = {};
    arr.forEach(function (x) { (m[x[k]] = m[x[k]] || []).push(x); });
    return m;
  }
  function pushInModal() {
    GET('/api/products').then(function (j) {
      var opts = j.data.map(function (p) {
        return '<option value="' + esc(p.code) + '">' + esc(p.code) + ' ' + esc(p.name) + '</option>';
      }).join('');
      modal('<h3>⚡ 插单重排</h3>' +
        '<div class="frow"><label>产品</label><select id="pi-prod">' + opts + '</select></div>' +
        '<div class="frow"><label>数量</label><input id="pi-qty" type="number" value="2" min="1"></div>' +
        '<div class="frow"><label>交期</label><input id="pi-due" type="date" value="' + new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10) + '"></div>' +
        '<div class="frow"><label>优先级</label><select id="pi-prio"><option value="1">1 紧急</option><option value="2">2 高</option><option value="3">3 普通</option></select></div>' +
        '<div class="frow"><label>客户</label><input id="pi-cust" value="插单客户"></div>' +
        '<button class="btn" id="pi-go">确认插单并重排</button> <button class="btn ghost" onclick="closeModal()">取消</button>' +
        '<div id="pi-out" style="margin-top:10px"></div>');
      document.getElementById('pi-go').onclick = function () {
        POST('/api/plan/push-in', {
          product: document.getElementById('pi-prod').value,
          qty: +document.getElementById('pi-qty').value,
          due_date: document.getElementById('pi-due').value,
          priority: +document.getElementById('pi-prio').value,
          customer: document.getElementById('pi-cust').value
        }).then(function (j) {
          var d = j.data;
          document.getElementById('pi-out').innerHTML =
            '<div class="tag ok">插单成功</div> ' + esc(d.so) + ' → ' + esc(d.wo) +
            '，预计完工 <b>' + esc(d.end) + '</b>；重排后迟交 ' + d.late_count + ' 张（' + esc(d.late_wos.join(', ')) + '）';
        }).catch(function (e) { toast(e.message || '插单失败', true); });
      };
    });
  }
};

/* ---------------- 销售订单 ---------------- */
PAGES.orders = function (main) {
  return GET('/api/sales-orders').then(function (j) {
    main.innerHTML = '<h2 class="page">销售订单</h2><div class="toolbar">' +
      (perm('so.write') ? '<button class="btn" id="btn-new">＋ 新增订单</button>' +
      '<button class="btn ghost" id="btn-rel">订单转工单</button>' : '') + '</div>' +
      table(['订单号', '客户', '产品', '数量', '交期', '优先级', '状态', ''], j.data,
        function (o) {
          return '<tr><td>' + esc(o.no) + '</td><td>' + esc(o.customer) + '</td><td>' + esc(o.product) +
            '</td><td>' + o.qty + '</td><td>' + esc(o.due_date) + '</td><td>' + o.priority + '</td><td>' +
            '<span class="tag ' + (o.status === '待排产' ? 'warn' : 'info') + '">' + esc(o.status) + '</span></td>' +
            '<td>' + (perm('so.write') ? '<button class="btn ghost sm" onclick="editSO(\'' + esc(o.no) + '\')">编辑</button>' : '') + '</td></tr>';
        });
    var nb = document.getElementById('btn-new');
    if (nb) nb.onclick = function () { editSO(null); };
    var rel = document.getElementById('btn-rel');
    if (rel) rel.onclick = function () {
      POST('/api/sales-orders/release').then(function (j) {
        toast('已生成 ' + j.data.count + ' 张工单'); go('orders');
      });
    };
    window._soProducts = null;
  });
};
window.editSO = function (no) {
  var ps = null;
  GET('/api/products').then(function (j) {
    ps = j.data;
    var p = no ? null : null;
    var pr = ps.map(function (x) {
      return '<option value="' + esc(x.code) + '">' + esc(x.code) + ' ' + esc(x.name) + '</option>';
    }).join('');
    GET('/api/sales-orders').then(function (j2) {
      var o = no ? j2.data.find(function (x) { return x.no === no; }) : {};
      modal('<h3>' + (no ? '编辑订单 ' + esc(no) : '新增销售订单') + '</h3>' +
        '<div class="frow"><label>客户</label><input id="f-cust" value="' + esc(o.customer || '') + '"></div>' +
        '<div class="frow"><label>产品</label><select id="f-prod">' + pr + '</select></div>' +
        '<div class="frow"><label>数量</label><input id="f-qty" type="number" value="' + (o.qty || 1) + '"></div>' +
        '<div class="frow"><label>交期</label><input id="f-due" type="date" value="' + (o.due_date || new Date(Date.now() + 10 * 86400000).toISOString().slice(0, 10)) + '"></div>' +
        '<div class="frow"><label>优先级</label><select id="f-prio"><option value="1">1 紧急</option><option value="2">2 高</option><option value="3" selected>3 普通</option></select></div>' +
        '<button class="btn" id="f-save">保存</button> <button class="btn ghost" onclick="closeModal()">取消</button>');
      if (o) document.getElementById('f-prod').value = o.product;
      if (o) document.getElementById('f-prio').value = o.priority;
      document.getElementById('f-save').onclick = function () {
        POST('/api/sales-orders/save', {
          no: no || undefined,
          customer: document.getElementById('f-cust').value,
          product: document.getElementById('f-prod').value,
          qty: +document.getElementById('f-qty').value,
          due_date: document.getElementById('f-due').value,
          priority: +document.getElementById('f-prio').value
        }).then(function () { closeModal(); toast('已保存'); go('orders'); })
          .catch(function (e) { toast(e.message || '保存失败', true); });
      };
    });
  });
};

/* ---------------- 工单 ---------------- */
PAGES.wos = function (main) {
  return GET('/api/work-orders').then(function (j) {
    main.innerHTML = '<h2 class="page">生产工单</h2>' +
      table(['工单号', '关联订单', '产品', '数量', '交期', '优先级', '状态', '下达日'], j.data,
        function (w) {
          return '<tr><td>' + esc(w.no) + '</td><td>' + esc(w.so || '—') + '</td><td>' + esc(w.product) +
            '</td><td>' + w.qty + '</td><td>' + esc(w.due_date) + '</td><td>' + w.priority + '</td><td>' +
            '<span class="tag ' + (w.status === '排程失败' ? 'err' : (w.status === '排产中' ? 'ok' : 'info')) + '">' +
            esc(w.status) + '</span></td><td>' + esc(fmtDate(w.release_date)) + '</td></tr>';
        });
  });
};

/* ---------------- 齐套 ---------------- */
PAGES.kit = function (main) {
  main.innerHTML = '<h2 class="page">物料齐套检查</h2>' +
    '<div style="color:var(--sub);font-size:12.5px;margin-bottom:10px">' +
    '按排程顺序模拟发料（先排先领）：逐单核对 BOM 需求量与现有库存，' +
    '缺料工单会被标记为阻塞，缺料不预扣库存以免虚假齐套。</div><div class="toolbar">' +
    '<button class="btn" id="btn-kit">▶ 执行齐套检查</button></div><div id="kit-body">' +
    '<div class="empty">点击按钮按当前排程顺序模拟发料</div></div>';
  document.getElementById('btn-kit').onclick = function () {
    document.getElementById('kit-body').innerHTML = '<div class="empty">计算中…</div>';
    POST('/api/kit/run').then(function (j) {
      var d = j.data;
      document.getElementById('kit-body').innerHTML =
        '<div class="kpis">' + kpi(d.ok_count, '齐套工单', 'ok') + kpi(d.block_count, '缺料阻塞', d.block_count ? 'err' : '') +
        kpi(Object.keys(d.stock_after).length, '物料品种') + '</div>' +
        '<div class="card"><h3>检查明细（批次 ' + esc(d.check_no) + '）</h3>' +
        table(['工单', '产品', '齐套', '缺口明细'], d.rows, function (r) {
          return '<tr><td>' + esc(r.wo) + '</td><td>' + esc(r.product) + '</td><td>' +
            (r.kit_ok ? '<span class="tag ok">齐套</span>' : '<span class="tag err">缺口 ' + r.shortage.length + '</span>') +
            '</td><td style="white-space:normal">' + esc(r.shortage.map(function (s) {
              return s.material + ' 需' + s.need + ' 存' + s.stock + ' 缺' + s.gap;
            }).join('；') || '—') + '</td></tr>';
        }) + '</div>' +
        '<div class="card"><h3>缺口汇总</h3>' +
        (d.shortage.length ? table(['物料', '总缺口', '阻塞工单'], d.shortage, function (s) {
          return '<tr><td>' + esc(s.material) + '</td><td>' + s.total_gap + '</td><td>' + esc(s.block_wos.join(', ')) + '</td></tr>';
        }) : '<div class="empty">无缺口 🎉</div>') + '</div>';
    }).catch(function (e) { toast(e.message || '检查失败', true); });
  };
};

/* ---------------- CTP ---------------- */
PAGES.ctp = function (main) {
  main.innerHTML = '<h2 class="page">交期承诺 CTP</h2>' +
    '<div class="card"><h3>模拟一条新订单，回答"这单能不能接、最早什么时候交"</h3>' +
    '<div class="toolbar"><select id="c-prod"></select>' +
    '<input id="c-qty" type="number" value="2" min="1" style="width:90px">' +
    '<input id="c-due" type="date" value="' + new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10) + '">' +
    '<button class="btn" id="c-go">查询可承诺</button></div>' +
    '<div id="c-out"></div></div>' +
    '<div class="card"><h3>历史查询</h3><div id="c-his"><div class="empty">加载中…</div></div></div>';
  GET('/api/products').then(function (j) {
    document.getElementById('c-prod').innerHTML = j.data.map(function (p) {
      return '<option value="' + esc(p.code) + '">' + esc(p.code) + ' ' + esc(p.name) + '</option>';
    }).join('');
  });
  document.getElementById('c-go').onclick = function () {
    POST('/api/ctp', {product: document.getElementById('c-prod').value,
      qty: +document.getElementById('c-qty').value,
      due_date: document.getElementById('c-due').value}).then(function (j) {
      var d = j.data;
      document.getElementById('c-out').innerHTML =
        '<div class="tag ' + (d.on_time ? 'ok' : (d.feasible ? 'warn' : 'err')) + '">' +
        (d.on_time ? '可按期承诺' : (d.feasible ? '需协商' : '无法排入')) + '</div> ' + esc(d.suggestion) +
        '<div style="margin-top:8px;font-size:12px;color:var(--sub)">最早完工 ' + esc(d.earliest_end || '—') +
        ' ｜ 要求交期 ' + esc(d.requested_due) + ' ｜ 队列 ' + d.queue_len + ' 工单</div>';
      loadHis();
    }).catch(function (e) { toast(e.message || '查询失败', true); });
  };
  loadHis();
  function loadHis() {
    GET('/api/ctp/history').then(function (j) {
      document.getElementById('c-his').innerHTML = table(
        ['时间', '产品', '数量', '要求交期', '最早完工', '按期', '查询人'], j.data, function (r) {
          return '<tr><td>' + esc(r.queried_at) + '</td><td>' + esc(r.product) + '</td><td>' + r.qty +
            '</td><td>' + esc(r.due_date) + '</td><td>' + esc(r.answer_end || '—') + '</td><td>' +
            (r.on_time ? '<span class="tag ok">是</span>' : '<span class="tag err">否</span>') + '</td><td>' +
            esc(r.queried_by) + '</td></tr>';
        });
    });
  }
};

/* ---------------- 主数据 ---------------- */
PAGES.master = function (main) {
  main.innerHTML = '<h2 class="page">主数据</h2><div class="toolbar">' +
    ['wc', 'mat', 'prod', 'bom', 'rt'].map(function (t, i) {
      return '<button class="btn ghost sm tab" data-t="' + t + '"' + (i === 0 ? ' style="background:var(--pri);color:#fff"' : '') + '>' +
        ['工作中心', '物料', '产品/BOM', '工艺路线', '库存调整'][i] + '</button>';
    }).join('') + '</div><div id="m-body"></div>';
  document.querySelectorAll('.tab').forEach(function (b) {
    b.onclick = function () {
      document.querySelectorAll('.tab').forEach(function (x) { x.style.cssText = ''; });
      b.style.cssText = 'background:var(--pri);color:#fff';
      draw(b.getAttribute('data-t'));
    };
  });
  draw('wc');
  function draw(t) {
    var el = document.getElementById('m-body');
    el.innerHTML = '<div class="empty">加载中…</div>';
    if (t === 'wc') GET('/api/workcenters').then(function (j) {
      el.innerHTML = table(['编码', '名称', '类型', '日产能(h)', '效率', '工作日', '班次', '成本率', '状态'], j.data,
        function (w) {
          return '<tr><td>' + esc(w.code) + '</td><td>' + esc(w.name) + '</td><td>' + esc(w.wtype) +
            '</td><td>' + w.hours_per_day + '</td><td>' + w.efficiency + '</td><td>' + esc(w.work_days) +
            '</td><td>' + esc(w.shift) + '</td><td>' + w.cost_rate + '</td><td>' +
            '<span class="tag ' + (w.status === '运行' ? 'ok' : 'warn') + '">' + esc(w.status) + '</span></td></tr>';
        });
    });
    else if (t === 'mat') GET('/api/materials').then(function (j) {
      el.innerHTML = table(['编码', '名称', '单位', '库存', '安全库存', '采购周期(天)', '单价', '供应商'], j.data,
        function (m) {
          return '<tr><td>' + esc(m.code) + '</td><td>' + esc(m.name) + '</td><td>' + esc(m.unit) +
            '</td><td>' + m.stock + '</td><td>' + m.safety + '</td><td>' + m.lead_days + '</td><td>' +
            m.price + '</td><td>' + esc(m.supplier) + '</td></tr>';
        });
    });
    else if (t === 'prod') Promise.all([GET('/api/products'), GET('/api/bom')]).then(function (rs) {
      var boms = rs[1].data;
      el.innerHTML = '<div class="card"><h3>产品</h3>' + table(['编码', '名称', '单位', '类别', '标准价'], rs[0].data,
        function (p) { return '<tr><td>' + esc(p.code) + '</td><td>' + esc(p.name) + '</td><td>' + esc(p.unit) +
          '</td><td>' + esc(p.category) + '</td><td>' + p.std_price + '</td></tr>'; }) + '</div>' +
        '<div class="card"><h3>BOM</h3>' + table(['产品', '物料', '单件用量', '损耗%'], boms,
          function (b) { return '<tr><td>' + esc(b.product) + '</td><td>' + esc(b.material) + ' ' + esc(b.mat_name || '') +
            '</td><td>' + b.qty_per_unit + '</td><td>' + b.loss_pct + '</td></tr>'; }) + '</div>';
    });
    else if (t === 'rt') GET('/api/routings').then(function (j) {
      el.innerHTML = table(['产品', '工序号', '工作中心', '工序名', '准备(h)', '单件(h)', '转移(h)'], j.data,
        function (r) { return '<tr><td>' + esc(r.product) + '</td><td>' + r.seq + '</td><td>' + esc(r.wc) + ' ' +
          esc(r.wc_name || '') + '</td><td>' + esc(r.op_name) + '</td><td>' + r.setup_h + '</td><td>' +
          r.run_h_per_unit + '</td><td>' + r.transfer_h + '</td></tr>'; });
    });
    else if (t === 'inv') {
      el.innerHTML = '<div class="card"><h3>库存调整</h3>' +
        '<div class="toolbar"><input id="adj-code" placeholder="物料编码 如 M-STEEL" style="width:200px">' +
        '<input id="adj-delta" type="number" value="10" style="width:100px">' +
        '<button class="btn" id="adj-go">调整</button></div><div id="adj-out"></div></div>';
      document.getElementById('adj-go').onclick = function () {
        POST('/api/materials/adjust', {code: document.getElementById('adj-code').value.trim(),
          delta: +document.getElementById('adj-delta').value}).then(function (j) {
          document.getElementById('adj-out').innerHTML = '<span class="tag ok">已调整，现库存 ' + j.data.stock + '</span>';
        }).catch(function (e) { toast(e.message || '失败', true); });
      };
    }
  }
};

/* ---------------- 告警 ---------------- */
PAGES.alerts = function (main) {
  return GET('/api/alerts').then(function (j) {
    var list = j.data || [];
    main.innerHTML = '<h2 class="page">告警中心</h2>' +
      '<div style="color:var(--sub);font-size:12.5px;margin-bottom:10px">' +
      '排程自动产出四类告警：工单迟交（ORDER_LATE）、交期临近（ORDER_NEAR）、' +
      '工作中心超载/繁忙（WC_OVER/WC_BUSY）、物料缺口（MAT_SHORT）。处理后可归档。</div>' +
      table(['编号', '级别', '类型', '对象', '消息', '状态', '时间', ''], list, function (a) {
        return '<tr><td>' + esc(a.no) + '</td><td><span class="tag ' +
          (a.level === 'high' ? 'err' : (a.level === 'mid' ? 'warn' : 'info')) + '">' + esc(a.level) +
          '</span></td><td>' + esc(a.atype) + '</td><td>' + esc(a.target) + '</td>' +
          '<td style="white-space:normal;max-width:380px">' + esc(a.message) + '</td><td>' +
          (a.status === '已处理' ? '<span class="tag ok">已处理</span>' : '<span class="tag warn">未处理</span>') +
          '</td><td>' + esc(a.created_at) + '</td><td>' +
          (a.status === '未处理' ? '<button class="btn sm" onclick="handleAlert(\'' + esc(a.no) + '\')">处理</button>' : '') +
          '</td></tr>';
      });
    window.handleAlert = function (no) {
      POST('/api/alerts/' + no + '/handle').then(function () { toast('已处理'); go('alerts'); })
        .catch(function (e) { toast(e.message || '失败', true); });
    };
  });
};

/* ---------------- 系统管理 ---------------- */
PAGES.system = function (main) {
  Promise.all([GET('/api/users'), GET('/api/roles'), GET('/api/rules'), GET('/api/logs'),
               GET('/api/api-keys')]).then(function (rs) {
    var users = rs[0].data, roles = rs[1].data, rulesObj = rs[2].data, logs = rs[3].data, keys = rs[4].data;
    main.innerHTML = '<h2 class="page">系统管理</h2>' +
      '<div class="card"><h3>业务规则</h3><div id="rules-box"></div></div>' +
      '<div class="card"><h3>用户与角色</h3>' +
      table(['用户名', '姓名', '角色', '电话', '状态'], users, function (x) {
        return '<tr><td>' + esc(x.username) + '</td><td>' + esc(x.name) + '</td><td>' + esc(x.role) +
          '</td><td>' + esc(x.phone) + '</td><td>' + esc(x.status) + '</td></tr>';
      }) + '<div style="margin-top:10px">' + roles.map(function (r) {
        return '<div style="font-size:12px;margin-bottom:4px"><b>' + esc(r.label) + '（' + esc(r.role) + '）</b>：' +
          esc(r.perms.join(', ')) + '</div>';
      }).join('') + '</div></div>' +
      '<div class="card"><h3>API 密钥（外部系统对接）</h3>' +
      (perm('system.write') ? '<div class="toolbar"><input id="ak-name" placeholder="密钥名称，如 MES 对接" style="width:200px">' +
      '<select id="ak-role"><option value="reader">reader</option><option value="planner">planner</option><option value="sales">sales</option></select>' +
      '<button class="btn" id="ak-go">创建</button></div><div id="ak-out"></div>' : '') +
      table(['ID', '名称', '前缀', '角色', '状态', '最近使用'], keys, function (k) {
        return '<tr><td>' + k.id + '</td><td>' + esc(k.name) + '</td><td>' + esc(k.key_prefix) + '</td><td>' +
          esc(k.role) + '</td><td>' + esc(k.status) + '</td><td>' + esc(k.last_used || '—') + '</td></tr>';
      }) + '</div>' +
      '<div class="card"><h3>审计日志（最近 200 条）</h3>' +
      table(['用户', '动作', '详情', '时间'], logs, function (l) {
        return '<tr><td>' + esc(l.username) + '</td><td>' + esc(l.action) + '</td><td>' + esc(l.detail) +
          '</td><td>' + esc(l.at) + '</td></tr>';
      }) + '</div>';
    var rb = document.getElementById('rules-box');
    rb.innerHTML = Object.keys(rulesObj).map(function (k) {
      return '<div class="frow" style="max-width:460px"><label>' + esc(k) + '</label>' +
        '<input value="' + esc(rulesObj[k]) + '" data-k="' + esc(k) + '"></div>';
    }).join('') + '<button class="btn" id="rules-save">保存规则</button>';
    document.getElementById('rules-save').onclick = function () {
      var obj = {};
      rb.querySelectorAll('input[data-k]').forEach(function (i) { obj[i.getAttribute('data-k')] = i.value; });
      POST('/api/rules/save', {rules: obj}).then(function () { toast('规则已保存，下次排程生效'); })
        .catch(function (e) { toast(e.message || '失败', true); });
    };
    var ak = document.getElementById('ak-go');
    if (ak) ak.onclick = function () {
      POST('/api/api-keys/create', {name: document.getElementById('ak-name').value,
        role: document.getElementById('ak-role').value}).then(function (j) {
        document.getElementById('ak-out').innerHTML = '<div class="tag warn">仅显示一次</div> <code>' +
          esc(j.data.key) + '</code>';
      }).catch(function (e) { toast(e.message || '失败', true); });
    };
  });
};
