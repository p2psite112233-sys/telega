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


def get_type_label(transfer_type):
    if transfer_type == "sbp":
        return "📲 Перевод по СБП"
    elif transfer_type == "card":
        return "💳 Перевод по номеру карты"
    return "💳 Карта под оплату"


def build_dispute_msg(order_id, amount, reason, card_data="", code="", code_requested=False,
                      transfer_type=None, transfer_phone="", transfer_bank="", transfer_name=""):
    extra = ""

    if transfer_type == "sbp":
        extra += f"📱 <b>Телефон:</b> <code>{transfer_phone}</code>\n"
        extra += f"🏦 <b>Банк:</b> {transfer_bank}\n"
        extra += f"👤 <b>Получатель:</b> {transfer_name}\n\n"
    else:
        if card_data:
            extra += f"💳 <b>Реквизиты для оплаты:</b>\n{card_data}\n\n"
        if code_requested and not code:
            extra += f"🔐 <b>Вы запросили код подтверждения, ожидайте.</b>\n⏳ ...\n\n"
        if code:
            extra += f"🔐 <b>Код подтверждения:</b> <code>{code}</code>\n\n"

    return (
        f"🆔 <b>Заявка:</b> #{order_id}\n"
        f"💰 <b>Сумма:</b> {amount:.2f} RUB\n\n"
        f"{extra}"
        f"📝 <b>Причина:</b> {reason}\n\n"
        f"⚠️ По сделке открыт спор"
    )


