import asyncio
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from db import cur, get_balance, add_balance
from config import ADMIN_ID
from utils.crypto import crypto_get_rate, crypto_create_invoice
from utils.cards import parse_card

# Глобальное состояние
pending_code = {}
pending_code_msg = {}
waiting = {}
waiting_topup = {}
waiting_card = {}
waiting_bank = {}
workers = set()
users_role = {}

menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="💳 Карта под оплату")]],
    resize_keyboard=True
)

def set_role(user_id: int, role: str):
    users_role[user_id] = role

def get_role(user_id: int):
    if user_id == ADMIN_ID:
        return "admin"
    return users_role.get(user_id, "user")

def load_workers():
    cur.execute("SELECT user_id FROM workers")
    rows = cur.fetchall()
    for row in rows:
        uid = row[0]
        workers.add(uid)
        users_role[uid] = "worker"

def register_common(dp, bot):

    @dp.message(F.text == "/start")
    async def start(message: types.Message):
        role = get_role(message.from_user.id)
        if role == "worker":
            await message.answer("🛠 Вы вошли как WORKER", reply_markup=menu)
        elif role == "admin":
            await message.answer("👑 Вы вошли как администратор", reply_markup=menu)
        else:
            text = (
                "🏠 Главное меню клиента\n\n"
                "Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
                "пополнить номер телефона или оплатить готовый QR-код.\n"
                "Все этапы заявки фиксируются внутри сервиса.\n\n"
                "💼 Комиссия сервиса: 20.00% от суммы заявки, но не меньше 30 RUB\n"
                "🆕 Уникальная карта: дополнительно +10.00%\n"
                "🔳 QR-оплата: скидка по комиссии -8.00%\n"
                "⚡️ Наши работники готовы обрабатывать заявки 24/7"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
                    InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
                ],
                [
                    InlineKeyboardButton(text="📳 Пополнить номер телефона через банк", callback_data="client_phone"),
                    InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
                ],
                [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
                [
                    InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
                    InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
                ],
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="client_support")]
            ])
            await message.answer(text, reply_markup=keyboard)

    @dp.message(F.text.startswith("/setworker"))
    async def set_worker(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Формат: /setworker 123456789")
            return
        try:
            user_id = int(parts[1])
            workers.add(user_id)
            set_role(user_id, "worker")
            cur.execute("INSERT INTO workers (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            await message.answer(f"✅ Worker назначен: {user_id}")
        except:
            await message.answer("Ошибка ID")

    @dp.message(F.text == "💳 Карта под оплату")
    async def new_order_btn(message: types.Message):
        waiting[message.from_user.id] = True
        await message.answer(
            "💳 Карта под оплату\n\n"
            "Введите сумму в RUB, на которую нужна карта.\n\n"
            "💸 Сумма заявки: в рублях\n"
            "Пример: 500"
        )

    @dp.message(F.text & ~F.text.startswith("/") & (F.text != "💳 Карта под оплату"))
    async def text_handler(message: types.Message):
        uid = message.from_user.id

        # 1. Воркер вводит код
        if uid in pending_code:
            order_id = pending_code.pop(uid)
            code = message.text.strip()

            cur.execute("SELECT user_id, amount, client_message_id FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()

            if not row or not row[0]:
                return await message.answer("❌ Ошибка: пользователь не найден")

            user_id, amount, client_msg_id = row

            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=client_msg_id,
                    text=f"🎉 Заявка принята в обработку\n\n"
                         f"🆔 ID: #{order_id}\n"
                         f"💳 Услуга: Карта под оплату\n"
                         f"💰 Сумма: {amount:.2f} RUB\n\n"
                         f"📊 Статус: 🟢 IN PROGRESS\n"
                         f"🔐 Ваш код: {code}"
                )
            except:
                pass

            try:
                await message.delete()
            except:
                pass

            btn_msg_id = pending_code_msg.pop(uid, None)
            if btn_msg_id:
                try:
                    await bot.delete_message(uid, btn_msg_id)
                except:
                    pass

            return await message.answer("✅ Код отправлен клиенту")

        # 2. Пополнение баланса
        if waiting_topup.get(uid):
            try:
                amount_rub = float(message.text.strip())
            except:
                return await message.answer("❌ Введите число, например 1000")
            if amount_rub <= 0:
                return await message.answer("❌ Сумма должна быть больше 0")
            waiting_topup[uid] = False

            rate = await crypto_get_rate()
            amount_usdt = round(amount_rub / rate, 2)
            commission = round(amount_usdt * 0.03, 2)
            to_credit = round(amount_usdt - commission, 2)

            invoice = await crypto_create_invoice(amount_usdt, uid)
            if not invoice:
                return await message.answer("❌ Ошибка создания инвойса. Попробуйте позже.")

            invoice_id = invoice["invoice_id"]
            pay_url = invoice["bot_invoice_url"]

            cur.execute(
                "INSERT INTO invoices (invoice_id, user_id, amount) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (invoice_id, uid, to_credit)
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Оплатить инвойс", url=pay_url)]
            ])
            await message.answer(
                f"🧾 Счёт на пополнение #{invoice_id}\n\n"
                f"💰 Сумма: {amount_rub:.2f} RUB (~{amount_usdt:.2f} USDT)\n"
                f"Комиссия: {commission:.2f} USDT\n"
                f"💎 К зачислению: {to_credit:.2f} USDT\n"
                f"🕒 Проверка: каждые 10 сек в течение 15 минут",
                reply_markup=keyboard
            )
            asyncio.create_task(check_payment_loop(bot, uid, invoice_id, to_credit))
            return

        # 3. Воркер вводит данные карты
        if waiting_card.get(uid):
            waiting_card[uid] = False
            card = parse_card(message.text)
            if not card:
                return await message.answer("❌ Не удалось найти номер карты. Попробуйте ещё раз.")
            waiting_bank[uid] = card
            return await message.answer(
                f"✅ Карта распознана:\n\n"
                f"💳 Номер: {card['number']}\n"
                f"📅 Срок: {card['expiry']}\n"
                f"🔐 CVV: {card['cvv']}\n\n"
                f"🏦 Введите название банка:"
            )

        # 4. Воркер вводит банк
        if uid in waiting_bank:
            card = waiting_bank.pop(uid)
            bank = message.text.strip()
            cur.execute(
                "INSERT INTO cards (worker_id, card_number, expiry, cvv, bank) VALUES (%s, %s, %s, %s, %s)",
                (uid, card["number"], card["expiry"], card["cvv"], bank)
            )
            cur.execute("SELECT COUNT(*) FROM cards WHERE worker_id=%s", (uid,))
            card_count = cur.fetchone()[0]
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="cards_add")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
            return await message.answer(
                f"✅ Карта сохранена!\n\n"
                f"💳 {card['number']}\n"
                f"🏦 Банк: {bank}\n"
                f"📅 Срок: {card['expiry']}\n\n"
                f"💼 Всего карт: {card_count}",
                reply_markup=keyboard
            )

        # 5. Пользователь вводит сумму заявки
        if not waiting.get(uid):
            return

        try:
            rub = float(message.text.strip())
        except:
            return await message.answer("❌ Введите число, например 500")

        waiting[uid] = False
        usdt = round(rub / 63.7, 2)
        total = round(rub * 1.2, 2)

        cur.execute(
            "INSERT INTO orders (user_id, amount, status, worker_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (uid, rub, "NEW", None)
        )
        order_id = cur.fetchone()[0]

        client_msg = await message.answer(
            f"🎉 Заявка принята в обработку\n\n"
            f"🆔 ID: #{order_id}\n"
            f"💳 Услуга: Карта под оплату\n"
            f"💰 Сумма: {rub:.2f} RUB\n\n"
            f"📊 Статус: 🟡 NEW\n"
            f"👨‍💻 Исполнитель: назначается\n\n"
            f"⏳ Ожидайте — скоро свяжемся с вами"
        )

        cur.execute("UPDATE orders SET client_message_id=%s WHERE id=%s", (client_msg.message_id, order_id))

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
        ])
        text_order = (
            f"📥 Новая заявка #{order_id}\n\n"
            f"💳 Метод: Карта под оплату\n"
            f"💰 Сумма: {rub:.2f} RUB\n"
            f"💎 Итог: {total:.2f} RUB\n"
            f"🔐 Резерв: {usdt} USDT\n\n"
            f"⏱ Время на принятие: 1500 сек"
        )
        for w in workers:
            try:
                await bot.send_message(w, text_order, reply_markup=keyboard)
            except:
                pass


async def check_payment_loop(bot, user_id: int, invoice_id: int, to_credit: float):
    from utils.crypto import crypto_check_invoice
    for _ in range(90):
        await asyncio.sleep(10)
        status = await crypto_check_invoice(invoice_id)

        if status == "paid":
            cur.execute("SELECT status FROM invoices WHERE invoice_id=%s", (invoice_id,))
            row = cur.fetchone()
            if row and row[0] == "active":
                add_balance(user_id, to_credit)
                cur.execute("UPDATE invoices SET status='paid' WHERE invoice_id=%s", (invoice_id,))
                balance = get_balance(user_id)
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ Баланс пополнен!\n\n"
                        f"💎 Зачислено: {to_credit:.2f} USDT\n"
                        f"💰 Текущий баланс: {balance:.2f} USDT"
                    )
                except:
                    pass
            return

        if status == "expired":
            cur.execute("UPDATE invoices SET status='expired' WHERE invoice_id=%s", (invoice_id,))
            try:
                await bot.send_message(user_id, f"❌ Инвойс #{invoice_id} истёк. Создайте новый.")
            except:
                pass
            return
