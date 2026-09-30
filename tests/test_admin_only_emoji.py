"""Regressions: shop/admin emoji insertion remains; experimental chat modes do not."""
import os
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, InlineQuery, Message, Update, User
from aiohttp import ClientSession

import bot
from config import settings
from storage import SCHEMA


class AdminOnlyTests(unittest.IsolatedAsyncioTestCase):
    def test_no_experimental_commands_modules_or_subscriptions(self):
        used = bot.router.resolve_used_update_types()
        for kind in ['business_connection', 'business_message', 'inline_query']:
            self.assertNotIn(kind, used)
        for name in ['secretary', 'direct_drafts', 'inline_catalog', 'inline_thumbnails',
                     'direct_emoji_callback', 'command_direct_emoji', 'inline_compose', 'inline_emoji_thumbnail']:
            self.assertFalse(hasattr(bot, name), name)
        self.assertNotIn('secretary_connections', SCHEMA)
        self.assertNotIn('secretary_chats', SCHEMA)
        self.assertNotIn('DROP TABLE', SCHEMA)
        self.assertFalse(hasattr(settings, 'public_base_url'))

    async def test_removed_business_and_inline_updates_cannot_send_shop_messages(self):
        dispatcher = Dispatcher()
        # A fresh parent uses the original router without retaining the parent after this test.
        dispatcher.include_router(bot.router)
        client = Bot('123456:ABCDEF')
        user = User(id=12, is_bot=False, first_name='Friend')
        updates = [
            Update(update_id=1, business_message=Message(message_id=1,date=datetime.now(timezone.utc),
                chat=Chat(id=12,type='private'),from_user=user,text='/start',business_connection_id='old_connection')),
            Update(update_id=2, inline_query=InlineQuery(id='old_query',from_user=user,query='Hello | star',offset='')),
        ]
        try:
            with patch.object(bot, 'get_database', side_effect=AssertionError('Removed mode reached the shop')):
                for update in updates:
                    await dispatcher.feed_update(client, update)
        finally:
            await client.session.close()
            bot.router._parent_router = None
            dispatcher.sub_routers.remove(bot.router)

    async def test_http_keeps_admin_emoji_routes_but_removes_public_inline_route(self):
        with patch.dict(os.environ, {'PORT':'0'}):
            runner = await bot.start_health_server()
        try:
            paths = {r.resource.canonical for r in runner.app.router.routes()}
            self.assertNotIn('/api/inline/emoji/{id}.jpg', paths)
            for path in ['/api/admin/emojis/settings', '/api/admin/emojis/catalog',
                         '/api/admin/emojis/previews', '/api/admin/emojis/image/{id}']:
                self.assertIn(path, paths)
            port = runner.addresses[0][1]
            async with ClientSession() as session:
                async with session.get(f'http://127.0.0.1:{port}/api/inline/emoji/123.jpg') as response:
                    self.assertEqual(response.status, 404)
                async with session.get(f'http://127.0.0.1:{port}/api/admin/emojis/catalog') as response:
                    self.assertEqual(response.status, 401)
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
