"""Admin panel HTML. All data comes from authenticated /api/admin routes."""

ADMIN_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nexus — панель магазина</title>
<style>
:root {
  color-scheme: dark;
  --bg: #050506; --side: rgba(255,255,255,.035); --panel: rgba(255,255,255,.06); --panel-2: rgba(255,255,255,.08); --panel-3: rgba(255,255,255,.14);
  --line: rgba(255,255,255,.11); --line-2: rgba(255,255,255,.22);
  --gold: #f3f4f6; --gold-2: #ffffff; --ink: #f4f5f7; --muted: #b1b5bd; --dim: #80848e;
  --green: #7ccf95; --red: #e27d73; --yellow: #e6c674; --blue: #c8ccd4; --violet: #c9cbd2;
  --radius: 18px;
  --blur: blur(22px) saturate(160%);
  --glass: linear-gradient(150deg, rgba(255,255,255,.10), rgba(255,255,255,.035) 62%);
  --glass-strong: linear-gradient(150deg, rgba(74,74,80,.62), rgba(20,20,23,.78));
  --shadow: inset 0 1px 0 rgba(255,255,255,.18), inset 0 0 0 1px rgba(255,255,255,.02), 0 14px 44px rgba(0,0,0,.5);
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --serif: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
[hidden] { display: none !important; }
html { background: var(--bg); }
body { min-height: 100vh; background: transparent; color: var(--ink); font: 14px/1.5 var(--sans); position: relative; }
body::before { content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(760px 520px at 88% -8%, rgba(255,255,255,.2), transparent 64%),
    radial-gradient(640px 520px at -6% 30%, rgba(255,255,255,.13), transparent 62%),
    radial-gradient(720px 560px at 62% 112%, rgba(214,218,226,.15), transparent 64%),
    radial-gradient(420px 320px at 30% 6%, rgba(255,255,255,.09), transparent 65%),
    #050506; }
button, input, textarea, select { font: inherit; color: inherit; }
button { cursor: pointer; }
h1, h2, h3 { font-family: var(--serif); font-weight: 700; letter-spacing: -.02em; }
h2 { font-size: 16px; color: var(--gold-2); }
.muted { color: var(--muted); }
.dim { color: var(--dim); }
code { background: rgba(255,255,255,.1); padding: 1px 6px; border-radius: 6px; font-size: 12px; }
::selection { background: rgba(255,255,255,.28); }
/* Hide bars, not scrolling; keep wheel, touch and keyboard scrolling. */
* { scrollbar-width: none; }
*::-webkit-scrollbar { display: none; width: 0; height: 0; }
input[type="number"] { appearance: textfield; -moz-appearance: textfield; }
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }

/* ---------- поля и кнопки ---------- */
input, textarea, select {
  background: rgba(255,255,255,.06); border: 1px solid var(--line); border-radius: 12px; padding: 9px 12px; width: 100%;
  outline: none; transition: border-color .15s, box-shadow .15s, background .15s; box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
}
input::placeholder, textarea::placeholder { color: var(--dim); }
input:focus, textarea:focus, select:focus { border-color: rgba(255,255,255,.6); background: rgba(255,255,255,.09); box-shadow: 0 0 0 3px rgba(255,255,255,.12); }
textarea { min-height: 96px; resize: vertical; }
select { appearance: none; padding-right: 30px; background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%); background-position: calc(100% - 16px) 55%, calc(100% - 11px) 55%; background-size: 5px 5px; background-repeat: no-repeat; }
select option { background: #16161a; color: #f4f5f7; }
label.lbl { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--line-2); background: linear-gradient(150deg, rgba(255,255,255,.12), rgba(255,255,255,.05)); border-radius: 12px; padding: 8px 15px; font-weight: 600; white-space: nowrap; box-shadow: inset 0 1px 0 rgba(255,255,255,.16); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); transition: background .15s, border-color .15s, transform .05s, box-shadow .15s; }
.btn:hover { background: linear-gradient(150deg, rgba(255,255,255,.2), rgba(255,255,255,.08)); border-color: rgba(255,255,255,.5); }
.btn:active { transform: translateY(1px); }
.btn.primary { background: linear-gradient(135deg, #ffffff, #c4c7ce); color: #0b0b0d; border-color: rgba(255,255,255,.9); box-shadow: inset 0 1px 0 #fff, 0 0 26px rgba(255,255,255,.22); }
.btn.primary:hover { filter: brightness(1.05); box-shadow: inset 0 1px 0 #fff, 0 0 34px rgba(255,255,255,.32); }
.btn.danger { background: rgba(226,125,115,.13); color: #f3aaa2; border-color: rgba(226,125,115,.5); }
.btn.danger:hover { background: var(--red); color: #fff; }
.btn.sm { padding: 5px 11px; font-size: 12.5px; border-radius: 10px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.switch { position: relative; width: 40px; height: 23px; flex: 0 0 auto; display: inline-block; }
.switch input { opacity: 0; width: 0; height: 0; position: absolute; }
.switch span { position: absolute; inset: 0; background: rgba(255,255,255,.08); border: 1px solid var(--line-2); border-radius: 999px; transition: .15s; cursor: pointer; }
.switch span::after { content: ""; position: absolute; width: 17px; height: 17px; left: 2px; top: 2px; border-radius: 50%; background: var(--muted); transition: .15s; }
.switch input:checked + span { background: rgba(255,255,255,.28); border-color: rgba(255,255,255,.7); }
.switch input:checked + span::after { transform: translateX(17px); background: #fff; box-shadow: 0 0 10px rgba(255,255,255,.6); }
.switch input:focus-visible + span { box-shadow: 0 0 0 3px rgba(255,255,255,.3); }
.card { background: var(--glass); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; box-shadow: var(--shadow); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur); }
.pill { display: inline-block; border-radius: 999px; padding: 1px 9px; font-size: 12px; border: 1px solid var(--line-2); color: var(--muted); white-space: nowrap; }
.pill.green { color: #a2e2b6; border-color: rgba(124,207,149,.55); background: rgba(124,207,149,.1); }
.pill.red { color: #f3aaa2; border-color: rgba(226,125,115,.55); background: rgba(226,125,115,.1); }
.pill.yellow { color: #f1d798; border-color: rgba(230,198,116,.55); background: rgba(230,198,116,.1); }
.pill.blue { color: #e6e8ec; border-color: rgba(255,255,255,.35); background: rgba(255,255,255,.08); }

/* ---------- вход ---------- */
.login { display: grid; place-items: center; min-height: 100vh; padding: 20px; }
.login-card { width: min(430px, 100%); padding: 36px; border: 1px solid var(--line-2); border-radius: 28px; background: var(--glass-strong); box-shadow: var(--shadow), 0 40px 90px rgba(0,0,0,.6), 0 0 80px rgba(255,255,255,.05); backdrop-filter: blur(30px) saturate(160%); -webkit-backdrop-filter: blur(30px) saturate(160%); }
.login-card h1 { font-size: 28px; margin: 22px 0 6px; }
.login-card form { display: grid; gap: 14px; margin-top: 18px; }
.logo { display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 800; }
.mark { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 auto; border-radius: 12px; background: linear-gradient(135deg, #ffffff, #a9adb6); color: #0b0b0d; font-size: 22px; box-shadow: inset 0 1px 0 #fff, 0 0 26px rgba(255,255,255,.28); }
.err { color: #ff9ba9; min-height: 20px; font-size: 13px; }
.eyebrow { color: var(--dim); font-size: 11px; letter-spacing: .14em; text-transform: uppercase; }

/* ---------- каркас ---------- */
.app { display: grid; grid-template-columns: 244px minmax(0, 1fr); min-height: 100vh; }
.side { background: linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.025)); border-right: 1px solid var(--line); box-shadow: inset -1px 0 0 rgba(255,255,255,.03); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur); padding: 20px 12px; position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: 4px; }
.brand { padding: 4px 10px 18px; display: flex; align-items: center; gap: 10px; }
.brand b { font-size: 17px; color: var(--ink); display: block; line-height: 1.1; }
.brand small { color: var(--dim); font-size: 12px; }
.nav { display: flex; flex-direction: column; gap: 4px; }
.nav button { display: flex; align-items: center; gap: 11px; width: 100%; text-align: left; background: none; border: 1px solid transparent; padding: 10px 13px; border-radius: 13px; color: var(--muted); font-weight: 600; transition: background .15s, color .15s; }
.nav button svg { width: 18px; height: 18px; flex: 0 0 auto; }
.nav button:hover { background: rgba(255,255,255,.06); color: var(--ink); }
.nav button[aria-current="true"] { background: linear-gradient(150deg, rgba(255,255,255,.17), rgba(255,255,255,.07)); border-color: rgba(255,255,255,.2); color: #fff; box-shadow: inset 0 1px 0 rgba(255,255,255,.2), 0 0 26px rgba(255,255,255,.07); }
.nav .badge { margin-left: auto; background: #fff; color: #0b0b0d; border-radius: 999px; font-size: 11px; font-weight: 700; padding: 0 7px; min-width: 20px; text-align: center; line-height: 18px; box-shadow: 0 0 12px rgba(255,255,255,.35); }
.side .spacer { flex: 1; }
.side .foot { display: flex; flex-direction: column; gap: 8px; padding: 10px; border-top: 1px solid var(--line); margin-top: 8px; font-size: 12px; color: var(--dim); }
.main { padding: 24px 30px 60px; min-width: 0; max-width: 1440px; }
.top { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; justify-content: space-between; margin-bottom: 20px; }
.top h1 { font-size: 26px; }
.top .tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.auto { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12.5px; }
.seg { display: inline-flex; background: rgba(255,255,255,.05); border: 1px solid var(--line); border-radius: 13px; padding: 3px; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: inset 0 1px 0 rgba(255,255,255,.08); }
.seg button { background: none; border: 0; padding: 5px 13px; border-radius: 10px; color: var(--muted); font-weight: 600; transition: background .15s, color .15s; }
.seg button:hover { color: #fff; }
.seg button[aria-pressed="true"] { background: linear-gradient(150deg, rgba(255,255,255,.26), rgba(255,255,255,.12)); color: #fff; box-shadow: inset 0 1px 0 rgba(255,255,255,.3), 0 0 16px rgba(255,255,255,.1); }

/* ---------- дашборд ---------- */
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }
.kpi { position: relative; overflow: hidden; background: var(--glass); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; box-shadow: var(--shadow); backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur); }
.kpi::after { content: ""; position: absolute; width: 150px; height: 150px; right: -50px; top: -70px; background: radial-gradient(circle, rgba(255,255,255,.14), transparent 70%); pointer-events: none; }
.khead { display: flex; align-items: center; gap: 11px; }
.ico { display: grid; place-items: center; width: 40px; height: 40px; flex: 0 0 auto; border-radius: 13px; color: #fff; background: linear-gradient(150deg, rgba(255,255,255,.2), rgba(255,255,255,.06)); border: 1px solid rgba(255,255,255,.2); box-shadow: inset 0 1px 0 rgba(255,255,255,.28), 0 0 20px rgba(255,255,255,.08); }
.ico svg { width: 19px; height: 19px; }
.klabel { color: var(--muted); font-size: 13px; }
.kpi b { display: block; font-family: var(--serif); font-size: 29px; letter-spacing: -.03em; color: #fff; margin: 12px 0 8px; text-shadow: 0 0 24px rgba(255,255,255,.25); }
.kfoot { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; }
.kdelta { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; min-width: 0; }
.kdelta small { font-size: 11.5px; color: var(--dim); }
.spark { width: 104px; height: 38px; flex: 0 0 auto; overflow: visible; filter: drop-shadow(0 0 5px rgba(255,255,255,.4)); }
.dchip { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; border: 1px solid transparent; }
.dchip.up { color: #a2e2b6; background: rgba(124,207,149,.12); border-color: rgba(124,207,149,.3); }
.dchip.down { color: #f3aaa2; background: rgba(226,125,115,.12); border-color: rgba(226,125,115,.3); }
.dchip.flat { color: var(--muted); background: rgba(255,255,255,.07); border-color: var(--line); }
.up { color: var(--green); } .down { color: var(--red); } .flat { color: var(--dim); }
.grid { display: grid; gap: 14px; grid-template-columns: repeat(12, minmax(0, 1fr)); }
.col-8 { grid-column: span 8; } .col-6 { grid-column: span 6; } .col-4 { grid-column: span 4; } .col-12 { grid-column: span 12; }
.card h2 { margin-bottom: 2px; }
.card.flexcol { display: flex; flex-direction: column; }
.card.flexcol .mstats { margin-top: auto; }
.card.flexcol .chart { margin-bottom: 14px; }
.card .sub { color: var(--dim); font-size: 12.5px; margin-bottom: 12px; }
.chart { position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart .tick { fill: var(--dim); font-size: 11px; }
.chart .grid-line { stroke: rgba(255,255,255,.08); stroke-width: 1; }
.chart path.glow { filter: drop-shadow(0 0 7px rgba(255,255,255,.55)); }
.tip { position: absolute; pointer-events: none; background: rgba(28,28,32,.72); backdrop-filter: blur(16px) saturate(150%); -webkit-backdrop-filter: blur(16px) saturate(150%); border: 1px solid rgba(255,255,255,.25); border-radius: 12px; padding: 7px 12px; font-size: 12px; white-space: nowrap; transform: translate(-50%, -115%); z-index: 5; box-shadow: inset 0 1px 0 rgba(255,255,255,.2), 0 10px 28px rgba(0,0,0,.55); }
.tip b { color: #fff; display: block; }
.empty { color: var(--dim); text-align: center; padding: 34px 10px; }
.mstats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.mstats div { display: flex; flex-direction: column; }
.mstats span { color: var(--dim); font-size: 12px; }
.mstats b { font-family: var(--serif); font-size: 19px; color: #fff; }
.mstats small { color: var(--dim); font-size: 12px; }
.donut-wrap { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; justify-content: center; }
.donut-wrap svg { width: 150px; height: 150px; flex: 0 0 auto; filter: drop-shadow(0 0 10px rgba(255,255,255,.12)); }
.legend { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
.legend em { font-style: normal; color: var(--muted); margin-left: 8px; }
.hbar { margin-bottom: 12px; }
.hbar .t { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; margin-bottom: 5px; }
.hbar .t span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar .t span:last-child { color: var(--muted); white-space: nowrap; }
.hbar .bar, .prow .bar { height: 7px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; }
.hbar .bar i, .prow .bar i { display: block; height: 100%; border-radius: 99px; background: linear-gradient(90deg, rgba(255,255,255,.45), #fff); box-shadow: 0 0 12px rgba(255,255,255,.5); }
.rlist, .plist { display: flex; flex-direction: column; }
.rrow { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left; background: none; border: 0; border-bottom: 1px solid var(--line); padding: 10px 4px; border-radius: 10px; transition: background .15s; }
.rrow:last-child { border-bottom: 0; }
.rrow:hover { background: rgba(255,255,255,.06); }
.ava { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 auto; border-radius: 50%; font-weight: 700; color: #fff; background: linear-gradient(150deg, rgba(255,255,255,.28), rgba(255,255,255,.08)); border: 1px solid rgba(255,255,255,.25); box-shadow: inset 0 1px 0 rgba(255,255,255,.3); }
.rrow .who { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.rrow .who b, .rrow .who small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rrow .who small { color: var(--dim); font-size: 12px; }
.rrow .amt { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex: 0 0 auto; }
.rrow .amt .status { font-size: 11px; padding: 0 8px; }
.prow { display: flex; align-items: flex-start; gap: 12px; padding: 8px 0; }
.rank { display: grid; place-items: center; width: 26px; height: 26px; flex: 0 0 auto; border-radius: 9px; font-size: 12px; font-weight: 700; color: #fff; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.18); margin-top: 1px; }
.pinfo { flex: 1; min-width: 0; }
.pinfo .pt { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 5px; }
.pinfo .pt b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.pinfo .pt span { color: var(--muted); white-space: nowrap; }
.pinfo small { color: var(--dim); font-size: 12px; display: block; margin-top: 3px; }
.todo { display: flex; flex-direction: column; gap: 8px; }
.todo button { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: rgba(255,255,255,.05); border: 1px solid var(--line); border-radius: 13px; padding: 10px 12px; transition: background .15s, border-color .15s; }
.todo button:hover { border-color: rgba(255,255,255,.45); background: rgba(255,255,255,.09); }
.todo .n { font-family: var(--serif); font-size: 20px; min-width: 30px; color: #fff; }
.todo .ok { color: #a2e2b6; padding: 8px 2px; }

/* ---------- таблицы и панели инструментов ---------- */
.toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
.toolbar .search { flex: 1 1 240px; max-width: 360px; }
.toolbar .grow { flex: 1; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: rgba(255,255,255,.05); border: 1px solid var(--line); border-radius: 999px; padding: 5px 13px; color: var(--muted); font-size: 13px; font-weight: 600; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); transition: border-color .15s, color .15s; }
.chip:hover { border-color: rgba(255,255,255,.5); color: #fff; }
.chip[aria-pressed="true"] { background: linear-gradient(135deg, #ffffff, #c4c7ce); color: #0b0b0d; border-color: #fff; box-shadow: 0 0 20px rgba(255,255,255,.2); }
.chip small { opacity: .75; margin-left: 4px; }
.table-card { padding: 0; overflow: hidden; }
.tscroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 11px 15px; border-bottom: 1px solid var(--line); vertical-align: middle; }
th { position: sticky; top: 0; background: rgba(255,255,255,.05); color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: #fff; }
tbody tr:hover td { background: rgba(255,255,255,.045); }
tbody tr:last-child td { border-bottom: 0; }
td.num, th.num { text-align: right; }
td .name { font-weight: 600; }
td .sub { color: var(--dim); font-size: 12px; }
.inline-num { width: 92px; text-align: right; padding: 5px 8px; }
.inline-num.saving { border-color: var(--yellow); }
.row-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
.status { display: inline-block; padding: 1px 9px; border: 1px solid var(--line-2); border-radius: 999px; font-size: 12px; white-space: nowrap; background: rgba(255,255,255,.05); }
.status.new, .status.preorder, .status.pending { color: #f1d798; border-color: rgba(230,198,116,.5); background: rgba(230,198,116,.1); }
.status.paid { color: #a2e2b6; border-color: rgba(124,207,149,.5); background: rgba(124,207,149,.1); }
.status.done { color: var(--muted); }
.status.cancelled { color: #f3aaa2; border-color: rgba(226,125,115,.5); background: rgba(226,125,115,.1); }
.status.nostock { color: #f2f3f5; border-color: rgba(255,255,255,.45); background: rgba(255,255,255,.12); }
.stars { color: #fff; letter-spacing: 2px; }
.reviews { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.review p { margin-top: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }
.review .meta { display: flex; justify-content: space-between; gap: 8px; color: var(--dim); font-size: 12px; margin-top: 8px; }

/* ---------- выезжающая карточка, окна, уведомления ---------- */
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); z-index: 40; display: flex; justify-content: flex-end; animation: fade .15s; }
.overlay.center { justify-content: center; align-items: center; padding: 16px; }
.drawer { width: min(560px, 100%); background: var(--glass-strong); border-left: 1px solid var(--line-2); box-shadow: inset 1px 0 0 rgba(255,255,255,.1), -30px 0 80px rgba(0,0,0,.5); backdrop-filter: blur(30px) saturate(160%); -webkit-backdrop-filter: blur(30px) saturate(160%); height: 100%; overflow-y: auto; padding: 24px; animation: slide .18s; }
.modal { width: min(440px, 100%); background: var(--glass-strong); border: 1px solid var(--line-2); border-radius: 22px; box-shadow: var(--shadow), 0 30px 80px rgba(0,0,0,.6); backdrop-filter: blur(30px) saturate(160%); -webkit-backdrop-filter: blur(30px) saturate(160%); padding: 24px; animation: pop .15s; }
.modal h3 { font-size: 18px; margin-bottom: 8px; }
.modal .actions, .drawer .actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; flex-wrap: wrap; }
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.drawer-head h3 { font-size: 20px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid .full { grid-column: 1 / -1; }
.section { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 16px; }
.section h4 { font-family: var(--serif); color: #fff; margin-bottom: 8px; font-size: 15px; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; }
.line-item { display: flex; gap: 6px; margin-top: 6px; }
.line-item input { font-family: ui-monospace, Consolas, monospace; font-size: 12.5px; }
.presets { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.toasts { position: fixed; right: 18px; bottom: 18px; display: flex; flex-direction: column; gap: 8px; z-index: 60; }
.toast { background: rgba(28,28,32,.7); backdrop-filter: blur(18px) saturate(150%); -webkit-backdrop-filter: blur(18px) saturate(150%); border: 1px solid rgba(255,255,255,.22); border-left: 4px solid #fff; border-radius: 14px; padding: 11px 15px; max-width: 360px; box-shadow: inset 0 1px 0 rgba(255,255,255,.16), 0 12px 32px rgba(0,0,0,.55); animation: pop .15s; }
.toast.error { border-left-color: var(--red); }
.kbd { border: 1px solid var(--line-2); border-radius: 5px; padding: 0 5px; font-size: 11px; color: var(--muted); background: rgba(255,255,255,.05); }
@keyframes fade { from { opacity: 0 } }
@keyframes slide { from { transform: translateX(30px); opacity: 0 } }
@keyframes pop { from { transform: scale(.96); opacity: 0 } }
.loading { opacity: .55; pointer-events: none; }

/* ---------- адаптив ---------- */
@media (max-width: 1100px) { .col-8, .col-6, .col-4 { grid-column: span 12; } .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 860px) {
  .app { grid-template-columns: 1fr; }
  .side { position: static; height: auto; flex-direction: row; align-items: center; overflow-x: auto; padding: 10px; border-right: 0; border-bottom: 1px solid var(--line); gap: 6px; }
  .brand, .side .foot, .side .spacer { display: none; }
  .nav { flex-direction: row; }
  .nav button { padding: 8px 12px; white-space: nowrap; }
  .main { padding: 16px 12px 50px; }
  .kpis { grid-template-columns: 1fr; }
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
.todo button.hot { border-color: rgba(226,125,115,.55); background: rgba(226,125,115,.08); }
.todo button.hot .n { color: #f3aaa2; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .card, .kpi, .side, .modal, .drawer, .login-card { background: rgba(28,28,32,.92); }
}


/* Premium emoji library — same monochrome glass surfaces. */
.emoji-thumb{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;flex:0 0 26px;vertical-align:middle;font-size:22px;border-radius:6px}
.emoji-thumb img.repaint{filter:brightness(0) invert(1)}
.emoji-thumb img{width:100%;height:100%;object-fit:contain}
.emoji-thumb.no-preview{border:1px dashed rgba(255,255,255,.45)}
.emoji-category-name{display:inline-flex;align-items:center;gap:10px}
.telegram-product-preview{background:#182633;border:1px solid rgba(255,255,255,.15);border-radius:14px;padding:20px;line-height:1.5;margin-top:12px;overflow-wrap:anywhere;font-size:16px}
.telegram-product-preview>div{display:flex;gap:8px;align-items:flex-start;white-space:pre-wrap}
.telegram-product-preview .preview-title{margin-bottom:20px}.telegram-product-preview .preview-description{margin-bottom:20px}

/* Centered product editor. Theme and glass surfaces are unchanged. */
.product-dialog{display:flex;width:min(700px,100%);height:min(920px,calc(100dvh - 40px));border:1px solid var(--line-2);border-radius:24px;overflow:hidden;box-shadow:var(--shadow),0 30px 90px rgba(0,0,0,.6);transition:width .15s;background:rgba(17,17,20,.85)}
.product-main{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.product-footer{display:flex;gap:12px;justify-content:flex-end;flex-wrap:wrap;flex:0 0 auto;padding:12px 24px;border-top:1px solid var(--line);background:rgba(26,26,30,.9)}
.product-footer .btn{min-height:44px}
.product-dialog .product-form{width:auto;min-width:0;min-height:0;flex:1;border:0;height:auto;box-shadow:none;animation:pop .15s}
.premium-inline{display:inline-block;width:1.5em;height:1.5em;vertical-align:middle;line-height:1;margin:0 2px;user-select:all}
.premium-inline .emoji-thumb{width:100%;height:100%;font-size:1em;display:inline-flex}
.premium-text{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0;flex:1}
@media(max-width:760px){.product-dialog{height:calc(100dvh - 24px);border-radius:18px}.product-form{padding:18px}.product-footer{padding:10px 18px}}
@media(prefers-reduced-motion:reduce){.product-dialog{transition:none}}
.product-form textarea[name="description"]{min-height:128px;max-height:340px;font-size:16px;line-height:1.6}
</style></head><body>
<section id="login" class="login"><div class="login-card"><div class="logo"><span class="mark"><svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z"/></svg></span>Nexus Admin</div><h1>Управление магазином</h1><p class="muted">Введите секретный ключ администратора</p><form id="loginForm"><div><label class="lbl" for="secret">Секретный ключ</label><input id="secret" type="password" autocomplete="current-password" required></div><button class="btn primary" type="submit">Войти в панель →</button><p id="loginError" class="err" role="status" aria-live="polite"></p></form></div></section>
<div class="app" id="app" hidden>
<aside class="side"><div class="brand"><span class="mark"><svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z"/></svg></span><div><b>Nexus Admin</b><small>панель магазина</small></div></div>
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
