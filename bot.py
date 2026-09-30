"""Telegram-магазин Nexus с PostgreSQL и закрытой web-админкой."""

import asyncio
import html
import logging
import os
import secrets
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from contextlib import suppress

from aiohttp import ClientSession, web
import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CopyTextButton,
    WebAppInfo,
    MenuButtonWebApp,
    Message,
)

from config import COVERS_DIR, settings
from admin_page import ADMIN_HTML
from storage import Database
from shop_emoji import DEFAULT_EMOJI, EMOJI_FALLBACKS, EMOJI_LABELS
from emoji_library import EmojiLibrary, validate_emoji_id
from rich_description import description_to_html
from exchange_rates import ExchangeRates
from crypto_pay import CryptoPay, PaymentError, money, quantity, valid_signature
from payments import Payments
from quantity_emoji import QuantityEmoji
from referrals import referral_link, start_referrer
from storefront import ShopSite

exchange_rates = ExchangeRates()
quantity_emoji = QuantityEmoji()

emoji_library = EmojiLibrary(Path(__file__).resolve().parent / "catalog/emojis.json")

router = Router()
database: Database | None = None
telegram_bot: Bot | None = None
payments: Payments | None = None
shop_site: ShopSite | None = None
admin_sessions: set[str] = set()


def get_database() -> Database:
    if not database:
        raise RuntimeError("PostgreSQL не подключён")
    return database


def get_payments() -> Payments:
    if payments is None:
        raise RuntimeError("Платежи ещё не подключены")
    return payments


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
    return usd_line + f"\nВ рублях: ≈ <b>{rubles} ₽</b>"


async def admin_payment_url(amount, context: str) -> str:
    quote = await exchange_rates.quote()
    rub = f" / ≈ {quote.rubles(str(amount)):.2f} ₽" if quote else ""
    text = f"Здравствуйте! {context}. Сумма: {amount:.2f} USD{rub}. Подскажите, как оплатить."
    return "https://t.me/Ditzzmback?" + urlencode({"text": text})


def payment_keyboard(payment=None, *, admin_url="https://t.me/Ditzzmback", retry="wallet", balance=False) -> InlineKeyboardMarkup:
    rows = []
    if payment and payment['status'] == 'pending' and payment['pay_url']:
        rows.append([premium_link_button("Оплатить через Crypto Bot", payment['pay_url'], EMOJI['crypto'], style="success")])
        rows.append([premium_button("Проверить оплату", f"check_payment:{payment['id']}", EMOJI['card'], style="success")])
        if balance:
            rows.append([premium_button("Оплатить с баланса", f"pay_balance:{payment['id']}", EMOJI['wallet'], style="success")])
    else:
        rows.append([premium_button("Оплата через Crypto Bot", retry, EMOJI['crypto'], style="success")])
    rows.append([premium_link_button("Оплата через администратора", admin_url, EMOJI['admin_payment'], style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_button("Каталог", "catalog", EMOJI["catalog"], style="success"), premium_button("Кошелёк", "wallet", EMOJI["wallet"])],
        [premium_button("Бонус", "bonus", EMOJI["bonus"]), premium_button("Профиль", "profile", EMOJI["profile"])],
        [premium_button("Техподдержка", "support", EMOJI["support"])],
        [premium_button("Прочее", "other", EMOJI["other"])],
        [InlineKeyboardButton(text="Открыть Web App", web_app=WebAppInfo(url=settings.shop_url), icon_custom_emoji_id=EMOJI["catalog"], style="success")],
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
        style="success" if p["stock_count"] > 0 else "danger",
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


@router.message(Command("start", "menu"))
async def command_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    login_match = re.fullmatch(r'/start(?:@wanderersshop_bot)?\s+auth_([A-Za-z0-9_-]{32})', message.text or '', re.I)
    if login_match:
        if message.chat.type != "private" or shop_site is None:
            await message.answer("Подтверждайте вход в личном чате с ботом.")
            return
        await get_database().upsert_customer(user.id, user.username, user.first_name)
        login = await shop_site.auth.claim(login_match[1], user.id)
        if not login:
            await message.answer("Ссылка входа истекла или уже используется. Создайте новый запрос на сайте.")
            return
        await message.answer(f"<b>Подтверждение входа на сайт</b>\n\n{html.escape(shop_site.site_url)}\n"
            f"Код: <code>{login['code']}</code>\n\nСравните этот код с кодом в браузере. "
            "Если вы не запрашивали вход или коды не совпадают — не подтверждайте его.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [button("Подтвердить вход", f"weblogin:allow:{login['id']}", style="success")],
                [button("Отказать", f"weblogin:deny:{login['id']}", style="danger")],
            ]))
        return
    referrer = start_referrer(message.text) if message.chat.type == "private" else None
    await get_database().upsert_customer(user.id, user.username, user.first_name, referrer)
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


