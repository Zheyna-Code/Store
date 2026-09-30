"""Telegram-магазин Nexus с PostgreSQL и закрытой web-админкой."""

import asyncio
import html
import logging
import os
import secrets
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiohttp import ClientSession, web
import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InlineQuery,
    InlineQueryResultsButton,
    LinkPreviewOptions,
)

from config import COVERS_DIR, settings
from admin_page import ADMIN_HTML
from storage import Database
from shop_emoji import DEFAULT_EMOJI, EMOJI_FALLBACKS, EMOJI_LABELS
from emoji_library import EmojiLibrary, validate_emoji_id
from rich_description import description_to_html
from exchange_rates import ExchangeRates
from inline_emoji import InlineCatalog, InlineThumbnails, PLACEHOLDER, compose, valid_thumbnail
from direct_emoji import DraftStore, DIRECT_PAGE_SIZE, plain_composed, has_exact_emoji
from secretary import Secretary
from secretary_store import SecretaryStore

exchange_rates = ExchangeRates()

emoji_library = EmojiLibrary(Path(__file__).resolve().parent / "catalog/emojis.json")

inline_catalog = InlineCatalog(emoji_library.items)
inline_thumbnails = InlineThumbnails()
direct_drafts = DraftStore()

router = Router()
database: Database | None = None
telegram_bot: Bot | None = None
admin_sessions: set[str] = set()


def get_database() -> Database:
    if not database:
        raise RuntimeError("PostgreSQL не подключён")
    return database


class WalletState(StatesGroup):
    waiting_for_amount = State()


EMOJI = dict(DEFAULT_EMOJI)


def button(text: str, callback_data: str, *, style: str = "primary") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


def premium_button(
    text: str,
    callback_data: str,
    emoji_id: str,
    *,
    style: str = "primary",
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        icon_custom_emoji_id=emoji_id,
        style=style,
    )


def premium_link_button(text: str, url: str, emoji_id: str, *, style: str = "primary") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url, icon_custom_emoji_id=emoji_id, style=style)


def premium_emoji(emoji_id: str, fallback: str) -> str:
    """HTML-разметка premium emoji для текста и подписей."""
    fallback = EMOJI_FALLBACKS.get(emoji_id, fallback)
    return f'<tg-emoji emoji-id="{emoji_id}">{html.escape(fallback)}</tg-emoji>'


def dollars(amount: str) -> str:
    return f"{premium_emoji(EMOJI['dollar'], '💵')} {Decimal(str(amount).replace(' ', '')):.2f}"


async def payment_summary(amount: str) -> str:
    """Show reference rubles only at checkout; the actual invoice is always USD."""
    quote = await exchange_rates.quote()
    usd_line = f"К оплате: <b>{dollars(amount)} USD</b>"
    if quote is None:
        return usd_line + "\n<i>Эквивалент в рублях временно недоступен. Счёт в USD.</i>"
    rubles = f"{quote.rubles(amount):,.2f}".replace(",", " ").replace(".", ",")
    date_label = ".".join(reversed(quote.effective_date.split("-")))
    note = " · обновление курса временно недоступно" if quote.stale else ""
    return (usd_line + f"\nВ рублях: ≈ <b>{rubles} ₽</b>\n"
            f"<i>Курс ЦБ на {date_label}{note}. Эквивалент справочный, счёт в USD.</i>")


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_button("Каталог", "catalog", EMOJI["catalog"], style="success"), premium_button("Кошелёк", "wallet", EMOJI["wallet"])],
        [premium_button("Бонус", "bonus", EMOJI["bonus"]), premium_button("Профиль", "profile", EMOJI["profile"])],
        [premium_button("Техподдержка", "support", EMOJI["support"])],
        [premium_button("Прочее", "other", EMOJI["other"])],
    ])


def back_keyboard(destination: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        premium_button("Назад", destination, EMOJI["back"], style="danger")
    ]])


def wallet_keyboard() -> InlineKeyboardMarkup:
    amounts = ["1", "3", "5", "10", "25"]
    rows = [
        [premium_button(amount, f"wallet_amount:{amount}", EMOJI["dollar"]) for amount in amounts[:3]],
        [premium_button(amount, f"wallet_amount:{amount}", EMOJI["dollar"]) for amount in amounts[3:]],
        [premium_button("Своя сумма", "wallet_custom", EMOJI["write"])],
        [premium_button("Назад", "menu", EMOJI["back"], style="danger")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def other_keyboard() -> InlineKeyboardMarkup:
    rows = []
    links = [
        ("Условия гарантии", settings.warranty_url),
        ("Пользовательское соглашение", settings.terms_url),
        ("Политика конфиденциальности", settings.privacy_url),
    ]
    for text, url in links:
        rows.append([premium_link_button(text, url, EMOJI["link"])] if url else [premium_button(text, "link_not_set", EMOJI["link"])])
    rows.append([premium_button("Назад", "menu", EMOJI["back"], style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_link_button("Написать", "https://t.me/DitzzmBack", EMOJI["link"])],
        [premium_button("Назад", "menu", EMOJI["back"], style="danger")],
    ])


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_link_button("Crypto Bot", "https://t.me/DitzzmBack", EMOJI["crypto"])],
        [premium_link_button("Оплата через администратора", "https://t.me/DitzzmBack", EMOJI["admin_payment"])],
        [premium_button("В меню", "menu", EMOJI["back"], style="danger")],
    ])


