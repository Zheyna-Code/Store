"""Manual, opt-in composer for connected accounts. No automatic replies."""
import asyncio
import html
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramServerError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from direct_emoji import has_exact_emoji
from inline_emoji import PLACEHOLDER, compose
from secretary_store import can_reply


class ComposeState(StatesGroup):
    text = State()


class Secretary:
    def __init__(self, store_factory, drafts, show_choices):
        self.store = store_factory
        self.drafts = drafts
        self.show_choices = show_choices
        self.router = Router(name='manual_secretary')
        self.connection_lock = asyncio.Lock()
        self.router.business_connection.register(self.connection_changed)
        self.router.business_message.register(self.observe_message)
        self.router.message.register(self.command, Command('say', 'e'), F.chat.type == 'private')
        self.router.message.register(self.cancel, Command('cancel'), StateFilter(ComposeState.text))
        self.router.message.register(self.receive_text, StateFilter(ComposeState.text), F.text, ~F.text.startswith('/'), F.chat.type == 'private')
        self.router.callback_query.register(self.select_target, F.data.startswith('sec:'))

    async def connection_changed(self, connection, bot):
        async with self.connection_lock:
            await self.store().save_connection(connection)
        notice = ('Режим секретаря подключён. Я не отвечаю автоматически. '
                  'Для сообщения с эмодзи открой «Управлять ботом» в диалоге или напиши /say текст | поиск.'
                  if connection.is_enabled and can_reply(connection) else
                  'Отправка от твоего имени отключена или нет права отвечать. Проверь подключение и разрешения.')
        try:
            await bot.send_message(connection.user_chat_id, notice)
        except TelegramAPIError:
            pass  # The owner may not have started the bot; no notification is essential.

    async def observe_message(self, message):
        """Track a reply window, never react to text or save its contents."""
        if message.chat.type != 'private' or not message.business_connection_id:
            return
        store = self.store()
        connection = await store.connection(message.business_connection_id)
        if connection is None:
            try:
                current = await message.bot.get_business_connection(message.business_connection_id)
            except TelegramAPIError:
                return
            async with self.connection_lock:
                await store.save_connection(current)
            connection = await store.connection(message.business_connection_id)
        if not connection or not connection['is_enabled']:
            return
        if (not message.from_user or message.from_user.id == connection['owner_id']
                or getattr(message, 'sender_business_bot', None)):
            return
        title = getattr(message.chat, 'full_name', None) or getattr(message.chat, 'title', None) or str(message.chat.id)
        await store.record_incoming(message.business_connection_id, message.chat.id, title,
                                    message.date or datetime.now(timezone.utc))

    async def command(self, message, state):
        if message.chat.type != 'private' or not message.from_user:
            return
        await state.clear()
        parts = (message.text or '').split(maxsplit=1)
        if len(parts) == 1:
            await state.set_state(ComposeState.text)
            await message.answer('Напиши текст и поиск эмодзи, например:\n'
                                 '<code>Привет {эмодзи}! | звезда</code>\n'
                                 'Затем выбери диалог и эмодзи. /cancel — отмена.', parse_mode='HTML')
            return
        await self.prepare(message, parts[1])

    async def cancel(self, message, state):
        await state.clear()
        await message.answer('Создание сообщения отменено.')

    async def receive_text(self, message, state):
        data = await state.get_data()
        await state.clear()
        await self.prepare(message, message.text, data.get('target'))

    async def open_chat(self, message, state, chat_id):
        if message.chat.type != 'private' or not message.from_user:
            return
        target = await self.store().find_target(message.from_user.id, chat_id)
        if not target:
            await message.answer('Этот диалог пока недоступен. Нужны разрешение секретарю и новое входящее '
                                 'сообщение от собеседника за последние 24 часа. Затем снова открой «Управлять ботом».')
            return
        await state.set_state(ComposeState.text)
        await state.update_data(target={'connection_id': target['connection_id'], 'chat_id': target['chat_id'], 'title': target['title']})
        await message.answer('Сообщение от твоего имени для <b>'+html.escape(target['title'])+'</b>.\n'
                             'Напиши текст, например <code>Привет {эмодзи}! | звезда</code>.\n'
                             'Выбор будет только здесь; собеседник увидит готовый текст. /cancel — отмена.', parse_mode='HTML')

    async def prepare(self, message, query, target=None):
        if message.chat.type != 'private' or not message.from_user:
            return
        store = self.store()
        if target:
            target = await store.target(message.from_user.id, target['connection_id'], target['chat_id'])
            if not target:
                await message.answer('Право отправки в этот диалог истекло. Начни заново с /say.')
                return
        targets = [target] if target else await store.targets(message.from_user.id)
        if not targets:
            await message.answer('Нет доступных диалогов. Подключи меня в «Автоматизация чатов», разреши ответы '
                                 'и попроси собеседника написать новое сообщение в разрешённый личный чат. Затем /say.')
            return
        try:
            draft = self.drafts.create(message.from_user.id, query, message.chat.id)
        except ValueError as exc:
            await message.answer(html.escape(str(exc)))
            return
        draft.secretary = True
        if target:
            self.bind(draft, target)
            await self.show_choices(message, draft)
            return
        draft.destinations = {str(row['chat_id']): dict(row) for row in targets}
        buttons = [[InlineKeyboardButton(text=row['title'][:60], callback_data=f"sec:{draft.token}:{row['chat_id']}")] for row in targets]
        buttons.append([InlineKeyboardButton(text='Отмена', callback_data=f'emod:{draft.token}:cancel:0')])
        picker = await message.answer('Выбери диалог. После выбора эмодзи сообщение будет отправлено от твоего имени.\n'
                                      'Показаны до 20 недавних разрешённых диалогов.',
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        draft.picker_id = picker.message_id

    @staticmethod
    def bind(draft, target):
        draft.business_connection_id = target['connection_id']
        draft.target_chat_id = target['chat_id']
        draft.target_title = target['title']
        draft.destinations.clear()

    async def select_target(self, callback):
        parts = (callback.data or '').split(':')
        draft = self.drafts.get(parts[1], callback.from_user.id) if len(parts) == 3 else None
        message = callback.message
        if (not draft or not draft.secretary or not message or not hasattr(message, 'edit_text')
                or message.chat.type != 'private' or message.chat.id != draft.chat_id or message.message_id != draft.picker_id):
            await callback.answer('Выбор устарел или принадлежит другому человеку.', show_alert=True)
            return
        async with draft.lock:
            if self.drafts.get(draft.token, callback.from_user.id) is not draft or draft.sent or parts[2] not in draft.destinations:
                await callback.answer('Начни заново с /say.', show_alert=True)
                return
            row = draft.destinations[parts[2]]
            target = await self.store().target(draft.owner_id, row['connection_id'], row['chat_id'])
            if not target:
                await callback.answer('Диалог больше недоступен.', show_alert=True)
                return
            await callback.answer()
            self.bind(draft, target)
            await self.show_choices(message, draft, edit=True)

    async def send_selected(self, message, draft, text, emoji_id, fallback):
        """Called only after a validated owner click, under the draft lock."""
        store = self.store()
        target = await store.target(draft.owner_id, draft.business_connection_id, draft.target_chat_id)
        if not target:
            self.finish(draft)
            await message.edit_text('Отправка отменена: диалог недоступен, подключение отключено или истекли 24 часа.',
                                    reply_markup=None)
            return
        try:
            connection = await message.bot.get_business_connection(draft.business_connection_id)
        except TelegramAPIError:
            await message.answer('Не удалось проверить подключение. Сообщение не отправлялось. Попробуй позже.')
            return
        if (connection.id != draft.business_connection_id or connection.user.id != draft.owner_id
                or not connection.is_enabled or not can_reply(connection)):
            self.finish(draft)
            await message.edit_text('Отправка отменена: подключение или разрешение секретарю изменилось.', reply_markup=None)
            return
        # Recheck durable revocations/window after awaiting Telegram's permission check.
        if not await store.target(draft.owner_id, draft.business_connection_id, draft.target_chat_id):
            self.finish(draft)
            await message.edit_text('Диалог больше недоступен. Начни заново с /say.', reply_markup=None)
            return
        if self.drafts.get(draft.token, draft.owner_id) is not draft:
            self.finish(draft)
            await message.edit_text('Выбор устарел. Начни заново с /say.', reply_markup=None)
            return
        self.finish(draft)  # No retry after send starts: an ambiguous network failure must not duplicate a message.
        try:
            result = await message.bot.send_message(chat_id=draft.target_chat_id,
                business_connection_id=draft.business_connection_id, text=compose(text, emoji_id, fallback),
                parse_mode='HTML', link_preview_options=LinkPreviewOptions(is_disabled=True))
        except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError):
            await message.edit_text('Связь с Telegram прервалась. Результат отправки неизвестен — проверь диалог '
                                    'перед повтором. Автоматического повтора не будет.', reply_markup=None)
            return
        except TelegramAPIError:
            await message.edit_text('Telegram отклонил отправку. Проверь разрешения, окно 24 часа и поддержку '
                                    'премиум-эмодзи в этом режиме. Автоматического повтора не будет.', reply_markup=None)
            return
        if not has_exact_emoji(result, emoji_id, max(1, text.count(PLACEHOLDER))):
            await message.edit_text('Telegram доставил сообщение, но не сохранил выбранный премиум-эмодзи '
                                    '(в диалоге может быть обычный символ). Этот тест не подтвердил поддержку эмодзи '
                                    'от твоего имени.', reply_markup=None)
            return
        await message.edit_text('Отправлено от твоего имени в «'+html.escape(draft.target_title)+'».\n'
                                'Можно вернуться к обычной переписке. Следующее сообщение с эмодзи — /say.',
                                parse_mode='HTML', reply_markup=None)

    @staticmethod
    def finish(draft):
        draft.sent = True
        draft.query = ''
        draft.allowed.clear()
        draft.destinations.clear()
