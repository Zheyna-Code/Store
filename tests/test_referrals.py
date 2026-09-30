"""Referral links, immutable attribution and transactional first-purchase rewards."""
import asyncio
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
import test_payments as payment_tests
from referrals import referral_link, start_referrer


class ReferralLinkTests(unittest.IsolatedAsyncioTestCase):
    def test_personal_link_uses_requested_bot(self):
        self.assertEqual(referral_link(123),'https://t.me/wanderersshop_bot?start=ref_123')
        self.assertNotEqual(referral_link(123),referral_link(124))
        for uid in [0,-1,True,'123',2**63]:
            with self.assertRaises(ValueError): referral_link(uid)

    def test_start_payload(self):
        self.assertEqual(start_referrer('/start ref_123'),123)
        self.assertEqual(start_referrer('/start@wanderersshop_bot ref_123'),123)
        for text in [None,'/menu ref_123','/start ref_0','/start ref_-1','/start ref_abc',
                     '/start ref_123 other','/start@other_bot ref_123','/start ref_9999999999999999999999']:
            self.assertIsNone(start_referrer(text))

    async def test_start_records_inviter_for_private_chat_only(self):
        db=SimpleNamespace(upsert_customer=AsyncMock(),visit=AsyncMock())
        state=SimpleNamespace(clear=AsyncMock())
        user=SimpleNamespace(id=30,username='new',first_name='Friend')
        message=SimpleNamespace(from_user=user,text='/start ref_10',chat=SimpleNamespace(type='private'),answer_photo=AsyncMock())
        with patch.object(bot,'database',db): await bot.command_menu(message,state)
        db.upsert_customer.assert_awaited_once_with(30,'new','Friend',10)
        db.upsert_customer.reset_mock();message.chat.type='group'
        with patch.object(bot,'database',db): await bot.command_menu(message,state)
        db.upsert_customer.assert_awaited_once_with(30,'new','Friend',None)

    async def test_bonus_screen_has_copy_share_and_real_stats(self):
        db=SimpleNamespace(upsert_customer=AsyncMock(),referral_stats=AsyncMock(return_value=dict(invited=4,earned='1.25',purchases=0)))
        state=SimpleNamespace(clear=AsyncMock())
        cb=SimpleNamespace(from_user=SimpleNamespace(id=10,username='test',first_name='Test'),answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(type='private',id=10),delete=AsyncMock(),answer=AsyncMock(),answer_photo=AsyncMock()))
        with patch.object(bot,'database',db): await bot.open_bonus(cb,state)
        call=cb.message.answer_photo.call_args or cb.message.answer.call_args
        text=call.kwargs['caption'] if cb.message.answer_photo.call_args else call.args[0]
        self.assertIn(referral_link(10),text);self.assertIn('5%',text)
        self.assertIn('<b>4</b>',text);self.assertIn('1.25',text)
        buttons=[b for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(buttons[0].copy_text.text,referral_link(10))
        self.assertIn('t.me/share/url?',buttons[1].url)
        self.assertEqual(buttons[-1].callback_data,'menu')

    async def test_bonus_handler_precedes_static_screen_handler(self):
        names=[h.callback.__name__ for h in bot.router.callback_query.handlers]
        self.assertLess(names.index('open_bonus'),names.index('open_screen'))


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'),'requires disposable TEST_DATABASE_URL')
class ReferralLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await payment_tests.LedgerTests.asyncSetUp(self)
        await self.db.upsert_customer(30,'friend','Friend',10)

    async def asyncTearDown(self):
        await payment_tests.LedgerTests.asyncTearDown(self)

    async def buy(self,owner=30,count=1):
        p=await self.service.checkout(owner,'product',product_id=self.pid,count=count)
        await self.store.apply(self.api.paid(p))
        return p

    async def test_new_invitee_is_attributed_existing_user_cannot_rebind(self):
        self.assertEqual((await self.db.customer(30))['referred_by'],10)
        await self.db.upsert_customer(30,'renamed','Friend',20)
        self.assertEqual((await self.db.customer(30))['referred_by'],10)
        await self.db.upsert_customer(20,'other','Other',10)
        self.assertIsNone((await self.db.customer(20))['referred_by'])
        stats=await self.db.referral_stats(10)
        self.assertEqual(stats['invited'],1)

    async def test_self_and_unknown_inviter_are_ignored(self):
        await self.db.upsert_customer(40,'self','Self',40)
        await self.db.upsert_customer(50,'unknown','Unknown',999)
        self.assertIsNone((await self.db.customer(40))['referred_by'])
        self.assertIsNone((await self.db.customer(50))['referred_by'])

    async def test_first_crypto_purchase_awards_5_percent_once(self):
        p=await self.service.checkout(30,'product',product_id=self.pid,count=2)
        invoice=self.api.paid(p)
        await asyncio.gather(*(self.store.apply(invoice) for _ in range(8)))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.25'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)
        self.assertEqual(await self.pool.fetchval('SELECT amount FROM referral_rewards'),Decimal('0.25'))
        self.assertEqual((await self.db.dashboard())['revenue'],'5.00')
        stats=await self.db.referral_stats(10)
        self.assertEqual(stats['earned'],'0.25')
        self.assertEqual((await self.db.referral_stats(30))['purchases'],1)

    async def test_second_purchase_does_not_award_again(self):
        await self.buy();await self.buy()
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)

    async def test_topup_does_not_award_but_wallet_purchase_does(self):
        p=await self.service.checkout(30,'topup',amount=Decimal('5'))
        await self.store.apply(self.api.paid(p))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0'))
        p=await self.service.checkout(30,'product',product_id=self.pid,count=2)
        await self.service.balance_purchase(p['id'],30)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.25'))
        self.assertEqual((await self.db.customer(30))['balance'],Decimal('0'))

    async def test_no_stock_credit_does_not_award_referral_bonus(self):
        p=await self.service.checkout(30,'product',product_id=self.pid,count=4)
        await self.store.release(p['id']);other=await self.service.checkout(20,'product',product_id=self.pid,count=4)
        await self.store.apply(self.api.paid(other));await self.store.apply(self.api.paid(p))
        self.assertEqual((await self.db.customer(30))['balance'],Decimal('10'))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),0)

    async def test_cancelled_or_active_invoice_does_not_award(self):
        p=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        await self.store.apply(dict(self.api.data[p['invoice_id']]))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),0)
        await self.store.release(p['id'])
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0'))

    async def test_zero_cent_reward_still_consumes_first_purchase(self):
        await self.db.save_product(dict(name='Tiny',price='0.01',description=''),self.pid)
        await self.buy()
        await self.db.save_product(dict(name='Large',price='2.50',description=''),self.pid)
        await self.buy()
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)
        self.assertEqual(await self.pool.fetchval('SELECT amount FROM referral_rewards'),Decimal('0'))
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0'))

    async def test_two_parallel_orders_reward_only_first(self):
        # Two pending orders are intentional for a concurrency regression; owner-bound
        # service normally reuses an active checkout, so prepare via direct test SQL expiry.
        first=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        await self.pool.execute("UPDATE payments SET expires_at=NOW()-INTERVAL '1 second' WHERE id=$1",first['id'])
        second=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        await asyncio.wait_for(asyncio.gather(self.store.apply(self.api.paid(first)),self.store.apply(self.api.paid(second))),3)
        self.assertEqual(await self.pool.fetchval("SELECT COUNT(*) FROM orders WHERE customer_id=30 AND status='paid'"),2)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))

    async def test_inviter_and_invitee_buying_same_product_do_not_deadlock(self):
        first=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        parent=await self.service.checkout(10,'product',product_id=self.pid,count=1)
        await asyncio.wait_for(asyncio.gather(self.store.apply(self.api.paid(first)),self.store.apply(self.api.paid(parent))),3)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM stock_items WHERE is_issued'),2)

    async def test_smaller_invitee_id_than_inviter_does_not_deadlock(self):
        await self.db.upsert_customer(5,'younger','Younger',20)
        child=await self.service.checkout(5,'product',product_id=self.pid,count=1)
        parent=await self.service.checkout(20,'product',product_id=self.pid,count=1)
        await asyncio.wait_for(asyncio.gather(self.store.apply(self.api.paid(child)),self.store.apply(self.api.paid(parent))),3)
        self.assertEqual((await self.db.customer(20))['balance'],Decimal('0.13'))

    async def test_chain_purchases_award_direct_inviter_only(self):
        await self.db.upsert_customer(40,'friend2','Friend2',30)
        one=await self.service.checkout(10,'product',product_id=self.pid,count=1)
        two=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        three=await self.service.checkout(40,'product',product_id=self.pid,count=1)
        await asyncio.wait_for(asyncio.gather(*(self.store.apply(self.api.paid(p)) for p in [one,two,three])),3)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))
        self.assertEqual((await self.db.customer(30))['balance'],Decimal('0.13'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),2)

    async def test_extra_crypto_payment_after_wallet_purchase_does_not_award_again(self):
        await self.db.grant_balance_by_id(30,Decimal('2.50'),'test')
        p=await self.service.checkout(30,'product',product_id=self.pid,count=1)
        late=dict(self.api.data[p['invoice_id']],status='paid')
        await self.service.balance_purchase(p['id'],30)
        await self.store.apply(late)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))
        self.assertEqual((await self.db.customer(30))['balance'],Decimal('2.50'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)

    async def test_schema_upgrade_keeps_attribution_and_rewards(self):
        from storage import SCHEMA
        await self.buy();await self.pool.execute(SCHEMA)
        self.assertEqual((await self.db.customer(30))['referred_by'],10)
        self.assertEqual((await self.db.customer(10))['balance'],Decimal('0.13'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM referral_rewards'),1)


if __name__=='__main__':
    unittest.main()
