"""Crypto Pay contract + real PostgreSQL transactional regression tests.

Run database tests with TEST_DATABASE_URL pointing ONLY to a disposable test database.
Each test creates/drops its own schema; no live invoices or production goods are used.
"""
import asyncio
import hashlib
import hmac
import json
import os
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import asyncpg
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

import bot
from crypto_pay import CryptoPay, PaymentError, money, quantity, validate_invoice, invoice_url, valid_signature
from payment_store import PaymentStore
from payments import Payments
from storage import Database, SCHEMA


def make_invoice(p, status='active'):
    return {'invoice_id': 1000 + p['id'], 'currency_type': 'fiat', 'fiat': 'USD',
            'amount': str(p['amount']), 'payload': p['payload'], 'status': status,
            'bot_invoice_url': 'https://t.me/CryptoBot?start=invoice-' + str(p['id'])}


class FakeAPI:
    token = 'test-only'

    def __init__(self):
        self.data = {}
        self.creations = 0
        self.fail_create = False
        self.fail_before_create = False
        self.fail_fetch = False

    async def create(self, p):
        self.creations += 1
        if self.fail_before_create:
            raise PaymentError(ambiguous=False)
        invoice = make_invoice(p)
        self.data[invoice['invoice_id']] = invoice
        if self.fail_create:
            raise PaymentError(ambiguous=True)
        return invoice

    async def invoices(self, ids=None):
        if self.fail_fetch:
            raise PaymentError()
        return [dict(i) for k, i in self.data.items() if ids is None or k in ids]

    async def delete(self, invoice_id):
        if self.data[invoice_id]['status'] == 'paid':
            raise PaymentError()
        self.data.pop(invoice_id)
        return True

    def paid(self, p):
        self.data[p['invoice_id']]['status'] = 'paid'
        return dict(self.data[p['invoice_id']])


