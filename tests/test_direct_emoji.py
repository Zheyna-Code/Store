import asyncio
import html
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

import bot
from direct_emoji import DraftStore, has_exact_emoji, plain_composed
from inline_emoji import InlineCatalog

ITEMS = [dict(id=str(1000+i), emoji='⭐️', pack='TestPack', category='finance') for i in range(25)]


class FakeMessage:
    def __init__(self, text='', owner=1, chat_id=10, message_id=1):
        self.text = text
        self.from_user = SimpleNamespace(id=owner)
        self.chat = SimpleNamespace(id=chat_id, type='private')
        self.message_id = message_id
        self.bot = object()
        self.entities = []
        self.keep_entities = True
        self.reply_markup = None
        self.messages = []
        self.answer = AsyncMock(side_effect=self._answer)
        self.edit_text = AsyncMock(side_effect=self._edit)

    def _update(self, text, kwargs):
        self.text = text
        self.reply_markup = kwargs.get('reply_markup')
        self.entities = [SimpleNamespace(custom_emoji_id=emoji_id) for emoji_id in re.findall(r'<tg-emoji emoji-id="([0-9]+)">', text)] if self.keep_entities else []

    async def _answer(self, text, **kwargs):
        message = FakeMessage(owner=999, chat_id=self.chat.id, message_id=100+len(self.messages))
        message.keep_entities = self.keep_entities
        message._update(text, kwargs)
        self.messages.append(message)
        return message

    async def _edit(self, text, **kwargs):
        self._update(text, kwargs)
        return self


class StoreTests(unittest.TestCase):
    def test_expiry_and_owner_binding(self):
        store = DraftStore()
        with patch('direct_emoji.time.monotonic', return_value=100):
            draft = store.create(1, 'Hello | ⭐')
        with patch('direct_emoji.time.monotonic', return_value=200):
            self.assertIs(store.get(draft.token, 1), draft)
            self.assertIsNone(store.get(draft.token, 2))
        with patch('direct_emoji.time.monotonic', return_value=1001):
            self.assertIsNone(store.get(draft.token, 1))

    def test_global_and_per_user_bounds(self):
        store = DraftStore(max_items=3, per_user=2)
        first = store.create(1, 'A')
        for _ in range(6):
            store.create(1, 'B')
        self.assertIsNone(store.get(first.token, 1))
        self.assertEqual(len(store.items), 2)
        store.create(2, 'C')
        store.create(3, 'D')
        self.assertEqual(len(store.items), 3)

    def test_lengths_and_token_size(self):
        store = DraftStore()
        draft = store.create(1, 'Hello')
        self.assertLessEqual(len(f'emod:{draft.token}:pick:12345678901234567890'.encode()), 64)
        for value in ['A'*4001, '🚀'*2100, '{эмодзи}'*81]:
            with self.assertRaises(ValueError):
                store.create(1, value)
        self.assertEqual(plain_composed('Hi {эмодзи}', '⭐️'), 'Hi ⭐️')

    def test_entity_validation(self):
        message = SimpleNamespace(entities=[SimpleNamespace(custom_emoji_id='123')])
        self.assertTrue(has_exact_emoji(message, '123'))
        self.assertFalse(has_exact_emoji(message, '456'))
        self.assertFalse(has_exact_emoji(message, '123', 2))
        self.assertFalse(has_exact_emoji(SimpleNamespace(entities=None), '123'))


class DirectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = DraftStore()
        self.catalog = InlineCatalog(ITEMS)
        self.library = SimpleNamespace(metadata={})
        async def previews(client, ids):
            return {emoji_id: dict(available=True, emoji='🌟') for emoji_id in ids}
        self.library.previews = AsyncMock(side_effect=previews)
        self.message = FakeMessage('/emoji Привет {эмодзи} друг! | звезда')
        self.patches = [patch.object(bot, 'direct_drafts', self.store), patch.object(bot, 'inline_catalog', self.catalog), patch.object(bot, 'emoji_library', self.library)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def choose(self):
        await bot.command_direct_emoji(self.message)
        self.draft = next(iter(self.store.items.values()))
        self.picker = self.message.messages[-1]
        self.choice_id = next(iter(self.draft.allowed))

    def callback(self, action='pick', value=None, owner=1, message=None):
        return SimpleNamespace(data=f'emod:{self.draft.token}:{action}:{value or self.choice_id}', from_user=SimpleNamespace(id=owner), message=message or self.picker, answer=AsyncMock())

    async def test_direct_send_uses_bot_owned_message_and_exact_id(self):
        await self.choose()
        self.assertEqual(self.picker.from_user.id, 999)
        self.assertEqual(len(self.draft.allowed), 8)
        for row in self.picker.reply_markup.inline_keyboard:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()), 64)
        await bot.direct_emoji_callback(self.callback())
        self.assertIn(f'Привет <tg-emoji emoji-id="{self.choice_id}">🌟</tg-emoji> друг!', self.picker.text)
        self.assertIsNone(self.picker.reply_markup)
        self.assertTrue(has_exact_emoji(self.picker, self.choice_id))
        self.assertTrue(self.draft.sent)
        self.assertEqual(self.draft.query, '')
        self.assertEqual(self.picker.from_user.id, 999)

    async def test_user_text_is_literal(self):
        self.message.text = '/emoji <b>Привет & друг</b> | ⭐'
        await self.choose()
        await bot.direct_emoji_callback(self.callback())
        self.assertIn('&lt;b&gt;Привет &amp; друг&lt;/b&gt;', self.picker.text)

    async def test_multiple_placeholders_keep_same_premium_id(self):
        self.message.text = '/emoji До {эмодзи} после {эмодзи} | ⭐'
        await self.choose()
        await bot.direct_emoji_callback(self.callback())
        self.assertTrue(has_exact_emoji(self.picker, self.choice_id, 2))

    async def test_foreign_user_cannot_send_draft(self):
        await self.choose()
        callback = self.callback(owner=2)
        await bot.direct_emoji_callback(callback)
        self.picker.edit_text.assert_not_awaited()
        self.assertTrue(callback.answer.call_args.kwargs['show_alert'])

    async def test_foreign_chat_and_message_blocked(self):
        await self.choose()
        for message in [FakeMessage(chat_id=20, message_id=self.picker.message_id), FakeMessage(chat_id=10, message_id=9999)]:
            callback = self.callback(message=message)
            await bot.direct_emoji_callback(callback)
            message.edit_text.assert_not_awaited()
            self.assertTrue(callback.answer.call_args.kwargs['show_alert'])

    async def test_unlisted_id_blocked(self):
        await self.choose()
        await bot.direct_emoji_callback(self.callback(value='999999'))
        self.picker.edit_text.assert_not_awaited()

    async def test_repeated_click_does_not_send_twice(self):
        await self.choose()
        await asyncio.gather(bot.direct_emoji_callback(self.callback()), bot.direct_emoji_callback(self.callback()))
        self.assertEqual(self.picker.edit_text.await_count, 1)

    async def test_evicted_draft_waiting_for_lock_cannot_send(self):
        await self.choose()
        await self.draft.lock.acquire()
        callback = self.callback()
        task = asyncio.create_task(bot.direct_emoji_callback(callback))
        await asyncio.sleep(0)
        self.store.items.pop(self.draft.token)
        self.draft.lock.release()
        await task
        self.picker.edit_text.assert_not_awaited()
        self.assertTrue(callback.answer.call_args.kwargs['show_alert'])

    async def test_group_command_with_bot_suffix(self):
        self.message.text = '/emoji@wanderersshop_bot Привет! | звезда'
        self.message.chat.type = 'supergroup'
        self.message.chat.id = -100123
        await self.choose()
        await bot.direct_emoji_callback(self.callback())
        self.assertEqual(self.picker.chat.id, -100123)
        self.assertTrue(has_exact_emoji(self.picker, self.choice_id))

    async def test_pagination_updates_allowed_choices(self):
        await self.choose()
        first = set(self.draft.allowed)
        await bot.direct_emoji_callback(self.callback('page', '8'))
        self.assertEqual(self.draft.offset, 8)
        self.assertFalse(first & set(self.draft.allowed))
        await bot.direct_emoji_callback(self.callback('pick', next(iter(first))))
        self.assertFalse(self.draft.sent)

    async def test_cancel_removes_buttons_and_erases_text(self):
        await self.choose()
        await bot.direct_emoji_callback(self.callback('cancel', '0'))
        self.assertTrue(self.draft.sent)
        self.assertEqual(self.draft.query, '')
        self.assertIsNone(self.picker.reply_markup)

    async def test_server_dropping_final_entity_is_detected(self):
        await self.choose()
        self.picker.keep_entities = False
        await bot.direct_emoji_callback(self.callback())
        self.assertIn('Telegram заменил', self.picker.text)
        self.assertTrue(self.draft.sent)
        self.assertNotIn('Привет', self.picker.text)

    async def test_server_dropping_choice_entities_does_not_fake_picker(self):
        self.message.keep_entities = False
        await bot.command_direct_emoji(self.message)
        self.assertIn('Telegram не сохранил', self.message.messages[-1].text)
        self.assertIsNone(self.message.messages[-1].reply_markup)
        draft = next(iter(self.store.items.values()))
        self.assertTrue(draft.sent)
        self.assertEqual(draft.query, '')

    async def test_api_denial_shows_error_not_plain_substitute(self):
        await self.choose()
        self.picker.edit_text.side_effect = TelegramBadRequest(method=EditMessageText(chat_id=10, message_id=100, text='test'), message='CUSTOM_EMOJI_NOT_ALLOWED')
        await bot.direct_emoji_callback(self.callback())
        self.assertIn('Не удалось', self.picker.answer.call_args.args[0])
        self.assertFalse(self.draft.sent)

    async def test_inline_text_handoff_and_private_start(self):
        query = SimpleNamespace(query='Hi {эмодзи} | ⭐', from_user=SimpleNamespace(id=1), answer=AsyncMock())
        await bot.inline_compose(query)
        self.assertEqual(query.answer.call_args.args[0], [])
        parameter = query.answer.call_args.kwargs['button'].start_parameter
        command = FakeMessage('/start '+parameter)
        with patch.object(bot, 'get_database', side_effect=AssertionError('No store DB')):
            await bot.command_menu(command, SimpleNamespace(clear=AsyncMock()))
        draft = self.store.get(parameter[2:], 1)
        self.assertEqual(draft.query, query.query)
        self.assertIsNotNone(draft.picker_id)
        self.assertEqual(draft.chat_id, 10)
        self.assertIn('Hi', command.messages[-1].text)

    async def test_handoff_not_available_to_another_user(self):
        draft = self.store.create(1, 'secret | ⭐')
        message = FakeMessage('/start e_'+draft.token, owner=2)
        with patch.object(bot, 'get_database', side_effect=AssertionError('No DB')):
            await bot.command_menu(message, SimpleNamespace(clear=AsyncMock()))
        self.assertNotIn('secret', message.messages[-1].text)
        self.assertIsNone(draft.picker_id)

    async def test_help_no_public_domain_no_fragment_setup(self):
        message = FakeMessage('/emoji')
        await bot.command_direct_emoji(message)
        self.assertIn('/emoji Привет!', message.messages[-1].text)
        self.assertNotIn('PUBLIC_BASE_URL', message.messages[-1].text)
        self.assertNotIn('Fragment', message.messages[-1].text)


if __name__ == '__main__':
    unittest.main()
