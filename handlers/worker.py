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

def order_info(order_id: int, amount: float, total_usdt: float, unique: bool = False) -> str:
    """Форматирует информацию о заявке для воркера"""
    total_rub = round(amount * (1.25 if unique else 1.20), 2)
    worker_usdt = round(total_usdt * 0.8, 4)
    unique_text = "✅ Уникальная карта" if unique else "❌ Обычная карта"
    return (
        f"🆔 ID: #{order_id}\n"
        f"💳 Услуга: Карта под оплату\n"
        f"💰 Сумма: {amount:.2f} RUB\n"
        f"💲 Резерв: {total_usdt:.4f} USDT\n"
        f"💎 К оплате: {total_rub:.2f} RUB\n"
        f"🃏 {unique_text}\n"
        f"💵 Ваш заработок: {worker_usdt:.4f} USDT"
    )


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
                f"• Баланс: <b>{balance:.2f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
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
            f"• Доступно: <b>{balance:.2f} USDT</b>\n\n"
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

        order = await db.db_fetchone("SELECT user_id, amount, client_message_id, total_usdt FROM orders WHERE id=$1", order_id)

        amount = float(order["amount"])
        total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0.0

        # Сначала отправляем новое сообщение клиенту, потом удаляем старое
        new_msg = await bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {amount:.2f} RUB\n\n"
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

        # Удаляем старое сообщение у воркера и отправляем новое с деталями
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            f"✅ Вы взяли заказ #{order_id}\n\n"
            f"{order_info(order_id, amount, total_usdt)}",
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
        try:
            await call.message.delete()
        except:
            pass
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
            "SELECT user_id, amount, client_message_id, total_usdt FROM orders WHERE id=$1 AND worker_id=$2",
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
                 f"⏳ Запросите код для успешной оплаты",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")],
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(order["user_id"], order["client_message_id"])
        except Exception as e:
            logger.error(f"[req_card] delete error: {e}")

        await call.answer("✅ Реквизиты отправлены клиенту", show_alert=True)
        try:
            await call.message.delete()
        except:
            pass
        total_usdt = float(order["total_usdt"]) if order.get("total_usdt") else 0.0
        await call.message.answer(
            f"✅ Реквизиты по заявке #{order_id} отправлены\n\n"
            f"{order_info(order_id, float(order['amount']), total_usdt)}\n\n"
            f"⏳ Ожидаем запрос кода от клиента"
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
        order = await db.db_fetchone(
            "SELECT amount, total_usdt FROM orders WHERE id=$1",
            order_id
        )
        amount = float(order["amount"]) if order else 0.0
        total_usdt = float(order["total_usdt"]) if order and order["total_usdt"] else 0.0

        # Удаляем старое сообщение воркера и отправляем новое с инфо
        try:
            # Получаем worker_message_id чтобы удалить
            w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
            if w_row and w_row["worker_message_id"]:
                await bot.delete_message(chat_id=worker_id, message_id=w_row["worker_message_id"])
        except:
            pass

        new_worker_msg = await bot.send_message(
            worker_id,
            f"🔑 Клиент запросил код\n\n"
            f"{order_info(order_id, amount, total_usdt)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_worker_msg.message_id, order_id)
        await call.answer("Запрос отправлен 📩")

    @dp.callback_query(F.data.startswith("send_code_"))
    async def send_code(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        order = await db.db_fetchone("SELECT id FROM orders WHERE id=$1 AND worker_id=$2", order_id, call.from_user.id)
        if not order:
            return await call.answer("❌ Нет доступа", show_alert=True)
        await state.set_state(WorkerStates.waiting_for_code)
        try:
            await call.message.delete()
        except:
            pass
        msg = await call.message.answer("🔐 Введите код для клиента одним сообщением:")
        await state.update_data(active_order_id=order_id, ask_code_msg_id=msg.message_id)
        await call.answer()

    @dp.message(WorkerStates.waiting_for_code)
    async def process_code(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("active_order_id")
        ask_code_msg_id = data.get("ask_code_msg_id")
        code = message.text.strip()

        row = await db.db_fetchone("SELECT user_id, amount, total_usdt, client_message_id FROM orders WHERE id=$1", order_id)
        if not row:
            await state.clear()
            return await message.answer("❌ Ошибка: заявка не найдена")

        user_id = row["user_id"]
        amount = float(row["amount"])
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        client_msg_id = row["client_message_id"]

        # Удаляем сообщение "Введите код" и введённый код
        if ask_code_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=ask_code_msg_id)
            except:
                pass
        try:
            await message.delete()
        except:
            pass

        # Клиенту — инфо о заявке + код, без кнопки отмены
        new_msg = await bot.send_message(
            chat_id=user_id,
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"🆔 ID: #{order_id}\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {amount:.2f} RUB\n\n"
                 f"📊 Статус: 🟢 В работе\n\n"
                 f"🔐 Код подтверждения: <code>{code}</code>",
            parse_mode="HTML"
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
        try:
            await bot.delete_message(chat_id=user_id, message_id=client_msg_id)
        except Exception as e:
            logger.error(f"[process_code] delete error: {e}")

        # Воркеру — инфо о заявке + кнопка подтверждения
        await message.answer(
            f"✅ Код отправлен клиенту\n\n"
            f"{order_info(order_id, amount, total_usdt)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order_id}")]
            ])
        )
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

        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            f"⏳ Ожидаем подтверждения от клиента\n\n"
            f"{order_info(order_id, float(order['amount']), total_usdt)}"
        )
        await call.answer()
