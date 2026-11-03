"""Бот онлайн-школы английского: тест уровня из 5 вопросов → запись на пробный урок.

Запуск: BOT_TOKEN=... ADMIN_ID=... python -m bots.school
"""
import re

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bots.common import choose, kb, notify_admin, run

# Вопросы от A1 к B2: (фраза, варианты, индекс верного)
QUESTIONS = [
    ("I ___ from Moscow.", ["am", "is", "are"], 0),
    ("She ___ to work by metro every day.", ["go", "goes", "going"], 1),
    ("I ___ this film last weekend.", ["have seen", "see", "saw"], 2),
    ("If I ___ more free time, I would travel more.", ["had", "have", "will have"], 0),
    ("By next June, she ___ here for ten years.", ["works", "will have worked", "is working"], 1),
]
LEVELS = ["A1", "A1", "A2", "B1", "B1+", "B2"]  # индекс — число верных ответов
TRIAL = ["Завтра 19:00", "Завтра 20:00", "Суббота 11:00", "Суббота 12:00"]


class Trial(StatesGroup):
    phone = State()


router = Router()


async def ask(msg: Message, step: int) -> None:
    q, options, _ = QUESTIONS[step]
    await msg.answer(
        f"Вопрос {step + 1}/{len(QUESTIONS)}\n\n<b>{q.replace('___', '_____')}</b>",
        reply_markup=kb([(o, f"ans:{step}:{i}") for i, o in enumerate(options)]),
    )


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer(
        "Hi! Я бот школы <b>Talkie</b> 🇬🇧\nОпределю ваш уровень английского за 2 минуты и запишу на бесплатный пробный урок.",
        reply_markup=kb([("Пройти тест", "test")], [("Сразу записаться", "trial")]),
    )


@router.callback_query(F.data == "test")
async def test(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(score=0)
    await choose(cb, "Пройти тест")
    await ask(cb.message, 0)


@router.callback_query(F.data.startswith("ans:"))
async def answer(cb: CallbackQuery, state: FSMContext) -> None:
    step, pick = map(int, cb.data.split(":")[1:])
    data = await state.get_data()
    if data.get("answered", -1) >= step:  # повторное нажатие на старый вопрос
        await cb.answer()
        return
    score = data.get("score", 0) + (pick == QUESTIONS[step][2])
    await state.update_data(score=score, answered=step)
    await choose(cb, QUESTIONS[step][1][pick])
    if step + 1 < len(QUESTIONS):
        await ask(cb.message, step + 1)
        return
    level = LEVELS[score]
    await state.update_data(level=level)
    await cb.message.answer(
        f"Ваш уровень: <b>{level}</b> ({score} из {len(QUESTIONS)})\n\n"
        "На пробном уроке преподаватель уточнит уровень в разговоре и составит план на 3 месяца. Когда удобно?",
        reply_markup=kb(*[[(t, f"slot:{i}")] for i, t in enumerate(TRIAL)]),
    )


@router.callback_query(F.data == "trial")
async def trial(cb: CallbackQuery) -> None:
    await choose(cb, "Сразу записаться")
    await cb.message.answer("Когда удобно пройти пробный урок?", reply_markup=kb(*[[(t, f"slot:{i}")] for i, t in enumerate(TRIAL)]))


@router.callback_query(F.data.startswith("slot:"))
async def slot(cb: CallbackQuery, state: FSMContext) -> None:
    when = TRIAL[int(cb.data.split(":")[1])]
    await state.update_data(slot=when)
    await choose(cb, when)
    await state.set_state(Trial.phone)
    await cb.message.answer(
        "Последний шаг: оставьте номер, пришлём ссылку на урок и напоминание.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )


@router.message(Trial.phone)
async def phone(msg: Message, state: FSMContext) -> None:
    digits = re.sub(r"\D", "", msg.contact.phone_number if msg.contact else (msg.text or ""))
    if len(digits) not in (10, 11):
        await msg.answer("Не похоже на номер. Нажмите кнопку «Отправить номер» или напишите +7 900 000-00-00.")
        return
    data = await state.get_data()
    await state.clear()
    await msg.answer(
        f"Готово! Пробный урок: <b>{data['slot']}</b>.\nЗа час пришлю ссылку. See you! 👋",
        reply_markup=ReplyKeyboardRemove(),
    )
    await notify_admin(
        msg.bot,
        f"🎓 Пробный урок: {data['slot']}\nУровень по тесту: {data.get('level', 'не проходил')}\n"
        f"Клиент: {msg.from_user.full_name}, +7{digits[-10:]}",
    )


if __name__ == "__main__":
    run(router)
