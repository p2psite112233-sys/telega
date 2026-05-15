import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import PROFILE_BANNER_FILE_ID
from utils.shared import get_role, workers
from utils.crypto import crypto_get_rate

logger = logging.getLogger(__name__)

class WorkerStates(StatesGroup):
    waiting_for_code = State()


def register_worker(dp, bot):

    @dp.message(F.text == "/lk")
    async def lk(message: types.Message):
        uid = message.from_user.id
        role = get_role(uid)
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"

        balance = await db.get_balance(uid)

        if role not in ["worker", "admin"]:
            frozen = await db.get_frozen(uid)
            c_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            c_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            paid_count = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)

            text = (
                f"<b>👤 Личный профиль</b>\n"
                f"<blockquote>{username}</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n"
                f"• Баланс: <b>{balance:.4f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.4f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Закрыто: {c_done['count']} шт\n"
                f"• Активно: {c_active['count']} шт\n"
                f"• Пополнений: {paid_count['count']} шт"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферал", callback_data="client_ref"),
                 InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="client_back_menu")]
            ])
            return await message.answer_photo(
                photo=PROFILE_BANNER_FILE_ID,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )

        # Профиль воркера
        w_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        w_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)

        text = (
            f"🛠 <b>Профиль работника</b>\n"
            f"Аккаунт: {username}\n\n"
            f"💼 <b>Финансы</b>\n"
            f"• Доступно: <b>{balance:.4f} USDT</b>\n\n"
            f"📊 <b>Статистика</b>\n"
            f"• Выполнено: {w_done['count']} шт\n"
            f"• В работе: {w_active['count']} шт"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод", callback_data="lk_withdraw")],
            [InlineKeyboardButton(text="🟢 Активные", callback_data="lk_active"),
             InlineKeyboardButton(text="📚 История", callback_data="lk_history")],
            [InlineKeyboardButton(text="💳 Карты", callback_data="lk_cards")]
        ])
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data.startswith("take_"))
    async def take(call: types.CallbackQuery):
        uid = call.from_user.id
        if get_role(uid) not in ["worker", "admin"]:
            return await call.answer("Нет доступа", show_alert=True)

        order_id = int(call.data.split("_")[1])
        res = await db.db_execute(
            "UPDATE orders SET status='IN_PROGRESS', worker_id=$1 WHERE id=$2 AND status='NEW'",
            uid, order_id
        )

        if "UPDATE 0" in res:
            return await call.answer("❌ Заявку уже забрали!", show_alert=True)

        order = await db.db_fetchone("SELECT user_id, amount, client_message_id FROM orders WHERE id=$1", order_id)

        # Сначала отправляем новое сообщение, потом удаляем старое
        new_msg = await bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {float(order['amount']):.2f} RUB\n\n"
                 f"📊 Статус: 🟢 В работе\n"
                 f"👨‍💻 Исполнитель уже готовит реквизиты\n\n"
                 f"⏳ Ожидайте реквизитов для оплаты",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(order["user_id"], order["client_message_id"])
        except Exception as e:
            logger.error(f"[take] delete old msg error: {e}")

        await call.message.answer(
            f"✅ Вы взяли заказ #{order_id}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data.startswith("send_req_"))
    async def send_req(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        order = await db.db_fetchone("SELECT id FROM orders WHERE id=$1 AND worker_id=$2", order_id, uid)
        if not order:
            return await call.answer("❌ Нет доступа к этой заявке", show_alert=True)

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
        uid = call.from_user.id

        card = await db.db_fetchone(
            "SELECT card_number, expiry, cvv, bank FROM cards WHERE id=$1 AND worker_id=$2",
            card_id, uid
        )
        order = await db.db_fetchone(
            "SELECT user_id, amount, client_message_id FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, uid
        )

        if not card or not order:
            return await call.answer("❌ Ошибка данных", show_alert=True)

        # Сначала отправляем новое, потом удаляем старое
        new_msg = await bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {float(order['amount']):.2f} RUB\n\n"
                 f"📊 Статус: 🟢 В работе\n\n"
                 f"💳 Реквизиты для оплаты:\n"
                 f"🏦 Банк: {card['bank']}\n"
                 f"💳 Номер карты: <code>{card['card_number']}</code>\n"
                 f"📅 Срок: {card['expiry']}\n"
                 f"🔐 CVV: <code>{card['cvv']}</code>\n\n"
                 f"⏳ После оплаты запросите код подтверждения",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(order["user_id"], order["client_message_id"])
        except Exception as e:
            logger.error(f"[req_card] delete error: {e}")

        await call.answer("✅ Реквизиты отправлены клиенту", show_alert=True)
        await call.message.answer(
            f"✅ Реквизиты по заявке #{order_id} отправлены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order_id}")]
            ])
        )

    @dp.callback_query(F.data.startswith("request_code_"))
    async def request_code(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        row = await db.db_fetchone(
            "SELECT worker_id FROM orders WHERE id=$1 AND user_id=$2",
            order_id, call.from_user.id
        )
        if not row or row["worker_id"] is None:
            return await call.answer("❌ Нет доступа", show_alert=True)

        worker_id = row["worker_id"]
        await bot.send_message(
            worker_id,
            f"🔑 Клиент запросил код\n\n📥 Заявка #{order_id}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")]
            ])
        )
        await call.answer("Запрос отправлен 📩")

    @dp.callback_query(F.data.startswith("send_code_"))
    async def send_code(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        order = await db.db_fetchone("SELECT id FROM orders WHERE id=$1 AND worker_id=$2", order_id, call.from_user.id)
        if not order:
            return await call.answer("❌ Нет доступа", show_alert=True)
        await state.set_state(WorkerStates.waiting_for_code)
        await state.update_data(active_order_id=order_id)
        await call.message.answer("🔐 Введите код для клиента одним сообщением:")
        await call.answer()

    @dp.message(WorkerStates.waiting_for_code)
    async def process_code(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("active_order_id")
        code = message.text.strip()

        row = await db.db_fetchone("SELECT user_id, client_message_id FROM orders WHERE id=$1", order_id)
        if not row:
            await state.clear()
            return await message.answer("❌ Ошибка: заявка не найдена")

        user_id = row["user_id"]
        client_msg_id = row["client_message_id"]

        new_msg = await bot.send_message(
            chat_id=user_id,
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"📊 Статус: 🟢 В работе\n\n"
                 f"🔐 Код подтверждения: <code>{code}</code>",
            parse_mode="HTML"
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(chat_id=user_id, message_id=client_msg_id)
        except Exception as e:
            logger.error(f"[process_code] delete error: {e}")
        try:
            await message.delete()
        except:
            pass

        await message.answer(f"✅ Код отправлен клиенту по заявке #{order_id}")
        await state.clear()

    @dp.callback_query(F.data.startswith("worker_confirm_"))
    async def worker_confirm(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        order = await db.db_fetchone(
            "SELECT user_id, amount, client_message_id, total_usdt FROM orders WHERE id=$1 AND worker_id=$2 AND status='IN_PROGRESS'",
            order_id, uid
        )
        if not order:
            return await call.answer("❌ Заявка неактивна или уже подтверждена", show_alert=True)

        total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0.0

        new_msg = await bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {float(order['amount']):.2f} RUB\n\n"
                 f"📊 Статус: 🟡 Ожидание подтверждения\n"
                 f"💸 К списанию: {total_usdt:.4f} USDT\n\n"
                 f"⏳ Пожалуйста, подтвердите оплату",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"client_paid_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(order["user_id"], order["client_message_id"])
        except Exception as e:
            logger.error(f"[worker_confirm] delete error: {e}")

        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(f"⏳ Ожидаем подтверждения от клиента по заявке #{order_id}")
        await call.answer()
