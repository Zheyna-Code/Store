"""Admin panel HTML. All data comes from authenticated /api/admin routes."""

ADMIN_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nexus — панель магазина</title>
<style>

:root {
  color-scheme: dark;
  --bg: #0b101c; --side: #101929; --panel: #172235; --panel-2: #1d2b40; --panel-3: #263750;
  --line: #2a3950; --line-2: #3f5573;
  --gold: #93b7ea; --gold-2: #accdff; --ink: #edf3fd; --muted: #9aabc4; --dim: #71829d;
  --green: #5fb27b; --red: #d0665b; --yellow: #e2b856; --blue: #6ea8d8; --violet: #a583d6;
  --radius: 12px;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --serif: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
[hidden] { display: none !important; }
body { min-height: 100vh; background: var(--bg); color: var(--ink); font: 14px/1.5 var(--sans); }
button, input, textarea, select { font: inherit; color: inherit; }
button { cursor: pointer; }
h1, h2, h3 { font-family: var(--serif); font-weight: 700; letter-spacing: -.02em; }
h2 { font-size: 16px; color: var(--gold-2); }
.muted { color: var(--muted); }
.dim { color: var(--dim); }
code { background: var(--panel-2); padding: 1px 6px; border-radius: 6px; font-size: 12px; }

/* ---------- поля и кнопки ---------- */
input, textarea, select {
  background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; width: 100%;
  outline: none; transition: border-color .15s, box-shadow .15s;
}
input:focus, textarea:focus, select:focus { border-color: var(--gold); box-shadow: 0 0 0 3px rgba(147,183,234,.2); }
textarea { min-height: 96px; resize: vertical; }
select { appearance: none; padding-right: 28px; background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%); background-position: calc(100% - 15px) 55%, calc(100% - 10px) 55%; background-size: 5px 5px; background-repeat: no-repeat; }
label.lbl { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--line-2); background: var(--panel-2); border-radius: 8px; padding: 8px 14px; font-weight: 600; white-space: nowrap; transition: background .15s, border-color .15s, transform .05s; }
.btn:hover { background: var(--panel-3); border-color: var(--gold); }
.btn:active { transform: translateY(1px); }
.btn.primary { background: linear-gradient(135deg, #edf4ff, #93b7ea); color: #182942; border-color: var(--gold); }
.btn.primary:hover { filter: brightness(1.08); }
.btn.danger { background: rgba(208,102,91,.14); color: #f0a49b; border-color: rgba(208,102,91,.5); }
.btn.danger:hover { background: var(--red); color: #fff; }
.btn.sm { padding: 5px 10px; font-size: 12.5px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.switch { position: relative; width: 38px; height: 22px; flex: 0 0 auto; display: inline-block; }
.switch input { opacity: 0; width: 0; height: 0; position: absolute; }
.switch span { position: absolute; inset: 0; background: var(--panel-3); border: 1px solid var(--line-2); border-radius: 999px; transition: .15s; cursor: pointer; }
.switch span::after { content: ""; position: absolute; width: 16px; height: 16px; left: 2px; top: 2px; border-radius: 50%; background: var(--muted); transition: .15s; }
.switch input:checked + span { background: rgba(95,178,123,.25); border-color: var(--green); }
.switch input:checked + span::after { transform: translateX(16px); background: var(--green); }
.switch input:focus-visible + span { box-shadow: 0 0 0 3px rgba(147,183,234,.35); }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; }
.pill { display: inline-block; border-radius: 999px; padding: 1px 9px; font-size: 12px; border: 1px solid var(--line-2); color: var(--muted); white-space: nowrap; }
.pill.green { color: #8fd6a4; border-color: rgba(95,178,123,.6); }
.pill.red { color: #f0a49b; border-color: rgba(208,102,91,.6); }
.pill.yellow { color: #f0d08a; border-color: rgba(226,184,86,.6); }
.pill.blue { color: #9cc8ee; border-color: rgba(110,168,216,.6); }

/* ---------- вход ---------- */
.login { display: grid; place-items: center; min-height: 100vh; padding: 20px; background: radial-gradient(circle at 95% 0%, #263c5b 0, transparent 32%), var(--bg); }
.login-card { width: min(430px, 100%); padding: 34px; border: 1px solid var(--line-2); border-radius: 22px; background: linear-gradient(145deg, #1d2b40, #121c2e); box-shadow: 0 35px 80px #0007; }
.login-card h1 { font-size: 28px; margin: 22px 0 6px; }
.login-card form { display: grid; gap: 14px; margin-top: 18px; }
.logo { display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 800; }
.mark { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 auto; border-radius: 11px; background: linear-gradient(130deg, #f2f7ff, #83a8db); color: #1b2b42; font-size: 23px; }
.err { color: #ff9ba9; min-height: 20px; font-size: 13px; }
.eyebrow { color: var(--dim); font-size: 11px; letter-spacing: .14em; text-transform: uppercase; }

/* ---------- каркас ---------- */
.app { display: grid; grid-template-columns: 236px minmax(0, 1fr); min-height: 100vh; }
.side { background: var(--side); border-right: 1px solid var(--line); padding: 20px 12px; position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: 4px; }
.brand { padding: 4px 10px 18px; }
.brand { display: flex; align-items: center; gap: 10px; }
.brand b { font-size: 17px; color: var(--ink); display: block; line-height: 1.1; }
.brand small { color: var(--dim); font-size: 12px; }
.nav { display: flex; flex-direction: column; gap: 3px; }
.nav button { display: flex; align-items: center; gap: 11px; width: 100%; text-align: left; background: none; border: 0; padding: 10px 12px; border-radius: 9px; color: var(--muted); font-weight: 600; }
.nav button svg { width: 18px; height: 18px; flex: 0 0 auto; }
.nav button:hover { background: var(--panel); color: var(--ink); }
.nav button[aria-current="true"] { background: var(--panel-3); color: var(--gold-2); box-shadow: inset 3px 0 0 var(--gold); }
.nav .badge { margin-left: auto; background: var(--red); color: #fff; border-radius: 999px; font-size: 11px; padding: 0 7px; min-width: 20px; text-align: center; line-height: 18px; }
.side .spacer { flex: 1; }
.side .foot { display: flex; flex-direction: column; gap: 8px; padding: 10px; border-top: 1px solid var(--line); margin-top: 8px; font-size: 12px; color: var(--dim); }
.main { padding: 22px 28px 60px; min-width: 0; max-width: 1400px; }
.top { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; justify-content: space-between; margin-bottom: 18px; }
.top h1 { font-size: 24px; }
.top .tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.auto { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12.5px; }
.seg { display: inline-flex; background: var(--panel); border: 1px solid var(--line); border-radius: 9px; padding: 3px; }
.seg button { background: none; border: 0; padding: 5px 12px; border-radius: 7px; color: var(--muted); font-weight: 600; }
.seg button[aria-pressed="true"] { background: var(--panel-3); color: var(--gold-2); }

/* ---------- дашборд ---------- */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 14px; }
.kpi { background: linear-gradient(160deg, var(--panel), var(--panel-2)); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; }
.kpi span { color: var(--muted); font-size: 12.5px; }
.kpi b { display: block; font-family: var(--serif); font-size: 25px; letter-spacing: -.03em; color: var(--gold-2); margin: 2px 0; }
.kpi small { font-size: 12px; color: var(--dim); }
.up { color: var(--green); } .down { color: var(--red); } .flat { color: var(--dim); }
.grid { display: grid; gap: 14px; grid-template-columns: repeat(12, minmax(0, 1fr)); }
.col-8 { grid-column: span 8; } .col-6 { grid-column: span 6; } .col-4 { grid-column: span 4; } .col-12 { grid-column: span 12; }
.card h2 { margin-bottom: 2px; }
.card .sub { color: var(--dim); font-size: 12.5px; margin-bottom: 10px; }
.chart { position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart .tick { fill: var(--dim); font-size: 11px; }
.chart .grid-line { stroke: var(--line); stroke-width: 1; }
.tip { position: absolute; pointer-events: none; background: #070c15; border: 1px solid var(--line-2); border-radius: 8px; padding: 6px 10px; font-size: 12px; white-space: nowrap; transform: translate(-50%, -110%); z-index: 5; box-shadow: 0 6px 18px rgba(0,0,0,.5); }
.tip b { color: var(--gold-2); display: block; }
.empty { color: var(--dim); text-align: center; padding: 34px 10px; }
.donut-wrap { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; justify-content: center; }
.donut-wrap svg { width: 150px; height: 150px; flex: 0 0 auto; }
.legend { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 8px; }
.legend em { font-style: normal; color: var(--muted); margin-left: 8px; }
.hbar { margin-bottom: 11px; }
.hbar .t { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; margin-bottom: 4px; }
.hbar .t span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar .t span:last-child { color: var(--muted); white-space: nowrap; }
.hbar .bar { height: 8px; border-radius: 99px; background: var(--panel-3); overflow: hidden; }
.hbar .bar i { display: block; height: 100%; border-radius: 99px; background: linear-gradient(90deg, var(--gold), var(--gold-2)); }
.todo { display: flex; flex-direction: column; gap: 8px; }
.todo button { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.todo button:hover { border-color: var(--gold); }
.todo .n { font-family: var(--serif); font-size: 20px; min-width: 30px; color: var(--gold-2); }
.todo .ok { color: var(--green); padding: 8px 2px; }

/* ---------- таблицы и панели инструментов ---------- */
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
.toolbar .search { flex: 1 1 240px; max-width: 360px; }
.toolbar .grow { flex: 1; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 5px 12px; color: var(--muted); font-size: 13px; font-weight: 600; }
.chip:hover { border-color: var(--gold); }
.chip[aria-pressed="true"] { background: linear-gradient(135deg, #edf4ff, #93b7ea); color: #182942; border-color: var(--gold); }
.chip small { opacity: .75; margin-left: 4px; }
.table-card { padding: 0; overflow: hidden; }
.tscroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
th { position: sticky; top: 0; background: var(--panel-2); color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--gold-2); }
tbody tr:hover td { background: rgba(255,255,255,.02); }
tbody tr:last-child td { border-bottom: 0; }
td.num, th.num { text-align: right; }
td .name { font-weight: 600; }
td .sub { color: var(--dim); font-size: 12px; }
.inline-num { width: 92px; text-align: right; padding: 5px 8px; }
.inline-num.saving { border-color: var(--yellow); }
.row-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
.status { display: inline-block; padding: 1px 9px; border: 1px solid var(--line-2); border-radius: 999px; font-size: 12px; white-space: nowrap; }
.status.new, .status.preorder { color: #f0d08a; border-color: rgba(226,184,86,.6); }
.status.paid { color: #8fd6a4; border-color: rgba(95,178,123,.6); }
.status.done { color: var(--muted); }
.status.cancelled { color: #f0a49b; border-color: rgba(208,102,91,.6); }
.stars { color: var(--gold); letter-spacing: 2px; }
.reviews { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.review p { margin-top: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }
.review .meta { display: flex; justify-content: space-between; gap: 8px; color: var(--dim); font-size: 12px; margin-top: 8px; }

/* ---------- выезжающая карточка, окна, уведомления ---------- */
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 40; display: flex; justify-content: flex-end; animation: fade .15s; }
.overlay.center { justify-content: center; align-items: center; padding: 16px; }
.drawer { width: min(560px, 100%); background: var(--panel); border-left: 1px solid var(--line-2); height: 100%; overflow-y: auto; padding: 22px; animation: slide .18s; }
.modal { width: min(440px, 100%); background: var(--panel); border: 1px solid var(--line-2); border-radius: 14px; padding: 22px; animation: pop .15s; }
.modal h3 { font-size: 18px; margin-bottom: 8px; }
.modal .actions, .drawer .actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; flex-wrap: wrap; }
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.drawer-head h3 { font-size: 20px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid .full { grid-column: 1 / -1; }
.section { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 16px; }
.section h4 { font-family: var(--serif); color: var(--gold-2); margin-bottom: 8px; font-size: 15px; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; }
.line-item { display: flex; gap: 6px; margin-top: 6px; }
.line-item input { font-family: ui-monospace, Consolas, monospace; font-size: 12.5px; }
.presets { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.toasts { position: fixed; right: 18px; bottom: 18px; display: flex; flex-direction: column; gap: 8px; z-index: 60; }
.toast { background: #070c15; border: 1px solid var(--line-2); border-left: 4px solid var(--green); border-radius: 9px; padding: 10px 14px; max-width: 360px; box-shadow: 0 8px 24px rgba(0,0,0,.5); animation: pop .15s; }
.toast.error { border-left-color: var(--red); }
.kbd { border: 1px solid var(--line-2); border-radius: 5px; padding: 0 5px; font-size: 11px; color: var(--muted); }
@keyframes fade { from { opacity: 0 } }
@keyframes slide { from { transform: translateX(30px); opacity: 0 } }
@keyframes pop { from { transform: scale(.96); opacity: 0 } }
.loading { opacity: .55; pointer-events: none; }

/* ---------- адаптив ---------- */
@media (max-width: 1100px) { .col-8, .col-6, .col-4 { grid-column: span 12; } }
@media (max-width: 860px) {
  .app { grid-template-columns: 1fr; }
  .side { position: static; height: auto; flex-direction: row; align-items: center; overflow-x: auto; padding: 10px; border-right: 0; border-bottom: 1px solid var(--line); gap: 6px; }
  .brand, .side .foot, .side .spacer { display: none; }
  .nav { flex-direction: row; }
  .nav button { padding: 8px 12px; white-space: nowrap; }
  .nav button[aria-current="true"] { box-shadow: inset 0 -3px 0 var(--gold); }
  .main { padding: 16px 12px 50px; }
  table.resp, table.resp tbody, table.resp tr, table.resp td { display: block; width: 100%; }
  table.resp thead { display: none; }
  table.resp tr { padding: 10px 14px; border-bottom: 1px solid var(--line); }
  table.resp td { display: grid; grid-template-columns: 38% 1fr; gap: 8px; border: 0; padding: 4px 0; text-align: left; }
  table.resp td.num { text-align: left; }
  table.resp td::before { content: attr(data-label); color: var(--dim); font-size: 12px; }
  table.resp td.act { display: block; padding-top: 8px; }
  table.resp td.act::before { display: none; }
  .row-actions { justify-content: flex-start; }
  .form-grid { grid-template-columns: 1fr; }
}

.cellflex { display: flex; gap: 8px; align-items: center; justify-content: flex-end; }
.clip { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.todo button.hot { border-color: rgba(208,102,91,.55); }
.todo button.hot .n { color: #f0a49b; }
.status.pending { color: #f0d08a; border-color: rgba(226,184,86,.6); }
.status.paid { color: #8fd6a4; border-color: rgba(95,178,123,.6); }
.status.nostock { color: #c9b0f0; border-color: rgba(165,131,214,.7); }
.status.cancelled { color: #f0a49b; border-color: rgba(208,102,91,.6); }

</style></head><body>
<section id="login" class="login"><div class="login-card"><div class="logo"><span class="mark">✦</span>Nexus Admin</div><h1>Управление магазином</h1><p class="muted">Введите секретный ключ администратора</p><form id="loginForm"><div><label class="lbl" for="secret">Секретный ключ</label><input id="secret" type="password" autocomplete="current-password" required></div><button class="btn primary" type="submit">Войти в панель →</button><p id="loginError" class="err" role="status" aria-live="polite"></p></form></div></section>
<div class="app" id="app" hidden>
<aside class="side"><div class="brand"><span class="mark">✦</span><div><b>Nexus Admin</b><small>панель магазина</small></div></div>
<nav class="nav" id="nav">
<button type="button" data-page="dashboard"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg>Обзор</button>
<button type="button" data-page="products"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/></svg>Товары<span class="badge" id="badge-products" hidden></span></button>
<button type="button" data-page="categories"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>Категории</button>
<button type="button" data-page="customers"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>Покупатели</button>
<button type="button" data-page="orders"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 01-8 0"/></svg>Покупки<span class="badge" id="badge-orders" hidden></span></button>
</nav><div class="spacer"></div>
<div class="foot"><span id="last-update">Данные ещё не загружены</span><span><span class="kbd">/</span> — поиск, <span class="kbd">Esc</span> — закрыть окно</span><button class="btn sm" id="logout" type="button">Выйти</button></div></aside>
<main class="main"><div class="top"><h1 id="page-title">Обзор магазина</h1><div class="tools" id="page-tools"></div></div><div id="page"></div></main></div>
<div class="toasts" id="toasts" aria-live="polite"></div>
<script src="/admin.js" defer></script></body></html>'''
