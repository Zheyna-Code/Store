const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('storefront/shop.js','utf8');
function harness({catalogError=false,mini=false,user=false,products=[]}={}){
 const nodes=new Map(),requests=[],timers=[],events=[];let error=catalogError;
 const node=s=>{if(!nodes.has(s))nodes.set(s,{value:'',textContent:'',innerHTML:'',hidden:false,open:false,dataset:{},classList:{toggle(){}},querySelectorAll(){return []},querySelector(sel){return node(sel)},setAttribute(){},removeAttribute(){},addEventListener(){},replaceChildren(){},showModal(){this.open=true},close(){this.open=false},scrollIntoView(){}});return nodes.get(s)};
 node('#sort').value='default';const me={name:'Test',balance:'1',csrf:'test-csrf',referral:{url:'https://t.me/test',invited:0,earned:'0'},purchases:0,id:10};
 const tg=mini?{initData:'SIGNED-RAW-TELEGRAM-DATA',initDataUnsafe:{user:{id:999}},colorScheme:'dark',ready(){this.didReady=true},expand(){},onEvent(){},setHeaderColor(){},setBackgroundColor(){},BackButton:{onClick(){},show(){},hide(){}}}:undefined;
 const context={Intl,URL,URLSearchParams,console,history:{replaceState(){}},location:{origin:'https://nexora.hostless.app',hash:''},navigator:{clipboard:{writeText:async()=>{}}},document:{querySelector:node,querySelectorAll(){return []},addEventListener(type,fn){if(type==='click')events.push(fn)},body:{classList:{toggle(){}},dataset:{}}},window:{Telegram:tg?{WebApp:tg}:undefined,scrollTo(){},open(){}},setTimeout,clearTimeout,setInterval:fn=>{timers.push(fn);return timers.length},clearInterval(){},fetch:async(url,options)=>{
  requests.push({url,...options});let status=200,d={};
  if(url.endsWith('/me')){status=user?200:401;d=user?me:{error:'Need login'}}
  else if(url.endsWith('/catalog')){status=error?503:200;d=error?{error:'Temporary error'}:{products,categories:[],policies:{}};}
  else if(url.endsWith('/rate'))d={rub_per_usd:'85'};
  else if(url.endsWith('/auth/telegram')){user=true;d={session:'mini-session',csrf:'test-csrf'}}
  else if(url.endsWith('/auth/link'))d={code:'123456',url:'https://t.me/wanderersshop_bot?start=auth_test'};
  else if(url.endsWith('/auth/logout')){user=false;d={ok:true}};
  return {ok:status===200,status,json:async()=>d};}};
 vm.runInNewContext(source,context);return {node,requests,timers,tg,context,login:()=>events.forEach(fn=>fn({target:{closest:sel=>sel==='.login-trigger'?node('#account'):null}})),recover:()=>error=false,tick:()=>new Promise(resolve=>setImmediate(resolve))};
}
test('catalog error remains visible at startup and retry recovers',async()=>{const h=harness({catalogError:true});await h.tick();assert.match(h.node('#products').innerHTML,/retry-catalog/);h.recover();await h.node('#retry-catalog').onclick();assert.match(h.node('#products').innerHTML,/Товары появятся здесь/);assert.equal(h.node('#catalog-count').textContent,'Найдено: 0');});
test('product text and attributes are escaped, never interpreted as HTML',async()=>{const h=harness({products:[{id:1,name:'<script>evil</script>',description:'<img src=x onerror=evil()>',category_name:'" onclick="bad',price:'1',stock:1,cover:null}]});await h.tick();const html=h.node('#products').innerHTML;assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>|<img src=x/);});
test('Mini App sends signed raw initData, ignores unsafe user identity and keeps bearer in memory',async()=>{const h=harness({mini:true});await h.tick();const login=h.requests.find(r=>r.url.endsWith('/auth/telegram'));assert.deepEqual(JSON.parse(login.body),{initData:'SIGNED-RAW-TELEGRAM-DATA'});assert.equal(h.requests.find(r=>r.url.endsWith('/me')).headers.Authorization,'Bearer mini-session');assert.equal(h.tg.didReady,true);assert.equal(h.context.document.body.dataset.theme,'dark');assert.doesNotMatch(source,/localStorage|sessionStorage/);});
test('home link switches view without a full-page navigation',async()=>{const h=harness();await h.tick();let prevented=false;h.node('.brand').onclick({preventDefault(){prevented=true}});assert.equal(prevented,true);assert.equal(h.node('#hero').hidden,false);});
test('browser login creates approval request and displays verification code',async()=>{const h=harness();await h.tick();h.login();await h.tick();assert.match(h.node('#modal-body').innerHTML,/123456/);assert.equal(h.node('#modal').open,true);assert.equal(h.timers.length,1);assert.equal(h.requests.find(r=>r.url.endsWith('/auth/link')).method,'POST');});
