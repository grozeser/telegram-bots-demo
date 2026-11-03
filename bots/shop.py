"""Бот предзаказа для кофейни: меню → корзина → время → оплата → заказ бариста.

Оплата через Telegram Payments, если задан PAYMENT_TOKEN (ЮKassa и др.), иначе — при получении.
Запуск: BOT_TOKEN=... ADMIN_ID=... [PAYMENT_TOKEN=...] python -m bots.shop
"""
import itertools
import os

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from bots.common import choose, kb, notify_admin, run

MENU = {
    "Кофе": {"cap": ("Капучино 300 мл", 230), "flat": ("Флэт уайт", 260), "raf": ("Раф ванильный", 290)},
    "Еда": {"croi": ("Круассан с миндалём", 210), "chees": ("Сырники со сметаной", 340)},
}
ITEMS = {k: v for group in MENU.values() for k, v in group.items()}
PICKUP = ["Через 10 минут", "Через 20 минут", "Через 30 минут"]
order_numbers = itertools.count(101)
router = Router()


def cart_text(cart: dict[str, int]) -> tuple[str, int]:
    total = sum(ITEMS[k][1] * n for k, n in cart.items())
    lines = "\n".join(f"• {ITEMS[k][0]} × {n} — {ITEMS[k][1] * n} ₽" for k, n in cart.items())
    return f"🛒 <b>Корзина</b>\n{lines}\n\nИтого: <b>{total} ₽</b>", total


def menu_kb(group: str):
    rows = [[(f"{name} · {price} ₽", f"add:{k}")] for k, (name, price) in MENU[group].items()]
    tabs = [(("• " if g == group else "") + g, f"cat:{g}") for g in MENU]
    return kb(tabs, *rows, [("🛒 Корзина", "cart")])


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer(
        "Привет! Это кофейня <b>Зерно</b> ☕️\nЗакажите заранее — заберёте без очереди.",
        reply_markup=menu_kb("Кофе"),
    )


@router.callback_query(F.data.startswith("cat:"))
async def category(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=menu_kb(cb.data.split(":")[1]))


@router.callback_query(F.data.startswith("add:"))
async def add(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    cart = (await state.get_data()).get("cart", {})
    cart[key] = cart.get(key, 0) + 1
    await state.update_data(cart=cart)
    await cb.answer(f"Добавлено: {ITEMS[key][0]}")


@router.callback_query(F.data == "cart")
async def show_cart(cb: CallbackQuery, state: FSMContext) -> None:
    cart = (await state.get_data()).get("cart", {})
    if not cart:
        await cb.answer("Корзина пустая", show_alert=True)
        return
    await cb.answer()
    text, _ = cart_text(cart)
    rows = [[(f"− {ITEMS[k][0]}", f"del:{k}")] for k in cart]
    await cb.message.answer(text, reply_markup=kb(*rows, [("Оформить заказ", "checkout")]))


@router.callback_query(F.data.startswith("del:"))
async def remove(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    cart = (await state.get_data()).get("cart", {})
    if cart.get(key, 0) > 1:
        cart[key] -= 1
    else:
        cart.pop(key, None)
    await state.update_data(cart=cart)
    await cb.answer()
    if not cart:
        await cb.message.edit_text("Корзина пустая. Вернитесь в меню: /start")
        return
    text, _ = cart_text(cart)
    rows = [[(f"− {ITEMS[k][0]}", f"del:{k}")] for k in cart]
    await cb.message.edit_text(text, reply_markup=kb(*rows, [("Оформить заказ", "checkout")]))


@router.callback_query(F.data == "checkout")
async def checkout(cb: CallbackQuery) -> None:
    await choose(cb, "Оформляем")
    await cb.message.answer("Когда заберёте?", reply_markup=kb(*[[(t, f"pick:{i}")] for i, t in enumerate(PICKUP)]))


@router.callback_query(F.data.startswith("pick:"))
async def pickup(cb: CallbackQuery, state: FSMContext) -> None:
    when = PICKUP[int(cb.data.split(":")[1])]
    data = await state.update_data(pickup=when)
    await choose(cb, when)
    _, total = cart_text(data["cart"])
    token = os.getenv("PAYMENT_TOKEN")
    if token:
        await cb.message.answer_invoice(
            title="Заказ в кофейне Зерно", description=f"Самовывоз: {when.lower()}", payload="order",
            provider_token=token, currency="RUB",
            prices=[LabeledPrice(label=ITEMS[k][0] + f" × {n}", amount=ITEMS[k][1] * n * 100) for k, n in data["cart"].items()],
        )
    else:
        await place_order(cb.message, state, cb.from_user.full_name, paid=False)


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def paid(msg: Message, state: FSMContext) -> None:
    await place_order(msg, state, msg.from_user.full_name, paid=True)


async def place_order(msg: Message, state: FSMContext, client: str, paid: bool) -> None:
    data = await state.get_data()
    await state.clear()
    number = next(order_numbers)
    text, total = cart_text(data["cart"])
    status = "оплачен онлайн" if paid else "оплата при получении"
    await msg.answer(f"Заказ <b>№{number}</b> принят, {status}.\nГотовим — заберите {data['pickup'].lower()} у кассы ☕️")
    await notify_admin(msg.bot, f"☕️ Заказ №{number} · {status}\n{data['pickup']}\nКлиент: {client}\n\n{text}")


if __name__ == "__main__":
    run(router)
