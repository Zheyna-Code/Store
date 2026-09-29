"use strict";
/* ==================================================================== утилиты == */
const $ = id => document.getElementById(id);
const TOKEN_KEY = "nexus_admin_token";
const NS = "http://www.w3.org/2000/svg";
let token = localStorage.getItem(TOKEN_KEY) || "";
const LOW_STOCK = 2;
const state = {
  page: "dashboard", days: 30, categories: [], products: [], customers: [], orders: [], dashboard: null, analytics: null,
  productSearch: "", productCategory: "", productFilter: "all",
  orderSearch: "", orderStatus: "", customerSearch: "", customerSort: "seen", autoRefresh: true,
};

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node && key !== "list") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}
function s(tag, attrs, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}
const num = v => Number(v) || 0;
const money = v => num(v).toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 2 }) + " ₽";
const plural = (n, a, b, c) => { const m = Math.abs(n) % 100, k = m % 10; return m > 10 && m < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; };
const short = v => v >= 1e6 ? (v / 1e6).toFixed(1).replace(".0", "") + "М" : v >= 1000 ? (v / 1000).toFixed(v % 1000 ? 1 : 0).replace(".0", "") + "к" : String(Math.round(v * 10) / 10);
const lower = v => String(v ?? "").toLocaleLowerCase("ru-RU");
const dayLabel = iso => { const [, m, d] = iso.split("-"); return `${d}.${m}`; };
const fmtDate = value => {
  const date = new Date(value);
  return isNaN(date) ? "" : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const STATUS = { paid: "оплачен", pending: "ждёт оплаты", cancelled: "отменён", paid_no_stock: "оплачен, нет товара" };
const STATUS_COLOR = { paid: "#ffffff", pending: "#b4b8c1", cancelled: "#6b6f79", paid_no_stock: "#8f939d" };
const clientName = o => o.username ? "@" + o.username : (o.first_name || "—");

/* ================================================================ уведомления == */
function toast(text, kind) {
  const node = h("div", { class: "toast" + (kind === "error" ? " error" : ""), role: "status" }, text);
  $("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 6500 : 3200);
}

/* ============================================================== окна и панели == */
let closeOverlay = null;
function openOverlay(content, { center = false, onClose } = {}) {
  closeTopOverlay();
  const overlay = h("div", { class: "overlay" + (center ? " center" : ""), onmousedown: event => { if (event.target === overlay) closeTopOverlay(); } }, content);
  document.body.append(overlay);
  closeOverlay = () => { overlay.remove(); closeOverlay = null; if (onClose) onClose(); };
  const first = overlay.querySelector("input, textarea, select");
  if (first) first.focus();
  return closeTopOverlay;
}
function closeTopOverlay() { if (closeOverlay) closeOverlay(); }

function confirmBox(title, message, okLabel = "Подтвердить", danger = false) {
  return new Promise(resolve => {
    let answered = false;
    const done = value => { if (!answered) { answered = true; resolve(value); } closeTopOverlay(); };
    const box = h("div", { class: "modal", role: "dialog", "aria-modal": "true" },
      h("h3", {}, title), h("p", { class: "muted" }, message),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: () => done(false) }, "Отмена"),
        h("button", { class: "btn " + (danger ? "danger" : "primary"), type: "button", onclick: () => done(true) }, okLabel)));
    openOverlay(box, { center: true, onClose: () => { if (!answered) { answered = true; resolve(false); } } });
    box.querySelector(".actions button:last-child").focus();
  });
}


/* ==================================================================== запросы == */
async function api(path, options = {}) {
  const response = await fetch("/api/admin" + path, {
    method: options.method || "GET",
    headers: Object.assign({ "X-Admin-Token": token }, options.body ? { "Content-Type": "application/json" } : {}),
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });
  let data = null;
  try { data = await response.json(); } catch { throw Object.assign(new Error("Сервер вернул некорректный ответ"), { status: response.status }); }
  if (response.status === 401) { logout("Сессия закончилась, введи ключ заново."); throw Object.assign(new Error("Войдите в панель заново"), { status: 401 }); }
  if (!response.ok) throw Object.assign(new Error((data && data.error) || `Ошибка ${response.status}`), { status: response.status });
  return data;
}

async function loadAll({ silent = false } = {}) {
  const tz = -new Date().getTimezoneOffset();
  const names = ["dashboard", "categories", "products", "customers", "orders", "analytics"];
  const results = await Promise.allSettled([
    api("/dashboard"), api("/categories"), api("/products"), api("/customers"), api("/orders"), api(`/analytics?days=${state.days}&tz=${tz}`),
  ]);
  const unauthorized = results.find(r => r.status === "rejected" && r.reason.status === 401);
  if (unauthorized) throw unauthorized.reason;
  const failed = [];
  results.forEach((result, index) => {
    if (result.status === "fulfilled") state[names[index]] = result.value;
    else if (names[index] !== "analytics") failed.push(result.reason);
    else state.analytics = null; // старый сервер без /analytics — графики скрыты, остальное работает
  });
  if (!state.dashboard) throw failed[0] || new Error("Не удалось загрузить данные.");
  $("last-update").textContent = "Обновлено: " + new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  updateBadges();
  render();
  if (!silent && failed.length) toast("Часть данных не загрузилась: " + failed[0].message, "error");
}

/** Выполняет действие, показывает уведомление и обновляет данные. */
async function act(request, success) {
  try {
    const result = await request();
    if (success) toast(success);
    await loadAll({ silent: true });
    return result || true;
  } catch (error) {
    if (error.status !== 401) toast(error.message, "error");
    return null;
  }
}