@router.callback_query(F.data.startswith("weblogin:"))
async def approve_web_login(callback: CallbackQuery):
    if not private_checkout(callback) or shop_site is None:
        await callback.answer("Подтвердите вход в личном чате с ботом.", show_alert=True)
        return
    parts=callback.data.split(":")
    if len(parts)!=3 or parts[1] not in {"allow","deny"} or not re.fullmatch(r'[A-Za-z0-9_-]{32}',parts[2]):
        await callback.answer("Неверный запрос входа.", show_alert=True)
        return
    login=await shop_site.auth.approve(parts[2],callback.from_user.id,parts[1]=="allow")
    if not login:
        await callback.answer("Запрос уже обработан или истёк.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("Вход подтверждён. Вернитесь в браузер — сайт откроет ваш профиль." if parts[1]=="allow" else "Вход отклонён.")


@router.callback_query(F.data == "profile")
async def open_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.delete()
    user = callback.from_user
    await get_database().upsert_customer(user.id, user.username, user.first_name)
    customer = await get_database().customer(user.id)
    stats = await get_database().referral_stats(user.id)
    username = f"@{html.escape(user.username)}" if user.username else "@не указан"
    caption = (
        f"<b>Профиль</b> {premium_emoji(EMOJI['profile'], '👤')}\n\n"
        f"{username} | <code>{user.id}</code>\n\n"
        f"Баланс: <b>{dollars(str(customer['balance']) if customer else '0.00')}</b>\n"
        f"Рефералов: <b>{stats['invited']}</b> {premium_emoji(EMOJI['friends'], '👥')}\n"
        f"Покупок: <b>{stats['purchases']}</b> {premium_emoji(EMOJI['card'], '💳')}"
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


def private_checkout(callback: CallbackQuery) -> bool:
    return bool(callback.message and callback.message.chat.type == "private" and callback.message.chat.id == callback.from_user.id)


@router.callback_query(F.data.startswith("product:"))
@router.callback_query(F.data.startswith("qty:"))
async def open_product(callback: CallbackQuery) -> None:
    if not private_checkout(callback):
        await callback.answer("Откройте магазин в личном чате с ботом.", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        product_id = int(parts[1])
        count = quantity(parts[2]) if len(parts) > 2 else 1
    except (ValueError, IndexError):
        await callback.answer("Некорректное количество.", show_alert=True)
        return
    product = await get_database().product(product_id)
    if not product or not product['is_active']:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    await callback.answer()
    await render_product(callback, product, count)


async def render_product(callback: CallbackQuery, product: dict, count: int) -> None:
    # Serialize the complete edit, not just createInvoice: fast quantity taps must not
    # overwrite a newer card with an older invoice link that has already been deleted.
    async with get_payments().lock(callback.from_user.id, 'card', product['id']):
        await _render_product(callback, product, count)


def quantity_button(symbol: str, callback_data: str, emoji_id: str | None) -> InlineKeyboardButton:
    # Bot API requires a non-empty label. Braille blank is a real non-whitespace
    # character: the premium icon remains the only visible +/- glyph.
    return InlineKeyboardButton(text="⠀" if emoji_id else symbol, callback_data=callback_data,
                                icon_custom_emoji_id=emoji_id, style="primary")


async def _render_product(callback: CallbackQuery, product: dict, count: int) -> None:
    user = callback.from_user
    await get_database().upsert_customer(user.id, user.username, user.first_name)
    available = await get_payments().store.available(product['id'], user.id)
    count = min(count, max(1, available), 100)
    text = product_card(product, available)
    rows = []
    if available:
        icons = await quantity_emoji.load(telegram_bot)
        rows.append([
            quantity_button("−", f"qty:{product['id']}:{max(1, count - 1)}", icons.get('minus')),
            button(f"{count} шт.", "quantity_info", style="primary"),
            quantity_button("+", f"qty:{product['id']}:{min(available, 100, count + 1)}", icons.get('plus')),
        ])
        rows.append([premium_button("Способы оплаты", f"pay_methods:{product['id']}:{count}", EMOJI['card'], style="success")])
    rows.append([premium_button("Назад к категории" if product['category_id'] else "Назад в каталог",
        f"category:{product['category_id']}" if product['category_id'] else "catalog", EMOJI['back'], style="danger")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    if callback.data.startswith('qty:'):
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as exc:
            if 'message is not modified' not in str(exc):
                raise
    else:
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("pay_methods:"))
async def open_payment_methods(callback: CallbackQuery):
    if not private_checkout(callback):
        await callback.answer("Откройте магазин в личном чате с ботом.", show_alert=True)
        return
    try:
        _, product_id, count = callback.data.split(":")
        product_id = int(product_id)
        count = quantity(count)
    except (ValueError, TypeError):
        await callback.answer("Некорректное количество.", show_alert=True)
        return
    product = await get_database().product(product_id)
    if not product or not product['is_active']:
        await callback.answer("Товар недоступен", show_alert=True)
        return
    await callback.answer()
    async with get_payments().lock(callback.from_user.id, 'card', product_id):
        await show_product_payment_methods(callback, product, count)


async def show_product_payment_methods(callback: CallbackQuery, product: dict, count: int):
    user = callback.from_user
    await get_database().upsert_customer(user.id, user.username, user.first_name)
    service = get_payments()
    payment = None
    error = ""
    back = premium_button("Назад к товару", f"product:{product['id']}:{count}", EMOJI['back'], style="primary")
    try:
        payment = await service.checkout(user.id, 'product', product_id=product['id'], count=count)
        if payment['status'] == 'paid':
            await service.deliver(payment['id'])
            await callback.message.answer("Этот счёт уже оплачен. Товар придёт отдельным сообщением.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back]]))
            return
    except PaymentError as exc:
        error = "\n\n" + html.escape(str(exc))
    except ValueError as exc:
        # Don't offer payment for nonexistent stock or an invalid quantity.
        await callback.message.answer(html.escape(str(exc)), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back]]))
        return
    total = payment['amount'] if payment else Decimal(str(product['price'])) * count
    name = payment['product_name'] if payment else product['name']
    text = f"<b>Способы оплаты</b>\n\n<b>{html.escape(name)}</b> × {count} шт.\n{await payment_summary(str(total))}"
    if payment:
        text += "\n\n<i>Счёт действителен 10 минут. Выберите только один способ оплаты.</i>"
    text += error
    admin_url = await admin_payment_url(total, f"Хочу купить {name} × {count} шт.")
    keyboard = payment_keyboard(payment, admin_url=admin_url,
        retry=f"pay_methods:{product['id']}:{count}", balance=True)
    keyboard.inline_keyboard.append([back])
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "quantity_info")
async def quantity_info(callback: CallbackQuery):
    await callback.answer("Выберите количество кнопками − и +.")


@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery) -> None:
    # Old shop messages should still open the new quantity/payment card.
    await open_product(callback)


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment(callback: CallbackQuery):
    if not private_checkout(callback):
        await callback.answer("Проверяйте оплату в личном чате с ботом.", show_alert=True)
        return
    await callback.answer("Проверяем оплату…")
    try:
        p = await get_payments().check(int(callback.data.split(":")[1]), callback.from_user.id)
        text = ("Оплата подтверждена ✅" if p['status'] == 'paid' else
                "Срок счёта истёк. Откройте товар или пополнение заново." if p['status'] == 'expired' else
                "Счёт пока не оплачен. После оплаты подтверждение придёт автоматически.")
        await callback.message.answer(text)
    except (ValueError, PaymentError) as exc:
        await callback.message.answer(html.escape(str(exc)))


