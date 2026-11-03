"""Бот поддержки интернет-магазина: ответы на частые вопросы и переписка с оператором.

Вопрос клиента уходит в админ-чат, оператор отвечает реплаем — ответ приходит клиенту от имени бота.
Запуск: BOT_TOKEN=... ADMIN_ID=... python -m bots.support
"""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bots.common import admin_id, choose, kb, run

FAQ = {
    "delivery": ("🚚 Доставка", "По Москве — на следующий день, 290 ₽, бесплатно от 3 000 ₽.\nПо России — СДЭК и Почта, 2–6 дней."),
    "return": ("↩️ Возврат", "Вернуть товар можно в течение 14 дней, если сохранены вид и бирки. Деньги придут за 3–5 дней."),
    "size": ("📏 Подбор размера", "Измерьте обхват груди и талии и сверьтесь с таблицей на карточке товара. Если между размерами — берите больший."),
    "order": ("📦 Где мой заказ", "Трек-номер приходит в SMS после отправки. Если его нет больше 2 дней — позовите оператора."),
}


class Chat(StatesGroup):
    operator = State()


# shortcut: связь «сообщение в админ-чате → клиент» в памяти, после перезапуска старые вопросы не ответить; для продакшена — Redis/SQLite
TICKETS: dict[int, int] = {}
router = Router()


def faq_kb():
    keys = list(FAQ)
    rows = [[(FAQ[a][0], f"faq:{a}"), (FAQ[b][0], f"faq:{b}")] for a, b in zip(keys[::2], keys[1::2])]
    return kb(*rows, [("👩‍💻 Написать оператору", "operator")])


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer(
        "Здравствуйте! Это поддержка магазина одежды <b>Лён и хлопок</b>.\nВыберите вопрос или напишите оператору:",
        reply_markup=faq_kb(),
    )


@router.callback_query(F.data.startswith("faq:"))
async def faq(cb: CallbackQuery) -> None:
    title, answer = FAQ[cb.data.split(":")[1]]
    await cb.answer()
    await cb.message.answer(f"<b>{title}</b>\n{answer}", reply_markup=kb([("Другой вопрос", "menu"), ("Оператор", "operator")]))


@router.callback_query(F.data == "menu")
async def menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer("Выберите вопрос:", reply_markup=faq_kb())


@router.callback_query(F.data == "operator")
async def operator(cb: CallbackQuery, state: FSMContext) -> None:
    await choose(cb, "Оператор")
    await state.set_state(Chat.operator)
    await cb.message.answer("Опишите вопрос одним сообщением, оператор ответит здесь же. Обычно отвечаем за 5 минут.")


@router.message(F.chat.id == admin_id(), F.reply_to_message)
async def admin_reply(msg: Message) -> None:
    user_id = TICKETS.get(msg.reply_to_message.message_id)
    if not user_id:
        await msg.reply("Не нашёл, кому это ответ. Отвечайте реплаем на вопрос клиента.")
        return
    await msg.bot.send_message(user_id, f"👩‍💻 <b>Оператор:</b> {msg.html_text}")
    await msg.reply("Отправлено клиенту ✅")


@router.message(Chat.operator, F.text)
async def to_operator(msg: Message) -> None:
    if not admin_id():
        await msg.answer("Операторы сейчас недоступны, попробуйте позже.")
        return
    sent = await msg.bot.send_message(
        admin_id(),
        f"❓ Вопрос от {msg.from_user.full_name}" + (f" (@{msg.from_user.username})" if msg.from_user.username else "")
        + f"\n\n{msg.html_text}\n\n<i>Ответьте реплаем на это сообщение</i>",
    )
    TICKETS[sent.message_id] = msg.chat.id
    await msg.answer("Передал оператору, ответ придёт сюда 🙌")


if __name__ == "__main__":
    run(router)
