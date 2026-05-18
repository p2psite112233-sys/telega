import logging
from aiogram import types, F, Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)


class DisputeStates(StatesGroup):
    waiting_for_reason = State()
    waiting_for_screenshot = State()
    waiting_for_worker_reason = State()
    waiting_for_worker_screenshot = State()


async def dispute_text(order_id, amount, reason, extra=""):
    # Достаем актуальное состояние заявки из базы
    row = await db.db_fetchone(
        "SELECT bank, card_number, card_expire, card_cvv, sms_code, code_requested FROM orders WHERE id=$1", 
        order_id
    )
    
    # 1. Базовая часть (всегда одинаковая)
    text = (
        f"🆘 <b>ВНИМАНИЕ: ОТКРЫТ СПОР</b>\n\n"
        f"🆔 <b>Заявка:</b> #{order_id}\n"
        f"💰 <b>Сумма:</b> {amount:.2f} RUB\n\n"
    )

    if row:
        # 2. Если воркер отправил реквизиты, добавляем этот блок
        if row["bank"] or row["card_number"]:
            text += (
                f"💳 <b>Реквизиты для оплаты:</b>\n"
                f"🏦 Банк: {row['bank'] or '—'}\n"
                f"💳 Номер карты: <code>{row['card_number'] or '—'}</code>\n"
                f"📅 Срок: {row['card_expire'] or '—'}\n"
                f"🔐 CVV: {row['card_cvv'] or '—'}\n\n"
            )
        
        # 3. Если клиент запросил код
        if row["code_requested"]:
            text += "🔐 Вы запросили код подтверждения, ожидайте.\n\n"
            
        # 4. Если воркер отправил код подтверждения
        elif row["sms_code"]:
            text += f"🔐 Код подтверждения: <code>{row['sms_code']}</code>\n\n"

    # Финальная часть (причина и концовка)
    text += (
        f"{extra}"
        f"📝 <b>Причина:</b> {reason}\n\n"
        f"⏳ <i>Средства заморожены. Администратор подключится в ближайшее время для вынесения вердикта.</i>"
    )
    
    return text