@router.callback_query(F.data.startswith("pay_balance:"))
async def pay_balance(callback: CallbackQuery):
    if not private_checkout(callback):
        await callback.answer("Оплачивайте в личном чате с ботом.", show_alert=True)
        return
    await callback.answer("Проверяем баланс…")
    try:
        await get_payments().balance_purchase(int(callback.data.split(":")[1]), callback.from_user.id)
        await callback.message.answer("Покупка подтверждена ✅ Товар придёт отдельным сообщением.")
    except (ValueError, PaymentError) as exc:
        await callback.message.answer(html.escape(str(exc)))


@router.callback_query(F.data == "bonus")
async def open_bonus(callback: CallbackQuery, state: FSMContext):
    if not private_checkout(callback):
        await callback.answer("Откройте «Бонус» в личном чате с ботом.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    user = callback.from_user
    await get_database().upsert_customer(user.id, user.username, user.first_name)
    stats = await get_database().referral_stats(user.id)
    link = referral_link(user.id)
    text = (f"<b>Бонус</b> {premium_emoji(EMOJI['bonus'], '🎁')}\n\n"
        "Пригласи друга по своей ссылке и получи <b>5% от его первой покупки</b> на баланс магазина.\n\n"
        f"Твоя реферальная ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено друзей: <b>{stats['invited']}</b>\n"
        f"Начислено бонусов: <b>{dollars(stats['earned'])} USD</b>\n\n"
        "Бонус начисляется после успешной покупки товара, не за пополнение. Ссылка действует для новых пользователей.")
    share = "https://t.me/share/url?" + urlencode({'url':link,'text':'Магазин Nexus Store — подписки и цифровые товары.'})
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скопировать ссылку", copy_text=CopyTextButton(text=link), style="primary")],
        [premium_link_button("Пригласить друга", share, EMOJI['friends'], style="success")],
        [premium_button("Назад", "menu", EMOJI['back'], style="danger")],
    ])
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    filename = COVERS_DIR / 'бонус.jpg'
    if filename.exists():
        await callback.message.answer_photo(FSInputFile(filename), caption=text, reply_markup=keyboard)
    else:
        await callback.message.answer(text, reply_markup=keyboard)


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
    if not private_checkout(callback):
        await callback.answer("Откройте кошелёк в личном чате с ботом.", show_alert=True)
        return
    amount = callback.data.split(":", maxsplit=1)[1]
    await callback.answer("Сумма выбрана")
    try:
        await show_payment_options(callback.message, amount, callback.from_user)
    except ValueError as exc:
        await callback.message.answer(html.escape(str(exc)))