/* ==================================================================== вход == */
async function login(event) {
  event.preventDefault();
  $("loginError").textContent = "";
  try {
    const response = await fetch("/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret: $("secret").value }) });
    const data = await response.json();
    if (!response.ok || !data.token) { $("loginError").textContent = data.error || "Неверный ключ"; return; }
    token = data.token;
    localStorage.setItem(TOKEN_KEY, token);
    await start();
  } catch (error) { $("loginError").textContent = error.message; }
}
async function start() {
  try {
    await loadAll({ silent: true });
    $("login").hidden = true; $("app").hidden = false;
    route();
  } catch (error) { if (error.status !== 401) { $("loginError").textContent = error.message; $("login").hidden = false; } }
}
function logout(message) {
  token = ""; localStorage.removeItem(TOKEN_KEY);
  $("app").hidden = true; $("login").hidden = false; $("secret").value = "";
  $("loginError").textContent = typeof message === "string" ? message : "";
  closeTopOverlay();
}

/* ================================================================== графики == */
let chartUid = 0;
function niceStep(v) { const p = 10 ** Math.floor(Math.log10(v)); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; }

/** Линейный график с областью или столбцы; points = [{label, value}]. */
function timeChart(points, { type = "line", fmt = short, color = "#ffffff", integer = false, tipFmt = fmt, height = 230 } = {}) {
  const wrap = h("div", { class: "chart" });
  const W = 720, H = height, L = 46, R = 10, T = 12, B = 26;
  const max = Math.max(...points.map(p => p.value), 0);
  if (!max) { wrap.append(h("div", { class: "empty" }, "За выбранный период данных пока нет.")); return wrap; }
  const step = niceStep(Math.max(max / 4, integer ? 1 : 0.0001));
  const top = step * 4;
  const x = i => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const slot = (W - L - R) / points.length;
  const bx = i => L + i * slot + slot / 2;
  const px = type === "bar" ? bx : x;
  const y = v => T + (H - T - B) * (1 - v / top);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "График" });
  const id = "g" + (++chartUid);
  svg.append(s("defs", {}, s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
    s("stop", { offset: "0%", "stop-color": color, "stop-opacity": ".38" }), s("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0" }))));
  for (let i = 0; i <= 4; i++) {
    const v = step * i, yy = y(v);
    svg.append(s("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "grid-line" }));
    const label = s("text", { x: L - 8, y: yy + 4, "text-anchor": "end", class: "tick" }); label.textContent = short(v); svg.append(label);
  }
  const every = Math.max(1, Math.ceil(points.length / 7));
  points.forEach((p, i) => {
    if (i % every !== 0 && i !== points.length - 1) return;
    if (points.length - 1 - i < every / 2 && i !== points.length - 1) return;
    const label = s("text", { x: px(i), y: H - 6, "text-anchor": "middle", class: "tick" }); label.textContent = p.label; svg.append(label);
  });
  let marker;
  if (type === "line") {
    const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
    svg.append(s("path", { d: `${line} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`, fill: `url(#${id})` }));
    svg.append(s("path", { d: line, fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round", class: "glow" }));
    marker = s("circle", { r: 5, fill: color, stroke: "#050506", "stroke-width": 2, opacity: 0 });
  } else {
    const bw = Math.min(28, slot * 0.7);
    var bars = points.map((p, i) => {
      const bar = s("rect", { x: bx(i) - bw / 2, width: bw, y: y(p.value), height: Math.max(0, y(0) - y(p.value)), rx: 4, fill: color, opacity: .8 });
      svg.append(bar); return bar;
    });
  }
  if (marker) svg.append(marker);
  const guide = s("line", { y1: T, y2: H - B, stroke: "rgba(255,255,255,.35)", "stroke-dasharray": "3 3", opacity: 0 });
  svg.insertBefore(guide, marker || null);
  const tip = h("div", { class: "tip", hidden: true });
  const hit = s("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
  svg.append(hit);
  const leave = () => { tip.hidden = true; guide.setAttribute("opacity", 0); if (marker) marker.setAttribute("opacity", 0); if (bars) bars.forEach(b => b.setAttribute("opacity", .8)); };
  hit.addEventListener("mousemove", event => {
    const box = svg.getBoundingClientRect(); const scale = W / box.width;
    const sx = (event.clientX - box.left) * scale;
    const i = Math.max(0, Math.min(points.length - 1, type === "bar" ? Math.floor((sx - L) / slot) : Math.round(((sx - L) / (W - L - R)) * (points.length - 1))));
    const p = points[i];
    tip.replaceChildren(h("b", {}, p.title || p.label), tipFmt(p.value));
    tip.hidden = false;
    tip.style.left = (px(i) / scale) + "px"; tip.style.top = (y(p.value) / scale) + "px";
    guide.setAttribute("x1", px(i)); guide.setAttribute("x2", px(i)); guide.setAttribute("opacity", 1);
    if (marker) { marker.setAttribute("cx", px(i)); marker.setAttribute("cy", y(p.value)); marker.setAttribute("opacity", 1); }
    if (bars) bars.forEach((b, j) => b.setAttribute("opacity", j === i ? 1 : .45));
  });
  hit.addEventListener("mouseleave", leave);
  wrap.append(svg, tip);
  return wrap;
}

function donut(entries) {
  const total = entries.reduce((sum, e) => sum + e.value, 0);
  if (!total) return h("div", { class: "empty" }, "Заказов за период нет.");
  const r = 54, c = 2 * Math.PI * r;
  const svg = s("svg", { viewBox: "0 0 150 150", role: "img", "aria-label": "Статусы заказов" });
  svg.append(s("circle", { cx: 75, cy: 75, r, fill: "none", stroke: "rgba(255,255,255,.08)", "stroke-width": 20 }));
  let offset = 0;
  for (const e of entries) {
    const len = (e.value / total) * c;
    svg.append(s("circle", { cx: 75, cy: 75, r, fill: "none", stroke: e.color, "stroke-width": 20, "stroke-dasharray": `${len} ${c - len}`, "stroke-dashoffset": -offset, transform: "rotate(-90 75 75)" }));
    offset += len;
  }
  const t1 = s("text", { x: 75, y: 73, "text-anchor": "middle", fill: "#ffffff", "font-size": 24, "font-family": "Inter, system-ui, sans-serif" }); t1.textContent = total;
  const t2 = s("text", { x: 75, y: 92, "text-anchor": "middle", fill: "#8b8f99", "font-size": 11 }); t2.textContent = "заказов";
  svg.append(t1, t2);
  return h("div", { class: "donut-wrap" }, svg,
    h("div", { class: "legend" }, entries.map(e => h("div", {}, h("i", { style: `background:${e.color}` }), e.label, h("em", {}, `${e.value} · ${Math.round((e.value / total) * 100)}%`)))));
}

function hbars(items) {
  if (!items.length) return h("div", { class: "empty" }, "Продаж за период пока нет.");
  const max = Math.max(...items.map(i => i.value), 1);
  return h("div", {}, items.map(i => h("div", { class: "hbar" },
    h("div", { class: "t" }, h("span", { title: i.name }, i.name), h("span", {}, i.text)),
    h("div", { class: "bar" }, h("i", { style: `width:${Math.max(3, (i.value / max) * 100)}%` })))));
}


/* ===================================================================== обзор == */
function spark(values, color = "#ffffff") {
  const W = 100, H = 36, P = 3;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", "aria-hidden": "true", preserveAspectRatio: "none" });
  const max = Math.max(...values, 0), min = Math.min(...values, 0), span = max - min || 1;
  const x = i => P + (values.length === 1 ? (W - 2 * P) / 2 : (i * (W - 2 * P)) / (values.length - 1));
  const y = v => max === min ? H - P : H - P - ((v - min) / span) * (H - 2 * P);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const id = "sp" + (++chartUid);
  svg.append(s("defs", {}, s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 },
    s("stop", { offset: "0%", "stop-color": color, "stop-opacity": ".35" }), s("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0" }))));
  svg.append(s("path", { d: `${line} L${x(values.length - 1)},${H} L${x(0)},${H} Z`, fill: `url(#${id})` }));
  svg.append(s("path", { d: line, fill: "none", stroke: color, "stroke-width": 1.8, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }));
  return svg;
}
function delta(current, previous) {
  if (!previous && !current) return h("span", { class: "dchip flat" }, "— как раньше");
  if (!previous) return h("span", { class: "dchip up" }, "▲ новое");
  const pct = Math.round(((current - previous) / previous) * 100);
  if (pct === 0) return h("span", { class: "dchip flat" }, "0%");
  return h("span", { class: "dchip " + (pct > 0 ? "up" : "down") }, `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%`);
}
const ICONS = {
  money: '<path d="M12 2v20"/><path d="M17 6.5c-.8-1.4-2.6-2.3-5-2.3-2.8 0-4.6 1.3-4.6 3.3 0 4.6 10 2 10 6.6 0 2-2 3.4-5 3.4-2.6 0-4.6-1-5.4-2.6"/>',
  bag: '<path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 01-8 0"/>',
  users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
};
function icon(name) {
  const box = h("span", { class: "ico" });
  box.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return box;
}
function kpi(label, ico, value, chip, series, note) {
  return h("div", { class: "kpi" },
    h("div", { class: "khead" }, icon(ico), h("span", { class: "klabel" }, label)),
    h("b", {}, value),
    h("div", { class: "kfoot" }, h("div", { class: "kdelta" }, chip, h("small", {}, note)), series ? spark(series) : ""));
}

function goOrders(status) { state.orderStatus = status; navigate("orders"); }
function goProducts(filter) { state.productFilter = filter; navigate("products"); }
function attentionItems() {
  const items = [];
  const noStock = state.orders.filter(o => o.status === "paid_no_stock").length;
  const pending = state.orders.filter(o => o.status === "pending").length;
  if (noStock) items.push([noStock, `${plural(noStock, "оплаченный заказ", "оплаченных заказа", "оплаченных заказов")} без товара — выдай вручную`, () => goOrders("paid_no_stock"), true]);
  const out = state.products.filter(p => p.is_active && p.stock_count <= 0);
  if (out.length) items.push([out.length, `${plural(out.length, "товар закончился", "товара закончились", "товаров закончились")} — покупатели их не видят`, () => goProducts("out"), true]);
  const low = state.products.filter(p => p.is_active && p.stock_count > 0 && p.stock_count <= LOW_STOCK);
  if (low.length) items.push([low.length, `${plural(low.length, "товар заканчивается", "товара заканчиваются", "товаров заканчиваются")} (≤ ${LOW_STOCK} шт.)`, () => goProducts("low")]);
  const nocat = state.products.filter(p => !p.category_id);
  if (nocat.length) items.push([nocat.length, `${plural(nocat.length, "товар", "товара", "товаров")} без категории`, () => goProducts("nocat")]);
  if (pending) items.push([pending, `${plural(pending, "заказ ждёт", "заказа ждут", "заказов ждут")} оплаты`, () => goOrders("pending")]);
  return items;
}

function recentOrders() {
  const list = [...state.orders].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 6);
  const cls = { paid: "paid", pending: "pending", cancelled: "cancelled", paid_no_stock: "nostock" };
  const short_ = { paid: "оплачен", pending: "ждёт оплаты", cancelled: "отменён", paid_no_stock: "нет товара" };
  return h("div", { class: "card col-4" }, h("h2", {}, "Последние заказы"), h("p", { class: "sub" }, "Нажми, чтобы открыть все покупки"),
    list.length ? h("div", { class: "rlist" }, list.map(o => h("button", { type: "button", class: "rrow", onclick: () => navigate("orders") },
      h("span", { class: "ava" }, String(clientName(o)).replace("@", "").charAt(0).toUpperCase() || "?"),
      h("span", { class: "who" }, h("b", {}, clientName(o)), h("small", {}, o.product_name || "—")),
      h("span", { class: "amt" }, h("b", {}, money(o.amount)), h("span", { class: "status " + (cls[o.status] || "") }, short_[o.status] || o.status)))))
      : h("div", { class: "empty" }, "Покупок пока нет."));
}
function popularProducts(an) {
  const items = an.top_products.slice(0, 6);
  const max = Math.max(...items.map(p => p.revenue), 1);
  return h("div", { class: "card col-4" }, h("h2", {}, "Популярные товары"), h("p", { class: "sub" }, `По выручке за ${an.days} дн.`),
    items.length ? h("div", { class: "plist" }, items.map((p, i) => h("div", { class: "prow" },
      h("span", { class: "rank" }, i + 1),
      h("div", { class: "pinfo" }, h("div", { class: "pt" }, h("b", { title: p.name }, p.name), h("span", {}, money(p.revenue))),
        h("div", { class: "bar" }, h("i", { style: `width:${Math.max(4, (p.revenue / max) * 100)}%` })),
        h("small", {}, `${p.sales} шт.`)))))
      : h("div", { class: "empty" }, "Продаж за период пока нет."));
}

function renderDashboard() {
  const d = state.dashboard, an = state.analytics;
  const page = h("div", {});
  const todo = attentionItems();
  const attention = h("div", { class: "card col-4" }, h("h2", {}, "Требует внимания"), h("p", { class: "sub" }, "Нажми, чтобы перейти к списку"),
    h("div", { class: "todo" }, todo.length
      ? todo.map(([n, text, go, hot]) => h("button", { type: "button", class: hot ? "hot" : "", onclick: go }, h("span", { class: "n" }, n), h("span", {}, text)))
      : h("div", { class: "ok" }, "Всё в порядке, срочных дел нет.")));
  const topCategories = h("div", { class: "card col-6" }, h("h2", {}, "Топ категорий"), h("p", { class: "sub" }, "По выручке за всё время"),
    hbars((d.top_categories || []).slice(0, 8).map(c => ({ name: c.name, value: num(c.revenue), text: `${money(c.revenue)} · ${c.sales} шт.` }))));
  const totals = h("div", { class: "mstats" },
    h("div", {}, h("span", {}, "Сегодня"), h("b", {}, money(d.today_revenue)), h("small", {}, `посетителей: ${d.today_visits}`)),
    h("div", {}, h("span", {}, "Всего заработано"), h("b", {}, money(d.revenue)), h("small", {}, `${d.orders} ${plural(d.orders, "оплаченная покупка", "оплаченные покупки", "оплаченных покупок")}`)));

  if (!an) {
    page.append(h("div", { class: "grid" }, recentOrders(), attention, topCategories,
      h("div", { class: "card col-12" }, h("h2", {}, "Графики"), totals,
        h("div", { class: "empty" }, "Сервер пока не отдаёт /api/admin/analytics — обнови и перезапусти бота, чтобы увидеть графики."))));
    return page;
  }
  const pts = key => an.series.map(p => ({ label: dayLabel(p.date), title: dayLabel(p.date), value: p[key] }));
  const vals = key => an.series.map(p => num(p[key]));
  const avg = an.current.orders ? an.current.revenue / an.current.orders : 0;
  const avgPrev = an.previous.orders ? an.previous.revenue / an.previous.orders : 0;
  const note = "к прошлому периоду";
  page.append(h("div", { class: "kpis" },
    kpi(`Выручка · ${an.days} дн.`, "money", money(an.current.revenue), delta(an.current.revenue, an.previous.revenue), vals("revenue"), note),
    kpi("Оплаченные заказы", "bag", an.current.orders, delta(an.current.orders, an.previous.orders), vals("orders"), note),
    kpi("Новые покупатели", "users", an.current.customers, delta(an.current.customers, an.previous.customers), vals("customers"), note),
    kpi("Посетители", "eye", an.current.visits, delta(an.current.visits, an.previous.visits), vals("visits"), note)));

  const sales = h("div", { class: "card col-8 flexcol" }, h("h2", {}, "Статистика продаж"), h("p", { class: "sub" }, `Выручка по дням за ${an.days} дн. · средний чек ${money(avg)} `, delta(avg, avgPrev)),
    timeChart(pts("revenue"), { type: "line", tipFmt: money, height: 300 }), totals);
  page.append(h("div", { class: "grid" },
    sales, recentOrders(),
    popularProducts(an),
    h("div", { class: "card col-4" }, h("h2", {}, "Статусы заказов"), h("p", { class: "sub" }, `Все заказы, созданные за ${an.days} дн.`),
      donut(Object.entries(an.statuses).sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ label: STATUS[key] || key, value, color: STATUS_COLOR[key] || "#8f939d" })))),
    attention,
    h("div", { class: "card col-6" }, h("h2", {}, "Покупки по дням"), h("p", { class: "sub" }, "Количество оплаченных заказов"),
      timeChart(pts("orders"), { type: "bar", integer: true, color: "#e6e8ec", tipFmt: v => `${v} ${plural(v, "покупка", "покупки", "покупок")}` })),
    h("div", { class: "card col-6" }, h("h2", {}, "Посетители"), h("p", { class: "sub" }, "Уникальные посетители сайта по дням"),
      timeChart(pts("visits"), { type: "line", integer: true, color: "#c3c6ce", tipFmt: v => `${v} ${plural(v, "посетитель", "посетителя", "посетителей")}` })),
    h("div", { class: "card col-6" }, h("h2", {}, "Новые покупатели"), h("p", { class: "sub" }, "Кто впервые запустил бота"),
      timeChart(pts("customers"), { type: "bar", integer: true, color: "#cfd2d8", tipFmt: v => `${v} ${plural(v, "покупатель", "покупателя", "покупателей")}` })),
    topCategories));
  return page;
}