def shop_keyboard(categories: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [premium_button(
            category["name"],
            f"category:{category['id']}",
            category_icon(category)[0],
        )]
        for category in categories
    ]
    rows.append([premium_button("Назад", "menu", EMOJI["back"], style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        premium_button("Назад", "menu", EMOJI["back"], style="danger")
    ]])


SCREENS: dict[str, tuple[str, str, InlineKeyboardMarkup]] = {
    "menu": (
        "меню.png",
        "<b>ГЛАВНОЕ МЕНЮ</b> {plane}\n\n"
        "Привет, {wave} {first_name}\n\n"
        "Добро пожаловать в магазин <b>Nexus</b> <b>Store</b> {store}\n\n"
        "Здесь ты можешь быстро и удобно купить нужные товары, "
        "пополнить баланс и посмотреть свои покупки. {dollar}",
        menu_keyboard(),
    ),
    "wallet": (
        "кошелек.png",
        "<b>Кошелёк</b> {crypto}\n"
        "Пополните баланс на нужную сумму {dollar}",
        wallet_keyboard(),
    ),
    "bonus": (
        "бонус.jpg",
        "<b>Бонус</b> {gift}\n\n"
        "Пригласи своего друга и получи награду за его первую покупку "
        "в размере <b>5%</b> на свой баланс {friends}",
        back_keyboard(),
    ),
    "support": (
        "тех подержка.jpg",
        "<b>Техподдержка</b> {plane}\n"
        "Возникли вопросы или проблемы {candy} Напишите в поддержку {chat}",
        support_keyboard(),
    ),
    "other": ("прочее.jpg", "<b>Прочее</b> {star}\nДокументы и важная информация {new}", other_keyboard()),
}

CATEGORIES: dict[str, tuple[str | None, str]] = {
    "chatgpt": ("chatgpt.png", "ChatGPT"),
    "claude": ("claude-cover.png", "Claude"),
    "gemini": ("gemini-cover.png", "Gemini"),
    "notion": ("notion-cover.png", "Notion"),
    "grok": ("grok-cover.png", "Grok"),
    "perplexity": ("perplexity-cover.png", "Perplexity"),
    "netflix": ("нетфликс.png", "Netflix"),
    "duolingo": ("duolingo.png", "Duolingo"),
    "capcut": ("capcut-cover.png", "CapCut"),
    "spotify": ("спотифай.png", "Spotify"),
}

CATEGORY_EMOJI: dict[str, tuple[str, str]] = {
    "chatgpt": (EMOJI["chatgpt"], "😄"),
    "claude": (EMOJI["claude"], "😄"),
    "gemini": (EMOJI["gemini"], "🤖"),
    "notion": (EMOJI["notion"], "📱"),
    "grok": (EMOJI["grok"], "😁"),
    "perplexity": (EMOJI["perplexity"], "🤖"),
    "netflix": (EMOJI["netflix"], "🌚"),
    "duolingo": (EMOJI["duolingo"], "🔫"),
    "capcut": (EMOJI["capcut"], "⚡️"),
    "spotify": (EMOJI["spotify"], "🍏"),
}


def category_icon(category: dict) -> tuple[str, str]:
    if category.get("custom_emoji_id"):
        return category["custom_emoji_id"], category.get("emoji_fallback") or "🛍"
    return CATEGORY_EMOJI.get((category.get("name") or "").strip().lower(), (EMOJI["catalog"], "🛍"))


def apply_emoji_settings(values: dict) -> None:
    EMOJI.clear()
    EMOJI.update(DEFAULT_EMOJI)
    EMOJI.update({k: v for k, v in values.items() if k in DEFAULT_EMOJI})
    # SCREENS are initially constructed on import; rebuild keyboards after a settings change.
    for key, builder in {"menu": menu_keyboard, "wallet": wallet_keyboard,
                         "bonus": back_keyboard, "support": support_keyboard, "other": other_keyboard}.items():
        filename, caption, _ = SCREENS[key]
        SCREENS[key] = (filename, caption, builder())


def product_card(product: dict, available: int) -> str:
    emoji_id, fallback = category_icon({"name": product.get("category_name"),
        "custom_emoji_id": product.get("category_emoji_id"), "emoji_fallback": product.get("category_emoji_fallback")})
    return (
        f"{premium_emoji(emoji_id, fallback)} <b>{html.escape(product['name'])}</b>\n\n"
        f"{premium_emoji(EMOJI['description'], '⭐️')} {description_to_html(product['description'])}\n\n"
        f"{dollars(product['price'])}\n"
        f"{premium_emoji(EMOJI['stock'], '⚙')} В наличии: <b>{available}</b>"
    )


