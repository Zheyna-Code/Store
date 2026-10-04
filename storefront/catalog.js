'use strict';
// Каталог сайта: карточки сервисов, вход (Telegram или почта + пароль) и оплата прямо на сайте.
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const e = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usdF = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'});
  const rubF = new Intl.NumberFormat('ru-RU', {style:'currency', currency:'RUB', maximumFractionDigits:0});
  const usd = x => Number.isFinite(Number(x)) ? usdF.format(Number(x)) : '—';
  const S = {user:null, csrf:'', cats:[], products:[], rate:null, filter:null, query:'', timers:[], loaded:false};
  const DARK_TILES = new Set(['chatgpt','grok','notion','netflix','capcut','spotify']);
  const BOT = 'https://t.me/wanderersshop_bot';

  async function api(path, method = 'GET', body) {
    const headers = {};
    if (method !== 'GET') { headers['Content-Type'] = 'application/json'; if (S.csrf) headers['X-CSRF-Token'] = S.csrf; }
    const r = await fetch('/api/store/' + path, {method, credentials:'same-origin', headers, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    let d; try { d = await r.json(); } catch { throw new Error('Сервер временно недоступен. Повторите позже.'); }
    if (!r.ok) { const err = new Error(d.error || 'Не удалось выполнить запрос.'); err.status = r.status; throw err; }
    return d;
  }
  const rub = x => S.rate && Number.isFinite(Number(x)) ? '≈ ' + rubF.format(Number(x) * Number(S.rate)) : '';

  // ---------- Диалог ----------
  const dlg = () => $('#dlg');
  function stopTimers() { S.timers.forEach(clearInterval); S.timers = []; }
  function open(html, wide = false) {
    stopTimers();
    const d = dlg(); $('#dlg-body').innerHTML = html; d.classList.toggle('wide', wide);
    if (!d.open) d.showModal();
  }
  function close() { stopTimers(); if (dlg().open) dlg().close(); }
  function msg(text, kind = 'error') { const m = $('#dlg-body .dlg-msg'); if (m) { m.textContent = text; m.className = 'dlg-msg ' + kind; } }
  async function busy(btn, fn) {
    if (btn?.disabled) return; if (btn) btn.disabled = true;
    try { return await fn(); } catch (err) { msg(err.message); } finally { if (btn?.isConnected) btn.disabled = false; }
  }

  // ---------- Данные ----------
  async function loadCatalog() {
    const [cat, rate] = await Promise.all([api('catalog'), api('rate').catch(() => ({}))]);
    S.cats = cat.categories; S.products = cat.products; S.rate = rate.rub_per_usd || null; S.loaded = true;
  }
  async function refreshMe() {
    try { S.user = await api('me'); S.csrf = S.user.csrf; } catch { S.user = null; }
    renderAccount();
  }
  function groups() {
    const list = S.cats.map(c => ({id:c.id, name:c.name, items:S.products.filter(p => p.category_id === c.id)}));
    const other = S.products.filter(p => !p.category_id || !S.cats.some(c => c.id === p.category_id));
    if (other.length) list.push({id:0, name:'Другое', items:other});
    const maxSold = Math.max(0, ...S.products.map(p => Number(p.sold) || 0));
    for (const g of list) {
      g.min = g.items.length ? Math.min(...g.items.map(p => Number(p.price))) : null;
      g.stock = g.items.reduce((n, p) => n + (Number(p.stock) || 0), 0);
      g.badge = maxSold > 0 && g.items.some(p => Number(p.sold) === maxSold) ? 'Popular' : g.items.some(p => p.is_new) ? 'New' : '';
    }
    return list;
  }
  const slug = name => String(name).toLowerCase().replace(/[^a-z0-9]+/g, '');

  // ---------- Отрисовка ----------
  function tile(name) {
    const dark = DARK_TILES.has(slug(name));
    return `<span class="tile${dark ? ' tile-dark' : ''}" aria-hidden="true"><span class="ring"></span><span class="ring ring2"></span><span class="tile-face"><span class="tile-mark">${e(String(name).slice(0, 1))}</span><span class="tile-name">${e(name)}</span></span><span class="drop d1"></span><span class="drop d2"></span></span>`;
  }
  function renderCats(list) {
    const all = [{id:null, name:'Все сервисы', count:list.reduce((n, g) => n + g.items.length, 0)}, ...list.map(g => ({id:g.id, name:g.name, count:g.items.length}))];
    $('#cats').innerHTML = all.map(c => `<button type="button" class="cat${S.filter === c.id ? ' on' : ''}" data-cat="${c.id ?? ''}"><span>${e(c.name)}</span><small>${c.count || ''}</small></button>`).join('');
  }
  function renderGrid() {
    const list = groups(); renderCats(list);
    const q = S.query.trim().toLowerCase();
    const shown = list.filter(g => (S.filter === null || g.id === S.filter) && (!q || g.name.toLowerCase().includes(q) || g.items.some(p => p.name.toLowerCase().includes(q))));
    $('#grid-title').textContent = S.filter === null ? 'Все сервисы' : (list.find(g => g.id === S.filter)?.name || 'Каталог');
    $('#grid').innerHTML = shown.length ? shown.map(g => `<button type="button" class="card${g.items.length ? '' : ' soon'}" data-group="${g.id}">
        ${g.badge ? `<span class="badge">${g.badge}</span>` : ''}${tile(g.name)}
        <span class="card-info"><span class="card-name">${e(g.name)}</span><span class="card-price">${g.items.length ? (g.stock ? 'от ' + usd(g.min) : 'Нет в наличии') : 'Скоро'}</span></span>
        <span class="card-go" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></span></button>`).join('')
      : '<p class="empty">Ничего не найдено.</p>';
  }
  function renderAccount() {
    const btn = $('#login-btn'); if (btn) btn.textContent = S.user ? (S.user.name || 'Профиль') : 'Войти';
    const box = $('#account-box'); if (!box) return;
    box.innerHTML = S.user
      ? `<button type="button" class="acc" data-action="account"><span class="acc-name">${e(S.user.name || 'Профиль')}</span><span class="acc-bal">Баланс ${usd(S.user.balance)}</span></button>`
      : `<button type="button" class="acc" data-action="auth"><span class="acc-name">Войти</span><span class="acc-bal">Telegram или почта</span></button>`;
  }

  // ---------- Сервис и тарифы ----------
  function showGroup(id) {
    const g = groups().find(x => String(x.id) === String(id)); if (!g) return;
    const rows = g.items.length ? g.items.map(p => `<div class="tariff">
        <div class="t-main"><strong>${e(p.name)}</strong>${p.description ? `<p>${e(p.description)}</p>` : ''}<span class="t-stock">${p.stock > 0 ? 'В наличии: ' + e(p.stock) : 'Нет в наличии'}</span></div>
        <div class="t-side"><span class="t-price">${usd(p.price)}</span><span class="t-rub">${rub(p.price)}</span>
          ${p.stock > 0 ? `<div class="qty"><button type="button" data-q="-1" aria-label="Меньше">−</button><output data-qty="${p.id}">1</output><button type="button" data-q="1" aria-label="Больше">+</button></div><button type="button" class="btn-buy" data-buy="${p.id}">Купить</button>` : ''}</div></div>`).join('')
      : '<p class="empty">Тарифы скоро появятся. Следи за новостями в нашем Telegram.</p>';
    open(`<div class="dlg-head">${tile(g.name)}<div><span class="kicker">Сервис</span><h3>${e(g.name)}</h3></div></div><div class="tariffs">${rows}</div><p class="dlg-msg"></p>`, true);
  }

  // ---------- Вход ----------
  let afterAuth = null;
  function authDialog(mode = 'login', then = null) {
    if (then) afterAuth = then;
    const reg = mode === 'register';
    open(`<span class="kicker">Аккаунт</span><h3>${reg ? 'Регистрация' : 'Вход'}</h3>
      <div class="tabs"><button type="button" class="${reg ? '' : 'on'}" data-mode="login">Вход</button><button type="button" class="${reg ? 'on' : ''}" data-mode="register">Регистрация</button></div>
      <form class="auth-form" id="auth-form" data-mode="${mode}" novalidate>
        ${reg ? '<label>Имя<input name="name" autocomplete="nickname" maxlength="64" placeholder="Как к тебе обращаться"></label>' : ''}
        <label>Почта<input name="email" type="email" autocomplete="${reg ? 'email' : 'username'}" required placeholder="you@mail.com"></label>
        <label>Пароль<input name="password" type="password" autocomplete="${reg ? 'new-password' : 'current-password'}" required minlength="8" maxlength="128" placeholder="${reg ? 'Минимум 8 символов' : 'Пароль'}"></label>
        <button class="btn-buy wide" type="submit">${reg ? 'Создать аккаунт' : 'Войти'}</button>
      </form>
      <div class="or"><span>или</span></div>
      <button type="button" class="btn-tg" data-action="tg-login"><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24"><path fill="currentColor" d="M21.4 3.6a1.3 1.3 0 0 0-1.36-.2L2.9 10.3a1 1 0 0 0 .06 1.88l4.3 1.43 1.62 5.06a.9.9 0 0 0 1.49.37l2.43-2.32 4.36 3.2a1.2 1.2 0 0 0 1.89-.71L21.83 4.9a1.3 1.3 0 0 0-.43-1.3ZM9.93 14.1l-.48 3.1-1.18-3.83 9.62-6.1Z"/></svg>Войти через Telegram</button>
      <p class="dlg-msg"></p>`);
    setTimeout(() => $('#auth-form input')?.focus(), 30);
  }
  async function signedIn() {
    await refreshMe();
    const next = afterAuth; afterAuth = null;
    if (next) await next(); else close();
  }
  async function submitAuth(form) {
    const reg = form.dataset.mode === 'register', f = new FormData(form);
    const body = {email: String(f.get('email') || ''), password: String(f.get('password') || '')};
    if (reg) body.name = String(f.get('name') || '');
    if (!body.email.includes('@')) return msg('Введите почту.');
    if (body.password.length < 8) return msg('Пароль должен быть не короче 8 символов.');
    const d = await api(reg ? 'auth/register' : 'auth/login', 'POST', body);
    S.csrf = d.csrf; await signedIn();
  }
  async function telegramLogin() {
    const d = await api('auth/link', 'POST', {});
    open(`<span class="kicker">Вход через Telegram</span><h3>Подтверди вход в боте</h3>
      <p class="muted">Открой бота и подтверди вход на сайт. Код в боте должен совпасть с этим:</p>
      <div class="code">${e(d.code)}</div>
      <a class="btn-buy wide" href="${e(d.url)}" target="_blank" rel="noopener noreferrer">Открыть бота</a>
      <p class="dlg-msg info">Ждём подтверждения…</p>`);
    let checking = false;
    S.timers.push(setInterval(async () => {
      if (checking || document.hidden || !dlg().open) return; checking = true;
      try {
        const s = await api('auth/status');
        if (s.status === 'approved') { stopTimers(); await signedIn(); }
        else if (s.status === 'expired' || s.status === 'denied') { stopTimers(); msg(s.status === 'denied' ? 'Вход отклонён.' : 'Время вышло. Попробуй ещё раз.'); }
      } catch {} finally { checking = false; }
    }, 2500));
  }
  function requireAuth(then) { if (S.user) return then(); authDialog('login', then); }

  // ---------- Оплата ----------
  async function buy(pid, qty) {
    requireAuth(async () => {
      open('<p class="muted">Создаём счёт…</p><p class="dlg-msg"></p>');
      try { showPayment(await api('checkout', 'POST', {purpose:'product', product_id:pid, quantity:qty})); }
      catch (err) { msg(err.status === 401 ? 'Войдите заново.' : err.message); if (err.status === 401) { S.user = null; renderAccount(); } }
    });
  }
  function showPayment(p) {
    const paid = p.status === 'paid', ready = p.status === 'pending' && p.url;
    const canBalance = ready && S.user && Number(S.user.balance) >= Number(p.amount);
    let body = `<span class="kicker">Счёт №${e(p.id)}</span><h3>${paid ? 'Оплата получена' : 'Оплата заказа'}</h3>
      <div class="bill"><div><span>Товар</span><strong>${e(p.name)}${p.quantity > 1 ? ' × ' + e(p.quantity) : ''}</strong></div>
      <div><span>К оплате</span><strong>${usd(p.amount)}${p.rubles ? ` <small>≈ ${rubF.format(Number(p.rubles))}</small>` : ''}</strong></div></div>`;
    if (paid) {
      if (p.outcome === 'product') {
        body += '<p class="dlg-msg ok">Готово! Твой товар ниже. Он также сохранён в «Мои покупки».</p>';
        (p.items || []).forEach((it, i) => { body += `<div class="item"><pre>${e(it)}</pre><button type="button" class="btn-copy" data-copy="${i}">Скопировать</button></div>`; });
      } else if (p.outcome === 'wallet_refund') body += '<p class="dlg-msg info">Товар закончился — вся сумма зачислена на твой баланс магазина.</p>';
      else body += '<p class="dlg-msg ok">Баланс пополнен.</p>';
    } else if (ready) {
      body += `<div class="pay-actions"><a class="btn-buy wide" href="${e(p.url)}" target="_blank" rel="noopener noreferrer">Оплатить через Crypto Bot ↗</a>
        ${canBalance ? `<button type="button" class="btn-ghost" data-action="pay-balance">Оплатить с баланса (${usd(S.user.balance)})</button>` : ''}
        <button type="button" class="btn-ghost" data-action="check">Я оплатил — проверить</button></div>
        <p class="muted small">Счёт действует 10 минут. После оплаты товар появится здесь автоматически.</p><p class="dlg-msg"></p>`;
    } else body += '<p class="dlg-msg info">Счёт закрыт или ещё обрабатывается. Проверь его в «Мои покупки».</p>';
    open(body);
    S.payment = p;
    if (ready) {
      let checking = false;
      S.timers.push(setInterval(async () => {
        if (checking || document.hidden || !dlg().open) return; checking = true;
        try { const fresh = await api('payments/' + p.id); if (fresh.status !== p.status) { showPayment(fresh); if (fresh.status === 'paid') afterPaid(); } }
        catch {} finally { checking = false; }
      }, 5000));
    }
  }
  async function afterPaid() { await refreshMe(); try { await loadCatalog(); renderGrid(); } catch {} }

  // ---------- Профиль и покупки ----------
  async function account() {
    await refreshMe(); if (!S.user) return authDialog();
    const who = S.user.email || (S.user.username ? '@' + S.user.username : 'Telegram');
    open(`<span class="kicker">Профиль</span><h3>${e(S.user.name || 'Профиль')}</h3><p class="muted">${e(who)}</p>
      <div class="bill"><div><span>Баланс</span><strong>${usd(S.user.balance)}</strong></div><div><span>Покупок</span><strong>${e(S.user.purchases)}</strong></div></div>
      <div class="pay-actions"><button type="button" class="btn-buy wide" data-action="orders">Мои покупки</button><button type="button" class="btn-ghost" data-action="logout">Выйти</button></div><p class="dlg-msg"></p>`);
  }
  async function orders() {
    const list = await api('orders');
    const rows = list.length ? list.map(p => `<button type="button" class="order" data-order="${p.id}"><span><strong>${e(p.purpose === 'topup' ? 'Пополнение' : p.name)}</strong><small>${new Date(p.created_at).toLocaleString('ru-RU')}</small></span><span class="o-side">${usd(p.amount)}<small class="st-${e(p.status)}">${p.status === 'paid' ? 'Оплачен' : p.status === 'pending' ? 'Ждёт оплаты' : 'Закрыт'}</small></span></button>`).join('')
      : '<p class="empty">Покупок пока нет.</p>';
    open(`<span class="kicker">Профиль</span><h3>Мои покупки</h3><div class="orders">${rows}</div><p class="dlg-msg"></p>`);
  }

  // ---------- События ----------
  document.addEventListener('click', ev => {
    const t = ev.target;
    const d = dlg();
    if (t === d) { const r = d.getBoundingClientRect(); if (ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom) close(); return; }
    if (t.closest('.dlg-close')) return close();
    if (t.closest('#login-btn')) { ev.preventDefault(); return S.user ? account() : authDialog(); }
    const cat = t.closest('[data-cat]'); if (cat) { S.filter = cat.dataset.cat === '' ? null : Number(cat.dataset.cat); return renderGrid(); }
    const card = t.closest('[data-group]'); if (card) return showGroup(card.dataset.group);
    const q = t.closest('[data-q]'); if (q) { const o = q.parentElement.querySelector('output'); const p = S.products.find(x => String(x.id) === o.dataset.qty); o.textContent = String(Math.max(1, Math.min(Number(p?.stock) || 1, 100, Number(o.textContent) + Number(q.dataset.q)))); return; }
    const b = t.closest('[data-buy]'); if (b) { const o = $(`output[data-qty="${b.dataset.buy}"]`); return buy(Number(b.dataset.buy), Number(o?.textContent) || 1); }
    const mode = t.closest('[data-mode]'); if (mode && mode.tagName === 'BUTTON') return authDialog(mode.dataset.mode);
    const copy = t.closest('[data-copy]'); if (copy && S.payment) { navigator.clipboard?.writeText(S.payment.items[Number(copy.dataset.copy)]).then(() => { copy.textContent = 'Скопировано'; }); return; }
    const ord = t.closest('[data-order]'); if (ord) return busy(ord, async () => showPayment(await api('payments/' + ord.dataset.order)));
    const a = t.closest('[data-action]'); if (!a) return;
    const act = a.dataset.action;
    if (act === 'auth') return authDialog();
    if (act === 'account') return account();
    if (act === 'tg-login') return busy(a, telegramLogin);
    if (act === 'orders') return busy(a, orders);
    if (act === 'logout') return busy(a, async () => { await api('auth/logout', 'POST', {}); S.user = null; S.csrf = ''; renderAccount(); close(); });
    if (act === 'check' && S.payment) return busy(a, async () => { const p = await api(`payments/${S.payment.id}/check`, 'POST', {}); showPayment(p); if (p.status === 'paid') afterPaid(); else msg('Оплата пока не поступила. Подожди минуту и проверь ещё раз.', 'info'); });
    if (act === 'pay-balance' && S.payment) return busy(a, async () => { showPayment(await api(`payments/${S.payment.id}/balance`, 'POST', {})); afterPaid(); });
  });
  document.addEventListener('submit', ev => { if (ev.target.id === 'auth-form') { ev.preventDefault(); busy(ev.target.querySelector('[type=submit]'), () => submitAuth(ev.target)); } });
  document.addEventListener('input', ev => { if (ev.target.id === 'cat-search') { S.query = ev.target.value; renderGrid(); } });
  document.addEventListener('DOMContentLoaded', async () => {
    dlg()?.addEventListener('close', stopTimers);
    renderAccount(); refreshMe();
    try { await loadCatalog(); renderGrid(); }
    catch (err) { $('#grid').innerHTML = `<p class="empty">${e(err.message)}</p>`; }
  });
})();