async def show_payment_options(message: Message, amount: str, user=None, *, replace=True) -> None:
    amount = money(amount, maximum=Decimal('10000'))
    payment = None
    error = ""
    if user is not None:
        await get_database().upsert_customer(user.id, user.username, user.first_name)
        try:
            payment = await get_payments().checkout(user.id, 'topup', amount=amount)
            if payment['status'] == 'paid':
                await get_payments().deliver(payment['id'])
                await message.answer("Этот счёт уже оплачен, баланс пополнен.")
                return
        except (ValueError, PaymentError) as exc:
            error = "\n\n" + html.escape(str(exc))
    keyboard = payment_keyboard(payment,
        admin_url=await admin_payment_url(amount, "Хочу пополнить баланс магазина"), retry=f"topup:{amount:.2f}")
    keyboard.inline_keyboard.append([premium_button("Назад в кошелёк", "wallet", EMOJI['back'], style="danger")])
    if replace:
        with suppress(TelegramBadRequest):
            await message.delete()
    await message.answer(f"<b>Пополнение</b>\n{await payment_summary(str(amount))}\n\n"
        "Выберите способ оплаты. Через Crypto Bot баланс пополнится автоматически; через администратора — после его подтверждения." + error,
        reply_markup=keyboard)


@router.callback_query(F.data.startswith("topup:"))
async def create_topup(callback: CallbackQuery):
    if not private_checkout(callback):
        await callback.answer("Откройте кошелёк в личном чате с ботом.", show_alert=True)
        return
    await callback.answer()
    try:
        await show_payment_options(callback.message, callback.data.split(":")[1], callback.from_user)
    except ValueError as exc:
        await callback.message.answer(html.escape(str(exc)))


