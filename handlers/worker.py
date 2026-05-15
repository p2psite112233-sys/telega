from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db import cur, get_balance, add_balance
from utils.crypto import crypto_get_rate
from handlers.common import pending_code, pending_code_msg, waiting_card, workers


def register_worker(dp, bot):

    @dp.message(F.text == "/lk")
    async def lk(message: types.Message):
        from handlers.common import get_role
        uid = message.from_user.id
        role = get_role(uid)

        if role not in ["worker", "admin"]:
            return

        username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
        balance = get_balance(uid)

        cur.execute("SELECT COUNT(*) FROM orders WHERE worker_id=%s AND status='DONE'", (uid,))
        done_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders WHERE worker_id=%s AND status='IN_PROGRESS'", (uid,))
        active_count = cur.fetchone()[0]

        text = (
            f"🛠 Профиль работника\n"
            f"Ваш профиль: {username} [{uid}]\n\n"
            f"💼 Финансы\n"
            f"• Доступно для вывода: {balance:.4f} USDT\n"
            f"• Заморожено: 0.00 USDT\n\n"
            f"📊 Статистика\n"
            f"• Обработано заявок: {done_count} шт\n"
            f"• Активных заявок: {active_count} шт"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
            [
                InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")
            ],
            [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="lk_menu")]
        ])

        await message.answer(text, reply_markup=keyboard)

    @dp.callback_query(F.data.startswith("take_"))
    async def take(call: types.CallbackQuery):
        from handlers.common import get_role
        role = get_role(call.from_user.id)
        if role not in ["worker", "admin"]:
            return await call.answer("Нет доступа", show_alert=True)

        order_id = int(call.data.split("_")[1])
        cur.execute(
            "UPDATE orders SET status='IN_PROGRESS', worker_id=%s WHERE id=%s",
            (call.from_user.id, order_id)
        )
        cur.execute("SELECT user_id, amount, client_message_id FROM orders WHERE id=%s", (order_id,))
        row = cur.fetchone()
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

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
                     f"👨‍💻 Исполнитель: уже работает над заявкой\n\n"
                     f"⏳ Ожидайте реквизитов для оплаты"
            )
        except:
            pass

        worker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")]
        ])
        worker_msg = await call.message.answer("Заявка принята🔥", reply_markup=worker_keyboard)
        cur.execute("UPDATE orders SET worker_message_id=%s WHERE id=%s", (worker_msg.message_id, order_id))
        await call.answer("Взял в работу ❤️")

    @dp.callback_query(F.data.startswith("send_req_"))
    async def send_req(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        cur.execute("SELECT id, card_number, expiry, bank FROM cards WHERE worker_id=%s", (uid,))
        cards = cur.fetchall()

        if not cards:
            return await call.answer("❌ У вас нет карт. Добавьте карту в /lk", show_alert=True)

        card_buttons = []
        for card in cards:
            cid, number, expiry, bank = card
            masked = f"{number[:6]}{'*'*6}{number[-4:]} · {bank}"
            card_buttons.append([
                InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"req_card_{order_id}_{cid}")
            ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
        await call.message.answer(f"💳 Выберите карту для заявки #{order_id}:", reply_markup=keyboard)
        await call.answer()

    @dp.callback_query(F.data.startswith("req_card_"))
    async def req_card(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        card_id = int(parts[3])

        cur.execute(
            "SELECT card_number, expiry, cvv, bank FROM cards WHERE id=%s AND worker_id=%s",
            (card_id, call.from_user.id)
        )
        row = cur.fetchone()
        if not row:
            return await call.answer("❌ Карта не найдена", show_alert=True)

        number, expiry, cvv, bank = row

        cur.execute("SELECT user_id, amount, client_message_id FROM orders WHERE id=%s", (order_id,))
        user_row = cur.fetchone()
        if not user_row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id, amount, client_msg_id = user_row

        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=client_msg_id,
                text=f"🎉 Заявка принята в обработку\n\n"
                     f"🆔 ID: #{order_id}\n"
                     f"💳 Услуга: Карта под оплату\n"
                     f"💰 Сумма: {amount:.2f} RUB\n\n"
                     f"📊 Статус: 🟢 IN PROGRESS\n\n"
                     f"💳 Реквизиты для оплаты:\n"
                     f"🏦 Банк: {bank}\n"
                     f"💳 Номер карты: {number}\n"
                     f"📅 Срок: {expiry}\n"
                     f"🔐 CVV: {cvv}\n\n"
                     f"⏳ Ожидайте кода подтверждения",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")]
                ])
            )
        except:
            pass

        await call.answer("✅ Реквизиты отправлены клиенту", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(
            f"✅ Реквизиты по заявке #{order_id} отправлены клиенту",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order_id}")]
            ])
        )

    @dp.callback_query(F.data.startswith("request_code_"))
    async def request_code(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        cur.execute("SELECT worker_id FROM orders WHERE id=%s", (order_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return await call.answer("❌ Нет исполнителя", show_alert=True)

        worker_id = row[0]
        worker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")]
        ])
        await bot.send_message(
            worker_id,
            f"🔑 Клиент запросил код\n\n📥 Заявка #{order_id}",
            reply_markup=worker_keyboard
        )
        await call.answer("Запрос отправлен 📩")

    @dp.callback_query(F.data.startswith("send_code_"))
    async def send_code(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        pending_code[call.from_user.id] = order_id
        pending_code_msg[call.from_user.id] = call.message.message_id
        await bot.send_message(call.from_user.id, "🔐 Введите код для клиента одним сообщением:")
        await call.answer()

    @dp.callback_query(F.data.startswith("worker_confirm_"))
    async def worker_confirm(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        worker_id = call.from_user.id

        cur.execute(
            "SELECT user_id, amount, status, client_message_id FROM orders WHERE id=%s AND worker_id=%s",
            (order_id, worker_id)
        )
        row = cur.fetchone()
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id, amount, status, client_msg_id = row
        if status == "DONE":
            return await call.answer("✅ Заявка уже завершена", show_alert=True)

        total = round(amount * 1.2, 2)
        rate = await crypto_get_rate()
        total_usdt = round(total / rate, 4)

        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=client_msg_id,
                text=f"🎉 Заявка принята в обработку\n\n"
                     f"🆔 ID: #{order_id}\n"
                     f"💳 Услуга: Карта под оплату\n"
                     f"💰 Сумма: {amount:.2f} RUB\n\n"
                     f"📊 Статус: 🟡 ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ\n"
                     f"💸 К списанию: {total_usdt:.4f} USDT ({total:.2f} RUB)\n\n"
                     f"⏳ Пожалуйста, подтвердите оплату",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"client_paid_{order_id}_{total_usdt}")]
                ])
            )
        except:
            pass

        await call.answer("✅ Запрос отправлен клиенту", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(f"⏳ Ожидаем подтверждения от клиента по заявке #{order_id}")
