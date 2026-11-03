"""Прогон ботов без Telegram: подменённая сессия записывает всё, что бот отправил.

python -m tests.simulate — проверяет сценарии (assert) и пишет transcripts/<бот>.json для картинок.
"""
import asyncio
import copy
import importlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

os.environ.setdefault("ADMIN_ID", "999")  # до импорта ботов: support фильтрует админ-чат по нему

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, TelegramMethod
from aiogram.types import (CallbackQuery, Chat, Contact, InlineKeyboardMarkup, Message, MessageEntity, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove, SuccessfulPayment, Update, User)

USER = User(id=1, is_bot=False, first_name="Анна", last_name="Смирнова", username="anna_s")
ADMIN = User(id=999, is_bot=False, first_name="Менеджер")
OUT = Path(__file__).resolve().parent.parent / "transcripts"


class FakeSession(BaseSession):
    """Вместо HTTP к Telegram: каждый вызов бота превращается в запись чата."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[dict] = []  # сообщения в порядке появления
        self.by_id: dict[int, dict] = {}
        self.toasts: list[str] = []
        self.markups: dict[int, dict[str, str]] = {}  # id сообщения → текст кнопки → callback_data
        self.next_id = 100

    def _remember(self, message_id: int, markup) -> None:
        if isinstance(markup, InlineKeyboardMarkup):
            self.markups[message_id] = {b.text: b.callback_data for row in markup.inline_keyboard for b in row}

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            if method.text:
                self.toasts.append(method.text)
            return True
        if isinstance(method, (EditMessageText, EditMessageReplyMarkup)):
            entry = self.by_id[method.message_id]
            if isinstance(method, EditMessageText):
                entry["text"] = method.text
            entry["buttons"] = buttons(method.reply_markup)
            self._remember(method.message_id, method.reply_markup)
            return True
        # send_message / send_invoice: новая запись в чате
        self.next_id += 1
        markup = getattr(method, "reply_markup", None)
        text = getattr(method, "text", None) or f"🧾 Счёт: {method.title}"
        entry = {"id": self.next_id, "from": "bot", "chat": method.chat_id, "text": text, "buttons": buttons(markup)}
        if isinstance(markup, ReplyKeyboardMarkup):
            entry["reply_kb"] = [[b.text for b in row] for row in markup.keyboard]
        if isinstance(markup, ReplyKeyboardRemove):
            entry["reply_kb"] = []
        self.log.append(entry)
        self.by_id[self.next_id] = entry
        self._remember(self.next_id, markup)
        return Message(message_id=self.next_id, date=datetime.now(), text=text,
                       chat=Chat(id=method.chat_id, type="private"))

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self) -> None:
        pass


def from_html(html: str) -> tuple[str, list[MessageEntity]]:
    """<b>/<i> → текст и entities, как их присылает Telegram (смещения в UTF-16)."""
    text, entities, opened = "", [], {}
    for part in re.split(r"(</?[bi]>)", html):
        if m := re.fullmatch(r"<(/?)([bi])>", part):
            pos = len(text.encode("utf-16-le")) // 2
            if m[1]:
                start = opened.pop(m[2])
                entities.append(MessageEntity(type="bold" if m[2] == "b" else "italic", offset=start, length=pos - start))
            else:
                opened[m[2]] = pos
        else:
            text += part.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text, entities


def buttons(markup) -> list[list[str]]:
    if isinstance(markup, InlineKeyboardMarkup):
        return [[b.text for b in row] for row in markup.inline_keyboard]
    return []


class Dialog:
    """Пользователь пишет и жмёт кнопки; проверяем, что отвечает бот."""

    def __init__(self, module: str) -> None:
        self.module = importlib.import_module(f"bots.{module}")
        self.name = module
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = Dispatcher()
        self.dp.include_router(self.module.router)
        self.uid = 0

    async def _feed(self, **update) -> None:
        self.uid += 1
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, **update))

    def _msg(self, user: User, **kw) -> Message:
        self.session.next_id += 1
        return Message(message_id=self.session.next_id, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                       from_user=user, **kw)

    async def say(self, text: str, user: User = USER, reply_to: int | None = None) -> None:
        reply = Message(message_id=reply_to, date=datetime.now(), chat=Chat(id=user.id, type="private")) if reply_to else None
        msg = self._msg(user, text=text, reply_to_message=reply)
        self.session.log.append({"id": msg.message_id, "from": "user" if user is USER else "admin_user", "chat": user.id, "text": text})
        await self._feed(message=msg)

    async def contact(self, phone: str) -> None:
        msg = self._msg(USER, contact=Contact(phone_number=phone, first_name=USER.first_name))
        self.session.log.append({"id": msg.message_id, "from": "user", "chat": USER.id, "text": f"📱 {phone}", "contact": True})
        await self._feed(message=msg)

    async def paid(self, total: int) -> None:
        pay = SuccessfulPayment(currency="RUB", total_amount=total * 100, invoice_payload="order",
                                telegram_payment_charge_id="t", provider_payment_charge_id="p")
        msg = self._msg(USER, successful_payment=pay)
        self.session.log.append({"id": msg.message_id, "from": "service", "chat": USER.id, "text": f"Оплачено {total} ₽"})
        await self._feed(message=msg)

    async def press(self, label: str) -> None:
        """Нажимает кнопку с таким текстом в последнем сообщении бота, где она есть."""
        for entry in reversed(self.session.log):
            if entry["from"] == "bot" and entry["chat"] == USER.id:
                for row in entry["buttons"]:
                    if label in row:
                        data = self._callback_data(entry, label)
                        text, entities = from_html(entry["text"])
                        msg = Message(message_id=entry["id"], date=datetime.now(), text=text, entities=entities,
                                      chat=Chat(id=USER.id, type="private"))
                        cb = CallbackQuery(id=str(self.uid), from_user=USER, chat_instance="c", data=data, message=msg)
                        await self._feed(callback_query=cb)
                        return
        raise AssertionError(f"{self.name}: нет кнопки «{label}»")

    def _callback_data(self, entry: dict, label: str) -> str:
        return self.session.markups[entry["id"]][label]

    def last(self, chat: int = USER.id) -> str:
        return next(e["text"] for e in reversed(self.session.log) if e["from"] == "bot" and e["chat"] == chat)

    def snap(self) -> None:
        """Запоминает чат в этот момент — его и сохраним для картинки (правки сообщений меняют записи на месте)."""
        self.snapshot = copy.deepcopy(self.session.log)

    def save(self) -> None:
        OUT.mkdir(exist_ok=True)
        log = getattr(self, "snapshot", None) or self.session.log
        user_chat = [e for e in log if e["chat"] == USER.id]
        admin_chat = [e for e in log if e["chat"] == ADMIN.id]
        data = {"bot": self.name, "chat": user_chat, "admin": admin_chat, "toasts": self.session.toasts}
        (OUT / f"{self.name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


async def booking() -> Dialog:
    d = Dialog("booking")
    await d.say("/start")
    assert "Brass & Blade" in d.last()
    await d.say("Записаться")
    await d.press("Стрижка + борода · 2700 ₽")
    await d.press("Илья")
    day = d.session.log[-1]["buttons"][0][0]
    await d.press(day)
    await d.press("14:00")
    assert "Стрижка + борода" in d.last() and "14:00" in d.last()
    await d.press("Подтвердить")
    assert "вы записаны" in d.last()
    assert "Новая запись" in d.last(ADMIN.id) and "@anna_s" in d.last(ADMIN.id)
    d.snap()
    # занятое время больше не предлагается
    await d.say("Записаться")
    await d.press("Стрижка + борода · 2700 ₽")
    await d.press("Илья")
    await d.press(day)
    assert "14:00" not in sum(d.session.log[-1]["buttons"], [])
    await d.say("Мои записи")
    assert "14:00" in d.last()
    return d


async def leads() -> Dialog:
    d = Dialog("leads")
    await d.say("/start")
    await d.press("Рассчитать ремонт")
    await d.press("Вторичка")
    await d.say("около 60 квадратов")
    await d.press("Капитальный · 11 900 ₽/м²")
    assert "785 400 ₽" in d.last()  # 60 × 11 900 × 1,1
    await d.say("позвоните мне")
    assert "Не похоже на номер" in d.last()
    await d.contact("+79001234567")
    assert "Заявка принята" in d.last()
    assert "+79001234567" in d.last(ADMIN.id) and "785 400 ₽" in d.last(ADMIN.id)
    return d


async def shop() -> Dialog:
    d = Dialog("shop")
    os.environ["PAYMENT_TOKEN"] = "TEST:token"
    await d.say("/start")
    await d.press("Капучино 300 мл · 230 ₽")
    await d.press("Капучино 300 мл · 230 ₽")
    await d.press("Еда")
    await d.press("Сырники со сметаной · 340 ₽")
    assert d.session.toasts[-1] == "Добавлено: Сырники со сметаной"
    await d.press("🛒 Корзина")
    assert "Итого: <b>800 ₽</b>" in d.last()
    await d.press("Оформить заказ")
    await d.press("Через 20 минут")
    assert "Счёт" in d.last()
    await d.paid(800)
    assert "№101" in d.last() and "оплачен онлайн" in d.last()
    assert "Сырники" in d.last(ADMIN.id)
    del os.environ["PAYMENT_TOKEN"]
    return d


async def support() -> Dialog:
    d = Dialog("support")
    await d.say("/start")
    await d.press("🚚 Доставка")
    assert "бесплатно от 3 000 ₽" in d.last()
    await d.press("Оператор")
    await d.say("Заказ 4512 не пришёл, трек не обновляется с понедельника")
    assert "Передал оператору" in d.last()
    question_id = next(e["id"] for e in reversed(d.session.log) if e["chat"] == ADMIN.id)
    await d.say("Анна, посылка застряла на сортировке. Отправили повторно, трек придёт сегодня до 18:00",
                user=ADMIN, reply_to=question_id)
    assert d.last().startswith("👩‍💻 <b>Оператор:</b> Анна")
    assert "Отправлено клиенту" in d.last(ADMIN.id)
    return d


async def school() -> Dialog:
    d = Dialog("school")
    await d.say("/start")
    await d.press("Пройти тест")
    for answer in ["am", "goes", "saw", "have", "will have worked"]:
        await d.press(answer)
    assert "Ваш уровень: <b>B1+</b> (4 из 5)" in d.last()
    await d.press("Суббота 11:00")
    await d.contact("89001234567")
    assert "Суббота 11:00" in d.last()
    assert "B1+" in d.last(ADMIN.id) and "+79001234567" in d.last(ADMIN.id)
    return d


async def main() -> None:
    for scenario in (booking, leads, shop, support, school):
        d = await scenario()
        d.save()
        print(f"ok  {d.name:8} сообщений: {len(d.session.log)}")


if __name__ == "__main__":
    asyncio.run(main())