async def replace_with_screen(message: Message, screen: str, first_name: str = "друг") -> None:
    """Удаляет прошлый экран и присылает новый с нужной обложкой."""
    filename, caption, keyboard = SCREENS[screen]
    await message.delete()
    await message.answer_photo(
        FSInputFile(COVERS_DIR / filename),
        caption=caption.format(
            first_name=html.escape(first_name),
            wave=premium_emoji(EMOJI["wave"], "👋"),
            plane=premium_emoji(EMOJI["plane"], "✈️"),
            crypto=premium_emoji(EMOJI["crypto"], "👛"),
            dollar=premium_emoji(EMOJI["dollar"], "💵"),
            store=premium_emoji(EMOJI["catalog"], "🏪"),
            gift=premium_emoji(EMOJI["bonus"], "🎁"),
            friends=premium_emoji(EMOJI["friends"], "👥"),
            candy=premium_emoji(EMOJI["candy"], "🍭"),
            chat=premium_emoji(EMOJI["support"], "💬"),
            star=premium_emoji(EMOJI["other"], "⭐️"),
            new=premium_emoji(EMOJI["new"], "🆕"),
        ),
        reply_markup=keyboard,
    )


async def show_category(message: Message, category_id: int) -> None:
    categories = await get_database().active_categories()
    category = next((item for item in categories if item["id"] == category_id), None)
    if category is None:
        await message.answer("Категория сейчас недоступна.", reply_markup=back_keyboard("catalog"))
        return
    title = category["name"]
    filename = CATEGORIES.get(title.lower(), (None, title))[0]
    products = await get_database().category_products(category_id)
    await message.delete()
    emoji_id, fallback = category_icon(category)
    caption = (
        f"{premium_emoji(emoji_id, fallback)} <b>{html.escape(title)}</b>\n\n"
        + ("Выберите товар из списка ниже." if products else "В этой категории пока нет товаров.")
    )
    rows = [[premium_button(
        f"{p['name']} · ${Decimal(p['price']):.2f}" + (" · нет в наличии" if not p["stock_count"] else ""),
        f"product:{p['id']}",
        emoji_id,
    )] for p in products]
    rows.append([premium_button("Назад к категориям", "catalog", EMOJI["back"], style="danger")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    if filename and (COVERS_DIR / filename).exists():
        await message.answer_photo(
            FSInputFile(COVERS_DIR / filename),
            caption=caption,
            reply_markup=keyboard,
        )
    else:
        await message.answer(caption, reply_markup=keyboard)


@router.message(Command("emoji"))
async def command_direct_emoji(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not message.from_user:
        await direct_emoji_help(message)
        return
    try:
        draft = direct_drafts.create(message.from_user.id, parts[1], message.chat.id)
        await show_direct_choices(message, draft)
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))


secretary = Secretary(
    lambda: SecretaryStore(get_database()._pool()), direct_drafts,
    lambda *args, **kwargs: show_direct_choices(*args, **kwargs),
)


async def direct_emoji_help(message: Message) -> None:
    await message.answer(
        "<b>Сообщение с премиум-эмодзи от бота</b>\n\n"
        "Отправь: <code>/emoji Привет! | звезда</code>\n"
        "Или: <code>/emoji Привет! | ⭐ TgAndroidIcons</code>\n"
        "Чтобы вставить значок внутри текста: "
        "<code>/emoji Привет {эмодзи} друг! | звезда</code>.\n\n"
        "Выбери нужный номер / эмодзи на кнопке. Бот заменит своё сообщение выбора "
        "на готовый текст — без via и без мини-приложения.\n"
        "Один выбранный вид эмодзи; все {эмодзи} заменяются им.\n\n"
        "В личном чате результат можно переслать. В группе бот должен быть добавлен "
        "и иметь право писать; используй /emoji@имя_бота. "
        "Выбор действует 15 минут и доступен только автору запроса.\n\n"
        "Для отправки от твоего аккаунта через режим секретаря — /say. "
        "Либо открой «Управлять ботом» в подключённом диалоге."
    )


@router.message(Command("inline"))
async def inline_help(message: Message, error: bool = False) -> None:
    await direct_emoji_help(message)


async def inline_notice(query: InlineQuery, label: str, parameter: str = "emoji_help") -> None:
    try:
        await query.answer([], cache_time=0, is_personal=True,
                           button=InlineQueryResultsButton(text=label, start_parameter=parameter))
    except TelegramAPIError:
        logging.debug("Old inline query could not be answered")


@router.inline_query()
async def inline_compose(query: InlineQuery) -> None:
    # Inline cannot send a bot-owned message into an unknown target chat.
    # Preserve the user's draft and hand it to the bot's private chat instead.
    if not query.query.strip():
        await inline_notice(query, "Написать сообщение от бота")
        return
    try:
        _, rows, _ = inline_catalog.page(query.query, page_size=DIRECT_PAGE_SIZE)
        if not rows:
            await inline_notice(query, "Ничего не найдено · помощь")
            return
        draft = direct_drafts.create(query.from_user.id, query.query)
    except ValueError:
        await inline_notice(query, "Сократите текст · помощь")
        return
    await inline_notice(query, "Отправить от имени бота", "e_" + draft.token)


async def show_direct_choices(message: Message, draft, offset=0, edit=False) -> None:
    text, rows, next_offset = inline_catalog.page(draft.query, str(offset), page_size=DIRECT_PAGE_SIZE)
    if not rows:
        await message.answer("Эмодзи не найдены. Попробуйте другой символ или название набора.")
        return
    try:
        metadata = await asyncio.wait_for(emoji_library.previews(message.bot, [row["id"] for row in rows]), timeout=4)
    except (TelegramAPIError, asyncio.TimeoutError):
        await message.answer("Не удалось получить эмодзи. Повторите /emoji чуть позже.")
        return
    available = [{**row, "emoji": metadata[row["id"]]["emoji"]} for row in rows
                 if metadata[row["id"]]["available"] and metadata[row["id"]]["emoji"] and len(metadata[row["id"]]["emoji"]) <= 32]
    if not available:
        await message.answer("Эмодзи этой страницы недоступны. Попробуйте другой поиск.")
        return
    heading = ("<b>Выбери эмодзи — отправлю от твоего имени</b>\nДиалог: " + html.escape(draft.target_title)
               if draft.secretary else "<b>Выберите эмодзи — сообщение отправит бот</b>")
    lines = [heading,
             "Текст: " + html.escape(text[:160] or "Только эмодзи"), ""]
    buttons = []
    for index, item in enumerate(available, 1):
        lines.append(f'{index}. <tg-emoji emoji-id="{item["id"]}">{html.escape(item["emoji"])}</tg-emoji> '
                     f'{html.escape(item["pack"])} · №{inline_catalog.positions[item["id"]]}')
        buttons.append(InlineKeyboardButton(text=str(index), icon_custom_emoji_id=item["id"],
                       callback_data=f'emod:{draft.token}:pick:{item["id"]}'))
    keyboard = [buttons[index:index+4] for index in range(0, len(buttons), 4)]
    nav = []
    if offset:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f'emod:{draft.token}:page:{max(0,offset-DIRECT_PAGE_SIZE)}'))
    if next_offset:
        nav.append(InlineKeyboardButton(text="Далее →", callback_data=f'emod:{draft.token}:page:{next_offset}'))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="Отмена", callback_data=f'emod:{draft.token}:cancel:0')])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    try:
        if edit:
            picker = await message.edit_text("\n".join(lines), reply_markup=markup, parse_mode="HTML")
        else:
            picker = await message.answer("\n".join(lines), reply_markup=markup, parse_mode="HTML")
    except TelegramAPIError:
        await message.answer("Telegram не разрешил показать премиум-эмодзи. Проверьте Premium у владельца бота.")
        return
    expected_ids = {item["id"] for item in available}
    actual_ids = {getattr(entity, "custom_emoji_id", None) for entity in (getattr(picker, "entities", None) or [])}
    if not expected_ids.issubset(actual_ids):
        draft.sent = True
        draft.query = ""
        draft.allowed.clear()
        await picker.edit_text("Telegram не сохранил премиум-эмодзи даже в прямом сообщении бота. "
                               "Проверьте Premium у владельца бота в BotFather.", reply_markup=None)
        return
    draft.chat_id = picker.chat.id
    draft.picker_id = picker.message_id
    draft.offset = offset
    draft.allowed = {item["id"]: item["emoji"] for item in available}