/* ==================================================================== товары == */
function productMatches(p) {
  const q = lower(state.productSearch.trim());
  if (q && !lower(p.name + " " + p.description).includes(q)) return false;
  if (state.productCategory && String(p.category_id) !== state.productCategory) return false;
  switch (state.productFilter) {
    case "on": return !!p.is_active;
    case "off": return !p.is_active;
    case "low": return p.stock_count > 0 && p.stock_count <= LOW_STOCK;
    case "out": return p.stock_count <= 0;
    case "nocat": return !p.category_id;
    default: return true;
  }
}
/** Сохраняет товар целиком: сервер принимает полный набор полей. */
function productBody(p, patch = {}) {
  return { name: p.name, description: p.description || "", price: p.price, category_id: p.category_id, is_active: p.is_active, ...patch };
}
const saveProduct = (p, patch, message) => act(() => api("/products/" + p.id, { method: "PUT", body: productBody(p, patch) }), message);

function inlinePrice(p) {
  const input = h("input", { class: "inline-num", type: "number", min: 0, step: "0.01", value: num(p.price), "aria-label": "Цена" });
  const save = async () => {
    const value = input.value.trim();
    if (value === "" || num(value) < 0 || num(value) === num(p.price)) { input.value = num(p.price); return; }
    input.classList.add("saving");
    const ok = await saveProduct(p, { price: value }, `«${p.name}»: цена ${money(value)}`);
    if (!ok) { input.value = num(p.price); input.classList.remove("saving"); }
  };
  input.addEventListener("change", save);
  input.addEventListener("keydown", event => { if (event.key === "Enter") input.blur(); if (event.key === "Escape") { input.value = num(p.price); input.blur(); } });
  return input;
}

