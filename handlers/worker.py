from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import db
from utils.crypto import crypto_get_rate
from handlers.common import pending_code, pending_code_msg, waiting_card, workers


def register_worker(dp, bot):

    @dp.message(F.text == "/lk")
    async def lk(message: types.Message):
        from handlers.common import get_role, PROFILE_BANNER_FILE_ID
        uid = message.from_user.id
        role = get_role(uid)

        if role not in ["worker", "admin"]:
            username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            frozen = await db.get_frozen(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            closed = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            active = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)
            paid_count = row["count"] if row else 0
            text = (
                f"<b>👤 Личный профиль</b>\n"
                f"<blockquote>{username} [{uid}]</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n"
                f"• Баланс: <b>{balance:.4f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.4f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Закрыто заявок: {closed} шт\n"
                f"• Активных заявок: {active} шт\n"
                f"• Успешных пополнений: {paid_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="client_ref")],
                [InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
            await message.answer_photo(
                photo=PROFILE_BANNER_FILE_ID,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

        username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
        balance = await db.get_balance(uid)
        row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        done_count = row["count"] if row else 0
        row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
        active_count = row["count"] if row else 0

        text = (
            f"🛠 Профиль работника\n"
            f"Ваш профиль: {username} [{uid}]\n\n"
            f"💼 Финансы\n"
            f"• Доступно для вывода: {balance:.4f} USDT\n\n"
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
        result = await db.db_execute(
            "UPDATE orders SET status='IN_PROGRESS', worker_id=$1 WHERE id=$2 AND status='NEW'",
            call.from_user.id, order_id
        )

        if "UPDATE 0" in result:
            return await call.answer("❌ Эту заявку уже забрали!", show_alert=True)
        row = await db.db_fetchone("SELECT user_id, amount, client_message_id FROM orders WHERE id=$1", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id = row["user_id"]
        amount = float(row["amount"])
        client_msg_id = row["client_message_id"]

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
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", worker_msg.message_id, order_id)
        await call.answer("Взял в работу ❤️")

    @dp.callback_query(F.data.startswith("send_req_"))
    async def send_req(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        cards = await db.db_fetchall("SELECT id, card_number, expiry, bank FROM cards WHERE worker_id=$1", uid)

        if not cards:
            return await call.answer("❌ У вас нет карт. Добавьте карту в /lk", show_alert=True)

        card_buttons = []
        for card in cards:
            masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['bank']}"
            card_buttons.append([
                InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"req_card_{order_id}_{card['id']}")
            ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
        await call.message.answer(f"💳 Выберите карту для заявки #{order_id}:", reply_markup=keyboard)
        await call.answer()

    @dp.callback_query(F.data.startswith("req_card_"))
    async def req_card(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        card_id = int(parts[3])

        row = await db.db_fetchone(
            "SELECT card_number, expiry, cvv, bank FROM cards WHERE id=$1 AND worker_id=$2",
            card_id, call.from_user.id
        )
        if not row:
            return await call.answer("❌ Карта не найдена", show_alert=True)

        number = row["card_number"]
        expiry = row["expiry"]
        cvv = row["cvv"]
        bank = row["bank"]

        order_row = await db.db_fetchone("SELECT user_id, amount, client_message_id FROM orders WHERE id=$1", order_id)
        if not order_row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id = order_row["user_id"]
        amount = order_row["amount"]
        client_msg_id = order_row["client_message_id"]

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
        row = await db.db_fetchone("SELECT worker_id FROM orders WHERE id=$1", order_id)
        if not row or row["worker_id"] is None:
            return await call.answer("❌ Нет исполнителя", show_alert=True)

        worker_id = row["worker_id"]
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

        row = await db.db_fetchone(
            "SELECT user_id, amount, status, client_message_id, total_usdt FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, worker_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id = row["user_id"]
        amount = float(row["amount"])
        status = row["status"]
        client_msg_id = row["client_message_id"]
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0

        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=client_msg_id,
                text=f"🎉 Заявка принята в обработку\n\n"
                     f"🆔 ID: #{order_id}\n"
                     f"💳 Услуга: Карта под оплату\n"
                     f"💰 Сумма: {amount:.2f} RUB\n\n"
                     f"📊 Статус: 🟡 ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ\n"
                     f"💸 К списанию: {total_usdt:.4f} USDT\n\n"
                     f"⏳ Пожалуйста, подтвердите оплату",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"client_paid_{order_id}_{total_usdt}")]
                ])
            )
        except Exception as e:
            print(f"[worker_confirm] edit_message_text error: {e}")

        await call.answer("✅ Запрос отправлен клиенту", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(f"⏳ Ожидаем подтверждения от клиента по заявке #{order_id}")