@router.callback_query(F.data.startswith("emod:"))
async def direct_emoji_callback(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректный выбор.", show_alert=True)
        return
    _, token, action, value = parts
    draft = direct_drafts.get(token, callback.from_user.id)
    message = callback.message
    if not draft or not message or not hasattr(message, "edit_text"):
        await callback.answer("Выбор устарел или принадлежит другому человеку. Начните с /emoji.", show_alert=True)
        return
    if message.chat.id != draft.chat_id or message.message_id != draft.picker_id:
        await callback.answer("Этот выбор относится к другому сообщению.", show_alert=True)
        return
    async with draft.lock:
        if direct_drafts.get(token, callback.from_user.id) is not draft:
            await callback.answer("Выбор устарел. Начните с /emoji.", show_alert=True)
            return
        if draft.sent:
            await callback.answer("Сообщение уже отправлено.")
            return
        if action == "cancel":
            await callback.answer()
            await message.edit_text("Выбор отменён.", reply_markup=None)
            draft.sent = True
            draft.query = ""
            draft.allowed.clear()
            draft.destinations.clear()
            return
        if action == "page" and value.isascii() and value.isdecimal() and len(value) <= 4:
            offset = int(value)
            if offset not in {max(0, draft.offset-DIRECT_PAGE_SIZE), draft.offset+DIRECT_PAGE_SIZE}:
                await callback.answer("Страница устарела.", show_alert=True)
                return
            await callback.answer()
            await show_direct_choices(message, draft, offset=offset, edit=True)
            return
        if action != "pick" or value not in draft.allowed:
            await callback.answer("Выберите эмодзи с текущей страницы.", show_alert=True)
            return
        text, _, _ = inline_catalog.page(draft.query, page_size=DIRECT_PAGE_SIZE)
        fallback = draft.allowed[value]
        if len(plain_composed(text, fallback).encode("utf-16-le")) // 2 > 4096:
            await callback.answer("Сообщение слишком длинное. Сократите текст.", show_alert=True)
            return
        await callback.answer()
        if draft.secretary:
            await secretary.send_selected(message, draft, text, value, fallback)
            return
        try:
            result = await message.edit_text(compose(text, value, fallback), parse_mode="HTML", reply_markup=None,
                                             link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramAPIError:
            await message.answer("Не удалось отправить премиум-эмодзи. Проверьте права бота и повторите /emoji.")
            return
        expected = max(1, text.count(PLACEHOLDER))
        draft.sent = True
        draft.query = ""
        draft.allowed.clear()
        if not has_exact_emoji(result, value, expected):
            await result.edit_text("Telegram заменил выбранный премиум-эмодзи обычным символом. "
                                   "Проверьте Premium у владельца бота в BotFather.", reply_markup=None)


async def inline_emoji_thumbnail(request: web.Request) -> web.Response:
    emoji_id = request.match_info["id"]
    if not valid_thumbnail(settings.admin_secret, inline_catalog.ids, emoji_id,
                           request.query.get("expires", ""), request.query.get("sig", "")):
        raise web.HTTPNotFound()
    if not telegram_bot:
        raise web.HTTPServiceUnavailable()
    try:
        data = await asyncio.wait_for(inline_thumbnails.get(telegram_bot, emoji_library, emoji_id), timeout=15)
    except (ValueError, TelegramAPIError, asyncio.TimeoutError):
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="image/jpeg", headers={
        "Cache-Control": "public, max-age=900", "X-Content-Type-Options": "nosniff"})


@router.message(Command("start", "menu"))
async def command_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    parameter = parts[1] if len(parts) == 2 and parts[0].split("@")[0] == "/start" else ""
    if parameter.startswith("bizChat"):
        chat = parameter[7:]
        if chat.isascii() and chat.isdecimal() and len(chat) <= 20:
            await secretary.open_chat(message, state, int(chat))
        else:
            await message.answer("Некорректный диалог. Начни с /say.")
        return
    if parameter in {"inline_help", "inline_error", "emoji_help"}:
        await direct_emoji_help(message)
        return
    if parameter.startswith("e_"):
        draft = direct_drafts.get(parameter[2:], message.from_user.id)
        if not draft or draft.sent or draft.chat_id is not None or message.chat.type != "private":
            await message.answer("Выбор устарел. Отправьте /emoji текст | эмодзи.")
            return
        async with draft.lock:
            if direct_drafts.get(parameter[2:], message.from_user.id) is draft and not draft.sent and draft.picker_id is None:
                await show_direct_choices(message, draft)
        return
    await get_database().upsert_customer(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    # Считаем уникальные визиты в магазин по Telegram ID, без учёта health-check.
    await get_database().visit("telegram-menu", str(message.from_user.id))
    filename, caption, keyboard = SCREENS["menu"]
    await message.answer_photo(
        FSInputFile(COVERS_DIR / filename),
        caption=caption.format(
            first_name=html.escape(message.from_user.first_name),
            wave=premium_emoji(EMOJI["wave"], "👋"),
            plane=premium_emoji(EMOJI["plane"], "✈️"),
            crypto=premium_emoji(EMOJI["crypto"], "👛"),
            dollar=premium_emoji(EMOJI["dollar"], "💵"),
            store=premium_emoji(EMOJI["catalog"], "🏪"),
            gift=premium_emoji(EMOJI["bonus"], "🎁"),
            friends=premium_emoji(EMOJI["friends"], "👥"),
            candy=premium_emoji(EMOJI["candy"], "🍭"),
            chat=premium_emoji(EMOJI["support"], "💬"),
            star=premium_emoji(EMOJI["other"], "⭐️"),
            new=premium_emoji(EMOJI["new"], "🆕"),
        ),
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "profile")
async def open_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.delete()
    user = callback.from_user
    await get_database().upsert_customer(user.id, user.username, user.first_name)
    customer = await get_database().customer(user.id)
    username = f"@{html.escape(user.username)}" if user.username else "@не указан"
    caption = (
        f"<b>Профиль</b> {premium_emoji(EMOJI['profile'], '👤')}\n\n"
        f"{username} | <code>{user.id}</code>\n\n"
        f"Баланс: <b>{dollars(str(customer['balance']) if customer else '0.00')}</b>\n"
        f"Рефералов: <b>0</b> {premium_emoji(EMOJI['friends'], '👥')}\n"
        f"Покупок: <b>0</b> {premium_emoji(EMOJI['card'], '💳')}"
    )
    await callback.message.answer_photo(
        FSInputFile(COVERS_DIR / "профиль.jpg"),
        caption=caption,
        reply_markup=profile_keyboard(),
    )


@router.callback_query(F.data == "catalog")
async def open_catalog(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.delete()
    categories = await get_database().active_categories()
    caption = (
        f"<b>Каталог</b> {premium_emoji(EMOJI['catalog'], '🏪')}\n\n"
        + ("Выберите категорию, затем товар." if categories else "Сейчас нет доступных категорий.")
    )
    await callback.message.answer_photo(
        FSInputFile(COVERS_DIR / "каталог.jpg"),
        caption=caption,
        reply_markup=shop_keyboard(categories),
    )


@router.callback_query(F.data.startswith("product:"))
async def open_product(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":", 1)[1])
    product = await get_database().product(product_id)
    if not product or not product["is_active"]:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    stock = await get_database().stock(product_id)
    available = sum(not item["is_issued"] for item in stock)
    await callback.answer()
    await callback.message.answer(
        product_card(product, available),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            *([[premium_button("Купить через Crypto Pay", f"buy:{product_id}", EMOJI["crypto"], style="success")]] if available else []),
            [premium_button(
                "Назад к категории" if product["category_id"] else "Назад в каталог",
                f"category:{product['category_id']}" if product["category_id"] else "catalog",
                EMOJI["back"],
                style="danger",
            )],
        ]),
    )