function renderProducts() {
  const all = state.products;
  const counts = {
    all: all.length, on: all.filter(p => p.is_active).length, off: all.filter(p => !p.is_active).length,
    low: all.filter(p => p.stock_count > 0 && p.stock_count <= LOW_STOCK).length, out: all.filter(p => p.stock_count <= 0).length,
    nocat: all.filter(p => !p.category_id).length,
  };
  const chip = (key, label) => (key === "nocat" && !counts.nocat) ? null
    : h("button", { class: "chip", type: "button", "aria-pressed": String(state.productFilter === key), onclick: () => { state.productFilter = key; render(); } }, label, h("small", {}, counts[key]));
  const search = h("input", { class: "search", id: "search", type: "search", placeholder: "Поиск по названию…  ( / )", value: state.productSearch });
  const category = h("select", { style: "width:auto", "aria-label": "Категория", onchange: event => { state.productCategory = event.target.value; render(); } },
    h("option", { value: "" }, "Все категории"), state.categories.map(c => h("option", { value: String(c.id), selected: String(c.id) === state.productCategory }, c.name)));
  const tbody = h("tbody", {}); const countNode = h("span", { class: "muted" });
  const empty = h("div", { class: "card empty" }); const tableCard = h("div", { class: "card table-card" });
  function refresh() {
    const rows = all.filter(productMatches);
    countNode.textContent = `Показано: ${rows.length} из ${all.length}`;
    tbody.replaceChildren(...rows.map(productRow));
    tableCard.hidden = !rows.length; empty.hidden = !!rows.length;
    empty.textContent = all.length ? "Ничего не найдено — измени фильтры." : "Товаров пока нет. Добавь первый.";
  }
  search.addEventListener("input", () => { state.productSearch = search.value; refresh(); });
  tableCard.append(h("div", { class: "tscroll" }, h("table", { class: "resp" },
    h("thead", {}, h("tr", {}, ["Товар", "Категория", "Цена, ₽", "Автовыдача", "На витрине", ""].map((t, i) => h("th", { class: i === 2 || i === 3 ? "num" : "" }, t)))), tbody)));
  refresh();
  return h("div", {},
    h("div", { class: "toolbar" }, search, category, h("div", { class: "chips" }, chip("all", "Все"), chip("on", "Активные"), chip("off", "Скрытые"), chip("low", "Заканчиваются"), chip("out", "Закончились"), chip("nocat", "Без категории")), h("span", { class: "grow" }), countNode),
    tableCard, empty);
}

