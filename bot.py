"""Каркас витрины Telegram-магазина.

Платежи Crypto Pay, Supabase и выдача товаров намеренно оставлены на следующий
этап: этот файл уже содержит все экраны и точки, куда их подключать.
"""

import asyncio
import html
import logging
from pathlib import Path

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


def button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🛍 Каталог", "catalog"), button("💰 Кошелёк", "wallet")],
        [button("🎁 Бонус", "bonus"), button("👤 Профиль", "profile")],
        [button("🛟 Техподдержка", "support")],
        [button("📌 Прочее", "other")],
    ])


def back_keyboard(destination: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("← Назад", destination)]])


def catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("ChatGPT", "category:chatgpt"), button("Claude", "category:claude")],
        [button("Gemini", "category:gemini")],
        [button("Notion", "category:notion"), button("Grok", "category:grok")],
        [button("Perplexity", "category:perplexity"), button("Netflix", "category:netflix")],
        [button("Duolingo", "category:duolingo"), button("CapCut", "category:capcut")],
        [button("← Назад", "menu")],
    ])


def wallet_keyboard() -> InlineKeyboardMarkup:
    amounts = ["1", "3", "5", "10", "25"]
    rows = [
        [button(f"${amount}", f"wallet_amount:{amount}") for amount in amounts[:3]],
        [button(f"${amount}", f"wallet_amount:{amount}") for amount in amounts[3:]],
        [button("✍️ Своя сумма", "wallet_custom")],
        [button("← Назад", "menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def other_keyboard() -> InlineKeyboardMarkup:
    rows = []
    links = [
        ("🛡 Условия гарантии", settings.warranty_url),
        ("📄 Пользовательское соглашение", settings.terms_url),
        ("🔒 Политика конфиденциальности", settings.privacy_url),
    ]
    for text, url in links:
        rows.append([InlineKeyboardButton(text=text, url=url)] if url else [button(text, "link_not_set")])
    rows.append([button("← Назад", "menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать @DitzzmBack", url="https://t.me/DitzzmBack")],
        [button("← Назад", "menu")],
    ])


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Crypto Bot — через администратора", url="https://t.me/DitzzmBack")],
        [InlineKeyboardButton(text="👤 Оплата через администратора", url="https://t.me/DitzzmBack")],
        [button("← В меню", "menu")],
    ])


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("← Назад", "menu")]])


SCREENS: dict[str, tuple[str, str, InlineKeyboardMarkup]] = {
    "menu": (
        "меню.jpg",
        "<b>ГЛАВНОЕ МЕНЮ</b>\n\n"
        "Привет, {first_name}\n\n"
        "Добро пожаловать в магазин <b>Лавка Странника</b>\n\n"
        "Здесь ты можешь быстро и удобно купить нужные товары, "
        "пополнить баланс и посмотреть свои покупки.",
        menu_keyboard(),
    ),
    "wallet": ("кошелек.png", "<b>Кошелёк</b>\nПополните баланс на нужную сумму.", wallet_keyboard()),
    "bonus": (
        "бонус.jpg",
        "<b>Бонус</b>\n\n"
        "Пригласи своего друга и получи награду за его первую покупку "
        "в размере <b>5%</b> на свой баланс.",
        back_keyboard(),
    ),
    "support": ("тех подержка.jpg", "<b>Техподдержка</b>\nОпишите вопрос — вам поможет @DitzzmBack.", support_keyboard()),
    "other": ("прочее.jpg", "<b>Прочее</b>\nДокументы и важная информация.", other_keyboard()),
}

CATEGORIES: dict[str, tuple[str | None, str]] = {
    "chatgpt": ("chatgpt.png", "ChatGPT"),
    "claude": ("claude-cover.png", "Claude"),
    "gemini": ("gemini-cover.png", "Gemini"),
    "notion": ("notion-cover.png", "Notion"),
    "grok": ("grok-cover.png", "Grok"),
    "perplexity": ("perplexity-cover.png", "Perplexity"),
    "netflix": ("нетфликс.png", "Netflix"),
    "duolingo": (None, "Duolingo"),
    "capcut": ("capcut-cover.png", "CapCut"),
}


async def replace_with_screen(message: Message, screen: str, first_name: str = "друг") -> None:
    """Удаляет прошлый экран и присылает новый с нужной обложкой."""
    filename, caption, keyboard = SCREENS[screen]
    await message.delete()
    await message.answer_photo(
        FSInputFile(COVERS_DIR / filename),
        caption=caption.format(first_name=html.escape(first_name)),
        reply_markup=keyboard,
    )


async def show_category(message: Message, category: str) -> None:
    filename, title = CATEGORIES[category]
    await message.delete()
    caption = (
        f"<b>{title}</b>\n\n"
        "Товары этой категории будут добавлены следующим этапом. "
        "Карточки товаров появятся здесь автоматически после подключения базы."
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
        caption=caption.format(first_name=html.escape(message.from_user.first_name)),
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
        "<b>Профиль</b>\n\n"
        f"{username} | <code>{user.id}</code>\n\n"
        "Баланс: <b>0 ₽</b> | <b>$0.00</b>\n"
        "Рефералов: <b>0</b>\n"
        "Покупок: <b>0</b>"
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
        caption="<b>Каталог</b>\nВыберите категорию:",
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
    await show_payment_options(callback.message, f"${amount}")


async def show_payment_options(message: Message, amount: str) -> None:
    await message.delete()
    await message.answer(
        f"<b>Пополнение на {amount}</b>\n\n"
        "Выберите способ оплаты. Для оплаты через Crypto Bot напишите администратору.",
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
        await message.answer("Введите сумму числом от $0.01 до $10 000.")
        return
    await state.clear()
    await show_payment_options(message, f"${amount:.2f}")


@router.callback_query(F.data == "link_not_set")
async def link_not_set(callback: CallbackQuery) -> None:
    await callback.answer("Ссылка будет добавлена владельцем магазина.", show_alert=True)


async def main() -> None:
    if not settings.token or settings.token == "123456789:replace_me":
        raise RuntimeError("Укажите настоящий BOT_TOKEN в файле .env")
    bot = Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
