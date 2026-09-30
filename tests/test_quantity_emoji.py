"""The real Telegram set supplies IDs; screenshots never become guessed IDs."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
from quantity_emoji import QuantityEmoji

# Deliberately synthetic test fixture IDs, not production defaults.
MINUS_ID = '1234567890123456781'
PLUS_ID = '1234567890123456782'


def pack():
    return SimpleNamespace(name='ABCEmoji',sticker_type='custom_emoji',stickers=[
        SimpleNamespace(emoji='🔤',custom_emoji_id='1234567890123456783'),
        SimpleNamespace(emoji='➖',custom_emoji_id=MINUS_ID),
        SimpleNamespace(emoji='➕',custom_emoji_id=PLUS_ID),
    ])


class QuantityEmojiTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_exact_set_and_caches(self):
        telegram=SimpleNamespace(get_sticker_set=AsyncMock(return_value=pack()))
        icons=QuantityEmoji()
        self.assertEqual(await icons.load(telegram), {'minus':MINUS_ID,'plus':PLUS_ID})
        self.assertEqual(await icons.load(telegram), {'minus':MINUS_ID,'plus':PLUS_ID})
        telegram.get_sticker_set.assert_awaited_once_with('ABCEmoji', request_timeout=5)

    async def test_concurrent_loads_share_request(self):
        async def load(*args,**kwargs):
            await asyncio.sleep(0.005);return pack()
        telegram=SimpleNamespace(get_sticker_set=AsyncMock(side_effect=load))
        icons=QuantityEmoji()
        result=await asyncio.gather(*(icons.load(telegram) for _ in range(8)))
        self.assertTrue(all(r['plus']==PLUS_ID for r in result))
        telegram.get_sticker_set.assert_awaited_once()

    async def test_wrong_pack_is_not_used(self):
        wrong=pack();wrong.name='OtherSet'
        telegram=SimpleNamespace(get_sticker_set=AsyncMock(return_value=wrong))
        self.assertEqual(await QuantityEmoji().load(telegram),{})

    async def test_outage_keeps_buttons_and_retries_after_delay(self):
        telegram=SimpleNamespace(get_sticker_set=AsyncMock(side_effect=RuntimeError('unavailable')))
        icons=QuantityEmoji()
        with patch('quantity_emoji.time.monotonic',return_value=100):
            self.assertEqual(await icons.load(telegram),{})
            self.assertEqual(await icons.load(telegram),{})
        telegram.get_sticker_set.assert_awaited_once()
        telegram.get_sticker_set.side_effect=None;telegram.get_sticker_set.return_value=pack()
        with patch('quantity_emoji.time.monotonic',return_value=161):
            self.assertEqual((await icons.load(telegram))['minus'],MINUS_ID)

    async def test_no_guessed_ids_when_bot_not_connected(self):
        self.assertEqual(await QuantityEmoji().load(None),{})
        b=bot.quantity_button('−','qty:1:1',None)
        self.assertEqual(b.text,'−');self.assertIsNone(b.icon_custom_emoji_id)
        self.assertEqual(b.style,'primary')

    def test_premium_button_has_only_one_visible_icon_and_is_blue(self):
        b=bot.quantity_button('+','qty:1:2',PLUS_ID)
        self.assertEqual(b.icon_custom_emoji_id,PLUS_ID)
        self.assertEqual(b.style,'primary')
        self.assertNotIn('+',b.text)
        self.assertTrue(b.text)

    async def test_card_does_not_create_or_display_payment_until_clicked(self):
        product=dict(id=2,name='Gemini',price='2.50',description='Access',category_id=1,is_active=True)
        db=SimpleNamespace(upsert_customer=AsyncMock())
        service=SimpleNamespace(store=SimpleNamespace(available=AsyncMock(return_value=3)),
                                checkout=AsyncMock(),lock=lambda *args:asyncio.Lock())
        cb=SimpleNamespace(data='product:2',from_user=SimpleNamespace(id=10,username='test',first_name='Test'),
                           message=SimpleNamespace(answer=AsyncMock(),edit_text=AsyncMock()))
        icons=SimpleNamespace(load=AsyncMock(return_value={'minus':MINUS_ID,'plus':PLUS_ID}))
        with patch.object(bot,'database',db),patch.object(bot,'payments',service),patch.object(bot,'quantity_emoji',icons):
            await bot.render_product(cb,product,2)
        service.checkout.assert_not_awaited()
        text=cb.message.answer.call_args.args[0]
        buttons=[b for row in cb.message.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertNotIn('К оплате',text);self.assertNotIn('В рублях',text);self.assertNotIn('Счёт действителен',text)
        self.assertEqual([b.style for b in buttons[:4]],['primary']*4)
        self.assertEqual(buttons[0].icon_custom_emoji_id,MINUS_ID)
        self.assertEqual(buttons[2].icon_custom_emoji_id,PLUS_ID)
        self.assertEqual(buttons[1].text,'2 шт.')
        self.assertEqual(buttons[3].text,'Способы оплаты')
        self.assertEqual(buttons[3].callback_data,'pay_methods:2:2')
        self.assertFalse(any(b.url for b in buttons))

    async def test_methods_screen_has_existing_payment_flow_and_total(self):
        from decimal import Decimal
        product=dict(id=2,name='Gemini',price='2.50',description='',category_id=1,is_active=True)
        p=dict(id=3,amount=Decimal('5.00'),quantity=2,status='pending',product_name='Gemini',pay_url='https://t.me/CryptoBot?start=invoice')
        service=SimpleNamespace(checkout=AsyncMock(return_value=p))
        db=SimpleNamespace(upsert_customer=AsyncMock())
        cb=SimpleNamespace(from_user=SimpleNamespace(id=10,username='test',first_name='Test'),message=SimpleNamespace(answer=AsyncMock()))
        with patch.object(bot,'database',db),patch.object(bot,'payments',service),patch.object(bot.exchange_rates,'quote',AsyncMock(return_value=None)):
            await bot.show_product_payment_methods(cb,product,2)
        service.checkout.assert_awaited_once_with(10,'product',product_id=2,count=2)
        text=cb.message.answer.call_args.args[0]
        self.assertIn('5.00',text);self.assertIn('2 шт.',text)
        buttons=[b for row in cb.message.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertTrue(any(b.url==p['pay_url'] for b in buttons))
        self.assertTrue(any(b.callback_data=='check_payment:3' for b in buttons))
        self.assertTrue(any(b.callback_data=='pay_balance:3' for b in buttons))
        self.assertEqual(buttons[-1].callback_data,'product:2:2')

    async def test_invalid_quantity_rejected_before_provider_request(self):
        cb=SimpleNamespace(data='pay_methods:2:101',from_user=SimpleNamespace(id=10),
            message=SimpleNamespace(chat=SimpleNamespace(type='private',id=10)),answer=AsyncMock())
        service=SimpleNamespace(checkout=AsyncMock())
        with patch.object(bot,'payments',service):
            await bot.open_payment_methods(cb)
        service.checkout.assert_not_awaited()
        cb.answer.assert_awaited_once()
        self.assertTrue(cb.answer.call_args.kwargs['show_alert'])

    async def test_methods_do_not_offer_payment_for_missing_stock(self):
        product=dict(id=2,name='Gemini',price='2.50')
        service=SimpleNamespace(checkout=AsyncMock(side_effect=ValueError('Товар закончился')))
        db=SimpleNamespace(upsert_customer=AsyncMock())
        cb=SimpleNamespace(from_user=SimpleNamespace(id=10,username='test',first_name='Test'),message=SimpleNamespace(answer=AsyncMock()))
        with patch.object(bot,'payments',service),patch.object(bot,'database',db):
            await bot.show_product_payment_methods(cb,product,2)
        buttons=[b for row in cb.message.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertFalse(any(b.url for b in buttons))
        self.assertEqual(len(buttons),1)


if __name__=='__main__':
    unittest.main()