function productRow(p) {
  const stockPill = p.stock_count <= 0 ? h("span", { class: "pill red" }, "нет") : p.stock_count <= LOW_STOCK ? h("span", { class: "pill yellow" }, "мало") : null;
  const toggle = h("label", { class: "switch", title: "Показывать в каталоге" },
    h("input", { type: "checkbox", checked: !!p.is_active, "aria-label": "Активен", onchange: event => saveProduct(p, { is_active: event.target.checked }, `«${p.name}»: ${event.target.checked ? "показан в каталоге" : "скрыт из каталога"}`) }),
    h("span", {}));
  const cell = (label, content, cls) => h("td", { dataset: { label }, class: cls || "" }, content);
  return h("tr", {},
    cell("Товар", h("div", {}, h("div", { class: "name" }, p.name), p.description ? h("div", { class: "sub clip" }, p.description) : "")),
    cell("Категория", p.category_name || h("span", { class: "pill yellow" }, "без категории")),
    cell("Цена", inlinePrice(p), "num"),
    cell("Автовыдача", h("div", { class: "cellflex" }, stockPill, `${p.stock_count} шт.`), "num"),
    cell("На витрине", toggle),
    h("td", { class: "act" }, h("div", { class: "row-actions" }, h("button", { class: "btn sm", type: "button", onclick: () => openProduct(p) }, "Открыть"))));
}

function openProduct(product) {
  const isNew = !product;
  const p = product || { name: "", description: "", price: "", category_id: (state.categories.find(c => c.is_active) || {}).id || "", is_active: true };
  const f = {
    name: h("input", { maxLength: 150, value: p.name, placeholder: "Например, ChatGPT Plus" }),
    category: h("select", {}, h("option", { value: "" }, "Без категории"), state.categories.map(c => h("option", { value: String(c.id), selected: String(c.id) === String(p.category_id) }, c.name + (c.is_active ? "" : " (скрыта)")))),
    price: h("input", { type: "number", min: 0, step: "0.01", value: p.price === "" ? "" : num(p.price), placeholder: "790" }),
    description: h("textarea", { placeholder: "Что получит покупатель", value: p.description || "" }),
    active: h("input", { type: "checkbox", checked: !!p.is_active }),
  };
  const field = (label, node, full) => h("div", { class: full ? "full" : "" }, h("label", { class: "lbl" }, label), node);
  const save = h("button", { class: "btn primary", type: "button" }, isNew ? "Создать товар" : "Сохранить");
  save.addEventListener("click", async () => {
    const body = { name: f.name.value.trim(), description: f.description.value.trim(), price: f.price.value.trim(), category_id: f.category.value ? Number(f.category.value) : null, is_active: f.active.checked };
    if (!body.name) { toast("Название не может быть пустым.", "error"); f.name.focus(); return; }
    if (body.price === "" || num(body.price) < 0) { toast("Укажи цену — число от 0.", "error"); f.price.focus(); return; }
    save.disabled = true;
    const ok = await act(() => api(isNew ? "/products" : "/products/" + p.id, { method: isNew ? "POST" : "PUT", body }), isNew ? `Товар «${body.name}» создан. Загрузи автовыдачу в его карточке.` : `Товар «${body.name}» сохранён.`);
    save.disabled = false;
    if (ok) closeTopOverlay();
  });
  const drawer = h("div", { class: "drawer", role: "dialog", "aria-modal": "true" },
    h("div", { class: "drawer-head" }, h("div", {}, h("p", { class: "eyebrow" }, isNew ? "Новый товар" : `Товар № ${p.id}`), h("h3", {}, isNew ? "Добавить товар" : p.name)),
      h("button", { class: "btn sm", type: "button", "aria-label": "Закрыть", onclick: closeTopOverlay }, "×")),
    h("div", { class: "form-grid" }, field("Название", f.name, true), field("Категория", f.category), field("Цена, ₽", f.price), field("Описание", f.description, true)),
    h("div", { class: "section" }, h("div", { class: "toggle-row" }, h("div", {}, h("div", {}, "Показывать в каталоге"), h("div", { class: "sub dim" }, "Скрытый товар покупатели не видят"), ), h("label", { class: "switch" }, f.active, h("span", {})))),
    h("div", { class: "actions" }, h("button", { class: "btn", type: "button", onclick: closeTopOverlay }, "Отмена"), save));
  if (!isNew) {
    drawer.append(stockSection(p));
    drawer.append(h("div", { class: "section" }, h("h4", {}, "Опасная зона"),
      h("button", { class: "btn danger", type: "button", onclick: async () => {
        if (!(await confirmBox("Удалить товар?", `«${p.name}» будет удалён вместе с невыданными позициями автовыдачи. Это нельзя отменить.`, "Удалить", true))) return;
        if (await act(() => api("/products/" + p.id, { method: "DELETE" }), `Товар «${p.name}» удалён.`)) closeTopOverlay();
      } }, "Удалить товар")));
  }
  openOverlay(drawer);
}

