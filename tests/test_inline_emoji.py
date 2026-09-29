import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerInlineQuery
from PIL import Image

import bot
from inline_emoji import (InlineCatalog, InlineThumbnails, PAGE_SIZE, compose, jpeg_thumbnail,
                          public_base, result_for, signature, thumbnail_url, valid_thumbnail)

SECRET = 'unit-test-secret-not-a-production-key'
BASE = 'https://example.invalid'
ITEMS = [dict(id=str(1000+i), emoji='⭐️' if i % 2 else '💵', pack='TestPack', category='finance') for i in range(70)]


def png(color='black', transparent=True):
    image = Image.new('RGBA' if transparent else 'RGB', (100, 100), (0, 0, 0, 0) if transparent else color)
    if transparent:
        image.paste(color, (25, 25, 75, 75))
    data = BytesIO()
    image.save(data, 'PNG')
    return data.getvalue()


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = InlineCatalog(ITEMS)

    def test_inline_registered_and_help_precedes_wallet_text(self):
        self.assertIn('inline_query', bot.router.resolve_used_update_types())
        names = [handler.callback.__name__ for handler in bot.router.message.handlers]
        self.assertLess(names.index('inline_help'), names.index('receive_custom_amount'))

    def test_bad_catalog_id_rejected(self):
        with self.assertRaises(ValueError):
            InlineCatalog([{**ITEMS[0], 'id': '1" onclick="bad'}])

    def test_alias_and_pack_search(self):
        text, rows, next_offset = self.catalog.page('Привет! | звезда TestPack')
        self.assertEqual(text, 'Привет!')
        self.assertEqual(len(rows), PAGE_SIZE)
        self.assertTrue(all(row['emoji'] == '⭐️' for row in rows))
        self.assertEqual(next_offset, str(PAGE_SIZE))
        _, remainder, final_offset = self.catalog.page('Привет! | ⭐', next_offset)
        self.assertEqual(len(remainder), 11)
        self.assertEqual(final_offset, '')
        self.assertEqual(self.catalog.page('Hi | unknown')[1], [])

    def test_default_order_and_emoji_only(self):
        text, rows, _ = self.catalog.page('')
        self.assertEqual(text, '')
        self.assertEqual(rows, ITEMS[:PAGE_SIZE])
        self.assertTrue(compose('', '1001', '⭐️').startswith('<tg-emoji'))

    def test_bad_offsets(self):
        for offset in ['-1', 'x', '1'*50, '１２']:
            with self.assertRaises(ValueError):
                self.catalog.page('Hi', offset)
        self.assertEqual(self.catalog.page('Hi', '99999')[1:], ([], ''))

    def test_text_is_literal_and_placeholder_supported(self):
        tag = '<tg-emoji emoji-id="1001">⭐️</tg-emoji>'
        self.assertEqual(compose('<b>A&B</b>', '1001', '⭐️'), '&lt;b&gt;A&amp;B&lt;/b&gt; ' + tag)
        self.assertEqual(compose('До {эмодзи} после {эмодзи}', '1001', '⭐️'), 'До ' + tag + ' после ' + tag)
        self.assertNotIn('<img', compose('<img src=x>', '1001', '⭐️'))

    def test_same_id_in_message_and_thumbnail(self):
        result = result_for('Hi | ⭐', 'Hi', ITEMS[1], self.catalog, BASE, SECRET)
        self.assertIn('emoji-id="1001"', result.input_message_content.message_text)
        self.assertIn('/1001.jpg?', result.thumbnail_url)
        self.assertEqual(result.input_message_content.parse_mode, 'HTML')
        self.assertTrue(result.input_message_content.link_preview_options.is_disabled)
        self.assertLessEqual(len(result.id.encode()), 64)
        self.assertNotIn(SECRET, result.thumbnail_url)
        self.assertNotIn('Hi', result.thumbnail_url)

    def test_https_base_only(self):
        self.assertEqual(public_base(BASE+'/'), BASE)
        for value in ['', 'http://example.invalid', BASE+'/admin', 'https://x:y@example.invalid', BASE+'?token=x', BASE+'#x']:
            with self.assertRaises(ValueError):
                public_base(value)

    def test_signed_urls_bounded_and_no_forged_images(self):
        url = thumbnail_url(BASE, SECRET, '1001', now=1000)
        params = parse_qs(urlsplit(url).query)
        expiry, sig = params['expires'][0], params['sig'][0]
        self.assertTrue(valid_thumbnail(SECRET, self.catalog.ids, '1001', expiry, sig, now=1001))
        for emoji_id, deadline, signature_value in [('999', expiry, sig), ('1001', expiry, 'λ'), ('1001', expiry, 'x'*64), ('1001', 'bad', sig)]:
            self.assertFalse(valid_thumbnail(SECRET, self.catalog.ids, emoji_id, deadline, signature_value, now=1001))
        self.assertFalse(valid_thumbnail(SECRET, self.catalog.ids, '1001', expiry, sig, now=1901))
        self.assertFalse(valid_thumbnail(SECRET, self.catalog.ids, '1001', '3000', signature(SECRET, '1001', 3000), now=1001))

    def test_real_image_conversion_and_repainting(self):
        for repaint in [False, True]:
            image = Image.open(BytesIO(jpeg_thumbnail(png(), repaint)))
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.size, (128, 128))
            self.assertEqual(image.mode, 'RGB')
            if repaint:
                self.assertGreater(min(image.getpixel((64, 64))), 240)
        # Do not repaint an opaque JPEG/PNG into a solid white block.
        image = Image.open(BytesIO(jpeg_thumbnail(png('red', transparent=False), True)))
        self.assertGreater(image.getpixel((64, 64))[0], 240)
        self.assertLess(image.getpixel((64, 64))[1], 20)
        with self.assertRaises(ValueError):
            jpeg_thumbnail(b'not an image')


class AsyncInlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = SimpleNamespace(public_base_url=BASE, admin_secret=SECRET)
        self.catalog = InlineCatalog(ITEMS)
        self.library = SimpleNamespace(metadata={})
        async def previews(client, ids):
            for emoji_id in ids:
                self.library.metadata[emoji_id] = SimpleNamespace(is_animated=False, is_video=False)
            # The original Telegram metadata wins over catalog Unicode labels.
            return {emoji_id: dict(available=True, emoji='🌟') for emoji_id in ids}
        self.library.previews = AsyncMock(side_effect=previews)
        self.query = SimpleNamespace(query='A&B | звезда', offset='', bot=object(), answer=AsyncMock())

    async def invoke(self):
        with patch.object(bot, 'settings', self.settings), patch.object(bot, 'inline_catalog', self.catalog), patch.object(bot, 'emoji_library', self.library):
            await bot.inline_compose(self.query)

    async def test_inline_returns_real_ids_and_private_cache(self):
        await self.invoke()
        results = self.query.answer.call_args.args[0]
        self.assertEqual(len(results), PAGE_SIZE)
        self.assertIn('A&amp;B', results[0].input_message_content.message_text)
        self.assertIn('🌟', results[0].input_message_content.message_text)
        self.assertIn(f'emoji-id="{ITEMS[1]["id"]}"', results[0].input_message_content.message_text)
        self.assertTrue(self.query.answer.call_args.kwargs['is_personal'])
        self.assertEqual(self.query.answer.call_args.kwargs['next_offset'], str(PAGE_SIZE))
        self.assertEqual(self.query.answer.call_args.kwargs['cache_time'], 10)

    async def test_missing_address_gives_setup_help_no_unicode_substitute(self):
        self.settings.public_base_url = ''
        await self.invoke()
        self.assertEqual(self.query.answer.call_args.args[0], [])
        self.assertEqual(self.query.answer.call_args.kwargs['button'].start_parameter, 'inline_help')
        self.library.previews.assert_not_awaited()

    async def test_api_premium_denial_gives_help(self):
        self.query.answer.side_effect = [TelegramBadRequest(method=AnswerInlineQuery(inline_query_id='test', results=[]), message='CUSTOM_EMOJI_NOT_ALLOWED'), True]
        await self.invoke()
        self.assertEqual(self.query.answer.await_count, 2)
        self.assertEqual(self.query.answer.call_args.args[0], [])
        self.assertEqual(self.query.answer.call_args.kwargs['button'].start_parameter, 'inline_error')

    async def test_expired_query_is_ignored_without_spamming(self):
        self.query.answer.side_effect = TelegramBadRequest(method=AnswerInlineQuery(inline_query_id='test', results=[]), message='query is invalid')
        await self.invoke()
        self.assertEqual(self.query.answer.await_count, 1)

    async def test_unavailable_metadata_no_fake_emoji(self):
        self.library.previews.side_effect = None
        self.library.previews.return_value = {row['id']: dict(available=False, emoji='') for row in ITEMS}
        await self.invoke()
        self.assertEqual(self.query.answer.call_args.args[0], [])

    async def test_network_error_returns_help(self):
        self.library.previews.side_effect = asyncio.TimeoutError
        await self.invoke()
        self.assertEqual(self.query.answer.call_args.args[0], [])

    async def test_empty_search_has_help(self):
        self.query.query = 'Hi | xyz_no_match'
        await self.invoke()
        self.library.previews.assert_not_awaited()
        self.assertEqual(self.query.answer.call_args.args[0], [])

    async def test_thumbnail_requests_share_work_and_cache(self):
        library = SimpleNamespace(metadata={'1001': SimpleNamespace(needs_repainting=True)}, image=AsyncMock(return_value=(png(), 'image/png')))
        thumbs = InlineThumbnails()
        values = await asyncio.gather(*(thumbs.get(object(), library, '1001') for _ in range(8)))
        self.assertTrue(all(value == values[0] for value in values))
        self.assertEqual(await thumbs.get(object(), library, '1001'), values[0])
        library.image.assert_awaited_once()

    async def test_public_thumbnail_requires_valid_signature(self):
        app = web.Application()
        app.router.add_get('/api/inline/emoji/{id}.jpg', bot.inline_emoji_thumbnail)
        service = SimpleNamespace(get=AsyncMock(return_value=jpeg_thumbnail(png())))
        with patch.object(bot, 'settings', self.settings), patch.object(bot, 'inline_catalog', self.catalog), patch.object(bot, 'inline_thumbnails', service), patch.object(bot, 'telegram_bot', object()):
            async with TestClient(TestServer(app)) as client:
                plain = await client.get('/api/inline/emoji/1001.jpg')
                self.assertEqual(plain.status, 404)
                bad = await client.get('/api/inline/emoji/1001.jpg?expires=123&sig=λ')
                self.assertEqual(bad.status, 404)
                url = thumbnail_url(BASE, SECRET, '1001')
                parsed = urlsplit(url)
                good = await client.get(parsed.path + '?' + parsed.query)
                self.assertEqual(good.status, 200)
                self.assertEqual(good.content_type, 'image/jpeg')
                self.assertTrue((await good.read()).startswith(b'\xff\xd8'))
                self.assertNotIn('BOT_TOKEN', str(good.headers))
                service.get.assert_awaited_once()

    async def test_help_and_deep_link_do_not_touch_shop_database(self):
        message = SimpleNamespace(text='/start inline_help', bot=SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username='TestBot'))), answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        with patch.object(bot, 'settings', self.settings), patch.object(bot, 'get_database', side_effect=AssertionError('No shop mutation')):
            await bot.command_menu(message, state)
        self.assertIn('@TestBot', message.answer.call_args.args[0])
        self.assertEqual(message.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0].switch_inline_query, 'Привет! | ⭐')


if __name__ == '__main__':
    unittest.main()
