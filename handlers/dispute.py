import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)


class DisputeStates(StatesGroup):
    waiting_for_reason = State()
    waiting_for_screenshot = State()
    waiting_for_worker_reason = State()
    waiting_for_worker_screenshot = State()


def dispute_text(order_id, amount, reason, extra=""):
    return (
        f"🆘 <b>ВНИМАНИЕ: ОТКРЫТ СПОР</b>\n\n"
        f"🆔 <b>Заявка:</b> #{order_id}\n"
        f"💰 <b>Сумма:</b> {amount:.2f} RUB\n\n"
        f"{extra}"
        f"📝 <b>Причина:</b> {reason}\n\n"
        f"⏳ <i>Средства заморожены. Администратор подключится в ближайшее время для вынесения вердикта.</i>"
    )


def register_dispute(dp, bot):

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
        except:
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

    @dp.callback_query(F.data == "dispute_cancel")
    async def dispute_cancel(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await call.answer("Спор отменён", show_alert=True)
        try:
            await call.message.delete()
        except:
            pass

    @dp.message(DisputeStates.waiting_for_reason)
    async def dispute_reason(message: types.Message, state: FSMContext):
        data = await state.get_data()
        step1_msg_id = data.get("dispute_step1_msg_id")
        await state.update_data(dispute_reason=message.text)
        await state.set_state(DisputeStates.waiting_for_screenshot)
        try:
            await message.delete()
        except:
            pass
        if step1_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step1_msg_id)
            except:
                pass
        msg = await message.answer(
            "📸 <b>Шаг 2/2: Отправьте скриншот</b>\n\nПрикрепите скрин подтверждения (или любое доказательство).",
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
        except:
            pass
        if step2_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step2_msg_id)
            except:
                pass

        result = await db.db_execute(
            "UPDATE orders SET status='DISPUTE', dispute_opened_by='client', dispute_reason=$2 WHERE id=$1 AND status='IN_PROGRESS'",
            order_id, reason
        )
        if "UPDATE 0" in result:
            await state.clear()
            return await message.answer("❌ Статус заявки уже изменён.")

        row_order = await db.db_fetchone("SELECT amount, total_usdt FROM orders WHERE id=$1", order_id)
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt = float(row_order["total_usdt"]) if row_order else 0

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

        if worker_id:
            try:
                await bot.send_message(
                    worker_id,
                    dispute_text(order_id, amount, reason),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✍️ Написать сообщение", url="https://t.me/usudhsuhd")],
                        [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                    ])
                )
            except:
                pass

        await state.clear()
        d_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
        ])
        new_msg = await message.answer(dispute_text(order_id, amount, reason), reply_markup=d_kb, parse_mode="HTML")
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)

    # --- СПОР ВОРКЕРА ---
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
        except:
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

    @dp.message(DisputeStates.waiting_for_worker_reason)
    async def worker_dispute_reason(message: types.Message, state: FSMContext):
        data = await state.get_data()
        step1_msg_id = data.get("dispute_step1_msg_id")
        await state.update_data(dispute_reason=message.text)
        await state.set_state(DisputeStates.waiting_for_worker_screenshot)
        try:
            await message.delete()
        except:
            pass
        if step1_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step1_msg_id)
            except:
                pass
        msg = await message.answer(
            "📸 <b>Шаг 2/2: Отправьте скриншот</b>\n\nПрикрепите доказательство.",
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
        except:
            pass
        if step2_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=step2_msg_id)
            except:
                pass

        result = await db.db_execute(
            "UPDATE orders SET status='DISPUTE', dispute_opened_by='worker', dispute_reason=$2 WHERE id=$1 AND status='IN_PROGRESS'",
            order_id, reason
        )
        if "UPDATE 0" in result:
            await state.clear()
            return await message.answer("❌ Статус заявки уже изменён.")

        row_order = await db.db_fetchone("SELECT amount, total_usdt FROM orders WHERE id=$1", order_id)
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt_val = float(row_order["total_usdt"]) if row_order else 0

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

        if client_id:
            try:
                await bot.send_message(
                    client_id,
                    dispute_text(order_id, amount, reason),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")],
                        [InlineKeyboardButton(text="🔐 Запросить код", callback_data=f"request_code_{order_id}")],
                        [InlineKeyboardButton(text="📄 Написать сообщение", url="https://t.me/usudhsuhd")],
                        [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                    ])
                )
            except:
                pass

        await state.clear()
        d_kb_w = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
            [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
        ])
        new_msg = await message.answer(dispute_text(order_id, amount, reason), reply_markup=d_kb_w, parse_mode="HTML")
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