function stockSection(p) {
  let items = [];
  let dirty = false;
  const list = h("div", {});
  const info = h("p", { class: "muted", style: "margin-top:10px" }, "Загружаем позиции…");
  const area = h("textarea", { placeholder: "Добавить сразу много: одна строка = одна позиция (логин:пароль, ключ, ссылка)" });
  const saveBtn = h("button", { class: "btn primary", type: "button", disabled: true }, "Сохранить список");
  const markDirty = () => { dirty = true; saveBtn.disabled = false; saveBtn.textContent = "Сохранить список *"; };
  let issued = 0;
  function draw() {
    info.textContent = `Готово к выдаче: ${items.length} шт. · выдано ранее: ${issued}`;
    list.replaceChildren(...items.map((value, index) => h("div", { class: "line-item" },
      h("input", { value, "aria-label": `Позиция ${index + 1}`, oninput: event => { items[index] = event.target.value; markDirty(); } }),
      h("button", { class: "btn danger sm", type: "button", "aria-label": "Удалить", onclick: () => { items.splice(index, 1); markDirty(); draw(); } }, "×"))));
  }
  const addMany = h("button", { class: "btn", type: "button", onclick: () => {
    const lines = area.value.split("\n").map(l => l.trim()).filter(Boolean);
    if (!lines.length) { toast("Вставь хотя бы одну строку.", "error"); return; }
    items.push(...lines); area.value = ""; markDirty(); draw();
    toast(`Добавлено строк: ${lines.length}. Нажми «Сохранить список».`);
  } }, "+ Добавить в список");
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    const ok = await act(() => api(`/products/${p.id}/stock`, { method: "PUT", body: { items: items.map(v => v.trim()).filter(Boolean) } }), "Автовыдача сохранена.");
    if (ok) { dirty = false; saveBtn.textContent = "Сохранить список"; load(); } else saveBtn.disabled = false;
  });
  async function load() {
    try {
      const rows = await api(`/products/${p.id}/stock`);
      items = rows.filter(r => !r.is_issued).map(r => r.payload);
      issued = rows.length - items.length;
      dirty = false; saveBtn.disabled = true; draw();
    } catch (error) { info.textContent = "Не удалось загрузить позиции: " + error.message; }
  }
  load();
  return h("div", { class: "section" }, h("h4", {}, "Автовыдача"), info, list,
    h("div", { style: "margin-top:10px" }, area, h("div", { class: "actions", style: "margin-top:8px" }, addMany, saveBtn)));
}

/* ================================================================== категории == */
function openCategory(category) {
  const isNew = !category;
  const c = category || { name: "", sort_order: state.categories.length + 1, is_active: true };
  const name = h("input", { maxLength: 80, value: c.name, placeholder: "Например, ChatGPT" });
  const order = h("input", { type: "number", value: c.sort_order });
  const active = h("input", { type: "checkbox", checked: !!c.is_active });
  const submit = h("button", { class: "btn primary", type: "button" }, "Сохранить");
  const send = async () => {
    const body = { name: name.value.trim(), sort_order: Number.parseInt(order.value, 10) || 0, is_active: active.checked };
    if (!body.name) { toast("Название не может быть пустым.", "error"); return; }
    submit.disabled = true;
    const ok = await act(() => api(isNew ? "/categories" : "/categories/" + c.id, { method: isNew ? "POST" : "PUT", body }), "Категория сохранена.");
    submit.disabled = false;
    if (ok) closeTopOverlay();
  };
  submit.addEventListener("click", send);
  name.addEventListener("keydown", event => { if (event.key === "Enter") send(); });
  openOverlay(h("div", { class: "modal", role: "dialog", "aria-modal": "true" },
    h("h3", {}, isNew ? "Новая категория" : "Изменить категорию"),
    h("div", { style: "margin-top:12px" }, h("label", { class: "lbl" }, "Название"), name),
    h("div", { style: "margin-top:12px" }, h("label", { class: "lbl" }, "Порядок показа"), order),
    h("div", { class: "toggle-row" }, h("span", {}, "Показывать в каталоге"), h("label", { class: "switch" }, active, h("span", {}))),
    h("div", { class: "actions" }, h("button", { class: "btn", type: "button", onclick: closeTopOverlay }, "Отмена"), submit)), { center: true });
  name.focus();
}
function renderCategories() {
  const cats = state.categories;
  if (!cats.length) return h("div", { class: "card empty" }, "Категорий пока нет.");
  const body = c => ({ name: c.name, sort_order: c.sort_order, is_active: c.is_active });
  const rows = cats.map(c => {
    const count = state.products.filter(p => p.category_id === c.id).length;
    const order = h("input", { class: "inline-num", type: "number", value: c.sort_order, "aria-label": "Порядок", style: "width:72px",
      onchange: event => act(() => api("/categories/" + c.id, { method: "PUT", body: { ...body(c), sort_order: Number.parseInt(event.target.value, 10) || 0 } }), `«${c.name}»: порядок ${event.target.value}`) });
    const toggle = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!c.is_active, "aria-label": "Показывать",
      onchange: event => act(() => api("/categories/" + c.id, { method: "PUT", body: { ...body(c), is_active: event.target.checked } }), `«${c.name}»: ${event.target.checked ? "показана" : "скрыта"}`) }), h("span", {}));
    const cell = (label, content, cls) => h("td", { dataset: { label }, class: cls || "" }, content);
    return h("tr", {}, cell("Название", h("span", { class: "name" }, c.name)), cell("Товаров", count, "num"), cell("Порядок", order, "num"), cell("В каталоге", toggle),
      h("td", { class: "act" }, h("div", { class: "row-actions" }, h("button", { class: "btn sm", type: "button", onclick: () => openCategory(c) }, "Изменить"))));
  });
  return h("div", { class: "card table-card" }, h("div", { class: "tscroll" }, h("table", { class: "resp" },
    h("thead", {}, h("tr", {}, ["Название", "Товаров", "Порядок", "В каталоге", ""].map((t, i) => h("th", { class: i === 1 || i === 2 ? "num" : "" }, t)))), h("tbody", {}, rows))));
}

