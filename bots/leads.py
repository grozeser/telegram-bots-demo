"""Бот-квиз для заявок на ремонт: жильё → площадь → тариф → телефон. Считает цену и шлёт заявку менеджеру.

Запуск: BOT_TOKEN=... ADMIN_ID=... python -m bots.leads
"""
import re

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bots.common import choose, kb, notify_admin, run

HOMES = {"new": "Новостройка", "old": "Вторичка"}
TARIFFS = {"cosmetic": ("Косметический", 6500), "capital": ("Капитальный", 11900), "design": ("Дизайнерский", 17500)}


class Quiz(StatesGroup):
    area = State()
    phone = State()


router = Router()


def rub(n: float) -> str:
    return f"{round(n, -2):,.0f} ₽".replace(",", " ")


def estimate(home: str, area: int, tariff: str) -> float:
    """Та же формула, что в калькуляторе на сайте: вторичка дороже на 10% из-за демонтажа."""
    return area * TARIFFS[tariff][1] * (1.1 if home == "old" else 1)


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer(
        "Здравствуйте! Я помощник компании <b>Ровно</b>.\n"
        "Ответьте на 4 вопроса — посчитаю стоимость ремонта и запишу на бесплатный замер.",
        reply_markup=kb([("Рассчитать ремонт", "go")]),
    )


@router.callback_query(F.data == "go")
async def go(cb: CallbackQuery) -> None:
    await choose(cb, "Рассчитать ремонт")
    await cb.message.answer("1/4. Какое жильё?", reply_markup=kb([(v, f"home:{k}") for k, v in HOMES.items()]))


@router.callback_query(F.data.startswith("home:"))
async def home(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    await state.update_data(home=key)
    await choose(cb, HOMES[key])
    await state.set_state(Quiz.area)
    await cb.message.answer("2/4. Площадь квартиры в м²? Напишите число, например 54.")


@router.message(Quiz.area)
async def area(msg: Message, state: FSMContext) -> None:
    value = re.sub(r"[^\d]", "", msg.text or "")
    if not value or not 10 <= int(value) <= 500:
        await msg.answer("Напишите площадь числом от 10 до 500, например 54.")
        return
    await state.update_data(area=int(value))
    await state.set_state(None)
    await msg.answer(
        "3/4. Какой ремонт нужен?",
        reply_markup=kb(*[[(f"{n} · {p:,} ₽/м²".replace(",", " "), f"tariff:{k}")] for k, (n, p) in TARIFFS.items()]),
    )


@router.callback_query(F.data.startswith("tariff:"))
async def tariff(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    data = await state.update_data(tariff=key)
    await choose(cb, TARIFFS[key][0])
    price = estimate(data["home"], data["area"], key)
    await state.set_state(Quiz.phone)
    await cb.message.answer(
        f"Предварительно: <b>{rub(price)}</b> за работы.\n\n"
        "4/4. Оставьте телефон — инженер приедет на бесплатный замер и зафиксирует цену в договоре.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )


@router.message(Quiz.phone)
async def phone(msg: Message, state: FSMContext) -> None:
    raw = msg.contact.phone_number if msg.contact else (msg.text or "")
    digits = re.sub(r"\D", "", raw)
    if len(digits) not in (10, 11):
        await msg.answer("Не похоже на номер. Нажмите кнопку или напишите в формате +7 900 000-00-00.")
        return
    data = await state.get_data()
    await state.clear()
    price = rub(estimate(data["home"], data["area"], data["tariff"]))
    await msg.answer(
        "Спасибо! Заявка принята, менеджер перезвонит в течение 15 минут.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await notify_admin(
        msg.bot,
        f"🔥 Заявка на замер\n{HOMES[data['home']]}, {data['area']} м², {TARIFFS[data['tariff']][0].lower()}\n"
        f"Расчёт: {price}\nТелефон: +7{digits[-10:]}\n"
        f"Клиент: {msg.from_user.full_name}",
    )


if __name__ == "__main__":
    run(router)