async def create_crypto_invoice(order: dict) -> dict:
    """Creates a fiat USD Crypto Pay invoice; the API token never reaches a client."""
    request_data = {
        "currency_type": "fiat",
        "fiat": "USD",
        "accepted_assets": "USDT,TON",
        "amount": order["price"],
        "description": order["name"][:1024],
        "payload": str(order["id"]),
        "expires_in": 3600,
    }
    async with ClientSession() as session:
        async with session.post(
            "https://pay.crypt.bot/api/createInvoice",
            json=request_data,
            headers={"Crypto-Pay-API-Token": settings.crypto_pay_token},
            timeout=20,
        ) as response:
            response_data = await response.json(content_type=None)
    if not response.ok or not response_data.get("ok"):
        raise RuntimeError(response_data.get("error", {}).get("name", "Crypto Pay не создал счёт"))
    return response_data["result"]


@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery) -> None:
    if not settings.crypto_pay_token:
        await callback.answer("Оплата временно не настроена", show_alert=True)
        return
    try:
        product_id = int(callback.data.split(":", maxsplit=1)[1])
        user = callback.from_user
        await get_database().upsert_customer(user.id, user.username, user.first_name)
        order = await get_database().create_crypto_order(user.id, product_id)
        invoice = await create_crypto_invoice(order)
        await get_database().set_crypto_invoice(order["id"], int(invoice["invoice_id"]))
    except (ValueError, RuntimeError, KeyError) as exc:
        if "order" in locals():
            await get_database().cancel_order(order["id"])
        logging.exception("Unable to create Crypto Pay invoice")
        await callback.answer(f"Не удалось создать счёт: {exc}", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        f"<b>{html.escape(order['name'])}</b>\n{await payment_summary(order['price'])}\n\n"
        "После подтверждения оплаты товар будет выдан автоматически.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            premium_link_button("Оплатить через Crypto Pay", invoice["pay_url"], EMOJI["crypto"])
        ]]),
    )