/* =================================================================== покупки == */
function renderOrders() {
  const all = state.orders;
  const counts = { "": all.length };
  for (const key of Object.keys(STATUS)) counts[key] = all.filter(o => o.status === key).length;
  const chip = (key, label) => (key && !counts[key]) ? null
    : h("button", { class: "chip", type: "button", "aria-pressed": String(state.orderStatus === key), onclick: () => { state.orderStatus = key; render(); } }, label, h("small", {}, counts[key]));
  const search = h("input", { class: "search", id: "search", type: "search", placeholder: "№ заказа, покупатель или товар  ( / )", value: state.orderSearch });
  const tbody = h("tbody", {}); const countNode = h("span", { class: "muted" });
  const empty = h("div", { class: "card empty" }); const tableCard = h("div", { class: "card table-card" });
  function refresh() {
    const q = lower(state.orderSearch.trim());
    const rows = all.filter(o => (!state.orderStatus || o.status === state.orderStatus)
      && (!q || lower([o.id, o.username, o.first_name, o.customer_id, o.product_name].join(" ")).includes(q)));
    countNode.textContent = `Показано: ${rows.length} из ${all.length}`;
    tbody.replaceChildren(...rows.map(orderRow));
    tableCard.hidden = !rows.length; empty.hidden = !!rows.length;
    empty.textContent = all.length ? "Заказы по этому фильтру не найдены." : "Покупок пока нет.";
  }
  search.addEventListener("input", () => { state.orderSearch = search.value; refresh(); });
  tableCard.append(h("div", { class: "tscroll" }, h("table", { class: "resp" },
    h("thead", {}, h("tr", {}, ["№", "Дата", "Покупатель", "Товар", "Сумма", "Статус"].map((t, i) => h("th", { class: i === 4 ? "num" : "" }, t)))), tbody)));
  refresh();
  return h("div", {},
    h("div", { class: "toolbar" }, search, h("span", { class: "grow" }), countNode),
    h("div", { class: "chips", style: "margin-bottom:12px" }, chip("", "Все"), chip("paid", "Оплачены"), chip("pending", "Ждут оплаты"), chip("paid_no_stock", "Оплачены без товара"), chip("cancelled", "Отменены")),
    state.orderStatus === "paid_no_stock" || counts.paid_no_stock ? h("p", { class: "muted", style: "margin-bottom:12px" }, "«Оплачен, нет товара» — деньги получены, но автовыдача была пуста. Выдай товар покупателю вручную. Показаны последние 500 заказов.") : h("p", { class: "muted", style: "margin-bottom:12px" }, "Показаны последние 500 заказов."),
    tableCard, empty);
}
function orderRow(o) {
  const cell = (label, content, cls) => h("td", { dataset: { label }, class: cls || "" }, content);
  const cls = { paid: "paid", pending: "pending", cancelled: "cancelled", paid_no_stock: "nostock" }[o.status] || "";
  return h("tr", {},
    cell("№", h("b", {}, o.id)), cell("Дата", fmtDate(o.created_at)), cell("Покупатель", clientName(o)),
    cell("Товар", o.product_name || h("span", { class: "dim" }, "Удалённый товар")), cell("Сумма", money(o.amount), "num"),
    cell("Статус", h("span", { class: "status " + cls }, STATUS[o.status] || o.status)));
}

