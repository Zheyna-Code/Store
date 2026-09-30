'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usdFormat = new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'});
  const rubFormat = new Intl.NumberFormat('ru-RU', {style:'currency',currency:'RUB'});
  const usd = x => Number.isFinite(Number(x)) ? usdFormat.format(Number(x)) : '—';
  const state = {catalogError:false,user:null,csrf:'',bearer:'',products:[],categories:[],category:null,rate:null,view:'catalog',product:null,quantity:1,payment:null,loginTimer:null,paymentTimer:null};
  const tg = window.Telegram?.WebApp;
  const modal = $('#modal');
  let toastTimer;
  function toast(text) { $('#toast').textContent=text; $('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500); }
  async function api(path, method='GET', body) {
    const headers={};if(method!=='GET'){headers['Content-Type']='application/json';headers['X-CSRF-Token']=state.csrf;}
    if(state.bearer)headers.Authorization='Bearer '+state.bearer;
    const response=await fetch('/api/store/'+path,{method,credentials:'same-origin',headers,...(body===undefined?{}:{body:JSON.stringify(body)})});
    let data;try{data=await response.json();}catch{throw new Error('Сервер временно недоступен. Повторите позже.');}
    if(!response.ok)throw new Error(data.error||'Не удалось выполнить запрос.');return data;
  }
  function closeModal() { if(modal.open)modal.close(); }
  modal.addEventListener('close',()=>{clearInterval(state.loginTimer);clearInterval(state.paymentTimer);state.payment=null;$('#modal-body').replaceChildren();tg?.BackButton?.hide();});
  $('#close-modal').onclick=closeModal;
  modal.addEventListener('click',event=>{if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeModal();}});
  function dialog(title,kicker,html) { $('#modal-title').textContent=title;$('#modal-kicker').textContent=kicker;$('#modal-body').innerHTML=html;if(!modal.open)modal.showModal();tg?.BackButton?.show(); }
  function external(url) { const parsed=new URL(url,location.origin);if(parsed.protocol!=='https:')return; if(tg?.initData&&parsed.hostname==='t.me')tg.openTelegramLink(parsed.href);else window.open(parsed.href,'_blank','noopener,noreferrer'); }
  document.addEventListener('click',event=>{const link=event.target.closest('a[data-external]');if(link){event.preventDefault();external(link.href);}});
  async function busy(button,fn) { if(button?.disabled)return;if(button)button.disabled=true;try{return await fn();}catch(error){toast(error.message);}finally{if(button?.isConnected)button.disabled=false;} }
  function heading(title,label='ТВОЙ МАГАЗИН',subtitle='') { return `<div class="section-heading"><div><span class="eyebrow">${e(label)}</span><h2>${e(title)}</h2></div>${subtitle?`<p class="muted">${e(subtitle)}</p>`:''}</div>`; }
  function authGate(title) { return heading(title)+`<div class="empty-state"><img class="loading-mark" src="/storefront/icon.svg" width="32" height="32" alt=""><h3>Твой магазин — с тобой</h3><p>Войди через Telegram, чтобы увидеть баланс, бонусы и свои покупки. Пароль не нужен.</p><button class="btn btn-bright login-trigger">Войти через Telegram ↗</button></div>`; }
  function header() { $('#account').textContent=state.user ? `${state.user.name || 'Профиль'} · ${usd(state.user.balance)}` : 'Войти через Telegram ↗'; }
  async function refreshMe() { state.user=await api('me');state.csrf=state.user.csrf;header(); }
  async function login() {
    if(tg?.initData){await busy(null,async()=>{const d=await api('auth/telegram','POST',{initData:tg.initData});state.bearer=d.session;state.csrf=d.csrf;await refreshMe();await view(state.view);toast('Вход выполнен');});return;}
    dialog('Войти через Telegram','БЕЗ ПАРОЛЯ','<p class="modal-message">Готовим безопасный вход…</p>');
    try {
      const data=await api('auth/link','POST',{});if(!modal.open)return;
      dialog('Войти через Telegram','ПОДТВЕРДИ ВХОД',`<p class="modal-message">Открой нашего бота и подтверди вход на сайт. Сравни код в боте с кодом ниже. Если коды не совпадают — не подтверждай вход.</p><div class="login-code">${e(data.code)}</div><div class="modal-actions"><a class="btn btn-bright" data-external href="${e(data.url)}" target="_blank" rel="noopener noreferrer">Открыть @wanderersshop_bot ↗</a></div><p class="modal-message">После подтверждения вернись сюда. Запрос действует 5 минут.</p>`);
      let checking=false;
      state.loginTimer=setInterval(async()=>{if(checking||document.hidden||!modal.open)return;checking=true;try{const d=await api('auth/status');if(d.status==='approved'){await refreshMe();closeModal();await view(state.view);toast('Вход подтверждён');}else if(['expired','denied'].includes(d.status)){clearInterval(state.loginTimer);$('#modal-body').innerHTML='<p class="error-message">Вход не подтверждён или время истекло. Закрой окно и попробуй заново.</p>';}}catch{}finally{checking=false;}},2500);
    }catch(error){$('#modal-body').innerHTML=`<p class="error-message">${e(error.message)}</p>`;}
  }
  document.addEventListener('click',event=>{if(event.target.closest('.login-trigger')){if(state.user)profile();else login();}});
  function profile() {dialog(state.user.name||'Профиль','ТВОЙ TELEGRAM',`<p class="modal-message">${e(state.user.username?'@'+state.user.username:'Telegram ID '+state.user.id)}</p><div class="bill-row"><span>Баланс</span><strong>${usd(state.user.balance)}</strong></div><div class="bill-row"><span>Покупок</span><strong>${e(state.user.purchases)}</strong></div><div class="modal-actions"><button class="btn" id="logout">Выйти из сайта</button></div>`);$('#logout').onclick=()=>busy($('#logout'),async()=>{await api('auth/logout','POST',{});state.user=null;state.csrf='';state.bearer='';closeModal();header();await view(state.view);});}
  async function view(name) {
    if(!['catalog','wallet','bonus','orders'].includes(name))name='catalog';state.view=name;
    document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==name);
    document.querySelectorAll('[data-view]').forEach(el=>{if(el.dataset.view===name)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
    document.body.classList.toggle('page-authenticated',name!=='catalog');$('#hero').hidden=name!=='catalog';$('#how').hidden=name!=='catalog';
    history.replaceState(null,'','#'+name);
    if(name==='catalog'){renderProducts();return;}
    const el=$('#'+name);
    if(!state.user){el.innerHTML=authGate({wallet:'Кошелёк',bonus:'Бонус',orders:'Мои покупки'}[name]);return;}
    try{await refreshMe();}catch{state.user=null;header();el.innerHTML=authGate('Войди заново');return;}
    if(name==='wallet')wallet();else if(name==='bonus')bonus();else await orders();
  }
  $('.brand').onclick=event=>{event.preventDefault();closeModal();view('catalog');window.scrollTo({top:0,behavior:'smooth'});};
  $('.hero-button').onclick=event=>{event.preventDefault();view('catalog');$('#catalog').scrollIntoView({behavior:'smooth'});};
  document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{closeModal();view(button.dataset.view);window.scrollTo({top:0,behavior:'smooth'});});
  function categories() {$('#categories').innerHTML=[{id:null,name:'Все продукты'},...state.categories].map(c=>`<button class="category" data-category="${c.id??'all'}" aria-pressed="${state.category===c.id}">${e(c.name)}</button>`).join('');$('#categories').querySelectorAll('button').forEach(b=>b.onclick=()=>{state.category=b.dataset.category==='all'?null:Number(b.dataset.category);categories();renderProducts();});}
  function renderProducts() {
    if(state.catalogError)return;
    let products=state.products.filter(p=>(state.category===null||p.category_id===state.category)&&(p.name+' '+p.category_name+' '+p.description).toLocaleLowerCase('ru').includes($('#search').value.trim().toLocaleLowerCase('ru')));
    if($('#sort').value!=='default')products.sort((a,b)=>(Number(a.price)-Number(b.price))*($('#sort').value==='price-up'?1:-1));
    $('#catalog-count').textContent=`Найдено: ${products.length}`;
    $('#products').innerHTML=products.length?products.map(p=>`<article class="product-card"><div class="product-art">${p.cover?`<img src="${e(p.cover)}" alt="${e(p.category_name)}" loading="lazy">`:`<span>${e(p.category_name.slice(0,2).toUpperCase())}</span>`}</div><div class="product-body"><span class="product-category">${e(p.category_name)}</span><h3>${e(p.name)}</h3><p class="product-description">${e(p.description||'Описание и условия — в карточке товара.')}</p><div class="product-bottom"><span class="price">${usd(p.price)}</span><span class="stock ${p.stock?'':'stock-empty'}">${p.stock?'В наличии: '+p.stock:'Нет в наличии'}</span></div><button class="btn ${p.stock?'btn-positive':''}" data-product="${p.id}">${p.stock?'Выбрать продукт ↗':'Подробнее'}</button></div></article>`).join(''):`<div class="empty-state"><img class="loading-mark" src="/storefront/icon.svg" width="32" height="32" alt=""><h3>${state.products.length?'Ничего не найдено':'Товары появятся здесь'}</h3><p>${state.products.length?'Попробуй другую категорию или измени запрос.':'Мы обновляем каталог. Загляни немного позже или напиши в поддержку.'}</p><a class="btn" href="https://t.me/Ditzzmback" data-external>Написать в поддержку ↗</a></div>`;
    $('#products').querySelectorAll('[data-product]').forEach(b=>b.onclick=()=>product(Number(b.dataset.product)));
    $('#products').querySelectorAll('img').forEach(img=>img.onerror=()=>{const art=img.parentElement;art.textContent=img.alt.slice(0,2).toUpperCase();});
  }
  async function loadCatalog() {try{const d=await api('catalog');state.catalogError=false;state.products=d.products;state.categories=d.categories;categories();renderProducts();$('#policy-links').innerHTML=Object.entries(d.policies||{}).map(([key,url])=>`<a data-external href="${e(url)}" target="_blank" rel="noopener noreferrer">${e({warranty:'Гарантия',terms:'Условия',privacy:'Конфиденциальность'}[key]||key)}</a>`).join('');}catch(error){state.catalogError=true;$('#catalog-count').textContent='Временно недоступен';$('#products').innerHTML=`<div class="empty-state"><h3>Не удалось открыть каталог</h3><p>${e(error.message)}</p><button class="btn" id="retry-catalog">Попробовать снова</button></div>`;$('#retry-catalog').onclick=loadCatalog;}}
  let searchTimer;$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(renderProducts,120);};$('#sort').onchange=renderProducts;
  function product(id) {state.product=state.products.find(p=>p.id===id);state.quantity=1;drawProduct();}
  function drawProduct() {
    const p=state.product;if(!p)return;
    const sum=Number(p.price)*state.quantity;
    dialog(p.name,p.category_name,`<p class="detail-description">${e(p.description||'Уточни условия товара у администратора перед покупкой.')}</p><div class="detail-price"><span class="price">${usd(p.price)}</span><span class="stock ${p.stock?'':'stock-empty'}">${p.stock?'В наличии: '+p.stock:'Нет в наличии'}</span></div>${p.stock?`<div class="bill-row"><span>Количество</span><div class="quantity-control"><button id="qty-minus" aria-label="Уменьшить количество" ${state.quantity===1?'disabled':''}>−</button><output>${state.quantity} шт.</output><button id="qty-plus" aria-label="Увеличить количество" ${state.quantity>=Math.min(100,p.stock)?'disabled':''}>+</button></div></div><div class="bill-row"><span>Итого</span><strong>${usd(sum)}</strong></div><div class="modal-actions"><button id="product-checkout" class="btn btn-positive">Способы оплаты ↗</button></div><p class="modal-message">Счёт и резерв создаются только после выбора способов оплаты.</p><a class="btn btn-full" data-external href="${e(adminUrl({purpose:'product',name:p.name,quantity:state.quantity,amount:sum,rubles:state.rate?sum*Number(state.rate):null}))}">Уточнить оплату у администратора ↗</a>`:'<p class="notice">Сейчас товар закончился. Выбери другой продукт или уточни наличие у поддержки.</p>'}`);
    if(p.stock){$('#qty-minus').onclick=()=>{state.quantity=Math.max(1,state.quantity-1);drawProduct();};$('#qty-plus').onclick=()=>{state.quantity=Math.min(100,p.stock,state.quantity+1);drawProduct();};$('#product-checkout').onclick=()=>checkout({purpose:'product',product_id:p.id,quantity:state.quantity},$('#product-checkout'));}
  }
  function adminUrl(p) {const context=p.purpose==='topup'?'Хочу пополнить баланс магазина':`Хочу купить ${p.name} × ${p.quantity} шт.`;return 'https://t.me/Ditzzmback?'+new URLSearchParams({text:`Здравствуйте! ${context}. Сумма: ${p.amount} USD${p.rubles?' / ≈ '+rubFormat.format(Number(p.rubles)):''}. Подскажите, как оплатить.`});}
  async function checkout(data,button) {
    if(!state.user){await login();return;}
    await busy(button,async()=>{const p=await api('checkout','POST',data);showPayment(p);});
  }
  function showPayment(p) {
    clearInterval(state.paymentTimer);state.payment=p;
    const paid=p.status==='paid';const ready=p.status==='pending'&&p.url;
    let body=`<div class="bill-row"><span>${p.purpose==='topup'?'Пополнение':'Продукт'}</span><strong>${e(p.purpose==='topup'?'Кошелёк':p.name)}</strong></div>${p.purpose==='product'?`<div class="bill-row"><span>Количество</span><strong>${e(p.quantity)} шт.</strong></div>`:''}<div class="bill-row"><span>К оплате</span><strong>${usd(p.amount)}</strong></div>${p.rubles?`<div class="bill-row"><span>В рублях</span><strong>≈ ${rubFormat.format(Number(p.rubles))}</strong></div>`:''}`;
    if(paid){body+=`<p class="notice success">${p.outcome==='product'?'Оплата подтверждена. Твой товар ниже.':p.outcome==='wallet_refund'?'Товар недоступен, вся сумма возвращена на баланс магазина.':'Баланс пополнен.'}</p>`;for(const [index,item]of(p.items||[]).entries())body+=`<pre class="receipt">${e(item)}</pre><button class="btn btn-full" data-copy-item="${index}">Скопировать товар ${p.items.length>1?index+1:''}</button>`;}
    else if(ready){body+=`<div class="modal-actions"><a class="btn btn-positive" data-external href="${e(p.url)}" target="_blank" rel="noopener noreferrer">Оплатить через Crypto Bot ↗</a><button id="check-payment" class="btn">Проверить оплату</button>${p.purpose==='product'?'<button id="pay-balance" class="btn">Оплатить с баланса</button>':''}<a class="btn" data-external href="${e(adminUrl(p))}" target="_blank" rel="noopener noreferrer">Оплата через администратора ↗</a></div><p class="modal-message">Счёт действует 10 минут. После оплаты вернись сюда: подтверждение и товар появятся автоматически. Оплата через администратора подтверждается им вручную.</p>`;}
    else body+='<p class="notice">Счёт закрыт или ещё обрабатывается. Проверь его в покупках либо создай новый через карточку товара.</p>';
    dialog(paid?'Оплата подтверждена':'Способы оплаты','NEXUS STORE / CHECKOUT',body);
    $('#modal-body').querySelectorAll('[data-copy-item]').forEach(b=>b.onclick=()=>copy(p.items[Number(b.dataset.copyItem)]));
    if(ready){$('#check-payment').onclick=()=>busy($('#check-payment'),async()=>{showPayment(await api(`payments/${p.id}/check`,'POST',{}));if(state.payment.status==='paid')await refreshAfterPayment();});if($('#pay-balance'))$('#pay-balance').onclick=()=>busy($('#pay-balance'),async()=>{showPayment(await api(`payments/${p.id}/balance`,'POST',{}));await refreshAfterPayment();});
      let checking=false;state.paymentTimer=setInterval(async()=>{if(checking||document.hidden||!modal.open)return;checking=true;try{const fresh=await api(`payments/${p.id}`);if(fresh.status!==p.status){showPayment(fresh);if(fresh.status==='paid')await refreshAfterPayment();}}catch{}finally{checking=false;}},8000);
    }
  }
  async function refreshAfterPayment(){await refreshMe();await loadCatalog();if(state.view==='wallet')wallet();if(state.view==='bonus')bonus();if(state.view==='orders')await orders();}
  function wallet() {
    $('#wallet').innerHTML=heading('Кошелёк','ТВОЙ БАЛАНС')+`<div class="panel-grid"><div class="panel"><span class="eyebrow">ДОСТУПНО ДЛЯ ПОКУПОК</span><div class="balance-value">${usd(state.user.balance)}</div><p>Один баланс для сайта и Telegram. Оплачивай товары без создания отдельного криптоплатежа.</p><button class="btn" data-view-link="orders">Посмотреть покупки ↗</button></div><div class="panel"><h3>Пополнить баланс</h3><p>Выбери сумму в долларах. При оплате также покажем эквивалент в рублях.</p><div class="amount-options">${[1,3,5,10,25].map(a=>`<button data-amount="${a}">${usd(a)}</button>`).join('')}</div><label class="field" for="topup-amount">Сумма, USD</label><input class="text-input" id="topup-amount" inputmode="decimal" value="5.00" autocomplete="off" maxlength="12"><div class="panel-actions"><button class="btn btn-positive" id="wallet-checkout">Способы оплаты ↗</button><a id="topup-admin" class="btn" data-external>Оплата через администратора ↗</a></div></div></div>`;
    const updateAdmin=()=>{const amount=Number($('#topup-amount').value.trim().replace(',','.'));$('#topup-admin').href=adminUrl({purpose:'topup',amount:Number.isFinite(amount)&&amount>0?amount:0,rubles:state.rate&&amount>0?amount*Number(state.rate):null});};updateAdmin();$('#topup-amount').oninput=updateAdmin;$('#wallet').querySelectorAll('[data-amount]').forEach(b=>b.onclick=()=>{$('#topup-amount').value=Number(b.dataset.amount).toFixed(2);updateAdmin();});$('#wallet-checkout').onclick=()=>checkout({purpose:'topup',amount:$('#topup-amount').value.trim().replace(',','.')},$('#wallet-checkout'));$('#wallet').querySelector('[data-view-link]').onclick=()=>view('orders');
  }
  async function copy(text) {try{await navigator.clipboard.writeText(text);toast('Скопировано');}catch{toast('Выдели текст и скопируй вручную.');}}
  function bonus() {
    const r=state.user.referral;
    $('#bonus').innerHTML=heading('Бонус','ПРИГЛАШАЙ ДРУЗЕЙ')+`<div class="panel-grid"><div class="panel"><span class="eyebrow">ЗА ПЕРВУЮ ПОКУПКУ ДРУГА</span><div class="balance-value">5%</div><p>Поделись персональной ссылкой. Когда новый приглашённый пользователь совершит первую успешную покупку, бонус автоматически придёт на твой баланс.</p><div class="stats-row"><div><strong>${e(r.invited)}</strong><span>Приглашено друзей</span></div><div><strong>${usd(r.earned)}</strong><span>Начислено бонусов</span></div></div></div><div class="panel"><h3>Твоя реферальная ссылка</h3><p>Друг должен впервые запустить бота именно по ней.</p><div class="ref-link">${e(r.url)}</div><div class="panel-actions"><button id="copy-ref" class="btn btn-bright">Скопировать ссылку</button><a data-external class="btn" href="https://t.me/share/url?${e(new URLSearchParams({url:r.url,text:'Nexus Store — подписки и цифровые товары.'}).toString())}" target="_blank" rel="noopener noreferrer">Пригласить друга ↗</a></div></div></div>`;
    $('#copy-ref').onclick=()=>copy(r.url);
  }
  async function orders() {
    $('#orders').innerHTML=heading('Мои покупки','ТВОЙ ЦИФРОВОЙ ДОСТУП')+'<div class="empty-state"><p>Загружаем покупки…</p></div>';
    try{const rows=await api('orders');$('#orders').innerHTML=heading('Мои покупки','ТВОЙ ЦИФРОВОЙ ДОСТУП')+(rows.length?`<div class="order-list">${rows.map(p=>`<article class="panel order-row"><div><h3>${e(p.purpose==='topup'?'Пополнение кошелька':p.name)}</h3><p>${new Date(p.created_at).toLocaleDateString('ru-RU')} · ${p.purpose==='product'?e(p.quantity)+' шт. · ':''}${e({paid:'Оплачено',pending:'Ожидает оплаты',creating:'Обрабатывается',expired:'Истёк',failed:'Не создан',balance_ready:'Для оплаты с баланса'}[p.status]||'Закрыт')}</p></div><div class="order-right"><span class="price">${usd(p.amount)}</span><br><button class="btn" data-order="${p.id}">${p.status==='paid'&&p.outcome==='product'?'Открыть товар':'Открыть счёт'}</button></div></article>`).join('')}</div>`:'<div class="empty-state"><img class="loading-mark" src="/storefront/icon.svg" width="32" height="32" alt=""><h3>Твоя первая покупка впереди</h3><p>Здесь будут счета, пополнения и выданные товары.</p><button class="btn btn-bright" id="orders-catalog">Открыть каталог ↗</button></div>');$('#orders').querySelectorAll('[data-order]').forEach(b=>b.onclick=()=>busy(b,async()=>showPayment(await api('payments/'+b.dataset.order))));if($('#orders-catalog'))$('#orders-catalog').onclick=()=>view('catalog');}
    catch(error){$('#orders').innerHTML=heading('Мои покупки')+`<div class="empty-state"><p>${e(error.message)}</p><button class="btn" id="retry-orders">Попробовать снова</button></div>`;$('#retry-orders').onclick=orders;}
  }
  function telegramTheme(){if(tg?.initData){document.body.dataset.theme=tg.colorScheme==='light'?'light':'dark';try{tg.setHeaderColor(tg.colorScheme==='light'?'#f7f8fa':'#0b0c0f');tg.setBackgroundColor(tg.colorScheme==='light'?'#f7f8fa':'#0b0c0f');}catch{}}}
  async function start() {
    if(tg?.initData){tg.ready();tg.expand();telegramTheme();tg.onEvent('themeChanged',telegramTheme);tg.BackButton?.onClick(closeModal);try{const d=await api('auth/telegram','POST',{initData:tg.initData});state.bearer=d.session;state.csrf=d.csrf;await refreshMe();}catch(error){state.user=null;toast(error.message);}}
    else {try{await refreshMe();}catch{state.user=null;header();}}
    api('rate').then(d=>state.rate=d.rub_per_usd).catch(()=>{});
    await loadCatalog();await view(location.hash.slice(1)||'catalog');
  }
  start();
})();