@router.callback_query(F.data.in_(SCREENS.keys()))
async def open_screen(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await replace_with_screen(callback.message, callback.data, callback.from_user.first_name)


@router.callback_query(F.data.startswith("category:"))
async def open_category(callback: CallbackQuery) -> None:
    category = callback.data.split(":", maxsplit=1)[1]
    await callback.answer()
    if category.isdigit():
        await show_category(callback.message, int(category))


@router.callback_query(F.data.startswith("wallet_amount:"))
async def choose_wallet_amount(callback: CallbackQuery) -> None:
    amount = callback.data.split(":", maxsplit=1)[1]
    await callback.answer("Сумма выбрана")
    await show_payment_options(callback.message, amount)


async def show_payment_options(message: Message, amount: str) -> None:
    await message.delete()
    await message.answer(
        f"<b>Пополнение</b>\n{await payment_summary(amount)}\n\n"
        f"Выберите способ оплаты {premium_emoji(EMOJI['card'], '💳')}",
        reply_markup=payment_keyboard(),
    )


@router.callback_query(F.data == "wallet_custom")
async def request_custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletState.waiting_for_amount)
    await callback.answer()
    await callback.message.answer("Введите сумму в долларах, например: <b>7.50</b>")


@router.message(WalletState.waiting_for_amount, F.text)
async def receive_custom_amount(message: Message, state: FSMContext) -> None:
    raw_amount = message.text.strip().replace(",", ".").replace("$", "")
    try:
        amount = float(raw_amount)
        if not 0 < amount <= 10_000:
            raise ValueError
    except ValueError:
        await message.answer(f"Введите сумму числом от {dollars('0.01')} до {dollars('10 000')}.")
        return
    await state.clear()
    await show_payment_options(message, f"{amount:.2f}")


@router.callback_query(F.data == "link_not_set")
async def link_not_set(callback: CallbackQuery) -> None:
    await callback.answer("Ссылка будет добавлена владельцем магазина.", show_alert=True)


async def main() -> None:
    if not settings.token or settings.token == "123456789:replace_me":
        raise RuntimeError("Укажите настоящий BOT_TOKEN в файле .env")
    if not settings.database_url:
        raise RuntimeError("Укажите DATABASE_URL PostgreSQL в .env")
    if not settings.admin_secret or settings.admin_secret.startswith("change-this"):
        raise RuntimeError("Укажите надёжный ADMIN_SECRET в .env")
    global database, telegram_bot
    database = Database(settings.database_url)
    await database.connect()
    apply_emoji_settings(await database.emoji_settings())
    bot = Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    telegram_bot = bot
    dispatcher = Dispatcher()
    dispatcher.include_router(secretary.router)
    dispatcher.include_router(router)
    health_runner = await start_health_server()
    try:
        await dispatcher.start_polling(bot)
    finally:
        await health_runner.cleanup()
        await database.close()


async def health(_: web.Request) -> web.Response:
    """Проверка состояния для Hostless и будущего Web App."""
    return web.json_response({"status": "ok", "service": "lavka-strannika-bot"})


def require_admin(request: web.Request) -> None:
    token = request.headers.get("X-Admin-Token", "")
    if not token or token not in admin_sessions:
        raise web.HTTPUnauthorized(text='{"error":"Требуется авторизация"}', content_type="application/json")


