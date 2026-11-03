"""Общее для всех ботов: запуск, админ-чат и шаг выбора кнопкой."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup


def admin_id() -> int:
    """Чат, куда приходят заявки. 0 — уведомления выключены."""
    return int(os.getenv("ADMIN_ID", "0"))


def kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """kb([("Текст", "data"), ...], ...) — инлайн-клавиатура по строкам."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


async def choose(cb: CallbackQuery, label: str) -> None:
    """Фиксирует выбор в сообщении с кнопками и убирает кнопки, чтобы не нажать дважды."""
    await cb.answer()
    await cb.message.edit_text(f"{cb.message.html_text}\n\n✅ <b>{label}</b>")


async def notify_admin(bot: Bot, text: str) -> None:
    if admin_id():
        await bot.send_message(admin_id(), text)


def run(router: Router) -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(os.environ["BOT_TOKEN"], default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.run(dp.start_polling(bot))