class ContractTests(unittest.IsolatedAsyncioTestCase):
    def test_money_and_quantity(self):
        self.assertEqual(money('1,20'), Decimal('1.20'))
        for amount in ['NaN', 'Infinity', '-Infinity', '0', '-1', '0.001', '1.234', '1000001', None]:
            with self.assertRaises(ValueError, msg=str(amount)):
                money(amount)
        for count in [0, -1, '1.1', 101, True, '١']:
            with self.assertRaises(ValueError):
                quantity(count)

    def test_invoice_binding(self):
        p = dict(id=1, amount=Decimal('4.50'), invoice_id=1001, payload='shop:secret')
        inv = make_invoice(p, 'paid')
        validate_invoice(inv, p)
        for field, value in [('invoice_id',1002),('invoice_id',True),('amount','4.49'),('fiat','RUB'),
                             ('currency_type','crypto'),('payload','other-user'),('status','unknown')]:
            bad = dict(inv, **{field: value})
            with self.assertRaises(ValueError):
                validate_invoice(bad,p)

    def test_modern_invoice_url_and_fallback(self):
        self.assertEqual(invoice_url({'bot_invoice_url':'https://t.me/CryptoBot?start=abc','pay_url':'https://evil.invalid'}), 'https://t.me/CryptoBot?start=abc')
        self.assertEqual(invoice_url({'pay_url':'https://t.me/CryptoBot?start=abc'}), 'https://t.me/CryptoBot?start=abc')
        for url in ['javascript:alert(1)', 'http://t.me/CryptoBot', 'https://t.me.evil.invalid', 'https://u@t.me/CryptoBot']:
            with self.assertRaises(PaymentError):
                invoice_url({'bot_invoice_url':url})

    def test_signature_is_raw_body_and_requires_token(self):
        raw = b'{"test": 1}'
        sig = hmac.new(hashlib.sha256(b'test').digest(),raw,hashlib.sha256).hexdigest()
        self.assertTrue(valid_signature('test',raw,sig))
        self.assertFalse(valid_signature('test',b'{"test":1}',sig))
        self.assertFalse(valid_signature('',raw,sig))

    async def test_real_http_contract_and_error(self):
        seen = []
        async def handle(request):
            data = await request.json()
            seen.append((request.match_info['method'], data, request.headers.get('Crypto-Pay-API-Token')))
            if request.match_info['method']=='createInvoice':
                return web.json_response({'ok': True, 'result': {'invoice_id':12,'bot_invoice_url':'https://t.me/CryptoBot?start=abc'}})
            if request.match_info['method']=='getInvoices':
                return web.json_response({'ok':True,'result':{'items':[{'invoice_id':12}]}})
            return web.json_response({'ok':False,'error':{'name':'UNAUTHORIZED'}},status=401)
        app=web.Application(); app.router.add_post('/{method}',handle)
        server=TestServer(app); await server.start_server()
        client=CryptoPay('private-test-token'); client.base=str(server.make_url('/'))
        try:
            p=dict(id=1,amount=Decimal('7.50'),purpose='product',quantity=3,product_name='Product',payload='shop:secret')
            await client.create(p)
            self.assertEqual(await client.invoices([12]),[{'invoice_id':12}])
            with self.assertRaises(PaymentError) as exc:
                await client.request('getMe',{})
            self.assertNotIn('private-test-token',str(exc.exception))
            self.assertFalse(exc.exception.ambiguous)
            method,data,token=seen[0]
            self.assertEqual(method,'createInvoice'); self.assertEqual(token,'private-test-token')
            self.assertEqual(data['fiat'],'USD'); self.assertEqual(data['currency_type'],'fiat')
            self.assertEqual(data['amount'],'7.50'); self.assertEqual(data['payload'],'shop:secret')
            self.assertEqual(data['expires_in'],600)
            self.assertEqual(seen[1][1],{'invoice_ids':'12','count':1})
        finally:
            await client.close(); await server.close()

    def test_testnet_is_explicit(self):
        self.assertEqual(CryptoPay('x').base,'https://pay.crypt.bot/api/')
        self.assertEqual(CryptoPay('x',testnet=True).base,'https://testnet-pay.crypt.bot/api/')

    def test_green_payment_buttons(self):
        p=dict(id=1,status='pending',pay_url='https://t.me/CryptoBot?start=a')
        buttons=[b for row in bot.payment_keyboard(p,balance=True).inline_keyboard for b in row]
        self.assertEqual(buttons[0].url,p['pay_url'])
        admin=next(b for b in buttons if b.url and 'Ditzzmback' in b.url)
        self.assertEqual(admin.style,'success'); self.assertEqual(buttons[0].style,'success')
        self.assertTrue(any(b.callback_data=='check_payment:1' for b in buttons))
        self.assertTrue(any(b.callback_data=='pay_balance:1' for b in buttons))

    async def test_check_rejects_other_owner_before_provider_call(self):
        service=Payments(None,FakeAPI(),None)
        service.store.get=AsyncMock(return_value=None)
        service.client.invoices=AsyncMock()
        with self.assertRaises(ValueError):
            await service.check(1,999)
        service.client.invoices.assert_not_awaited()

    def test_group_checkout_is_not_allowed(self):
        cb=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(type='group',id=-1)),from_user=SimpleNamespace(id=10))
        self.assertFalse(bot.private_checkout(cb))


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'requires disposable TEST_DATABASE_URL')
class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dsn=os.environ['TEST_DATABASE_URL']
        self.schema='payments_test_'+uuid.uuid4().hex
        self.admin=await asyncpg.connect(self.dsn)
        await self.admin.execute(f'CREATE SCHEMA {self.schema}')
        self.pool=await asyncpg.create_pool(self.dsn,min_size=1,max_size=5,server_settings={'search_path':self.schema})
        await self.pool.execute(SCHEMA)
        self.db=Database(self.dsn); self.db.pool=self.pool
        await self.db.upsert_customer(10,'test','Test'); await self.db.upsert_customer(20,'other','Other')
        self.product=await self.db.save_product(dict(name='Gemini',description='Access',price='2.50'))
        self.pid=self.product['id']
        await self.db.replace_stock(self.pid,['credential-A','credential-B','credential-C','credential-D'])
        self.api=FakeAPI(); self.telegram=SimpleNamespace(send_message=AsyncMock())
        self.service=Payments(self.pool,self.api,self.telegram); self.store=self.service.store

    async def asyncTearDown(self):
        await self.pool.close()
        await self.admin.execute(f'DROP SCHEMA {self.schema} CASCADE'); await self.admin.close()

    async def product_payment(self,count=1,owner=10):
        return await self.service.checkout(owner,'product',product_id=self.pid,count=count)

    async def test_schema_can_run_twice_without_data_loss(self):
        p=await self.product_payment(); await self.pool.execute(SCHEMA)
        self.assertEqual((await self.store.get(p['id']))['amount'],Decimal('2.50'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items'),4)

    async def test_topup_credits_exactly_once_under_concurrency(self):
        p=await self.service.checkout(10,'topup',amount=Decimal('7.50'))
        inv=self.api.paid(p)
        await asyncio.gather(*(self.store.apply(inv) for _ in range(8)))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('7.50'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM balance_transactions'),1)
        self.assertEqual((await self.db.dashboard())['revenue'],'0')
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM orders'),0)

    async def test_quantity_order_issues_exactly_n_items_once(self):
        p=await self.product_payment(3)
        self.assertEqual(p['amount'],Decimal('7.50'))
        inv=self.api.paid(p)
        await asyncio.gather(*(self.store.apply(inv) for _ in range(5)))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),3)
        self.assertEqual(await self.pool.fetchval('SELECT quantity FROM orders'),3)
        self.assertEqual((await self.db.dashboard())['revenue'],'7.50')
        self.assertEqual(len(json.loads((await self.store.get(p['id']))['delivery_items'])),3)

    async def test_reserved_stock_cannot_be_oversold_or_removed(self):
        await self.product_payment(3)
        with self.assertRaises(ValueError): await self.product_payment(2,20)
        with self.assertRaises(ValueError): await self.db.replace_stock(self.pid,['new'])
        with self.assertRaises(ValueError): await self.db.delete_product(self.pid)
        self.assertEqual(await self.store.available(self.pid,20),1)
        self.assertEqual(await self.store.available(self.pid,10),4)

    async def test_concurrent_checkouts_share_one_invoice(self):
        result=await asyncio.gather(*(self.product_payment(2) for _ in range(5)))
        self.assertEqual(len({r['id'] for r in result}),1)
        self.assertEqual(self.api.creations,1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM orders'),1)

    async def test_quantity_change_deletes_old_invoice_and_replaces_reservation(self):
        first=await self.product_payment(1); second=await self.product_payment(3)
        self.assertNotIn(first['invoice_id'],self.api.data)
        self.assertEqual((await self.store.get(first['id']))['status'],'expired')
        self.assertEqual(second['amount'],Decimal('7.50'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE reserved_until>NOW()'),3)

    async def test_timeout_after_creation_recovers_without_duplicate(self):
        self.api.fail_create=True
        with self.assertRaises(PaymentError): await self.product_payment(2)
        self.api.fail_create=False
        p=await self.product_payment(2)
        self.assertEqual(self.api.creations,1)
        self.assertEqual(p['status'],'pending')

    async def test_definitive_failure_releases_reservation(self):
        self.api.fail_before_create=True
        with self.assertRaises(PaymentError): await self.product_payment(2)
        self.assertEqual(await self.store.available(self.pid,20),4)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM payments'),'failed')

    async def test_webhook_before_create_response_is_not_lost(self):
        p,_=await self.store.prepare(10,'product',product_id=self.pid,count=2)
        inv=make_invoice(p,'paid')
        await self.store.apply(inv)
        await self.store.bind(p['id'],inv,invoice_url(inv))
        self.assertEqual((await self.store.get(p['id']))['status'],'paid')
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),2)

    async def test_amount_currency_or_payload_mismatch_cannot_credit(self):
        p=await self.service.checkout(10,'topup',amount=Decimal('7.50'))
        inv=self.api.paid(p)
        for field,value in [('amount','1'),('fiat','RUB'),('invoice_id',9999)]:
            with self.assertRaises(ValueError): await self.store.apply(dict(inv,**{field:value}))
        self.assertIsNone(await self.store.apply(dict(inv,payload='unknown')))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0'))

    async def test_polling_confirms_topup_without_webhook(self):
        p=await self.service.checkout(10,'topup',amount=Decimal('8.20'))
        self.api.paid(p); await self.service.reconcile()
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('8.20'))
        await self.service.deliver(); self.telegram.send_message.assert_awaited_once()
        self.assertIn('8.20',self.telegram.send_message.call_args.args[1])
        self.assertEqual(self.telegram.send_message.call_args.args[0],10)

    async def test_delivery_failure_does_not_lose_goods_or_credit_again(self):
        p=await self.product_payment(2); await self.store.apply(self.api.paid(p))
        self.telegram.send_message.side_effect=RuntimeError('network')
        self.assertFalse(await self.service.deliver(p['id']))
        self.assertIsNone((await self.store.get(p['id']))['delivered_at'])
        first_text=self.telegram.send_message.call_args.args[1]
        await self.pool.execute("UPDATE payments SET delivery_attempt_at=NOW()-INTERVAL '31 seconds'")
        self.telegram.send_message.side_effect=None
        self.assertTrue(await self.service.deliver(p['id']))
        self.assertEqual(self.telegram.send_message.call_args.args[1],first_text)
        self.assertIsNotNone((await self.store.get(p['id']))['delivered_at'])
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),2)

    async def test_concurrent_delivery_has_one_sender(self):
        p=await self.product_payment(); await self.store.apply(self.api.paid(p))
        await asyncio.gather(*(self.service.deliver(p['id']) for _ in range(8)))
        self.telegram.send_message.assert_awaited_once()

    async def test_expired_invoice_frees_stock(self):
        p=await self.product_payment(4); self.api.data[p['invoice_id']]['status']='expired'
        await self.service.reconcile()
        self.assertEqual(await self.store.available(self.pid,20),4)
        self.assertEqual((await self.store.get(p['id']))['status'],'expired')

    async def test_late_paid_invoice_with_no_stock_returns_full_amount_to_wallet(self):
        p=await self.product_payment(4); await self.store.release(p['id'])
        other=await self.product_payment(4,20); await self.store.apply(self.api.paid(other))
        invoice=self.api.paid(p); await self.store.apply(invoice); await self.store.apply(invoice)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('10'))
        self.assertEqual((await self.store.get(p['id']))['outcome'],'wallet_refund')
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),4)
        self.assertEqual((await self.db.dashboard())['revenue'],'10.00')

    async def test_balance_purchase_is_atomic_and_idempotent(self):
        await self.db.grant_balance_by_id(10,Decimal('10'),'test')
        p=await self.product_payment(3)
        await asyncio.gather(*(self.service.balance_purchase(p['id'],10) for _ in range(3)))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('2.50'))
        self.assertEqual(await self.pool.fetchval("SELECT COUNT(*) FROM balance_transactions WHERE amount<0"),1)
        self.assertEqual(await self.pool.fetchval("SELECT provider FROM orders"),'balance')
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),3)
        self.assertNotIn(p['invoice_id'],self.api.data)

    async def test_crypto_payment_racing_wallet_payment_is_credited_once(self):
        await self.db.grant_balance_by_id(10,Decimal('10'),'test')
        p=await self.product_payment(3)
        delayed_invoice=dict(self.api.data[p['invoice_id']],status='paid')
        await self.service.balance_purchase(p['id'],10)
        await asyncio.gather(*(self.store.apply(delayed_invoice) for _ in range(6)))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('10'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM payments WHERE compensates_id IS NOT NULL'),1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),3)
        self.assertEqual((await self.db.dashboard())['revenue'],'7.50')

    async def test_checkout_and_paid_event_same_owner_do_not_deadlock(self):
        first=await self.product_payment()
        inv=self.api.paid(first)
        for _ in range(10):
            await asyncio.wait_for(asyncio.gather(self.store.apply(inv),self.store.prepare(10,'topup',amount=Decimal('5'))),3)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),1)

    async def test_wallet_has_direct_green_payment_and_admin_link(self):
        user=SimpleNamespace(id=10,username='test',first_name='Test')
        message=SimpleNamespace(delete=AsyncMock(),answer=AsyncMock())
        with patch.object(bot,'database',self.db),patch.object(bot,'payments',self.service),patch.object(bot.exchange_rates,'quote',AsyncMock(return_value=None)):
            await bot.show_payment_options(message,'3.30',user)
        buttons=[b for row in message.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertTrue(any(b.url and 'CryptoBot' in b.url and b.style=='success' for b in buttons))
        self.assertTrue(any(b.url and 'Ditzzmback' in b.url and b.style=='success' for b in buttons))
        self.assertEqual(await self.pool.fetchval('SELECT purpose FROM payments'),'topup')

    async def test_insufficient_balance_does_not_cancel_crypto_invoice(self):
        p=await self.product_payment()
        with self.assertRaises(ValueError): await self.service.balance_purchase(p['id'],10)
        self.assertEqual((await self.store.get(p['id']))['status'],'pending')
        self.assertIn(p['invoice_id'],self.api.data)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),0)

    async def test_invoice_keeps_original_price_when_admin_updates_product(self):
        p=await self.product_payment(2)
        await self.db.save_product(dict(name='New name',price='99',description=''),self.pid)
        same=await self.product_payment(2)
        self.assertEqual(same['id'],p['id']); self.assertEqual(same['amount'],Decimal('5'))
        self.assertEqual(same['product_name'],'Gemini')
        await self.store.apply(self.api.paid(p))
        self.assertEqual((await self.db.dashboard())['revenue'],'5.00')

    async def test_deleted_product_late_payment_still_credits_customer(self):
        p=await self.product_payment(); await self.store.release(p['id']); await self.db.delete_product(self.pid)
        await self.store.apply(self.api.paid(p))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('2.50'))

    async def test_legacy_pending_usd_order_is_adopted_and_issued_once(self):
        oid=await self.pool.fetchval("INSERT INTO orders(customer_id,product_id,amount,status,provider,provider_invoice_id) VALUES(10,$1,2.50,'pending','crypto_pay',1234) RETURNING id",self.pid)
        inv=dict(invoice_id=1234,currency_type='fiat',fiat='USD',amount='2.50',payload=str(oid),status='paid',bot_invoice_url='https://t.me/CryptoBot?start=legacy')
        await asyncio.gather(self.store.apply(inv),self.store.apply(inv))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM payments'),1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),1)

    async def test_signed_webhook_replay_and_invalid_requests(self):
        p=await self.service.checkout(10,'topup',amount=Decimal('3.30'))
        app=web.Application(); app.router.add_post('/crypto/{secret}',bot.crypto_webhook)
        client=TestClient(TestServer(app)); await client.start_server()
        settings=SimpleNamespace(crypto_pay_webhook_secret='path-secret',crypto_pay_token='provider-secret')
        invoice=self.api.paid(p)
        raw=json.dumps(dict(update_type='invoice_paid',payload=invoice)).encode()
        signature=lambda body: hmac.new(hashlib.sha256(b'provider-secret').digest(),body,hashlib.sha256).hexdigest()
        try:
            with patch.object(bot,'settings',settings),patch.object(bot,'payments',self.service):
                for _ in range(2):
                    response=await client.post('/crypto/path-secret',data=raw,headers={'crypto-pay-api-signature':signature(raw)})
                    self.assertEqual(response.status,200)
                self.assertEqual((await self.db.customer(10))['balance'],Decimal('3.30'))
                response=await client.post('/crypto/path-secret',data=raw,headers={'crypto-pay-api-signature':'forged'})
                self.assertEqual(response.status,401)
                response=await client.post('/crypto/wrong',data=raw)
                self.assertEqual(response.status,404)
                response=await client.post('/crypto/path-secret',data=b'[]',headers={'crypto-pay-api-signature':signature(b'[]')})
                self.assertEqual(response.status,400)
        finally:
            await client.close()

    async def test_product_card_has_quantity_total_and_direct_green_links(self):
        user=SimpleNamespace(id=10,username='test',first_name='Test')
        cb=SimpleNamespace(data='product:'+str(self.pid),from_user=user,message=SimpleNamespace(answer=AsyncMock(),edit_text=AsyncMock()))
        with patch.object(bot,'database',self.db),patch.object(bot,'payments',self.service),patch.object(bot.exchange_rates,'quote',AsyncMock(return_value=None)):
            await bot.render_product(cb,self.product,2)
        text=cb.message.answer.call_args.args[0]
        markup=cb.message.answer.call_args.kwargs['reply_markup']
        buttons=[b for row in markup.inline_keyboard for b in row]
        self.assertIn('2 шт.',text); self.assertIn('5.00',text)
        crypto=next(b for b in buttons if b.url and 'CryptoBot' in b.url)
        admin=next(b for b in buttons if b.url and 'Ditzzmback' in b.url)
        self.assertEqual(crypto.style,'success'); self.assertEqual(admin.style,'success')
        self.assertTrue(any(b.callback_data==f'qty:{self.pid}:3' for b in buttons))


if __name__ == '__main__':
    unittest.main()