async def json_body(request: web.Request) -> dict:
    try:
        return await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text='{"error":"Некорректный JSON"}', content_type="application/json") from exc


async def admin_login(request: web.Request) -> web.Response:
    data = await json_body(request)
    if not secrets.compare_digest(str(data.get("secret", "")), settings.admin_secret):
        return web.json_response({"error": "Неверный секретный ключ"}, status=401)
    token = secrets.token_urlsafe(32)
    admin_sessions.add(token)
    return web.json_response({"token": token})


async def admin_page(_: web.Request) -> web.Response:
    return web.Response(text=ADMIN_HTML, content_type="text/html", headers={"Cache-Control": "no-store"})


async def admin_script(_: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).resolve().parent / "admin.js", headers={"Cache-Control": "no-store"})


async def admin_dashboard(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(await get_database().dashboard())


async def admin_analytics(request: web.Request) -> web.Response:
    require_admin(request)
    try:
        days = int(request.query.get("days", "30"))
        tz_offset = int(request.query.get("tz", "0"))
    except ValueError:
        return web.json_response({"error": "Некорректный период"}, status=400)
    return web.json_response(await get_database().analytics(days, tz_offset))


async def admin_categories(request: web.Request) -> web.Response:
    require_admin(request)
    if request.method == "GET":
        return web.json_response(await get_database().list_categories())
    try:
        return web.json_response(await get_database().save_category(await json_body(request)), status=201)
    except (ValueError, asyncpg.UniqueViolationError) as exc:
        return web.json_response({"error": str(exc) or "Такая категория уже существует"}, status=400)


async def admin_category(request: web.Request) -> web.Response:
    require_admin(request)
    try:
        return web.json_response(await get_database().save_category(await json_body(request), int(request.match_info["id"])))
    except (ValueError, asyncpg.UniqueViolationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def admin_products(request: web.Request) -> web.Response:
    require_admin(request)
    if request.method == "GET":
        return web.json_response(await get_database().list_products())
    try:
        return web.json_response(await get_database().save_product(await json_body(request)), status=201)
    except (ValueError, InvalidOperation, asyncpg.PostgresError) as exc:
        return web.json_response({"error": f"Не удалось сохранить товар: {exc}"}, status=400)


async def admin_product(request: web.Request) -> web.Response:
    require_admin(request)
    product_id = int(request.match_info["id"])
    try:
        if request.method == "DELETE":
            await get_database().delete_product(product_id)
            return web.json_response({"ok": True})
        return web.json_response(await get_database().save_product(await json_body(request), product_id))
    except (ValueError, InvalidOperation, asyncpg.PostgresError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def admin_stock(request: web.Request) -> web.Response:
    require_admin(request)
    product_id = int(request.match_info["id"])
    if request.method == "GET":
        return web.json_response(await get_database().stock(product_id))
    data = await json_body(request)
    if not isinstance(data.get("items"), list) or not all(isinstance(item, str) for item in data["items"]):
        return web.json_response({"error": "items должен быть списком строк"}, status=400)
    try:
        await get_database().replace_stock(product_id, data["items"])
        return web.json_response({"ok": True})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=404)


async def admin_emoji_settings(request: web.Request) -> web.Response:
    require_admin(request)
    if request.method == "PUT":
        data = await json_body(request)
        if not isinstance(data, dict) or set(data) - set(EMOJI_LABELS):
            return web.json_response({"error": "Неизвестная настройка эмодзи"}, status=400)
        try:
            values = {key: validate_emoji_id(value) for key, value in data.items()}
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        for emoji_id in values.values():
            sticker = emoji_library.metadata.get(emoji_id)
            if sticker and sticker.emoji:
                EMOJI_FALLBACKS[emoji_id] = sticker.emoji
        saved = await get_database().save_emoji_settings(values)
        apply_emoji_settings(saved)
    return web.json_response({"values": {k: EMOJI[k] for k in EMOJI_LABELS}, "labels": EMOJI_LABELS, "defaults": {k: DEFAULT_EMOJI[k] for k in EMOJI_LABELS},
        "categories": {k: {"id": v[0], "emoji": v[1]} for k, v in CATEGORY_EMOJI.items()}})


async def admin_emoji_catalog(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(emoji_library.items)


async def admin_emoji_previews(request: web.Request) -> web.Response:
    require_admin(request)
    data = await json_body(request)
    ids = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(ids, list) or len(ids) > 60:
        return web.json_response({"error": "Нужно не больше 60 ID"}, status=400)
    try:
        ids = list(dict.fromkeys(validate_emoji_id(value) for value in ids))
        if not telegram_bot:
            raise RuntimeError("Бот ещё не подключён")
        return web.json_response(await emoji_library.previews(telegram_bot, ids))
    except (ValueError, RuntimeError):
        return web.json_response({"error": "Не удалось загрузить предпросмотр. Проверьте ID и подключение бота."}, status=400)
    except Exception:
        # Telegram file URLs contain BOT_TOKEN: never log or expose raw exception text.
        return web.json_response({"error": "Telegram временно не отдаёт предпросмотр. Повторите позже."}, status=502)


async def admin_emoji_image(request: web.Request) -> web.Response:
    require_admin(request)
    try:
        emoji_id = validate_emoji_id(request.match_info["id"])
        if not telegram_bot:
            raise RuntimeError
        content, mime = await emoji_library.image(telegram_bot, emoji_id)
        return web.Response(body=content, content_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Emoji-Repainting": str(bool(emoji_library.metadata.get(emoji_id) and emoji_library.metadata[emoji_id].needs_repainting)).lower()})
    except Exception:
        return web.json_response({"error": "Предпросмотр недоступен"}, status=404)


async def admin_customers(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(await get_database().customers(request.query.get("q", "")))


async def admin_grant_balance(request: web.Request) -> web.Response:
    require_admin(request)
    data = await json_body(request)
    try:
        amount = Decimal(str(data.get("amount", "")))
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        result = await get_database().grant_balance(request.match_info["username"], amount, str(data.get("reason", "")))
        return web.json_response(result)
    except (InvalidOperation, ValueError) as exc:
        return web.json_response({"error": str(exc) or "Некорректная сумма"}, status=400)


async def admin_grant_balance_by_id(request: web.Request) -> web.Response:
    require_admin(request)
    data = await json_body(request)
    try:
        amount = Decimal(str(data.get("amount", "")))
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        result = await get_database().grant_balance_by_id(int(request.match_info["telegram_id"]), amount, str(data.get("reason", "")))
        return web.json_response(result)
    except (InvalidOperation, ValueError) as exc:
        return web.json_response({"error": str(exc) or "Некорректная сумма"}, status=400)


async def admin_orders(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(await get_database().orders())


async def crypto_webhook(request: web.Request) -> web.Response:
    """Receives signed `invoice_paid` updates from Crypto Pay and delivers once."""
    if not settings.crypto_pay_webhook_secret or not secrets.compare_digest(
        request.match_info["secret"], settings.crypto_pay_webhook_secret
    ):
        raise web.HTTPNotFound()
    raw_body = await request.read()
    signature = request.headers.get("crypto-pay-api-signature", "")
    signature_key = hashlib.sha256(settings.crypto_pay_token.encode()).digest()
    expected_signature = hmac.new(signature_key, raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected_signature):
        logging.warning("Rejected Crypto Pay webhook with an invalid signature")
        raise web.HTTPUnauthorized()
    try:
        update = json.loads(raw_body)
        invoice = update.get("payload", {})
        if update.get("update_type") != "invoice_paid" or invoice.get("status") != "paid":
            return web.json_response({"ok": True})
        delivery = await get_database().finalize_crypto_order(int(invoice["invoice_id"]))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logging.warning("Invalid Crypto Pay webhook payload: %s", exc)
        raise web.HTTPBadRequest() from exc
    if not delivery:
        return web.json_response({"ok": True})
    if not telegram_bot:
        raise web.HTTPServiceUnavailable()
    if delivery["out_of_stock"]:
        await telegram_bot.send_message(
            delivery["customer_id"],
            "Оплата получена, но товар закончился. Напишите в поддержку для возврата.",
        )
    else:
        await telegram_bot.send_message(
            delivery["customer_id"],
            f"<b>Оплата получена ✅</b>\n\n<b>{html.escape(delivery['product_name'])}</b>\n\n"
            f"<code>{html.escape(delivery['payload'])}</code>",
        )
    return web.json_response({"ok": True})


async def start_health_server() -> web.AppRunner:
    """Поднимает HTTP-сервер магазина и закрытой админ-панели."""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/admin.js", admin_script)
    app.router.add_post("/api/admin/login", admin_login)
    app.router.add_get("/api/admin/dashboard", admin_dashboard)
    app.router.add_get("/api/admin/analytics", admin_analytics)
    app.router.add_get("/api/admin/categories", admin_categories)
    app.router.add_post("/api/admin/categories", admin_categories)
    app.router.add_put("/api/admin/categories/{id}", admin_category)
    app.router.add_get("/api/admin/products", admin_products)
    app.router.add_post("/api/admin/products", admin_products)
    app.router.add_put("/api/admin/products/{id}", admin_product)
    app.router.add_delete("/api/admin/products/{id}", admin_product)
    app.router.add_get("/api/admin/products/{id}/stock", admin_stock)
    app.router.add_put("/api/admin/products/{id}/stock", admin_stock)
    app.router.add_get("/api/admin/customers", admin_customers)
    app.router.add_post("/api/admin/customers/{username}/balance", admin_grant_balance)
    app.router.add_post("/api/admin/customers/id/{telegram_id}/balance", admin_grant_balance_by_id)
    app.router.add_get("/api/admin/orders", admin_orders)
    app.router.add_get("/api/admin/emojis/settings", admin_emoji_settings)
    app.router.add_put("/api/admin/emojis/settings", admin_emoji_settings)
    app.router.add_get("/api/admin/emojis/catalog", admin_emoji_catalog)
    app.router.add_post("/api/admin/emojis/previews", admin_emoji_previews)
    app.router.add_get("/api/admin/emojis/image/{id}", admin_emoji_image)
    app.router.add_get("/api/inline/emoji/{id}.jpg", inline_emoji_thumbnail)
    app.router.add_post("/api/payments/crypto/{secret}", crypto_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("Health server started on port %s", port)
    return runner


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
