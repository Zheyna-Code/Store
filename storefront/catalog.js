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
  const COVERS = {"chatgpt": "c96ea251", "claude": "c3b0326c", "gemini": "375082a0", "grok": "57166daf", "notion": "039baa03", "perplexity": "ed4b4ab6", "duolingo": "94b9d71b", "capcut": "5bd53255", "netflix": "33256db0", "spotify": "1cb9d96e"};
  const CART_KEY = 'nexus-cart';

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
  const go = '<span class="card-go" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h15m-6-6 6 6-6 6"/></svg></span>';
  const art = name => COVERS[slug(name)] ? `<img class="cover" src="/storefront/cover-${slug(name)}.webp?v=${COVERS[slug(name)]}" alt="" loading="lazy" decoding="async">` : tile(name);
  function renderGrid() {
    const list = groups(); renderCats(list);
    const q = S.query.trim().toLowerCase();
    const g = S.filter === null ? null : list.find(x => x.id === S.filter);
    if (S.filter !== null && !g) S.filter = null;
    $('#grid-title').textContent = g ? g.name : 'Все сервисы';
    $('#grid-back').hidden = !g; $('.main-head').classList.toggle('has-back', !!g);
    let html;
    if (!g) {
      const shown = list.filter(x => !q || x.name.toLowerCase().includes(q) || x.items.some(p => p.name.toLowerCase().includes(q)));
      html = shown.map(x => `<button type="button" class="card${x.items.length ? '' : ' soon'}" data-cat="${x.id}">
        ${x.badge ? `<span class="badge">${x.badge}</span>` : ''}${art(x.name)}
        <span class="card-info"><span class="card-name">${e(x.name)}</span><span class="card-price">${x.items.length ? `${x.items.length} ${plural(x.items.length)}${x.stock ? ' · от ' + usd(x.min) : ''}` : 'Скоро'}</span></span>${go}</button>`).join('');
    } else {
      const maxSold = Math.max(0, ...S.products.map(p => Number(p.sold) || 0));
      const shown = g.items.filter(p => !q || p.name.toLowerCase().includes(q));
      html = shown.map(p => `<button type="button" class="card${p.stock > 0 ? '' : ' soon'}" data-product="${p.id}">
        ${maxSold > 0 && Number(p.sold) === maxSold ? '<span class="badge">Popular</span>' : p.is_new ? '<span class="badge">New</span>' : ''}${art(g.name)}
        <span class="card-info"><span class="card-name">${e(p.name)}</span><span class="card-price">${usd(p.price)}${p.stock > 0 ? '' : ' · нет в наличии'}</span></span>${go}</button>`).join('');
      if (!g.items.length) html = '<p class="empty">Товары этой категории скоро появятся.</p>';
    }
    $('#grid').innerHTML = html || '<p class="empty">Ничего не найдено.</p>';
  }
  const plural = n => n % 10 === 1 && n % 100 !== 11 ? 'товар' : [2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100) ? 'товара' : 'товаров';
  function renderAccount() {
    const btn = $('#login-btn'); if (btn) btn.textContent = S.user ? (S.user.name || 'Профиль') : 'Войти';
    const box = $('#account-box'); if (!box) return;
    box.innerHTML = S.user
      ? `<button type="button" class="acc" data-action="account"><span class="acc-name">${e(S.user.name || 'Профиль')}</span><span class="acc-bal">Баланс ${usd(S.user.balance)}</span></button>`
      : `<button type="button" class="acc" data-action="auth"><span class="acc-name">Войти</span><span class="acc-bal">Telegram или почта</span></button>`;
  }

  // ---------- Сервис и тарифы ----------
  function showProduct(id) {
    const p = S.products.find(x => String(x.id) === String(id)); if (!p) return;
    const cat = S.cats.find(c => c.id === p.category_id)?.name || p.category_name || '';
    const img = COVERS[slug(cat)] ? `<img class="dlg-cover" src="/storefront/cover-${slug(cat)}.webp?v=${COVERS[slug(cat)]}" alt="">` : tile(cat || p.name);
    open(`<div class="dlg-head">${img}<div><span class="kicker">${e(cat || 'Товар')}</span><h3>${e(p.name)}</h3></div></div>
      ${p.description ? `<p class="muted desc">${e(p.description)}</p>` : ''}
      <div class="bill"><div><span>Цена</span><strong>${usd(p.price)}${rub(p.price) ? ` <small>${rub(p.price)}</small>` : ''}</strong></div><div><span>В наличии</span><strong>${p.stock > 0 ? e(p.stock) + ' шт.' : 'нет'}</strong></div></div>
      ${p.stock > 0 ? `<div class="buy-row"><div class="qty"><button type="button" data-q="-1" aria-label="Меньше">−</button><output data-qty="${p.id}">1</output><button type="button" data-q="1" aria-label="Больше">+</button></div>
        <button type="button" class="btn-ghost" data-add="${p.id}">В корзину</button><button type="button" class="btn-buy" data-buy="${p.id}">Купить</button></div>`
        : '<p class="dlg-msg info">Сейчас нет в наличии. Загляни позже или напиши нам в Telegram.</p>'}<p class="dlg-msg"></p>`);
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
  async function buy(pid, qty, fromCart = false) {
    S.cartPid = fromCart ? pid : null;
    requireAuth(async () => {
      open('<p class="muted">Создаём счёт…</p><p class="dlg-msg"></p>');
      try { showPayment(await api('checkout', 'POST', {purpose:'product', product_id:pid, quantity:qty})); }
      catch (err) { msg(err.status === 401 ? 'Войдите заново.' : err.message); if (err.status === 401) { S.user = null; renderAccount(); } }
    });
  }
  const ADMIN = 'https://t.me/Ditzzmback';
  function adminUrl(p) {
    const who = S.user ? (S.user.email || (S.user.username ? '@' + S.user.username : 'ID ' + S.user.id)) : '';
    const text = `Здравствуйте! Хочу оплатить заказ №${p.id} на сайте: ${p.name} × ${p.quantity} шт. Сумма: ${p.amount} USD${p.rubles ? ' / ≈ ' + rubF.format(Number(p.rubles)) : ''}.${who ? ' Аккаунт: ' + who + '.' : ''} Подскажите, как оплатить.`;
    return ADMIN + '?text=' + encodeURIComponent(text);
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
        <a class="btn-ghost" href="${e(adminUrl(p))}" target="_blank" rel="noopener noreferrer">Оплатить через администратора ↗</a>
        <button type="button" class="btn-ghost" data-action="check">Я оплатил — проверить</button></div>
        <p class="muted small">Счёт Crypto Bot действует 10 минут — после оплаты товар появится здесь автоматически. Оплату через администратора (@Ditzzmback) он подтверждает вручную.</p><p class="dlg-msg"></p>`;
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
  async function afterPaid() { if (S.cartPid) { cartSave(cartLoad().filter(x => x.id !== S.cartPid)); S.cartPid = null; } await refreshMe(); try { await loadCatalog(); renderGrid(); } catch {} }

  // ---------- Корзина ----------
  function cartLoad() { try { const c = JSON.parse(localStorage.getItem(CART_KEY) || '[]'); return Array.isArray(c) ? c.filter(x => Number.isInteger(x.id) && x.qty > 0) : []; } catch { return []; } }
  function cartSave(c) { try { localStorage.setItem(CART_KEY, JSON.stringify(c)); } catch {} cartBadge(); }
  function cartBadge() { const n = cartLoad().reduce((a, x) => a + x.qty, 0), el = $('#cart-count'); if (el) { el.textContent = String(n); el.hidden = !n; } }
  function cartAdd(id, qty) {
    const c = cartLoad(), p = S.products.find(x => x.id === id), cur = c.find(x => x.id === id);
    const max = Math.min(Number(p?.stock) || 1, 100);
    if (cur) cur.qty = Math.min(max, cur.qty + qty); else c.push({id, qty:Math.min(max, qty)});
    cartSave(c);
  }
  function cartItems() { return cartLoad().map(x => ({...x, p:S.products.find(p => p.id === x.id)})).filter(x => x.p); }
  function showCart() {
    const items = cartItems();
    if (!items.length) return open('<span class="kicker">Корзина</span><h3>Корзина пуста</h3><p class="muted">Открой сервис в каталоге и нажми «В корзину».</p><p class="dlg-msg"></p>');
    const total = items.reduce((a, x) => a + Number(x.p.price) * x.qty, 0);
    const canAll = S.user && Number(S.user.balance) >= total;
    open(`<span class="kicker">Корзина</span><h3>Твой заказ</h3><div class="cart-list">${items.map(x => `<div class="cart-row">
        <div class="t-main"><strong>${e(x.p.name)}</strong><span class="t-stock">${usd(x.p.price)} × ${x.qty}${x.p.stock > 0 ? '' : ' · нет в наличии'}</span></div>
        <div class="cart-side"><div class="qty"><button type="button" data-cq="-1" data-id="${x.id}" aria-label="Меньше">−</button><output>${x.qty}</output><button type="button" data-cq="1" data-id="${x.id}" aria-label="Больше">+</button></div>
        ${x.p.stock > 0 ? `<button type="button" class="btn-buy small-btn" data-cpay="${x.id}">Оплатить</button>` : ''}<button type="button" class="btn-x" data-cdel="${x.id}" aria-label="Удалить">×</button></div></div>`).join('')}</div>
      <div class="bill"><div><span>Итого</span><strong>${usd(total)}${rub(total) ? ` <small>${rub(total)}</small>` : ''}</strong></div></div>
      <div class="pay-actions">${canAll ? `<button type="button" class="btn-buy wide" data-action="cart-balance">Оплатить всё с баланса (${usd(S.user.balance)})</button>` : `<p class="muted small">${S.user ? 'Каждый товар оплачивается отдельным счётом: Crypto Bot или через администратора. Чтобы оплатить всё сразу, пополни баланс.' : 'Чтобы оплатить, войди в аккаунт.'}</p>`}</div><p class="dlg-msg"></p>`);
  }
  async function cartBalance() {
    const items = cartItems().filter(x => x.p.stock > 0), got = [];
    for (const x of items) {
      const p = await api('checkout', 'POST', {purpose:'product', product_id:x.id, quantity:x.qty});
      const paid = await api(`payments/${p.id}/balance`, 'POST', {});
      got.push(paid); cartSave(cartLoad().filter(c => c.id !== x.id));
    }
    await afterPaid();
    S.payment = {items: got.flatMap(p => p.items || [])};
    let i = 0;
    open(`<span class="kicker">Корзина</span><h3>Оплата получена</h3><p class="dlg-msg ok">Готово! Товары ниже и в «Мои покупки».</p>${got.map(p => `<p class="muted"><strong>${e(p.name)}</strong> × ${e(p.quantity)}</p>${(p.items || []).map(it => `<div class="item"><pre>${e(it)}</pre><button type="button" class="btn-copy" data-copy="${i++}">Скопировать</button></div>`).join('')}`).join('')}`);
  }

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
    const cat = t.closest('[data-cat]'); if (cat) { S.filter = cat.dataset.cat === '' ? null : Number(cat.dataset.cat); S.query = ''; const si = $('#cat-search'); if (si) si.value = ''; renderGrid(); $('#grid').scrollTop = 0; return; }
    if (t.closest('#grid-back')) { S.filter = null; renderGrid(); return; }
    const card = t.closest('[data-product]'); if (card) return showProduct(card.dataset.product);
    const q = t.closest('[data-q]'); if (q) { const o = q.parentElement.querySelector('output'); const p = S.products.find(x => String(x.id) === o.dataset.qty); o.textContent = String(Math.max(1, Math.min(Number(p?.stock) || 1, 100, Number(o.textContent) + Number(q.dataset.q)))); return; }
    if (t.closest('#cart-btn')) return showCart();
    const add = t.closest('[data-add]'); if (add) { const o = $(`output[data-qty="${add.dataset.add}"]`); cartAdd(Number(add.dataset.add), Number(o?.textContent) || 1); add.textContent = 'Добавлено ✓'; return; }
    const cq = t.closest('[data-cq]'); if (cq) { const c = cartLoad(), it = c.find(x => x.id === Number(cq.dataset.id)), p = S.products.find(x => x.id === it?.id); if (it) { it.qty = Math.max(1, Math.min(Number(p?.stock) || 1, 100, it.qty + Number(cq.dataset.cq))); cartSave(c); } return showCart(); }
    const cdel = t.closest('[data-cdel]'); if (cdel) { cartSave(cartLoad().filter(x => x.id !== Number(cdel.dataset.cdel))); return showCart(); }
    const cpay = t.closest('[data-cpay]'); if (cpay) { const id = Number(cpay.dataset.cpay), it = cartLoad().find(x => x.id === id); return buy(id, it?.qty || 1, true); }
    const b = t.closest('[data-buy]'); if (b) { const o = $(`output[data-qty="${b.dataset.buy}"]`); return buy(Number(b.dataset.buy), Number(o?.textContent) || 1); }
    const mode = t.closest('[data-mode]'); if (mode && mode.tagName === 'BUTTON') return authDialog(mode.dataset.mode);
    const copy = t.closest('[data-copy]'); if (copy && S.payment) { navigator.clipboard?.writeText(S.payment.items[Number(copy.dataset.copy)]).then(() => { copy.textContent = 'Скопировано'; }); return; }
    const ord = t.closest('[data-order]'); if (ord) return busy(ord, async () => showPayment(await api('payments/' + ord.dataset.order)));
    const a = t.closest('[data-action]'); if (!a) return;
    const act = a.dataset.action;
    if (act === 'cart-balance') return busy(a, cartBalance);
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
    renderAccount(); refreshMe(); cartBadge();
    try { await loadCatalog(); renderGrid(); cartSave(cartLoad().filter(x => S.products.some(p => p.id === x.id))); }
    catch (err) { $('#grid').innerHTML = `<p class="empty">${e(err.message)}</p>`; }
  });
})();
