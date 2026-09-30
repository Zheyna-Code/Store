from decimal import Decimal
import asyncio
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import bot
from emoji_library import EmojiLibrary, validate_emoji_id
from shop_emoji import DEFAULT_EMOJI
from storage import Database

PNG = b'\x89PNG\r\n\x1a\npreview-fixture'


class FakeTelegram:
    def __init__(self):
        self.calls = 0
    async def get_custom_emoji_stickers(self, custom_emoji_ids):
        self.calls += 1
        return [SimpleNamespace(custom_emoji_id=value, emoji='⭐️', set_name='TestPack',
            needs_repainting=True, is_animated=True, is_video=False,
            thumbnail=SimpleNamespace(file_id='thumb'), file_id='animated') for value in custom_emoji_ids if value != '999']
    async def get_file(self, file_id):
        assert file_id == 'thumb'
        return SimpleNamespace(file_path='private/path.webp', file_size=len(PNG))
    async def download_file(self, path, destination, timeout):
        destination.write(PNG)


class EmojiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.apply_emoji_settings({})
    def test_ids_are_strings(self):
        self.assertEqual(validate_emoji_id('5843843420468024653'), '5843843420468024653')
        for value in [5843843420468024653, '', '0', '1<script>', '1'*21, [], None]:
            with self.assertRaises(ValueError): validate_emoji_id(value)
    def test_inherited_category_icons(self):
        for name in ['ChatGPT', 'Claude', 'Gemini']:
            self.assertEqual(bot.category_icon({'name':name})[0], DEFAULT_EMOJI[name.lower()])
        self.assertEqual(bot.category_icon({'name':'ChatGPT','custom_emoji_id':'123','emoji_fallback':'⭐️'}), ('123','⭐️'))
        self.assertEqual(bot.category_icon({'name':None})[0], DEFAULT_EMOJI['catalog'])
    def test_card_order_and_escaping(self):
        p = dict(name='<Pro>', description='A & B', price='1.00', category_name='ChatGPT')
        card = bot.product_card(p, 3)
        for text in [DEFAULT_EMOJI['chatgpt'], '5843843420468024653', '5974217466270716579', '5877260593903177342']:
            self.assertIn(text, card)
        self.assertLess(card.index(DEFAULT_EMOJI['chatgpt']), card.index('&lt;Pro&gt;'))
        self.assertLess(card.index('5843843420468024653'), card.index('A &amp; B'))
        self.assertNotIn('₽', card)
        self.assertIn('В наличии: <b>3</b>', card)
        self.assertIn('1.00', card)
    def test_custom_category_in_card(self):
        card = bot.product_card(dict(name='X',description='',price='3',category_name='Claude',category_emoji_id='123',category_emoji_fallback='🌟'),0)
        self.assertTrue(card.startswith('<tg-emoji emoji-id="123">🌟</tg-emoji>'))
    def test_settings_rebuild_static_keyboards(self):
        bot.apply_emoji_settings({'catalog':'123','dollar':'456'})
        self.assertEqual(bot.SCREENS['menu'][2].inline_keyboard[0][0].icon_custom_emoji_id, '123')
        self.assertEqual(bot.SCREENS['wallet'][2].inline_keyboard[0][0].icon_custom_emoji_id, '456')
        self.assertIn('emoji-id="456"', bot.dollars('10 000'))
        bot.apply_emoji_settings({})
        self.assertEqual(bot.EMOJI['catalog'], DEFAULT_EMOJI['catalog'])
    async def test_product_buttons_use_category_and_usd(self):
        db = SimpleNamespace(active_categories=AsyncMock(return_value=[dict(id=1,name='ChatGPT')]),
            category_products=AsyncMock(return_value=[dict(id=5,name='Test',price='1.00',stock_count=3),
                dict(id=6,name='Empty',price='2.00',stock_count=0)]))
        message = SimpleNamespace(delete=AsyncMock(),answer=AsyncMock(),answer_photo=AsyncMock())
        with patch.object(bot,'database',db): await bot.show_category(message,1)
        call = message.answer_photo.call_args or message.answer.call_args
        keyboard = call.kwargs['reply_markup']
        self.assertEqual(keyboard.inline_keyboard[0][0].icon_custom_emoji_id, DEFAULT_EMOJI['chatgpt'])
        self.assertEqual(keyboard.inline_keyboard[0][0].text, 'Test · $1.00')
        self.assertEqual(keyboard.inline_keyboard[0][0].style, 'success')
        self.assertEqual(keyboard.inline_keyboard[1][0].style, 'danger')
        self.assertIn('нет в наличии', keyboard.inline_keyboard[1][0].text)
    async def test_crypto_invoice_is_usd(self):
        from crypto_pay import CryptoPay
        client = CryptoPay('test')
        client.request = AsyncMock(return_value={'invoice_id': 1})
        await client.create(dict(amount=Decimal('1.00'), product_name='Test', quantity=1, purpose='product', payload='shop:test'))
        self.assertEqual(client.request.call_args.args[1]['fiat'], 'USD')
        self.assertEqual(client.request.call_args.args[1]['amount'], '1.00')
    async def test_library_thumbnails_and_cache(self):
        library = EmojiLibrary(Path('catalog/emojis.json')); tg = FakeTelegram()
        meta = await library.previews(tg,['123','999'])
        self.assertTrue(meta['123']['available']); self.assertFalse(meta['999']['available'])
        content,mime = await library.image(tg,'123')
        self.assertEqual(content,PNG); self.assertEqual(mime,'image/png')
        self.assertEqual(await library.image(tg,'123'),(PNG,'image/png'))
        self.assertEqual(tg.calls,1)
    async def test_no_animated_file_without_thumbnail(self):
        library = EmojiLibrary(Path('catalog/emojis.json')); tg = FakeTelegram()
        await library.previews(tg,['123']); library.metadata['123'].thumbnail=None
        with self.assertRaises(ValueError): await library.image(tg,'123')
    async def test_category_update_preserves_emoji_for_older_clients(self):
        db=Database('unused'); pool=SimpleNamespace(fetchrow=AsyncMock(return_value={'id':1}))
        db.pool=pool
        await db.save_category(dict(name='ChatGPT',sort_order=1,is_active=False),1)
        args=pool.fetchrow.call_args.args
        self.assertFalse(args[4]); self.assertIn('ELSE custom_emoji_id',args[0])
        await db.save_category(dict(name='ChatGPT',custom_emoji_id='123',emoji_fallback='⭐️'),1)
        self.assertTrue(pool.fetchrow.call_args.args[4]); self.assertEqual(pool.fetchrow.call_args.args[5],'123')
        await db.save_category(dict(name='ChatGPT',custom_emoji_id=None),1)
        self.assertTrue(pool.fetchrow.call_args.args[4]); self.assertIsNone(pool.fetchrow.call_args.args[5])
    async def test_product_query_joins_category_emoji(self):
        db=Database('unused'); pool=SimpleNamespace(fetchrow=AsyncMock(return_value={'name':'Test','category_emoji_id':'123'}));db.pool=pool
        row=await db.product(1)
        self.assertEqual(row['category_emoji_id'],'123'); self.assertIn('c.custom_emoji_id',pool.fetchrow.call_args.args[0])
    def test_catalog_unique_string_ids(self):
        library=EmojiLibrary(Path('catalog/emojis.json'))
        ids=[validate_emoji_id(e['id']) for e in library.items]
        self.assertEqual(len(ids),1923); self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(library.items[0]['id'],'5875465628285931233')


class AdminApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bot.apply_emoji_settings({}); bot.admin_sessions.add('test-token')
        self.old_db,self.old_tg,self.old_library=bot.database,bot.telegram_bot,bot.emoji_library
        self.saved={}
        async def save(values): self.saved.update(values); return self.saved
        bot.database=SimpleNamespace(save_emoji_settings=save)
        bot.telegram_bot=FakeTelegram(); bot.emoji_library=EmojiLibrary(Path('catalog/emojis.json'))
        app=web.Application()
        app.router.add_route('*','/settings',bot.admin_emoji_settings)
        app.router.add_get('/catalog',bot.admin_emoji_catalog)
        app.router.add_post('/previews',bot.admin_emoji_previews)
        app.router.add_get('/image/{id}',bot.admin_emoji_image)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.headers={'X-Admin-Token':'test-token'}
    async def asyncTearDown(self):
        await self.client.close();bot.database,bot.telegram_bot,bot.emoji_library=self.old_db,self.old_tg,self.old_library
        bot.admin_sessions.discard('test-token');bot.apply_emoji_settings({})
    async def test_all_emoji_endpoints_require_auth(self):
        for method,path in [('GET','/settings'),('GET','/catalog'),('POST','/previews'),('GET','/image/123')]:
            response=await self.client.request(method,path,json={'ids':['123']} if method=='POST' else None)
            self.assertEqual(response.status,401)
    async def test_settings_roundtrip(self):
        response=await self.client.put('/settings',headers=self.headers,json={'stock':'123'})
        self.assertEqual(response.status,200);values=await response.json();self.assertEqual(values['values']['stock'],'123')
        self.assertEqual(self.saved,{'stock':'123'})
        response=await self.client.get('/settings',headers=self.headers)
        self.assertEqual((await response.json())['values']['stock'],'123')
    async def test_malformed_settings_rejected(self):
        for body in [{'stock':123},{'no-such-role':'123'},['123']]:
            response=await self.client.put('/settings',headers=self.headers,json=body);self.assertEqual(response.status,400)
    async def test_preview_limits_and_exact_id(self):
        for ids in [[123],['123']*61]:
            response=await self.client.post('/previews',headers=self.headers,json={'ids':ids});self.assertEqual(response.status,400)
        response=await self.client.post('/previews',headers=self.headers,json={'ids':['5843843420468024653']})
        self.assertEqual(response.status,200);self.assertTrue((await response.json())['5843843420468024653']['available'])
    async def test_image_returns_bytes_without_private_urls(self):
        response=await self.client.get('/image/123',headers=self.headers)
        self.assertEqual(response.status,200);self.assertEqual(await response.read(),PNG)
        self.assertEqual(response.headers['Content-Type'],'image/png'); self.assertEqual(response.headers['X-Emoji-Repainting'],'true')
    async def test_telegram_error_never_exposes_token(self):
        bot.telegram_bot.get_custom_emoji_stickers=AsyncMock(side_effect=RuntimeError('https://api.telegram.org/botPRIVATE-TOKEN/file'))
        response=await self.client.post('/previews',headers=self.headers,json={'ids':['123']})
        self.assertEqual(response.status,400);self.assertNotIn('PRIVATE-TOKEN',await response.text())

if __name__ == '__main__': unittest.main()