@router.callback_query(F.data == "wallet_custom")
async def request_custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    if not private_checkout(callback):
        await callback.answer("Откройте кошелёк в личном чате с ботом.", show_alert=True)
        return
    await state.set_state(WalletState.waiting_for_amount)
    await callback.answer()
    await callback.message.answer("Введите сумму в долларах, например: <b>7.50</b>")


@router.message(WalletState.waiting_for_amount, F.text)
async def receive_custom_amount(message: Message, state: FSMContext) -> None:
    raw_amount = message.text.strip().replace(",", ".").replace("$", "")
    try:
        amount = money(raw_amount, maximum=Decimal("10000"))
    except ValueError:
        await message.answer(f"Введите сумму числом от {dollars('0.01')} до {dollars('10 000')}.")
        return
    await state.clear()
    await show_payment_options(message, f"{amount:.2f}", message.from_user, replace=False)


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
    global database, telegram_bot, payments
    database = Database(settings.database_url)
    await database.connect()
    apply_emoji_settings(await database.emoji_settings())
    bot = Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    telegram_bot = bot
    payments = Payments(database._pool(), CryptoPay(settings.crypto_pay_token, testnet=settings.crypto_pay_testnet), bot)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    health_runner = await start_health_server()
    await quantity_emoji.load(bot)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Магазин", web_app=WebAppInfo(url=settings.shop_url)),request_timeout=5)
    except Exception:
        logging.warning("Telegram menu button was not configured; Web App link remains in shop menu")
    worker = asyncio.create_task(payments.run(), name="payment-reconciliation")
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await health_runner.cleanup()
        await payments.client.close()
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
    if not settings.crypto_pay_webhook_secret or not secrets.compare_digest(request.match_info["secret"], settings.crypto_pay_webhook_secret):
        raise web.HTTPNotFound()
    raw = await request.read()
    if not valid_signature(settings.crypto_pay_token, raw, request.headers.get("crypto-pay-api-signature", "")):
        raise web.HTTPUnauthorized()
    try:
        update = json.loads(raw)
        if not isinstance(update, dict):
            raise ValueError
        if update.get('update_type') != 'invoice_paid':
            return web.json_response({'ok': True})
        invoice = update.get('payload')
        if not isinstance(invoice, dict) or invoice.get('status') != 'paid':
            raise ValueError
        if payments is None:
            raise web.HTTPServiceUnavailable()
        p = await payments.store.apply(invoice)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest() from None
    # Ledger commits first; delivery failures remain in a durable retry queue.
    # Returning 200 on duplicates is safe because stock and balance settle only once.
    if p:
        await payments.deliver(p['id'])
    return web.json_response({'ok': True})


async def start_health_server() -> web.AppRunner:
    """Поднимает HTTP-сервер магазина и закрытой админ-панели."""
    app = web.Application()
    global shop_site
    shop_site=ShopSite(get_database,get_payments,settings.token,settings.shop_url,exchange_rates,COVERS_DIR,
        {"warranty":settings.warranty_url,"terms":settings.terms_url,"privacy":settings.privacy_url})
    shop_site.setup(app)
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