/* ================================================================= покупатели == */
async function grant(target, amount, label) {
  const path = target.username ? "/customers/" + encodeURIComponent(target.username) + "/balance" : "/customers/id/" + target.telegram_id + "/balance";
  return act(() => api(path, { method: "POST", body: { amount: String(amount), reason: "Выдано администратором" } }), `Баланс ${label} пополнен на ${money(amount)}.`);
}
function openTopup(customer) {
  const who = h("input", { placeholder: "@username или Telegram ID", value: customer ? (customer.username ? "@" + customer.username : customer.telegram_id) : "" });
  const amount = h("input", { type: "number", min: 0, step: "0.01", placeholder: "Сумма, ₽" });
  const submit = h("button", { class: "btn primary", type: "button" }, "Пополнить");
  const send = async () => {
    const raw = who.value.trim().replace(/^@/, ""), sum = num(amount.value);
    if (!raw || sum <= 0) { toast("Нужны покупатель и сумма больше нуля.", "error"); return; }
    const target = /^\d+$/.test(raw) ? { telegram_id: raw } : { username: raw };
    submit.disabled = true;
    const ok = await grant(target, sum, raw);
    submit.disabled = false;
    if (ok) closeTopOverlay();
  };
  submit.addEventListener("click", send);
  [who, amount].forEach(node => node.addEventListener("keydown", event => { if (event.key === "Enter") send(); }));
  openOverlay(h("div", { class: "modal", role: "dialog", "aria-modal": "true" },
    h("h3", {}, customer ? `Пополнить баланс: ${customer.first_name || clientName(customer)}` : "Пополнить баланс"),
    customer ? h("p", { class: "muted" }, `Сейчас на балансе ${money(customer.balance)}`) : h("p", { class: "muted" }, "Покупатель должен уже запускать бота."),
    h("div", { style: "margin-top:12px" }, h("label", { class: "lbl" }, "Покупатель"), who),
    h("div", { class: "presets" }, [100, 250, 500, 1000, 1500].map(v => h("button", { class: "btn sm", type: "button", onclick: () => { amount.value = v; amount.focus(); } }, "+" + v))),
    h("label", { class: "lbl" }, "Сумма, ₽"), amount,
    h("div", { class: "actions" }, h("button", { class: "btn", type: "button", onclick: closeTopOverlay }, "Отмена"), submit)), { center: true });
  (customer ? amount : who).focus();
}
function renderCustomers() {
  const search = h("input", { class: "search", id: "search", type: "search", placeholder: "Имя, @username или Telegram ID  ( / )", value: state.customerSearch });
  const sort = h("select", { style: "width:auto", "aria-label": "Сортировка", onchange: event => { state.customerSort = event.target.value; refresh(); } },
    [["seen", "Недавно активные"], ["balance", "По балансу"], ["purchases", "По числу покупок"]].map(([v, t]) => h("option", { value: v, selected: v === state.customerSort }, t)));
  const tbody = h("tbody", {}); const countNode = h("span", { class: "muted" });
  const empty = h("div", { class: "card empty" }); const tableCard = h("div", { class: "card table-card" });
  function refresh() {
    const q = lower(state.customerSearch.trim().replace(/^@/, ""));
    let rows = state.customers.filter(c => !q || lower([c.first_name, c.username, c.telegram_id].join(" ")).includes(q));
    if (state.customerSort === "balance") rows = [...rows].sort((a, b) => num(b.balance) - num(a.balance));
    if (state.customerSort === "purchases") rows = [...rows].sort((a, b) => b.purchases - a.purchases);
    countNode.textContent = `Показано: ${rows.length} из ${state.customers.length}`;
    tbody.replaceChildren(...rows.map(customerRow));
    tableCard.hidden = !rows.length; empty.hidden = !!rows.length;
    empty.textContent = state.customers.length ? "Покупатели по этому запросу не найдены." : "Покупатели появятся после входа в бот.";
  }
  search.addEventListener("input", () => { state.customerSearch = search.value; refresh(); });
  tableCard.append(h("div", { class: "tscroll" }, h("table", { class: "resp" },
    h("thead", {}, h("tr", {}, ["Покупатель", "Telegram ID", "Баланс", "Покупок", "Был в боте", ""].map((t, i) => h("th", { class: i === 2 || i === 3 ? "num" : "" }, t)))), tbody)));
  refresh();
  return h("div", {}, h("div", { class: "toolbar" }, search, sort, h("span", { class: "grow" }), countNode), tableCard, empty);
}
function customerRow(c) {
  const cell = (label, content, cls) => h("td", { dataset: { label }, class: cls || "" }, content);
  const label = c.username ? "@" + c.username : c.first_name;
  const quick = amount => h("button", { class: "btn sm", type: "button", onclick: async () => {
    if (await confirmBox("Пополнить баланс?", `${label}: +${money(amount)}.`, "Пополнить")) grant(c, amount, label);
  } }, "+" + amount);
  return h("tr", {},
    cell("Покупатель", h("div", {}, h("div", { class: "name" }, c.first_name || "—"), c.username ? h("div", { class: "sub" }, "@" + c.username) : "")),
    cell("Telegram ID", h("span", { class: "dim" }, c.telegram_id)), cell("Баланс", money(c.balance), "num"), cell("Покупок", c.purchases, "num"),
    cell("Был в боте", fmtDate(c.last_seen_at)),
    h("td", { class: "act" }, h("div", { class: "row-actions" }, quick(500), quick(1000), h("button", { class: "btn primary sm", type: "button", onclick: () => openTopup(c) }, "Другая сумма"))));
}

/* ==================================================================== каркас == */
const PAGES = {
  dashboard: { title: "Обзор магазина", render: renderDashboard },
  products: { title: "Товары", render: renderProducts },
  categories: { title: "Категории", render: renderCategories },
  customers: { title: "Покупатели", render: renderCustomers },
  orders: { title: "Покупки", render: renderOrders },
};
function pageTools() {
  const tools = h("div", { class: "tools" });
  if (state.page === "dashboard") {
    tools.append(h("div", { class: "seg", role: "group", "aria-label": "Период" }, [7, 30, 90].map(d => h("button", { type: "button", "aria-pressed": String(state.days === d), onclick: async () => { state.days = d; await refreshData(); } }, d + " дн."))));
  }
  if (state.page === "products") tools.append(h("button", { class: "btn primary", type: "button", onclick: () => openProduct(null) }, "+ Добавить товар"));
  if (state.page === "categories") tools.append(h("button", { class: "btn primary", type: "button", onclick: () => openCategory(null) }, "+ Добавить категорию"));
  if (state.page === "customers") tools.append(h("button", { class: "btn primary", type: "button", onclick: () => openTopup(null) }, "+ Пополнить баланс"));
  tools.append(
    h("label", { class: "auto", title: "Обновлять данные раз в минуту" }, h("span", { class: "switch" }, h("input", { type: "checkbox", checked: state.autoRefresh, onchange: event => { state.autoRefresh = event.target.checked; } }), h("span", {})), "Авто"),
    h("button", { class: "btn", type: "button", onclick: refreshData }, "Обновить"));
  return tools;
}
function render() {
  const page = PAGES[state.page] || PAGES.dashboard;
  $("page-title").textContent = page.title;
  $("page-tools").replaceChildren(...pageTools().childNodes);
  $("page").replaceChildren(page.render());
  for (const button of $("nav").querySelectorAll("button")) button.setAttribute("aria-current", String(button.dataset.page === state.page));
}
function updateBadges() {
  const urgent = state.orders.filter(o => o.status === "paid_no_stock").length;
  const trouble = state.products.filter(p => p.is_active && p.stock_count <= LOW_STOCK).length;
  for (const [id, n] of [["badge-orders", urgent], ["badge-products", trouble]]) { $(id).textContent = n; $(id).hidden = !n; }
}
async function refreshData() {
  $("page").classList.add("loading");
  try { await loadAll(); toast("Данные обновлены."); } catch (error) { if (error.status !== 401) toast(error.message, "error"); }
  $("page").classList.remove("loading");
}
function navigate(page) { location.hash = "#/" + page; }
function route() {
  const page = location.hash.replace(/^#\/?/, "");
  state.page = PAGES[page] ? page : "dashboard";
  if (!$("app").hidden) render();
}

$("loginForm").addEventListener("submit", login);
$("logout").addEventListener("click", () => logout());
$("nav").addEventListener("click", event => { const button = event.target.closest("button[data-page]"); if (button) navigate(button.dataset.page); });
window.addEventListener("hashchange", route);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeTopOverlay();
  if (event.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
    const search = $("search"); if (search) { event.preventDefault(); search.focus(); }
  }
});
setInterval(() => {
  if (!token || $("app").hidden || !state.autoRefresh || document.hidden || closeOverlay) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  loadAll({ silent: true }).catch(() => { /* следующая попытка через минуту */ });
}, 60000);

if (token) start();