# --- УНИВЕРСАЛЬНАЯ ФУНКЦИЯ ДИНАМИЧЕСКОГО ОБНОВЛЕНИЯ СООБЩЕНИЙ СПОРА ---
async def update_client_dispute_msg(order_id: int, bot: Bot):
    """
    Универсальная функция, которая берет текущее состояние спора из БД,
    формирует актуальный текст и обновляет сообщения у Клиента и Воркера.
    """
    row = await db.db_fetchone(
        "SELECT user_id, worker_id, amount, dispute_reason, client_message_id, worker_message_id, bank, card_number, sms_code, code_requested "
        "FROM orders WHERE id=$1", order_id
    )
    if not row:
        return

    user_id = row["user_id"]
    worker_id = row["worker_id"]
    amount = float(row["amount"])
    reason = row["dispute_reason"] or "Не указана"
    client_msg_id = row["client_message_id"]
    worker_msg_id = row["worker_message_id"]

    # Генерируем новый текст на основе текущего состояния БД
    text = await dispute_text(order_id, amount, reason)

    # 1. ОБНОВЛЕНИЕ КЛИЕНТА
    client_buttons = []
    # Если реквизиты отправлены, но код еще не запрошен и не получен — даем кнопку запроса кода
    if (row["bank"] or row["card_number"]) and not row["code_requested"] and not row["sms_code"]:
        client_buttons.append([InlineKeyboardButton(text="🔐 Запросить код", callback_data=f"request_code_{order_id}")])
    
    client_buttons.extend([
        [InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")],
        [InlineKeyboardButton(text="📄 Написать сообщение", url="https://t.me/usudhsuhd")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
    ])
    
    if client_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=user_id, message_id=client_msg_id, text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=client_buttons), parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass # Игнорируем, если текст не изменился или сообщение удалено

    # 2. ОБНОВЛЕНИЕ ВОРКЕРА
    if worker_id:
        worker_buttons = []
        # Если реквизитов еще нет, воркер может их отправить
        if not row["bank"] and not row["card_number"]:
            worker_buttons.append([InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")])
        # Если клиент запросил код, воркер видит кнопку отправки кода
        if row["code_requested"]:
            worker_buttons.append([InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")])
            
        worker_buttons.extend([
            [InlineKeyboardButton(text="✍️ Написать сообщение", url="https://t.me/usudhsuhd")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
        ])

        if worker_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=worker_id, message_id=worker_msg_id, text=text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=worker_buttons), parse_mode="HTML"
                )
            except TelegramBadRequest:
                pass


def register_dispute(dp: Dispatcher, bot: Bot):

    # --- ОБЩАЯ ОТМЕНА СПОРА ---
    @dp.callback_query(F.data == "dispute_cancel")
    async def dispute_cancel(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await call.answer("Спор отменён", show_alert=True)
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

    # --- СПОР КЛИЕНТА ---
    @dp.callback_query(F.data.startswith("dispute_"))
    async def dispute_start(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[1])
        uid = call.from_user.id
        row = await db.db_fetchone("SELECT status, worker_id FROM orders WHERE id=$1 AND user_id=$2", order_id, uid)
        if not row or row["status"] != "IN_PROGRESS":
            return await call.answer("❌ Спор недоступен для этой заявки", show_alert=True)

        await state.set_state(DisputeStates.waiting_for_reason)
        await state.update_data(dispute_order_id=order_id, dispute_worker_id=row["worker_id"])
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        msg = await call.message.answer(
            f"🆘 <b>Открытие спора по заявке #{order_id}</b>\n\nШаг 1/2: Опишите причину спора — что пошло не так?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dispute_cancel")]
            ])
        )
        await state.update_data(dispute_step1_msg_id=msg.message_id)
        await call.answer()

    @dp.message(DisputeStates.waiting_for_reason, F.text)
    async def dispute_reason(message: types.Message, state: FSMContext):
        data = await state.get_data()
        step1_msg_id = data.get("dispute_step1_msg_id")
        await state.update_data(dispute_reason=message.text)
        await state.set_state(DisputeStates.waiting_for_screenshot)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if step1_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step1_msg_id)
            except TelegramBadRequest:
                pass
        msg = await message.answer(
            "📸 <b>Шаг 2/2: Отправьте скриншот</b>\n\nПрикрепите скрин подтверждения (одним изображением).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dispute_cancel")]
            ])
        )
        await state.update_data(dispute_step2_msg_id=msg.message_id)

    @dp.message(DisputeStates.waiting_for_screenshot, F.photo)
    async def dispute_screenshot(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("dispute_order_id")
        worker_id = data.get("dispute_worker_id")
        reason = data.get("dispute_reason")
        step2_msg_id = data.get("dispute_step2_msg_id")
        uid = message.from_user.id
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
        photo_id = message.photo[-1].file_id

        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if step2_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step2_msg_id)
            except TelegramBadRequest:
                pass

        result = await db.db_execute(
            "UPDATE orders SET status='DISPUTE', dispute_opened_by='client', dispute_reason=$2 WHERE id=$1 AND status='IN_PROGRESS'",
            order_id, reason
        )
        if "UPDATE 0" in result:
            await state.clear()
            return await message.answer("❌ Статус заявки уже изменён.")

        row_order = await db.db_fetchone("SELECT amount, total_usdt, worker_message_id FROM orders WHERE id=$1", order_id)
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt = float(row_order["total_usdt"]) if row_order else 0
        old_worker_msg_id = row_order["worker_message_id"] if row_order else None

        try:
            await bot.send_photo(
                ADMIN_ID, photo=photo_id,
                caption=(
                    f"🆘 <b>СПОР по заявке #{order_id}</b>\n\n"
                    f"⚡️ <b>Открыл:</b> Клиент\n"
                    f"👤 Клиент: {username} (<code>{uid}</code>)\n"
                    f"👷 Воркер: <code>{worker_id}</code>\n"
                    f"💰 Сумма: {amount:.2f} RUB ({total_usdt:.4f} USDT)\n\n"
                    f"📝 <b>Причина:</b> {reason}"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Вернуть клиенту", callback_data=f"dispute_refund_{order_id}")],
                    [InlineKeyboardButton(text="💸 Отправить воркеру", callback_data=f"dispute_pay_worker_{order_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"[dispute_screenshot] admin notify error: {e}")

        # Удаляем старое обычное сообщение воркера, если оно было
        if worker_id and old_worker_msg_id:
            try:
                await bot.delete_message(chat_id=worker_id, message_id=old_worker_msg_id)
            except Exception:
                pass

        if worker_id:
            try:
                worker_text = await dispute_text(order_id, amount, reason)
                new_w_msg = await bot.send_message(
                    worker_id,
                    worker_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✍️ Написать сообщение", url="https://t.me/usudhsuhd")],
                        [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                    ])
                )
                await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_w_msg.message_id, order_id)
            except Exception:
                pass

        await state.clear()
        d_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
        ])
        client_final_text = await dispute_text(order_id, amount, reason)
        new_msg = await message.answer(client_final_text, reply_markup=d_kb, parse_mode="HTML")
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)

    @dp.message(DisputeStates.waiting_for_screenshot)
    async def dispute_screenshot_invalid(message: types.Message):
        await message.answer("⚠️ Пожалуйста, отправьте именно <b>фотографию</b> (скриншот) для подтверждения.")

    # --- --- --- СПОР ВОРКЕРА --- --- ---
    @dp.callback_query(F.data.startswith("worker_dispute_"))
    async def worker_dispute_start(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id
        row = await db.db_fetchone("SELECT status, user_id FROM orders WHERE id=$1 AND worker_id=$2", order_id, uid)
        if not row or row["status"] != "IN_PROGRESS":
            return await call.answer("❌ Спор недоступен", show_alert=True)

        await state.set_state(DisputeStates.waiting_for_worker_reason)
        await state.update_data(dispute_order_id=order_id, dispute_client_id=row["user_id"])
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        msg = await call.message.answer(
            f"🆘 <b>Открытие спора по заявке #{order_id}</b>\n\nШаг 1/2: Опишите причину спора.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dispute_cancel")]
            ])
        )
        await state.update_data(dispute_step1_msg_id=msg.message_id)
        await call.answer()

    @dp.message(DisputeStates.waiting_for_worker_reason, F.text)
    async def worker_dispute_reason(message: types.Message, state: FSMContext):
        data = await state.get_data()
        step1_msg_id = data.get("dispute_step1_msg_id")
        await state.update_data(dispute_reason=message.text)
        await state.set_state(DisputeStates.waiting_for_worker_screenshot)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if step1_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step1_msg_id)
            except TelegramBadRequest:
                pass
        msg = await message.answer(
            "📸 <b>Шаг 2/2: Отправьте скриншот</b>\n\nПрикрепите доказательство (одним изображением).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dispute_cancel")]
            ])
        )
        await state.update_data(dispute_step2_msg_id=msg.message_id)

    @dp.message(DisputeStates.waiting_for_worker_screenshot, F.photo)
    async def worker_dispute_screenshot(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("dispute_order_id")
        client_id = data.get("dispute_client_id")
        reason = data.get("dispute_reason")
        step2_msg_id = data.get("dispute_step2_msg_id")
        uid = message.from_user.id
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
        photo_id = message.photo[-1].file_id

        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        if step2_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step2_msg_id)
            except TelegramBadRequest:
                pass

        result = await db.db_execute(
            "UPDATE orders SET status='DISPUTE', dispute_opened_by='worker', dispute_reason=$2 WHERE id=$1 AND status='IN_PROGRESS'",
            order_id, reason
        )
        if "UPDATE 0" in result:
            await state.clear()
            return await message.answer("❌ Статус заявки уже изменён.")

        row_order = await db.db_fetchone("SELECT amount, total_usdt, client_message_id FROM orders WHERE id=$1", order_id)
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt_val = float(row_order["total_usdt"]) if row_order else 0
        old_client_msg_id = row_order["client_message_id"] if row_order else None

        try:
            await bot.send_photo(
                ADMIN_ID, photo=photo_id,
                caption=(
                    f"🆘 <b>СПОР по заявке #{order_id}</b>\n\n"
                    f"⚡️ <b>Открыл:</b> Воркер\n"
                    f"👷 Воркер: {username} (<code>{uid}</code>)\n"
                    f"👤 Клиент: <code>{client_id}</code>\n"
                    f"💰 Сумма: {amount:.2f} RUB ({total_usdt_val:.4f} USDT)\n\n"
                    f"📝 <b>Причина:</b> {reason}"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Вернуть клиенту", callback_data=f"dispute_refund_{order_id}")],
                    [InlineKeyboardButton(text="💸 Отправить воркеру", callback_data=f"dispute_pay_worker_{order_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"[worker_dispute_screenshot] admin notify error: {e}")

        # Удаляем старое обычное сообщение клиента, если оно было
        if client_id and old_client_msg_id:
            try:
                await bot.delete_message(chat_id=client_id, message_id=old_client_msg_id)
            except Exception:
                pass

        if client_id:
            try:
                client_text = await dispute_text(order_id, amount, reason)
                new_c_msg = await bot.send_message(
                    client_id,
                    client_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")],
                        [InlineKeyboardButton(text="📄 Написать сообщение", url="https://t.me/usudhsuhd")],
                        [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                    ])
                )
                await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_c_msg.message_id, order_id)
            except Exception:
                pass

        await state.clear()
        d_kb_w = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
        ])
        worker_final_text = await dispute_text(order_id, amount, reason)
        new_msg = await message.answer(worker_final_text, reply_markup=d_kb_w, parse_mode="HTML")
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)

    @dp.message(DisputeStates.waiting_for_worker_screenshot)
    async def worker_dispute_screenshot_invalid(message: types.Message):
        await message.answer("⚠️ Пожалуйста, отправьте именно <b>фотографию</b> (скриншот) для подтверждения.")

    # --- РЕШЕНИЕ СПОРА АДМИНОМ ---
    @dp.callback_query(F.data.startswith("dispute_refund_"))
    async def dispute_refund(call: types.CallbackQuery):
        if call.from_user.id != int(ADMIN_ID):
            return await call.answer("❌ Нет прав", show_alert=True)

        order_id = int(call.data.split("_")[-1])
        row = await db.db_fetchone("SELECT user_id, total_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
            
        await db.db_execute("UPDATE orders SET status='CANCELLED' WHERE id=$1", order_id)
        await db.unfreeze_back(row['user_id'], float(row['total_usdt'] or 0))
        
        try:
            await bot.send_message(row['user_id'], f"✅ Спор по заявке #{order_id} решён в вашу пользу. Средства возвращены на баланс.")
        except Exception: pass
        
        try:
            if call.message.photo:
                await call.message.edit_caption(caption=f"✅ Спор #{order_id} закрыт. Средства возвращены клиенту.", reply_markup=None)
            else:
                await call.message.edit_text(f"✅ Спор #{order_id} закрыт. Средства возвращены клиенту.", reply_markup=None)
        except TelegramBadRequest: pass
        await call.answer("✅ Готово!", show_alert=True)

    @dp.callback_query(F.data.startswith("dispute_pay_worker_"))
    async def dispute_pay_worker(call: types.CallbackQuery):
        if call.from_user.id != int(ADMIN_ID):
            return await call.answer("❌ Нет прав", show_alert=True)

        order_id = int(call.data.split("_")[-1])
        row = await db.db_fetchone("SELECT user_id, worker_id, total_usdt, amount_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
            
        await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1", order_id)
        await db.unfreeze_to_worker(row['user_id'], row['worker_id'], float(row['total_usdt'] or 0), float(row['amount_usdt'] or 0))
        
        try:
            await bot.send_message(row['worker_id'], f"✅ Спор по заявке #{order_id} решён в вашу пользу. Средства зачислены.")
        except Exception: pass
        try:
            await bot.send_message(row['user_id'], f"❌ Спор по заявке #{order_id} решён не в вашу пользу.")
        except Exception: pass
        
        try:
            if call.message.photo:
                await call.message.edit_caption(caption=f"✅ Спор #{order_id} закрыт. Средства отправлены воркеру.", reply_markup=None)
            else:
                await call.message.edit_text(f"✅ Спор #{order_id} закрыт. Средства отправлены воркеру.", reply_markup=None)
        except TelegramBadRequest: pass
        await call.answer("✅ Готово!", show_alert=True)

    # --- АДМИН-ПАНЕЛЬ: СПИСКИ ---
    @dp.callback_query(F.data == "adm_disputes")
    async def active_disputes(call: types.CallbackQuery):
        if call.from_user.id != int(ADMIN_ID):
            return await call.answer("❌ Нет прав", show_alert=True)

        disputes = await db.db_fetchall(
            "SELECT id, user_id, worker_id, amount FROM orders WHERE status='DISPUTE' ORDER BY id DESC LIMIT 20"
        )
        if not disputes:
            return await call.answer("✅ Активных споров нет", show_alert=True)
        buttons = []
        for d in disputes:
            buttons.append([InlineKeyboardButton(
                text=f"🆘 #{d['id']} — {float(d['amount']):.0f} RUB | К: {d['user_id']} В: {d['worker_id']}",
                callback_data=f"adm_dispute_info_{d['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")])
        await call.message.edit_text(
            f"🆘 <b>Активные споры</b>\n\nВсего: {len(disputes)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_dispute_info_"))
    async def dispute_info(call: types.CallbackQuery):
        if call.from_user.id != int(ADMIN_ID):
            return await call.answer("❌ Нет прав", show_alert=True)

        order_id = int(call.data.split("_")[-1])
        row = await db.db_fetchone(
            "SELECT id, user_id, worker_id, amount, total_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id
        )
        if not row:
            return await call.answer("❌ Спор не найден или уже решён", show_alert=True)
        text = (
            f"🆘 <b>Спор по заявке #{order_id}</b>\n\n"
            f"👤 Клиент: <code>{row['user_id']}</code>\n"
            f"👷 Воркер: <code>{row['worker_id']}</code>\n"
            f"💰 Сумма: {float(row['amount']):.2f} RUB\n"
            f"💎 Заморожено: {float(row['total_usdt'] or 0):.4f} USDT"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Вернуть клиенту", callback_data=f"dispute_refund_{order_id}")],
            [InlineKeyboardButton(text="💸 Отправить воркеру", callback_data=f"dispute_pay_worker_{order_id}")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_disputes")]
        ])
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer()