def dispute_client_kb(order_id, transfer_type=None):
    buttons = []
    if transfer_type == "sbp":
        buttons.append([InlineKeyboardButton(text="✅ Перевод получен", callback_data=f"client_paid_{order_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="💳 Оплата получена", callback_data=f"client_paid_{order_id}")])
        buttons.append([InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")])
    buttons.append([InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")])
    buttons.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")])
    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def update_client_dispute_msg(bot, order_id, user_id, amount, reason, card_data="", code="", code_requested=False):
    row = await db.db_fetchone(
        "SELECT client_message_id, transfer_type, transfer_phone, transfer_bank, transfer_recipient_name FROM orders WHERE id=$1",
        order_id
    )
    transfer_type = row["transfer_type"] if row else None
    transfer_phone = (row["transfer_phone"] or "") if row else ""
    transfer_bank = (row["transfer_bank"] or "") if row else ""
    transfer_name = (row["transfer_recipient_name"] or "") if row else ""

    if row and row["client_message_id"]:
        try:
            await bot.delete_message(chat_id=user_id, message_id=row["client_message_id"])
        except:
            pass
    new_msg = await bot.send_message(
        chat_id=user_id,
        text=build_dispute_msg(order_id, amount, reason, card_data, code, code_requested,
                               transfer_type=transfer_type, transfer_phone=transfer_phone,
                               transfer_bank=transfer_bank, transfer_name=transfer_name),
        parse_mode="HTML",
        reply_markup=dispute_client_kb(order_id, transfer_type=transfer_type)
    )
    await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)


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

        row_order = await db.db_fetchone(
            "SELECT amount, total_usdt, dispute_card_data, dispute_code, transfer_type, transfer_phone, transfer_bank, transfer_recipient_name FROM orders WHERE id=$1",
            order_id
        )
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt = float(row_order["total_usdt"]) if row_order else 0
        card_data = row_order["dispute_card_data"] or ""
        dispute_code = row_order["dispute_code"] or ""
        transfer_type = row_order["transfer_type"]
        transfer_phone = row_order["transfer_phone"] or ""
        transfer_bank = row_order["transfer_bank"] or ""
        transfer_name = row_order["transfer_recipient_name"] or ""

        type_label = get_type_label(transfer_type)
        dispute_text = build_dispute_msg(
            order_id, amount, reason, card_data=card_data, code=dispute_code,
            transfer_type=transfer_type, transfer_phone=transfer_phone,
            transfer_bank=transfer_bank, transfer_name=transfer_name
        )

        try:
            await bot.send_photo(
                ADMIN_ID, photo=photo_id,
                caption=(
                    f"🆘 <b>СПОР по заявке #{order_id}</b>\n\n"
                    f"⚡️ <b>Открыл:</b> Клиент\n"
                    f"👤 Клиент: {username} (<code>{uid}</code>)\n"
                    f"👷 Воркер: <code>{worker_id}</code>\n"
                    f"💳 <b>Тип:</b> {type_label}\n"
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
                worker_kb_buttons = []
                if transfer_type == "sbp":
                    worker_kb_buttons.append([InlineKeyboardButton(text="✅ Перевод выполнен", callback_data=f"sbp_done_{order_id}")])
                else:
                    if not card_data:
                        worker_kb_buttons.append([InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")])
                    worker_kb_buttons.append([InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")])
                worker_kb_buttons.append([InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")])
                worker_kb_buttons.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")])
                worker_kb_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
                await bot.send_message(
                    worker_id, dispute_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=worker_kb_buttons)
                )
            except:
                pass

        await state.clear()
        new_msg = await message.answer(
            dispute_text,
            reply_markup=dispute_client_kb(order_id, transfer_type=transfer_type),
            parse_mode="HTML"
        )
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

        row_order = await db.db_fetchone(
            "SELECT amount, total_usdt, dispute_card_data, dispute_code, transfer_type, transfer_phone, transfer_bank, transfer_recipient_name FROM orders WHERE id=$1",
            order_id
        )
        amount = float(row_order["amount"]) if row_order else 0
        total_usdt_val = float(row_order["total_usdt"]) if row_order else 0
        card_data = row_order["dispute_card_data"] or ""
        dispute_code = row_order["dispute_code"] or ""
        transfer_type = row_order["transfer_type"]
        transfer_phone = row_order["transfer_phone"] or ""
        transfer_bank = row_order["transfer_bank"] or ""
        transfer_name = row_order["transfer_recipient_name"] or ""

        type_label = get_type_label(transfer_type)
        dispute_text = build_dispute_msg(
            order_id, amount, reason, card_data=card_data, code=dispute_code,
            transfer_type=transfer_type, transfer_phone=transfer_phone,
            transfer_bank=transfer_bank, transfer_name=transfer_name
        )

        try:
            await bot.send_photo(
                ADMIN_ID, photo=photo_id,
                caption=(
                    f"🆘 <b>СПОР по заявке #{order_id}</b>\n\n"
                    f"⚡️ <b>Открыл:</b> Воркер\n"
                    f"👷 Воркер: {username} (<code>{uid}</code>)\n"
                    f"👤 Клиент: <code>{client_id}</code>\n"
                    f"💳 <b>Тип:</b> {type_label}\n"
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
                new_client_msg = await bot.send_message(
                    client_id, dispute_text,
                    parse_mode="HTML",
                    reply_markup=dispute_client_kb(order_id, transfer_type=transfer_type)
                )
                await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_client_msg.message_id, order_id)
            except:
                pass

        await state.clear()

        worker_kb_buttons2 = []
        if transfer_type == "sbp":
            worker_kb_buttons2.append([InlineKeyboardButton(text="✅ Перевод выполнен", callback_data=f"sbp_done_{order_id}")])
        else:
            if not card_data:
                worker_kb_buttons2.append([InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")])
            worker_kb_buttons2.append([InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")])
        worker_kb_buttons2.append([InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")])
        worker_kb_buttons2.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")])
        worker_kb_buttons2.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
        new_msg = await message.answer(
            dispute_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=worker_kb_buttons2),
            parse_mode="HTML"
        )
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)

    @dp.callback_query(F.data == "noop")
    async def noop_handler(call: types.CallbackQuery):
        await call.answer()

    # --- РЕШЕНИЕ СПОРА АДМИНОМ ---
    @dp.callback_query(F.data.startswith("dispute_refund_"))
    async def dispute_refund(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        row = await db.db_fetchone("SELECT user_id, total_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
        await db.db_execute("UPDATE orders SET status='CANCELLED' WHERE id=$1", order_id)
        await db.unfreeze_back(row['user_id'], float(row['total_usdt'] or 0))
        try:
            await bot.send_message(row['user_id'], f"✅ Спор по заявке #{order_id} решён в вашу пользу. Средства возвращены на баланс.")
        except: pass
        try:
            await call.message.delete()
        except: pass
        await call.message.answer(f"✅ Спор #{order_id} — средства возвращены клиенту.")
        await call.answer("✅ Готово!", show_alert=True)

    @dp.callback_query(F.data.startswith("dispute_pay_worker_"))
    async def dispute_pay_worker(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[3])
        row = await db.db_fetchone("SELECT user_id, worker_id, total_usdt, amount_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
        await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1", order_id)
        await db.unfreeze_to_worker(row['user_id'], row['worker_id'], float(row['total_usdt'] or 0), float(row['amount_usdt'] or 0))
        try:
            await bot.send_message(row['worker_id'], f"✅ Спор по заявке #{order_id} решён в вашу пользу. Средства зачислены.")
        except: pass
        try:
            await bot.send_message(row['user_id'], f"❌ Спор по заявке #{order_id} решён не в вашу пользу.")
        except: pass
        try:
            await call.message.delete()
        except: pass
        await call.message.answer(f"✅ Спор #{order_id} — средства отправлены воркеру.")
        await call.answer("✅ Готово!", show_alert=True)

    @dp.callback_query(F.data == "adm_disputes")
    async def active_disputes(call: types.CallbackQuery):
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
        order_id = int(call.data.split("_")[3])
        row = await db.db_fetchone(
            "SELECT id, user_id, worker_id, amount, total_usdt, transfer_type FROM orders WHERE id=$1 AND status='DISPUTE'", order_id
        )
        if not row:
            return await call.answer("❌ Спор не найден или уже решён", show_alert=True)
        type_label = get_type_label(row["transfer_type"])
        text = (
            f"🆘 <b>Спор по заявке #{order_id}</b>\n\n"
            f"👤 Клиент: <code>{row['user_id']}</code>\n"
            f"👷 Воркер: <code>{row['worker_id']}</code>\n"
            f"💳 Тип: {type_label}\n"
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
