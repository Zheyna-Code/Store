"""Каркас витрины Telegram-магазина.

Платежи Crypto Pay, Supabase и выдача товаров намеренно оставлены на следующий
этап: этот файл уже содержит все экраны и точки, куда их подключать.
"""

import asyncio
import html
import logging
import os
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import COVERS_DIR, settings

router = Router()


class WalletState(StatesGroup):
    waiting_for_amount = State()


EMOJI = {
    "catalog": "5312361253610475399",
    "wallet": "5445353829304387411",
    "bonus": "5406756500108501710",
    "support": "5253742260054409879",
    "other": "5222444124698853913",
    "wave": "5440431182602842059",
    "chatgpt": "6134246530380472478",
    "claude": "6131771460986872161",
    "notion": "5364199932620194408",
    "duolingo": "5796371348808799072",
    "netflix": "5796522630441867305",
    "spotify": "5796304385973686816",
    "grok": "6179337489350663129",
    "capcut": "5267309292943331240",
    "perplexity": "5321199630585732877",
    "gemini": "5321197740800120767",
    "dollar": "5409048419211682843",
    "write": "5458382591121964689",
    "link": "5271604874419647061",
    "crypto": "5276137490846075469",
    "admin_payment": "5201691993775818138",
}


def button(text: str, callback_data: str, *, style: str = "primary") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


def premium_button(text: str, callback_data: str, emoji_id: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        icon_custom_emoji_id=emoji_id,
        style="primary",
    )


def premium_link_button(text: str, url: str, emoji_id: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url, icon_custom_emoji_id=emoji_id, style="primary")


