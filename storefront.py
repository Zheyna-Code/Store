"""Public shop, same-origin authenticated API and existing payment service integration."""
import base64
import functools
import hmac
import json
import re
import time
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from crypto_pay import money,quantity,PaymentError
from referrals import referral_link,start_referrer
from rich_description import description_parts
from web_auth import WebAuth,validate_init_data

SESSION_COOKIE='__Host-nexus_session'
LOGIN_COOKIE='__Host-nexus_login'
FILES=Path(__file__).resolve().parent/'storefront'
CSP="default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"

# Картинки и шрифт хранятся в репозитории как base64 (*.b64) и отдаются в бинарном виде.
BINARY_ASSETS={'hero.webp':'image/webp','hero-dark.webp':'image/webp','catalog.webp':'image/webp','catalog-dark.webp':'image/webp','manrope.woff2':'font/woff2'}


@functools.lru_cache(maxsize=None)
def binary_asset(name):
    return base64.b64decode((FILES/(name+'.b64')).read_text())


def api(fn):
    @functools.wraps(fn)
    async def wrapped(self,request):
        try:
            response=await fn(self,request)
        except web.HTTPException as exc:
            response=web.json_response({'error':exc.reason},status=exc.status)
        except PaymentError as exc:
            response=web.json_response({'error':str(exc)},status=502)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError):
            response=web.json_response({'error':'Проверьте данные запроса или остаток товара.'},status=400)
        except Exception:
            # Never expose/log credentials, sessions, initData, stock payloads or provider URLs.
            response=web.json_response({'error':'Сервис временно недоступен. Повторите позже.'},status=503)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        return response
    return wrapped


