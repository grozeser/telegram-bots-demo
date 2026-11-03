"""Бот записи в барбершоп: услуга → мастер → день → свободное время → подтверждение.

Запуск: BOT_TOKEN=... ADMIN_ID=... python -m bots.booking
"""
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

from bots.common import choose, kb, notify_admin, run

SERVICES = {"cut": ("Мужская стрижка", 1800), "beard": ("Стрижка бороды", 1200), "combo": ("Стрижка + борода", 2700)}
MASTERS = {"ilya": "Илья", "artem": "Артём"}
SLOTS = ["11:00", "12:30", "14:00", "15:30", "17:00", "18:30"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
# shortcut: записи в памяти и пропадают при перезапуске, для продакшена — SQLite или Google Таблица
BOOKED: dict[tuple[str, str, str], int] = {}  # (мастер, день, время) → user_id

MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Записаться")], [KeyboardButton(text="Мои записи"), KeyboardButton(text="Цены и адрес")]],
    resize_keyboard=True,
)
router = Router()


def days() -> list[date]:
    return [date.today() + timedelta(days=i) for i in range(1, 4)]


def day_label(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day:02}.{d.month:02}"


@router.message(CommandStart())
async def start(msg: Message) -> None:
    await msg.answer(
        f"Здравствуйте, {msg.from_user.first_name}! Это барбершоп <b>Brass & Blade</b>.\n"
        "Запишу к мастеру за минуту, напомню о визите накануне.",
        reply_markup=MENU,
    )


@router.message(F.text == "Цены и адрес")
async def prices(msg: Message) -> None:
    lines = "\n".join(f"• {name} — {price} ₽" for name, price in SERVICES.values())
    await msg.answer(f"{lines}\n\n📍 ул. Кузнечная, 12, ежедневно 10:00–21:00")


@router.message(F.text == "Записаться")
async def book(msg: Message) -> None:
    await msg.answer(
        "Выберите услугу:",
        reply_markup=kb(*[[(f"{n} · {p} ₽", f"svc:{k}")] for k, (n, p) in SERVICES.items()]),
    )


@router.callback_query(F.data.startswith("svc:"))
async def pick_service(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    await state.update_data(service=key)
    await choose(cb, SERVICES[key][0])
    await cb.message.answer("К какому мастеру?", reply_markup=kb([(n, f"mst:{k}") for k, n in MASTERS.items()]))


@router.callback_query(F.data.startswith("mst:"))
async def pick_master(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    await state.update_data(master=key)
    await choose(cb, MASTERS[key])
    await cb.message.answer("Выберите день:", reply_markup=kb([(day_label(d), f"day:{d.isoformat()}") for d in days()]))


@router.callback_query(F.data.startswith("day:"))
async def pick_day(cb: CallbackQuery, state: FSMContext) -> None:
    day = cb.data.split(":", 1)[1]
    data = await state.update_data(day=day)
    free = [t for t in SLOTS if (data["master"], day, t) not in BOOKED]
    await choose(cb, day_label(date.fromisoformat(day)))
    if not free:
        await cb.message.answer("На этот день всё занято. Нажмите «Записаться», чтобы выбрать другой.")
        return
    rows = [[(t, f"time:{t}") for t in free[i:i + 3]] for i in range(0, len(free), 3)]
    await cb.message.answer("Свободное время:", reply_markup=kb(*rows))


@router.callback_query(F.data.startswith("time:"))
async def pick_time(cb: CallbackQuery, state: FSMContext) -> None:
    time = cb.data.split(":", 1)[1]
    data = await state.update_data(time=time)
    name, price = SERVICES[data["service"]]
    await choose(cb, time)
    await cb.message.answer(
        f"Проверьте запись:\n\n✂️ {name} — {price} ₽\n👤 Мастер: {MASTERS[data['master']]}\n"
        f"🗓 {day_label(date.fromisoformat(data['day']))} в {time}",
        reply_markup=kb([("Подтвердить", "ok"), ("Изменить", "again")]),
    )


@router.callback_query(F.data == "again")
async def again(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await choose(cb, "Изменить")
    await book(cb.message)


@router.callback_query(F.data == "ok")
async def confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    slot = (data["master"], data["day"], data["time"])
    if slot in BOOKED:  # пока клиент думал, время успели занять
        await cb.answer("Это время только что заняли, выберите другое", show_alert=True)
        return
    BOOKED[slot] = cb.from_user.id
    await state.clear()
    await choose(cb, "Подтверждено")
    when = f"{day_label(date.fromisoformat(data['day']))} в {data['time']}"
    await cb.message.answer(f"Готово, вы записаны на {when}. Напомню за день до визита 👋")
    user = cb.from_user
    await notify_admin(
        cb.bot,
        f"🆕 Новая запись\n{SERVICES[data['service']][0]}, мастер {MASTERS[data['master']]}\n{when}\n"
        f"Клиент: {user.full_name}" + (f" (@{user.username})" if user.username else ""),
    )


@router.message(F.text == "Мои записи")
async def my(msg: Message) -> None:
    mine = sorted((d, t, m) for (m, d, t), uid in BOOKED.items() if uid == msg.from_user.id)
    if not mine:
        await msg.answer("Записей пока нет. Нажмите «Записаться».")
        return
    lines = "\n".join(f"• {day_label(date.fromisoformat(d))} в {t}, мастер {MASTERS[m]}" for d, t, m in mine)
    await msg.answer(f"Ваши записи:\n{lines}")


if __name__ == "__main__":
    run(router)
