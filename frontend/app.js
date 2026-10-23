/* 飞划APS · 框架层 */
var TOKEN = localStorage.getItem('aps_token') || '';
var ME = JSON.parse(localStorage.getItem('aps_user') || '{}');
var PERMS = ME.perms || [];

function api(method, path, body, raw) {
  return fetch(path, {
    method: method,
    headers: Object.assign({'Content-Type': 'application/json'},
      TOKEN ? {Authorization: 'Bearer ' + TOKEN} : {}),
    body: method === 'POST' ? JSON.stringify(body || {}) : undefined
  }).then(function (r) {
    if (r.status === 401) { localStorage.clear(); location.href = 'login.html'; throw new Error('unauth'); }
    if (r.status >= 400) {
      return r.text().then(function (t) {
        var msg = 'HTTP ' + r.status;
        try { msg = (JSON.parse(t) || {}).error || msg; } catch (e) { /* 非 JSON 响应 */ }
        throw new Error(msg);
      });
    }
    return raw ? r.text() : r.json();
  });
}
function GET(p) { return api('GET', p); }
function POST(p, b) { return api('POST', p, b); }
function CSV(p) { return api('GET', p, null, true); }

function toast(msg, err) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = err ? '#d03050' : '#1f2733';
  t.classList.remove('hidden');
  clearTimeout(t._tm);
  t._tm = setTimeout(function () { t.classList.add('hidden'); }, 2600);
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
  });
}
function perm(p) { return PERMS.indexOf('*') >= 0 || PERMS.indexOf(p) >= 0; }
function fmtPct(x) { return (x * 100).toFixed(1) + '%'; }
function fmtDate(s) { return s ? String(s).slice(0, 10) : '—'; }

var NAV = [
  ['dash', '仪表盘', '📊'],
  ['plan', '排程与甘特', '📅'],
  ['orders', '销售订单', '🧾'],
  ['wos', '生产工单', '📋'],
  ['kit', '物料齐套', '📦'],
  ['ctp', '交期承诺 CTP', '🤝'],
  ['master', '主数据', '🗂️'],
  ['alerts', '告警中心', '🔔'],
  ['system', '系统管理', '⚙️']
];

function boot() {
  if (!TOKEN) { location.href = 'login.html'; return; }
  GET('/api/auth/me').then(function (j) {
    ME = j.data; PERMS = ME.perms || [];
    document.getElementById('who').textContent = ME.name + '·' + ME.roleLabel;
    var nav = document.getElementById('nav');
    nav.innerHTML = NAV.map(function (n) {
      return '<a href="#/' + n[0] + '" data-k="' + n[0] + '">' + n[2] + ' ' + n[1] + '</a>';
    }).join('');
    nav.onclick = function (e) {
      var a = e.target.closest('a'); if (!a) return;
      e.preventDefault();
      go(a.getAttribute('data-k'));
    };
    var key = (location.hash || '#/dash').replace('#/', '');
    go(NAV.some(function (n) { return n[0] === key; }) ? key : 'dash');
    document.getElementById('btn-logout').onclick = function () {
      POST('/api/auth/logout').then(function () {
        localStorage.clear(); location.href = 'login.html';
      });
    };
    window.addEventListener('hashchange', function () {
      var k = (location.hash || '#/dash').replace('#/', '');
      if (PAGES[k]) go(k);
    });
  }).catch(function (e) { if (e.message !== 'unauth') location.href = 'login.html'; });
}

var CUR = null;
function go(key) {
  CUR = key;
  location.hash = '#/' + key;
  document.querySelectorAll('#nav a').forEach(function (a) {
    a.classList.toggle('on', a.getAttribute('data-k') === key);
  });
  var main = document.getElementById('main');
  main.innerHTML = '<div class="empty">加载中…</div>';
  /* 页面函数可能同步渲染完毕、不返回 Promise，统一兜底成 Promise */
  var task;
  try {
    task = PAGES[key](main);
  } catch (e) {
    task = Promise.reject(e);
  }
  Promise.resolve(task).catch(function (e) {
    if (e && e.message === 'unauth') return;
    main.innerHTML = '<div class="empty">加载失败：' + esc(e && e.message) + '</div>';
  });
}

function modal(html) {
  var mask = document.getElementById('modal-mask');
  document.getElementById('modal').innerHTML = html;
  mask.classList.remove('hidden');
  mask.onclick = function (e) { if (e.target === mask) closeModal(); };
}
function closeModal() { document.getElementById('modal-mask').classList.add('hidden'); }

function table(headers, rows, rowHtml) {
  return '<table><thead><tr>' + headers.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
    '</tr></thead><tbody>' + rows.map(rowHtml).join('') + '</tbody></table>';
}