class ShopSite:
    def __init__(self,get_db,get_payments,token,site_url,rates,policies=None):
        self.get_db=get_db;self.get_payments=get_payments;self.token=token
        parsed=urlparse(site_url)
        if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
            raise ValueError('SHOP_URL должен быть полным HTTPS адресом без параметров.')
        self.origin=f'{parsed.scheme}://{parsed.netloc}';self.site_url=site_url.rstrip('/')+'/'
        self.rates=rates;self.auth=WebAuth(get_db);self.limits=OrderedDict()
        self.policies={k:v for k,v in (policies or {}).items() if v and urlparse(v).scheme=='https'}

    def limit(self,key,maximum=30):
        now=time.monotonic();times=[t for t in self.limits.pop(key,[]) if now-t<60]
        if len(times)>=maximum: raise web.HTTPTooManyRequests(reason='Слишком много запросов. Подождите минуту.')
        times.append(now);self.limits[key]=times
        while len(self.limits)>2048:self.limits.popitem(last=False)

    def origin_check(self,request):
        if request.headers.get('Origin')!=self.origin:
            raise web.HTTPForbidden(reason='Запрос должен выполняться с сайта магазина.')

    async def body(self,request):
        if request.content_length and request.content_length>20000: raise web.HTTPRequestEntityTooLarge(max_size=20000,actual_size=request.content_length)
        value=await request.json()
        if not isinstance(value,dict): raise ValueError
        return value

    async def user(self,request,mutating=False):
        authorization=request.headers.get('Authorization','')
        token=authorization[7:] if authorization.startswith('Bearer ') else request.cookies.get(SESSION_COOKIE,'')
        session=await self.auth.session(token)
        if not session:raise web.HTTPUnauthorized(reason='Войдите через Telegram.')
        if mutating:
            self.origin_check(request)
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']):
                raise web.HTTPForbidden(reason='Подтвердите вход заново.')
        return session

    def set_session(self,response,token):
        response.set_cookie(SESSION_COOKIE,token,max_age=86400,secure=True,httponly=True,samesite='Lax',path='/')

    async def index(self,request):
        return web.FileResponse(FILES/'index.html',headers={'Cache-Control':'no-cache','Content-Security-Policy':CSP,
            'Referrer-Policy':'same-origin','X-Content-Type-Options':'nosniff'})

    async def asset(self,request):
        name=request.match_info['name']
        if name in BINARY_ASSETS:
            return web.Response(body=binary_asset(name),content_type=BINARY_ASSETS[name],
                headers={'Cache-Control':'public, max-age=86400','X-Content-Type-Options':'nosniff'})
        if name not in {'shop.css','shop.js','theme.js','icon.svg'}:raise web.HTTPNotFound()
        return web.FileResponse(FILES/name,headers={'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'})

    @api
    async def catalog(self,request):
        self.limit(('catalog',request.remote),120)
        categories=await self.get_db().active_categories()
        rows=await self.get_db()._pool().fetch("""SELECT p.id,p.name,p.description,p.price,p.category_id,c.name AS category_name,
            COUNT(s.id) FILTER(WHERE NOT s.is_issued AND (s.reserved_until IS NULL OR s.reserved_until<=NOW())) AS stock_count
            FROM products p LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN stock_items s ON s.product_id=p.id
            WHERE p.is_active AND (p.category_id IS NULL OR c.is_active) GROUP BY p.id,c.name ORDER BY p.created_at DESC LIMIT 1000""")
        products=[]
        for r in rows:
            products.append({'id':r['id'],'name':r['name'],'description':''.join(part.get('text',part.get('emoji','')) for part in description_parts(r['description'])),
                'price':str(r['price']),'category_id':r['category_id'],'category_name':r['category_name'] or 'Другое','stock':r['stock_count']})
        return web.json_response({'categories':[{'id':c['id'],'name':c['name']} for c in categories],'products':products,'policies':self.policies})

    @api
    async def rate(self,request):
        q=await self.rates.quote()
        return web.json_response({'rub_per_usd':str(q.rub_per_usd) if q else None})

    @api
    async def mini_login(self,request):
        self.origin_check(request);self.limit(('auth',request.remote))
        data=await self.body(request)
        try: user,signed=validate_init_data(data.get('initData'),self.token)
        except ValueError:raise web.HTTPUnauthorized(reason='Откройте Mini App из Telegram заново.')
        ref=start_referrer('/start '+signed['start_param']) if signed.get('start_param') else None
        await self.get_db().upsert_customer(user['id'],user.get('username'),user.get('first_name',''),ref)
        token,csrf=await self.auth.create_session(user['id']);response=web.json_response({'ok':True,'csrf':csrf,'session':token})
        self.set_session(response,token);return response

    @api
    async def login_link(self,request):
        self.origin_check(request);self.limit(('login',request.remote),15)
        token,login_id,code=await self.auth.create_login()
        response=web.json_response({'url':f'https://t.me/wanderersshop_bot?start=auth_{login_id}','code':code})
        response.set_cookie(LOGIN_COOKIE,token,max_age=300,secure=True,httponly=True,samesite='Strict',path='/')
        return response

    @api
    async def login_status(self,request):
        status,result=await self.auth.poll(request.cookies.get(LOGIN_COOKIE,''))
        response=web.json_response({'status':status or 'expired'})
        if result:
            self.set_session(response,result[0]);response.del_cookie(LOGIN_COOKIE,path='/',secure=True,httponly=True,samesite='Strict')
        return response

    @api
    async def me(self,request):
        session=await self.user(request);uid=session['customer_id'];customer=await self.get_db().customer(uid)
        stats=await self.get_db().referral_stats(uid)
        return web.json_response({'id':uid,'name':customer['first_name'],'username':customer['username'],'balance':str(customer['balance']),
            'referral':{'url':referral_link(uid),'invited':stats['invited'],'earned':stats['earned']},'purchases':stats['purchases'],'csrf':session['csrf']})

    @api
    async def logout(self,request):
        session=await self.user(request,True)
        await self.auth.pool.execute('DELETE FROM web_sessions WHERE token_hash=$1',session['token_hash'])
        response=web.json_response({'ok':True});response.del_cookie(SESSION_COOKIE,path='/',secure=True,httponly=True,samesite='Lax');return response

    async def payment_json(self,p,q=None,*,lookup_rate=True):
        if lookup_rate:q=await self.rates.quote()
        result={'id':p['id'],'purpose':p['purpose'],'name':p['product_name'],'quantity':p['quantity'],'amount':str(p['amount']),
            'rubles':str(q.rubles(str(p['amount']))) if q else None,'status':p['status'],'outcome':p['outcome'],
            'url':p['pay_url'] if p['status']=='pending' else None,'created_at':p['created_at'].isoformat()}
        if p['status']=='paid' and p['outcome']=='product':
            result['items']=json.loads(p['delivery_items']) if isinstance(p['delivery_items'],str) else p['delivery_items']
        return result

    @api
    async def checkout(self,request):
        session=await self.user(request,True);uid=session['customer_id'];self.limit(('checkout',uid),20)
        data=await self.body(request);purpose=data.get('purpose')
        if purpose=='product':
            pid=data.get('product_id')
            if isinstance(pid,bool) or not isinstance(pid,int) or pid<=0:raise ValueError
            product=await self.get_db().product(pid)
            if not product or not product['is_active']:raise ValueError
            if product['category_id'] and not any(c['id']==product['category_id'] for c in await self.get_db().active_categories()):raise ValueError
            p=await self.get_payments().checkout(uid,'product',product_id=pid,count=quantity(data.get('quantity',1)))
        elif purpose=='topup':
            p=await self.get_payments().checkout(uid,'topup',amount=money(data.get('amount'),maximum=Decimal('10000')))
        else:raise ValueError
        return web.json_response(await self.payment_json(p))

    @api
    async def payment(self,request):
        session=await self.user(request);pid=int(request.match_info['id'])
        p=await self.get_payments().store.get(pid,session['customer_id'])
        if not p:raise web.HTTPNotFound(reason='Счёт не найден.')
        return web.json_response(await self.payment_json(p))

    @api
    async def check_payment(self,request):
        session=await self.user(request,True);self.limit(('check',session['customer_id']),30)
        p=await self.get_payments().check(int(request.match_info['id']),session['customer_id'])
        return web.json_response(await self.payment_json(p))

    @api
    async def balance_payment(self,request):
        session=await self.user(request,True);self.limit(('balance',session['customer_id']),20)
        p=await self.get_payments().balance_purchase(int(request.match_info['id']),session['customer_id'])
        return web.json_response(await self.payment_json(p))

    @api
    async def orders(self,request):
        session=await self.user(request)
        rows=await self.get_db()._pool().fetch('SELECT * FROM payments WHERE customer_id=$1 ORDER BY id DESC LIMIT 100',session['customer_id'])
        # Include only this customer's receipts; catalog never returns private stock payloads.
        q=await self.rates.quote()
        return web.json_response([await self.payment_json(p,q,lookup_rate=False) for p in rows])

    def setup(self,app):
        app.router.add_get('/',self.index)
        app.router.add_get('/storefront/{name}',self.asset)
        routes=[('GET','catalog',self.catalog),('GET','rate',self.rate),('POST','auth/telegram',self.mini_login),
            ('POST','auth/link',self.login_link),('GET','auth/status',self.login_status),('GET','me',self.me),('POST','auth/logout',self.logout),
            ('POST','checkout',self.checkout),('GET','payments/{id}',self.payment),('POST','payments/{id}/check',self.check_payment),
            ('POST','payments/{id}/balance',self.balance_payment),('GET','orders',self.orders)]
        for method,path,handler in routes:app.router.add_route(method,'/api/store/'+path,handler)
