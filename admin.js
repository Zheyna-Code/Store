const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const money = value => new Intl.NumberFormat('ru-RU', {style:'currency',currency:'RUB'}).format(Number(value));
let token = localStorage.getItem('nexus_admin_token') || '';
let categories = [], products = [], stockItems = [];

function notice(message, bad = false) {
  const box = $('notice'); box.textContent = message; box.classList.toggle('bad', bad); box.hidden = false;
  clearTimeout(notice.timer); notice.timer = setTimeout(() => box.hidden = true, 4000);
}
function logout() {
  token = ''; localStorage.removeItem('nexus_admin_token'); $('app').hidden = true; $('login').hidden = false;
}
async function api(path, options = {}) {
  const response = await fetch('/api/admin' + path, {
    ...options, headers: {'Content-Type':'application/json','X-Admin-Token':token,...options.headers}
  });
  let data;
  try { data = await response.json(); } catch { throw Error('Сервер вернул некорректный ответ'); }
  if (response.status === 401) { logout(); throw Error('Войдите в панель заново'); }
  if (!response.ok) throw Error(data.error || `Ошибка ${response.status}`);
  return data;
}
async function safe(work) { try { await work(); } catch (error) { notice(error.message, true); } }
const titles = {
  dashboard:['Обзор магазина','Продажи, посещения и популярные категории'],
  products:['Товары','Управление ассортиментом и автовыдачей'],
  categories:['Категории','Структура каталога магазина'],
  customers:['Покупатели','Клиенты, покупки и баланс'],
  orders:['Покупки','История заказов магазина']
};
function show(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === view));
  document.querySelectorAll('[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('pageTitle').textContent = titles[view][0]; $('pageSubtitle').textContent = titles[view][1];
  safe({dashboard:loadDashboard,products:loadProducts,categories:loadCategories,customers:loadCustomers,orders:loadOrders}[view]);
}
function modal(html) { $('modalContent').innerHTML = html; $('modal').hidden = false; }
function closeModal() { $('modal').hidden = true; $('modalContent').innerHTML = ''; }
const statusPill = active => `<span class="pill ${active?'':'off'}">${active?'Активен':'Скрыт'}</span>`;

