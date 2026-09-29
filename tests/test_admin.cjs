// Dependency-free request/load regression tests: node --test tests/test_admin.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'admin.js'), 'utf8');

function setup(fetch) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, textContent: '', value: '',
      addEventListener() {}, querySelectorAll: () => [],
      classList: { add() {}, remove() {} },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    fetch, AbortController, URL, Intl, console,
    setTimeout, clearTimeout, setInterval: () => 0,
    localStorage: { getItem: () => '', setItem() {}, removeItem() {} },
    location: { hash: '#/products' }, window: { addEventListener() {} },
    document: { getElementById: element, addEventListener() {} },
  });
  vm.runInContext(source, context);
  vm.runInContext('token = "test"; render = () => {}; toast = () => {};', context);
  return { run: code => vm.runInContext(code, context), element };
}
const response = (data = [], status = 200) => ({ ok: status < 400, status, json: async () => data });

test('identical GETs share one request and settled work is released', async () => {
  let calls = 0;
  const app = setup(async () => { calls++; await new Promise(r => setTimeout(r, 10)); return response(); });
  await app.run('Promise.all([api("/products"), api("/products"), api("/products")])');
  assert.equal(calls, 1);
  await app.run('api("/products")');
  assert.equal(calls, 2);
});

test('writes are neither combined nor retried', async () => {
  let calls = 0;
  const app = setup(async () => { calls++; return response({ error: 'failure' }, 500); });
  await app.run('Promise.allSettled([api("/products", {method:"POST", body:{name:"A"}}), api("/products", {method:"POST", body:{name:"A"}})])');
  assert.equal(calls, 2);
});

test('products load only the required datasets, shared refresh runs once', async () => {
  const paths = [];
  const app = setup(async url => { paths.push(url); return response(); });
  app.run('state.page = "products";');
  await app.run('Promise.all([loadAll(), loadAll(), loadAll()])');
  assert.deepEqual(paths.sort(), ['/api/admin/categories', '/api/admin/emojis/settings', '/api/admin/orders', '/api/admin/products']);
  paths.length = 0;
  await app.run('loadAll()');
  assert.equal(paths.length, 3);
});

test('failed first primary load is rejected, cached data survives a later outage', async () => {
  let failing = true;
  const app = setup(async url => response([], url.endsWith('/products') && failing ? 503 : 200));
  app.run('state.page = "products";');
  await assert.rejects(app.run('loadAll()'));
  assert.equal(app.run('loadedData.has("products")'), false);
  failing = false;
  await app.run('loadAll()');
  failing = true;
  await app.run('loadAll()');
  assert.equal(app.run('loadedData.has("products")'), true);
});

test('an old unauthorized response cannot log out the new session', async () => {
  let resolve;
  const app = setup(() => new Promise(r => { resolve = r; }));
  const request = app.run('api("/products")');
  app.run('token = "new-session";');
  resolve(response({}, 401));
  await assert.rejects(request, error => error.status === 401);
  assert.equal(app.run('token'), 'new-session');
  assert.equal(app.element('login').hidden, false); // unchanged by the old response
});

test('current unauthorized response clears session and cached datasets', async () => {
  const app = setup(async () => response({}, 401));
  app.run('loadedData.add("products"); state.products = [{id:1}];');
  await assert.rejects(app.run('api("/products")'), error => error.status === 401);
  assert.equal(app.run('token'), '');
  assert.equal(app.run('loadedData.size'), 0);
  assert.equal(app.run('state.products.length'), 0);
});

test('late analytics for an old period never replaces the selected period', async () => {
  let oldResponse;
  const app = setup(url => url.includes('days=30') ? new Promise(r => { oldResponse = r; }) : Promise.resolve(response(url.includes('/analytics') ? {days:7} : url.endsWith('/dashboard') || url.endsWith('/settings') ? {} : [])));
  app.run('state.page="dashboard"; state.days=30;');
  const oldLoad = app.run('loadAll()');
  app.run('state.days=7;');
  await app.run('loadAll()');
  oldResponse(response({days:30}));
  await oldLoad;
  assert.equal(app.run('state.analytics.days'), 7);
});
