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
    """Форматирует информацию о заявке для воркера по твоей математике с минимальной комиссией 30 RUB"""
    # 1. Рублевая математика с защитой от маленьких сумм
    percent = 0.25 if unique else 0.20
    dirty_profit_rub = amount * percent
    
    # Проверка на минимальную комиссию сервиса
    is_min_commission = False
    if dirty_profit_rub < 30.0:
        dirty_profit_rub = 30.0
        is_min_commission = True
        
    total_rub = round(amount + dirty_profit_rub, 2)  # Сколько платит клиент в итоге
    worker_profit_rub = round(dirty_profit_rub * 0.80, 2)  # Заработок воркера (80% от спреда)

    # 2. Перевод в USDT по реальному курсу заявки
    rate = total_rub / total_usdt if total_usdt > 0 else 1.0
    amount_usdt = round(amount / rate, 4)
    worker_profit_usdt = round(worker_profit_rub / rate, 4)
    
    # Итого к начислению воркеру (Тело + 80% от спреда)
    worker_total_payout = amount_usdt + worker_profit_usdt 

    unique_text = "✅ Уникальная карта" if unique else "❌ Обычная карта"
    min_commission_note = " ⚠️ (Мин. комиссия 30 RUB)" if is_min_commission else ""
    
    return (
        f"🆔 <b>ID заявки:</b> #{order_id}\n"
        f"💳 <b>Услуга:</b> Карта под оплату\n"
        f"🃏 {unique_text}\n\n"
        f"💰 <b>Сумма перевода:</b> {amount:.2f} RUB (~{amount_usdt:.4f} USDT)\n"
        f"💎 <b>Клиент оплатит:</b> {total_rub:.2f} RUB{min_commission_note}\n\n"
        f"💵 <b>Ваш чистый заработок:</b> +{worker_profit_rub:.2f} RUB (+{worker_profit_usdt:.4f} USDT)\n"
        f"📈 <b>Итог к зачислению вам:</b> <b>{worker_total_payout:.4f} USDT</b>"
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
                f"<b>👤 Личный профиль клиента</b>\n"
                f"<blockquote>Аккаунт: {username}</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n"
                f"• Баланс: <b>{balance:.2f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Закрыто заявок: <b>{c_done['count']} шт.</b>\n"
                f"• Активно сейчас: <b>{c_active['count']} шт.</b>\n"
                f"• Пополнений баланса: <b>{paid_count['count']} шт.</b>"
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

        # --- Кабинет Воркера ---
        w_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        w_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)

        text = (
            f"🛠 <b>Рабочий кабинет исполнителя</b>\n"
            f"<blockquote>Аккаунт: {username} [{uid}]</blockquote>\n\n"
            f"<b>💼 Ваши финансы</b>\n"
            f"• Доступно к выводу: <b>{balance:.2f} USDT</b>\n\n"
            f"<b>📊 Ваша статистика</b>\n"
            f"• Выполнено заявок: <b>{w_done['count']} шт.</b>\n"
            f"• Сейчас в работе: <b>{w_active['count']} шт.</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
            [InlineKeyboardButton(text="🟢 Активные", callback_data="lk_active"),
             InlineKeyboardButton(text="📚 История", callback_data="lk_history")],
            [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")]
        ])
        await message.answer_photo(
            photo=PROFILE_BANNER_FILE_ID,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )

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

        try:
            await call.message.delete()
        except:
            pass
            
        await call.message.answer(
            f"✅ Вы успешно взяли заказ в работу!\n\n"
            f"{order_info(order_id, amount, total_usdt)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")]
            ]),
            parse_mode="HTML"
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
            return await call.answer("❌ У вас нет сохраненных карт. Сначала добавьте карту в личном кабинете.", show_alert=True)

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

        new_msg = await bot.send_message(
            chat_id=order["user_id"],
            text=f"🎉 Заявка #{order_id}\n\n"
                 f"💳 Услуга: Карта под оплату\n"
                 f"💰 Сумма: {float(order['amount']):.2f} RUB\n\n"
                 f"📊 Статус: 🟢 В работе\n\n"
                 f"💳 <b>Реквизиты для оплаты:</b>\n"
                 f"🏦 Банк: {card['bank']}\n"
                 f"💳 Номер карты: <code>{card['card_number']}</code>\n"
                 f"📅 Срок: {card['expiry']}\n"
                 f"🔐 CVV: <code>{card['cvv']}</code>\n\n"
                 f"⏳ После успешной оплаты запросите код подтверждения",
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
            f"⏳ Ожидаем запрос кода от клиента",
            parse_mode="HTML"
        )

    @dp.callback_query(F.data.startswith("request_code_"))
    async def request_code(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        
        order = await db.db_fetchone(
            "SELECT worker_id, amount, total_usdt, worker_message_id FROM orders WHERE id=$1", 
            order_id
        )
        if not order or order["worker_id"] is None:
            return await call.answer("❌ Нет доступа или исполнитель не назначен", show_alert=True)

        worker_id = order["worker_id"]
        amount = float(order["amount"])
        total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0.0
        old_worker_msg_id = order["worker_message_id"]

        if old_worker_msg_id:
            try:
                await bot.delete_message(chat_id=worker_id, message_id=old_worker_msg_id)
            except:
                pass

        new_worker_msg = await bot.send_message(
            chat_id=worker_id,
            text=f"🔑 <b>Клиент запросил код подтверждения!</b>\n\n"
                 f"{order_info(order_id, amount, total_usdt)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")]
            ]),
            parse_mode="HTML"
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

        if ask_code_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=ask_code_msg_id)
            except:
                pass
        try:
            await message.delete()
        except:
            pass

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

        await message.answer(
            f"✅ Код успешно отправлен клиенту!\n\n"
            f"{order_info(order_id, amount, total_usdt)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order_id}")]
            ]),
            parse_mode="HTML"
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
                 f"⏳ Пожалуйста, подтвердите оплату со своей стороны.",
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
            f"⏳ Запрос на списание отправлен клиенту. Ожидаем подтверждения...\n\n"
            f"{order_info(order_id, float(order['amount']), total_usdt)}",
            parse_mode="HTML"
        )
        await call.answer()