async function loadDashboard() {
  const data = await api('/dashboard');
  const metrics = [
    ['↗','Всего заработано',money(data.revenue)],['◴','Заработано сегодня',money(data.today_revenue)],
    ['▣','Оплаченных покупок',data.orders],['◉','Посещений сегодня',data.today_visits]
  ];
  $('metrics').innerHTML = metrics.map(([icon,label,value]) => `<div class="metric"><i>${icon}</i><small>${label}</small><strong>${value}</strong></div>`).join('');
  $('tops').innerHTML = data.top_categories.length ? data.top_categories.map((item,index) => `<tr><td>${index+1}</td><td><b>${escapeHtml(item.name)}</b></td><td>${item.sales}</td><td>${money(item.revenue)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">Продаж пока нет. Рейтинг появится после первой оплаченной покупки.</td></tr>';
}
async function loadCategories() {
  categories = await api('/categories');
  $('categoryRows').innerHTML = categories.length ? categories.map(item => `<tr><td><b>${escapeHtml(item.name)}</b></td><td>${item.sort_order}</td><td>${statusPill(item.is_active)}</td><td class="actions"><button class="secondary" data-action="edit-category" data-id="${item.id}">Изменить</button></td></tr>`).join('') : '<tr><td colspan="4" class="empty">Категории пока не добавлены</td></tr>';
}
async function loadProducts() {
  [categories,products] = await Promise.all([api('/categories'),api('/products')]);
  $('productRows').innerHTML = products.length ? products.map(item => `<tr><td><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.description)}</small></td><td>${escapeHtml(item.category_name || 'Без категории')}</td><td><b>${money(item.price)}</b></td><td>${item.stock_count} шт.</td><td>${statusPill(item.is_active)}</td><td class="actions"><button class="secondary" data-action="edit-product" data-id="${item.id}">Изменить</button><button class="secondary" data-action="stock" data-id="${item.id}">Автовыдача</button><button class="danger" data-action="delete-product" data-id="${item.id}">Удалить</button></td></tr>`).join('') : '<tr><td colspan="6" class="empty">Создайте первый товар и выберите для него категорию</td></tr>';
}
function categoryForm(id) {
  const item = categories.find(row => row.id === id) || {name:'',sort_order:categories.length+1,is_active:true};
  modal(`<h2>${id?'Изменить категорию':'Новая категория'}</h2><form id="categoryForm" class="form"><label>Название<input name="name" value="${escapeHtml(item.name)}" required maxlength="80"></label><label>Порядок показа<input name="sort_order" type="number" value="${item.sort_order}" required></label><label class="check"><input name="is_active" type="checkbox" ${item.is_active?'checked':''}> Показывать в каталоге</label><div class="form-actions"><button type="button" class="secondary" data-action="close">Отмена</button><button class="primary">Сохранить</button></div></form>`);
  $('categoryForm').onsubmit = event => safe(async () => {
    event.preventDefault(); const form = new FormData(event.target);
    await api('/categories'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify({name:form.get('name').trim(),sort_order:Number(form.get('sort_order')),is_active:form.has('is_active')})});
    closeModal(); await loadCategories(); notice('Категория сохранена');
  });
}
function productForm(id) {
  const item = products.find(row => row.id === id) || {name:'',description:'',price:'0',category_id:'',is_active:true};
  modal(`<h2>${id?'Изменить товар':'Новый товар'}</h2><form id="productForm" class="form"><label>Название<input name="name" value="${escapeHtml(item.name)}" required maxlength="150" placeholder="Например, ChatGPT Plus"></label><label>Описание<textarea name="description" placeholder="Что получит покупатель">${escapeHtml(item.description)}</textarea></label><div class="form-row"><label>Цена, ₽<input name="price" type="number" min="0.01" step="0.01" value="${item.price}" required></label><label>Категория<select name="category_id" required><option value="">Выберите категорию</option>${categories.map(c => `<option value="${c.id}" ${String(c.id)===String(item.category_id)?'selected':''}>${escapeHtml(c.name)}</option>`).join('')}</select></label></div><label class="check"><input name="is_active" type="checkbox" ${item.is_active?'checked':''}> Активный товар</label><div class="form-actions"><button type="button" class="secondary" data-action="close">Отмена</button><button class="primary">Сохранить</button></div></form>`);
  $('productForm').onsubmit = event => safe(async () => {
    event.preventDefault(); const form = new FormData(event.target);
    await api('/products'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify({name:form.get('name').trim(),description:form.get('description').trim(),price:form.get('price'),category_id:Number(form.get('category_id')),is_active:form.has('is_active')})});
    closeModal(); await loadProducts(); notice('Товар сохранён');
  });
}
function renderStock() {
  const holder = $('stockList');
  holder.innerHTML = stockItems.length ? stockItems.map((value,index) => `<div class="stock-line"><input data-stock-index="${index}" value="${escapeHtml(value)}" aria-label="Позиция ${index+1}"><button type="button" class="danger" data-action="remove-stock" data-index="${index}">Удалить</button></div>`).join('') : '<p class="hint">Пока нет позиций. Добавьте ключ или аккаунт ниже.</p>';
  holder.querySelectorAll('input').forEach(input => input.oninput = () => { stockItems[Number(input.dataset.stockIndex)] = input.value; });
}
async function stockForm(id) {
  const product = products.find(row => row.id === id);
  const records = await api(`/products/${id}/stock`);
  stockItems = records.filter(row => !row.is_issued).map(row => row.payload);
  modal(`<h2>Автовыдача · ${escapeHtml(product.name)}</h2><p class="hint">Каждая строка — отдельная выдаваемая позиция. Можно изменить, удалить или добавить запись в любом месте. Уже выданные позиции сохраняются отдельно.</p><div id="stockList" class="stock-list"></div><div class="form-row"><input id="newStock" placeholder="Новая позиция"><button class="secondary" data-action="add-stock">+ Добавить</button></div><p class="hint">Выдано ранее: ${records.filter(row => row.is_issued).length}</p><div class="form-actions"><button class="secondary" data-action="close">Отмена</button><button class="primary" data-action="save-stock" data-id="${id}">Сохранить список</button></div>`);
  renderStock();
}
async function loadCustomers() {
  const rows = await api('/customers?q='+encodeURIComponent($('customerSearch').value));
  $('customerRows').innerHTML = rows.length ? rows.map(row => `<tr><td>${row.username?'@'+escapeHtml(row.username):'—'}</td><td>${escapeHtml(row.first_name)}<small>ID ${row.telegram_id}</small></td><td>${money(row.balance)}</td><td>${row.purchases}</td><td class="actions">${row.username?`<button class="secondary" data-action="grant" data-username="${escapeHtml(row.username)}">Выдать баланс</button>`:''}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">Покупатели появятся после входа в бот</td></tr>';
}
function grantForm(username) {
  modal(`<h2>Баланс · @${escapeHtml(username)}</h2><form id="grantForm" class="form"><label>Сумма, ₽<input name="amount" type="number" min="0.01" step="0.01" required></label><label>Причина<input name="reason" value="Выдано администратором"></label><div class="form-actions"><button type="button" class="secondary" data-action="close">Отмена</button><button class="primary">Зачислить</button></div></form>`);
  $('grantForm').onsubmit = event => safe(async () => {
    event.preventDefault(); const form = new FormData(event.target);
    await api('/customers/'+encodeURIComponent(username)+'/balance',{method:'POST',body:JSON.stringify({amount:form.get('amount'),reason:form.get('reason')})});
    closeModal(); await loadCustomers(); notice('Баланс зачислен');
  });
}
async function loadOrders() {
  const rows = await api('/orders');
  $('orderRows').innerHTML = rows.length ? rows.map(row => `<tr><td>${new Date(row.created_at).toLocaleString('ru-RU')}</td><td>${row.username?'@'+escapeHtml(row.username):escapeHtml(row.first_name||'—')}</td><td>${escapeHtml(row.product_name||'Удалённый товар')}</td><td>${money(row.amount)}</td><td>${escapeHtml(row.status)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">Покупок пока нет</td></tr>';
}

document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.view) return show(button.dataset.view);
  const id = Number(button.dataset.id);
  switch(button.dataset.action) {
    case 'close': closeModal(); break;
    case 'edit-category': categoryForm(id); break;
    case 'edit-product': productForm(id); break;
    case 'stock': safe(() => stockForm(id)); break;
    case 'delete-product': if (confirm('Удалить товар? Невыданные позиции также будут удалены.')) safe(async () => { await api('/products/'+id,{method:'DELETE'}); await loadProducts(); notice('Товар удалён'); }); break;
    case 'remove-stock': stockItems.splice(Number(button.dataset.index),1); renderStock(); break;
    case 'add-stock': { const input=$('newStock'); if(input.value.trim()){stockItems.push(input.value.trim());input.value='';renderStock();} break; }
    case 'save-stock': safe(async () => { await api(`/products/${id}/stock`,{method:'PUT',body:JSON.stringify({items:stockItems.filter(value => value.trim()).map(value => value.trim())})}); closeModal(); await loadProducts(); notice('Автовыдача сохранена'); }); break;
    case 'grant': grantForm(button.dataset.username); break;
  }
});
$('addProduct').onclick = () => productForm(null);
$('addCategory').onclick = () => categoryForm(null);
$('searchCustomers').onclick = () => safe(loadCustomers);
$('customerSearch').onkeydown = event => { if(event.key==='Enter') safe(loadCustomers); };
$('logout').onclick = logout;
$('closeModal').onclick = closeModal;
$('modal').onclick = event => { if(event.target === $('modal')) closeModal(); };
$('loginForm').onsubmit = event => safe(async () => {
  event.preventDefault(); $('loginError').textContent = '';
  const response = await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:$('secret').value})});
  const data = await response.json();
  if (!response.ok || !data.token) { $('loginError').textContent = data.error || 'Неверный ключ'; return; }
  token = data.token; localStorage.setItem('nexus_admin_token',token); $('login').hidden = true; $('app').hidden = false; show('dashboard');
});
if (token) { $('login').hidden = true; $('app').hidden = false; show('dashboard'); }