def premium_emoji(emoji_id: str, fallback: str) -> str:
    """HTML-разметка premium emoji для текста и подписей."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def dollars(amount: str) -> str:
    return f"{premium_emoji(EMOJI['dollar'], '💵')}{amount}"


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_button("Каталог", "catalog", EMOJI["catalog"]), premium_button("Кошелёк", "wallet", EMOJI["wallet"])],
        [premium_button("Бонус", "bonus", EMOJI["bonus"]), button("👤 Профиль", "profile")],
        [premium_button("Техподдержка", "support", EMOJI["support"])],
        [premium_button("Прочее", "other", EMOJI["other"])],
    ])


def back_keyboard(destination: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("← Назад", destination, style="danger")]])


def catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_button("ChatGPT", "category:chatgpt", EMOJI["chatgpt"]), premium_button("Claude", "category:claude", EMOJI["claude"])],
        [premium_button("Gemini", "category:gemini", EMOJI["gemini"])],
        [premium_button("Notion", "category:notion", EMOJI["notion"]), premium_button("Grok", "category:grok", EMOJI["grok"])],
        [premium_button("Perplexity", "category:perplexity", EMOJI["perplexity"]), premium_button("Netflix", "category:netflix", EMOJI["netflix"])],
        [premium_button("Duolingo", "category:duolingo", EMOJI["duolingo"]), premium_button("CapCut", "category:capcut", EMOJI["capcut"])],
        [premium_button("Spotify", "category:spotify", EMOJI["spotify"])],
        [button("← Назад", "menu", style="danger")],
    ])


def wallet_keyboard() -> InlineKeyboardMarkup:
    amounts = ["1", "3", "5", "10", "25"]
    rows = [
        [premium_button(amount, f"wallet_amount:{amount}", EMOJI["dollar"]) for amount in amounts[:3]],
        [premium_button(amount, f"wallet_amount:{amount}", EMOJI["dollar"]) for amount in amounts[3:]],
        [premium_button("Своя сумма", "wallet_custom", EMOJI["write"])],
        [button("← Назад", "menu", style="danger")],
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
    rows.append([button("← Назад", "menu", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_link_button("Написать", "https://t.me/DitzzmBack", EMOJI["link"])],
        [button("← Назад", "menu", style="danger")],
    ])


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [premium_link_button("Crypto Bot", "https://t.me/DitzzmBack", EMOJI["crypto"])],
        [premium_link_button("Оплата через администратора", "https://t.me/DitzzmBack", EMOJI["admin_payment"])],
        [button("← В меню", "menu", style="danger")],
    ])


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("← Назад", "menu", style="danger")]])


SCREENS: dict[str, tuple[str, str, InlineKeyboardMarkup]] = {
    "menu": (
        "меню.png",
        "<b>ГЛАВНОЕ МЕНЮ</b> {plane}\n\n"
        "Привет, {wave} {first_name}\n\n"
        "Добро пожаловать в магазин <b>Nexus</b> <b>Store</b> 🏪\n\n"
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
        "<b>Бонус</b> 🎁\n\n"
        "Пригласи своего друга и получи награду за его первую покупку "
        "в размере <b>5%</b> на свой баланс 👥",
        back_keyboard(),
    ),
    "support": (
        "тех подержка.jpg",
        "<b>Техподдержка</b> {plane}\n"
        "Возникли вопросы или проблемы 🍭 Напишите в поддержку 💬",
        support_keyboard(),
    ),
    "other": ("прочее.jpg", "<b>Прочее</b> ⭐️\nДокументы и важная информация 🆕", other_keyboard()),
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


async def replace_with_screen(message: Message, screen: str, first_name: str = "друг") -> None:
    """Удаляет прошлый экран и присылает новый с нужной обложкой."""
    filename, caption, keyboard = SCREENS[screen]
    await message.delete()
    await message.answer_photo(
        FSInputFile(COVERS_DIR / filename),
        caption=caption.format(
            first_name=html.escape(first_name),
            wave=premium_emoji(EMOJI["wave"], "👋"),
            plane=premium_emoji(EMOJI["admin_payment"], "✈️"),
            crypto=premium_emoji(EMOJI["crypto"], "👛"),
            dollar=premium_emoji(EMOJI["dollar"], "💵"),
        ),
        reply_markup=keyboard,
    )


async def show_category(message: Message, category: str) -> None:
    filename, title = CATEGORIES[category]
    await message.delete()
    emoji_id, fallback = CATEGORY_EMOJI[category]
    caption = (
        f"<b>{title}</b> {premium_emoji(emoji_id, fallback)}\n\n"
        "Выберите подходящий товар из списка ниже 🍔\n"
        "После выбора вы сможете ознакомиться с деталями и оформить покупку 📄"
    )
    if filename and (COVERS_DIR / filename).exists():
        await message.answer_photo(
            FSInputFile(COVERS_DIR / filename),
            caption=caption,
            reply_markup=back_keyboard("catalog"),
        )
    else:
        await message.answer(caption, reply_markup=back_keyboard("catalog"))


@router.message(Command("start", "menu"))
async def command_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    filename, caption, keyboard = SCREENS["menu"]
    await message.answer_photo(
        FSInputFile(COVERS_DIR / filename),
        caption=caption.format(
            first_name=html.escape(message.from_user.first_name),
            wave=premium_emoji(EMOJI["wave"], "👋"),
            plane=premium_emoji(EMOJI["admin_payment"], "✈️"),
            crypto=premium_emoji(EMOJI["crypto"], "👛"),
            dollar=premium_emoji(EMOJI["dollar"], "💵"),
        ),
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "profile")
async def open_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """Поля с нулями заменятся данными Supabase на этапе подключения БД."""
    await state.clear()
    await callback.answer()
    await callback.message.delete()
    user = callback.from_user
    username = f"@{html.escape(user.username)}" if user.username else "@не указан"
    caption = (
        "<b>Профиль</b> 👤\n\n"
        f"{username} | <code>{user.id}</code>\n\n"
        f"Баланс: <b>0.00</b> {premium_emoji(EMOJI['dollar'], '💵')}\n"
        "Рефералов: <b>0</b> 👥\n"
        "Покупок: <b>0</b> 💳"
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
    await callback.message.answer_photo(
        FSInputFile(COVERS_DIR / "каталог.jpg"),
        caption="<b>Каталог</b> 🏪\nВыберите категорию из списка ниже для просмотра доступных предложений 🍔",
        reply_markup=catalog_keyboard(),
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
    if category in CATEGORIES:
        await show_category(callback.message, category)


@router.callback_query(F.data.startswith("wallet_amount:"))
async def choose_wallet_amount(callback: CallbackQuery) -> None:
    amount = callback.data.split(":", maxsplit=1)[1]
    await callback.answer("Сумма выбрана")
    await show_payment_options(callback.message, dollars(amount))


async def show_payment_options(message: Message, amount: str) -> None:
    await message.delete()
    await message.answer(
        f"<b>Пополнение на {amount}</b>\n\n"
        "Выберите способ оплаты 💳",
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
    await show_payment_options(message, dollars(f"{amount:.2f}"))


@router.message(F.entities)
async def get_custom_emoji_id(message: Message) -> None:
    """Возвращает ID premium emoji, присланного владельцем в сообщении."""
    emoji_ids = [
        entity.custom_emoji_id
        for entity in message.entities
        if entity.type == "custom_emoji" and entity.custom_emoji_id
    ]
    if not emoji_ids:
        return
    ids_text = "\n".join(f"<code>{emoji_id}</code>" for emoji_id in dict.fromkeys(emoji_ids))
    await message.answer(
        "<b>ID premium emoji:</b>\n"
        f"{ids_text}\n\n"
        "Скопируйте ID и пришлите его сюда — я добавлю emoji в нужное место меню."
    )


@router.callback_query(F.data == "link_not_set")
async def link_not_set(callback: CallbackQuery) -> None:
    await callback.answer("Ссылка будет добавлена владельцем магазина.", show_alert=True)


async def main() -> None:
    if not settings.token or settings.token == "123456789:replace_me":
        raise RuntimeError("Укажите настоящий BOT_TOKEN в файле .env")
    bot = Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    health_runner = await start_health_server()
    try:
        await dispatcher.start_polling(bot)
    finally:
        await health_runner.cleanup()


async def health(_: web.Request) -> web.Response:
    """Проверка состояния для Hostless и будущего Web App."""
    return web.json_response({"status": "ok", "service": "lavka-strannika-bot"})


async def start_health_server() -> web.AppRunner:
    """Поднимает минимальный HTTP-сервер, не мешая Telegram polling."""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
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
