"""Public storefront, owner-only API and browser/Mini App authentication.
No production tokens, payments or stock. DB tests create a disposable schema.
"""
import dataclasses
import asyncio
import hashlib
import hmac
import json
import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import bot
import test_payments as fixture
from storefront import ShopSite, SESSION_COOKIE, LOGIN_COOKIE
from web_auth import validate_init_data, digest

ORIGIN='https://nexora.hostless.app'
TOKEN='123:test-only'


def signed(user=None,**fields):
    data={'user':json.dumps(user if user is not None else {'id':10,'first_name':'Test','username':'test'}),'auth_date':str(int(time.time())),**fields}
    key=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


class InitDataTests(unittest.TestCase):
    def test_valid_signature(self):
        u,d=validate_init_data(signed(start_param='ref_20'),TOKEN)
        self.assertEqual(u['id'],10);self.assertEqual(d['start_param'],'ref_20')
    def test_tampered_and_wrong_token_rejected(self):
        for raw,token in [(signed()+'&other=fake',TOKEN),(signed(),'other'),('user={}',TOKEN),(signed(),''),('',TOKEN),(None,TOKEN)]:
            with self.assertRaises(ValueError):validate_init_data(raw,token)
    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):validate_init_data(signed()+'&auth_date=1',TOKEN)
    def test_stale_future_and_bad_dates(self):
        for value in [str(int(time.time())-3601),str(int(time.time())+40),'bad']:
            with self.assertRaises(ValueError):validate_init_data(signed(auth_date=value),TOKEN)
    def test_signed_invalid_user_rejected(self):
        for u in [{'id':True},{'id':-1},{'id':2**63},{'id':'10'},{'id':10,'is_bot':True},{'id':10,'first_name':[]},[]]:
            with self.assertRaises(ValueError):validate_init_data(signed(u),TOKEN)
    def test_shop_origin_validation(self):
        for url in ['http://example.com','https://u@host','https://host/sub/','https://host/?bad=1','https://host/#x']:
            with self.assertRaises(ValueError):ShopSite(None,None,TOKEN,url,None)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'),'requires disposable TEST_DATABASE_URL')
class StoreApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixture.LedgerTests.asyncSetUp(self)
        self.rates=SimpleNamespace(quote=AsyncMock(return_value=None))
        self.site=ShopSite(lambda:self.db,lambda:self.service,TOKEN,ORIGIN+'/',self.rates)
        app=web.Application();self.site.setup(app)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.token,self.csrf=await self.site.auth.create_session(10)
        self.headers={'Origin':ORIGIN,'Authorization':'Bearer '+self.token,'X-CSRF-Token':self.csrf}
    async def asyncTearDown(self):
        await self.client.close();await fixture.LedgerTests.asyncTearDown(self)
    async def request(self,path,body=None,headers=None,method=None):
        r=await self.client.request(method or ('POST' if body is not None else 'GET'),'/api/store/'+path,json=body,headers=self.headers if headers is None else headers)
        return r,await r.json()
    async def test_index_and_assets_security(self):
        r=await self.client.get('/');self.assertEqual(r.status,200)
        html=await r.text();self.assertIn('Nexus Store',html);self.assertNotIn('/store-media/',html);self.assertNotIn('brand-covers',html);self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])
        for path in ['/storefront/shop.js','/storefront/shop.css','/storefront/icon.svg','/storefront/hero.webp','/storefront/hero-dark.webp','/storefront/theme.js','/storefront/manrope.woff2']:
            r=await self.client.get(path);self.assertEqual(r.status,200)
        self.assertEqual((await self.client.get('/storefront/bot.py')).status,404)
        self.assertEqual((await self.client.get('/store-media/../bot.py')).status,404)
        self.assertEqual((await self.client.get('/store-media/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3.jpg')).status,404)
    async def test_catalog_public_no_secret_stock_and_hidden_products(self):
        hidden=await self.db.save_product(dict(name='Hidden',description='private',price='1',is_active=False))
        r,d=await self.request('catalog',headers={});self.assertEqual(r.status,200)
        self.assertNotIn('credential',json.dumps(d));self.assertNotIn('cover',d['products'][0]);self.assertNotIn(hidden['id'],[p['id'] for p in d['products']])
        self.assertEqual(d['products'][0]['stock'],4);self.assertEqual(d['products'][0]['price'],'2.50')
    async def test_inactive_category_hides_and_blocks_product(self):
        c=await self.db.save_category(dict(name='ChatGPT',is_active=False))
        await self.pool.execute('UPDATE products SET category_id=$1 WHERE id=$2',c['id'],self.pid)
        _,d=await self.request('catalog',headers={});self.assertEqual(d['products'],[])
        r,_=await self.request('checkout',{'purpose':'product','product_id':self.pid});self.assertEqual(r.status,400)
    async def test_private_endpoints_require_owner_session(self):
        for path,body in [('me',None),('orders',None),('payments/1',None),('checkout',{}),('payments/1/check',{}),('payments/1/balance',{})]:
            r,_=await self.request(path,body,headers={});self.assertEqual(r.status,401)
    async def test_csrf_and_origin_required(self):
        for headers in [dict(self.headers,Origin='https://evil.invalid'),{k:v for k,v in self.headers.items() if k!='Origin'},dict(self.headers,**{'X-CSRF-Token':'bad'})]:
            r,_=await self.request('checkout',{'purpose':'topup','amount':'1'},headers);self.assertEqual(r.status,403)
        self.assertEqual(self.api.creations,0)
    async def test_mini_app_login_validated_and_no_identity_from_client(self):
        r,d=await self.request('auth/telegram',{'initData':signed(),'id':20},headers={'Origin':ORIGIN})
        self.assertEqual(r.status,200);self.assertTrue(d['session']);self.assertIn('HttpOnly',str(r.cookies))
        r,d=await self.request('me',headers={'Authorization':'Bearer '+d['session']});self.assertEqual(d['id'],10)
        r,_=await self.request('auth/telegram',{'initData':signed()+'x'},headers={'Origin':ORIGIN});self.assertEqual(r.status,401)
    async def test_cookie_browser_session_supported(self):
        r,d=await self.request('me',headers={'Cookie':SESSION_COOKIE+'='+self.token});self.assertEqual(d['id'],10)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
    async def test_logout_revokes_bearer(self):
        r,_=await self.request('auth/logout',{});self.assertEqual(r.status,200)
        r,_=await self.request('me');self.assertEqual(r.status,401)
    async def test_session_hashes_and_expiry(self):
        row=await self.site.auth.session(self.token)
        self.assertEqual(row['token_hash'],digest(self.token));self.assertNotEqual(row['token_hash'],self.token)
        await self.pool.execute("UPDATE web_sessions SET expires_at=NOW()-INTERVAL '1 second'")
        r,_=await self.request('me');self.assertEqual(r.status,401)
    async def test_browser_approval_one_use_bound_to_browser_and_person(self):
        secret,lid,code=await self.site.auth.create_login()
        self.assertEqual(len(code),6);self.assertEqual(len(lid),32)
        self.assertEqual((await self.site.auth.poll(secret))[0],'pending')
        self.assertIsNotNone(await self.site.auth.claim(lid,10))
        self.assertIsNone(await self.site.auth.claim(lid,20));self.assertIsNone(await self.site.auth.approve(lid,20))
        await self.site.auth.approve(lid,10)
        self.assertIsNone((await self.site.auth.poll(lid))[0])
        results=await asyncio.gather(*(self.site.auth.poll(secret) for _ in range(5)))
        self.assertEqual(sum(r[1] is not None for r in results),1)
        self.assertIsNone((await self.site.auth.poll(secret))[1])
    async def test_browser_denied_and_expired(self):
        secret,lid,_=await self.site.auth.create_login();await self.site.auth.claim(lid,10);await self.site.auth.approve(lid,10,False)
        self.assertEqual(await self.site.auth.poll(secret),('denied',None))
        await self.pool.execute("UPDATE web_logins SET expires_at=NOW()-INTERVAL '1 second'")
        self.assertIsNone(await self.site.auth.claim(lid,10));self.assertEqual(await self.site.auth.poll(secret),(None,None))
    async def test_link_and_status_set_only_secure_cookies(self):
        r,d=await self.request('auth/link',{});self.assertEqual(r.status,200)
        cookie=r.cookies[LOGIN_COOKIE];self.assertTrue(cookie['secure']);self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Strict')
        lid=d['url'].split('auth_')[1];await self.site.auth.claim(lid,10);await self.site.auth.approve(lid,10)
        r,d=await self.request('auth/status',headers={'Cookie':LOGIN_COOKIE+'='+cookie.value});self.assertEqual(d['status'],'approved')
        cookie=r.cookies[SESSION_COOKIE];self.assertTrue(cookie['secure']);self.assertTrue(cookie['httponly'])
    async def test_checkouts_use_server_prices_and_are_idempotent(self):
        r,p=await self.request('checkout',{'purpose':'product','product_id':self.pid,'quantity':2,'amount':'0.01','customer_id':20})
        self.assertEqual(r.status,200);self.assertEqual(p['amount'],'5.00')
        _,same=await self.request('checkout',{'purpose':'product','product_id':self.pid,'quantity':2});self.assertEqual(same['id'],p['id'])
        self.assertNotIn('items',p);self.assertNotIn('payload',p)
        _,me=await self.request('me');self.assertEqual(me['balance'],'0.00')
    async def test_cross_customer_payment_unavailable(self):
        p=await self.service.checkout(20,'product',product_id=self.pid)
        for suffix,body in [('',None),('/check',{}),('/balance',{})]:
            r,d=await self.request(f'payments/{p["id"]}'+suffix,body);self.assertIn(r.status,[400,404]);self.assertNotIn('items',d)
        _,orders=await self.request('orders');self.assertEqual(orders,[])
    async def test_paid_delivery_and_wallet_shared_with_bot(self):
        await self.db.grant_balance_by_id(10,'10','test')
        _,p=await self.request('checkout',{'purpose':'product','product_id':self.pid,'quantity':2})
        r,paid=await self.request(f'payments/{p["id"]}/balance',{});self.assertEqual(r.status,200);self.assertEqual(paid['items'],['credential-A','credential-B'])
        _,me=await self.request('me');self.assertEqual(me['balance'],'5.00')
        _,orders=await self.request('orders');self.assertEqual(orders[0]['items'],paid['items'])
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),2)
    async def test_topup_checked_and_credited_once(self):
        _,p=await self.request('checkout',{'purpose':'topup','amount':'3'})
        row=await self.store.get(p['id']);self.api.paid(row)
        for _ in range(2):
            r,d=await self.request(f'payments/{p["id"]}/check',{});self.assertEqual(r.status,200);self.assertEqual(d['outcome'],'topup')
        _,me=await self.request('me');self.assertEqual(me['balance'],'3.00')
    async def test_invalid_quantity_topup_and_ids(self):
        for body in [{'purpose':'product','product_id':True},{'purpose':'product','product_id':self.pid,'quantity':101},{'purpose':'product','product_id':self.pid,'quantity':5},{'purpose':'topup','amount':'NaN'},{'purpose':'topup','amount':'10001'},[]]:
            r,_=await self.request('checkout',body);self.assertEqual(r.status,400)
    async def test_failures_do_not_expose_tokens_or_stock(self):
        self.db.customer=AsyncMock(side_effect=RuntimeError('SECRET-STOCK/BOT-TOKEN'))
        r,d=await self.request('me');self.assertEqual(r.status,503);self.assertNotIn('SECRET',json.dumps(d))
    async def test_rate_and_login_throttled(self):
        _,d=await self.request('rate',headers={});self.assertIsNone(d['rub_per_usd'])
        for _ in range(15):r,_=await self.request('auth/link',{})
        r,_=await self.request('auth/link',{});self.assertEqual(r.status,429)
    async def test_web_menu_button_and_bot_approval(self):
        with patch.object(bot,'settings',dataclasses.replace(bot.settings,web_app_enabled=False)):
            kb=bot.menu_keyboard();buttons=[b for row in kb.inline_keyboard for b in row]
            self.assertFalse(any(b.web_app for b in buttons))
        with patch.object(bot,'settings',dataclasses.replace(bot.settings,web_app_enabled=True)):
            kb=bot.menu_keyboard();buttons=[b for row in kb.inline_keyboard for b in row]
            self.assertTrue(any(b.web_app and b.web_app.url==ORIGIN+'/' for b in buttons))
        _,lid,_=await self.site.auth.create_login();await self.site.auth.claim(lid,10)
        cb=SimpleNamespace(data='weblogin:allow:'+lid,from_user=SimpleNamespace(id=20),answer=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(type='private',id=20),edit_text=AsyncMock()))
        with patch.object(bot,'shop_site',self.site):await bot.approve_web_login(cb)
        cb.message.edit_text.assert_not_awaited()
        cb.from_user.id=10;cb.message.chat.id=10
        with patch.object(bot,'shop_site',self.site):await bot.approve_web_login(cb)
        cb.message.edit_text.assert_awaited_once()


if __name__=='__main__':unittest.main()
