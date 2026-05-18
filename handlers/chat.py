import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db

logger = logging.getLogger(__name__)


class ChatStates(StatesGroup):
    waiting_for_message = State()


def chat_msg_text(order_id, text):
    return (
        f"📥 Сообщение по сделке #{order_id}:\n\n"
        f"<i>⚠️ <b>Не используйте</b> платёжные реквизиты или контактную информацию из этого сообщения.</i>\n\n"
        f"<blockquote>{text}</blockquote>"
    )


def chat_msg_kb(order_id, is_worker=False):
    view_cb = f"chat_view_order_{order_id}" if is_worker else f"chat_view_client_order_{order_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"chat_reply_{order_id}")],
        [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=view_cb)]
    ])


def register_chat(dp, bot):

    @dp.callback_query(F.data.startswith("chat_write_"))
    async def chat_write(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        # Определяем кто пишет — клиент или воркер
        row = await db.db_fetchone(
            "SELECT user_id, worker_id FROM orders WHERE id=$1", order_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        if uid == row["user_id"]:
            role = "client"
        elif uid == row["worker_id"]:
            role = "worker"
        else:
            return await call.answer("❌ Нет доступа", show_alert=True)

        await state.set_state(ChatStates.waiting_for_message)
        await state.update_data(chat_order_id=order_id, chat_role=role)

        try:
            await call.message.delete()
        except:
            pass

        msg = await call.message.answer(
            f"📤 <b>Введите сообщение по сделке #{order_id}.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data=f"chat_back_{order_id}")]
            ])
        )
        await state.update_data(chat_prompt_msg_id=msg.message_id)
        await call.answer()

    @dp.callback_query(F.data.startswith("chat_reply_"))
    async def chat_reply(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, worker_id FROM orders WHERE id=$1", order_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        if uid == row["user_id"]:
            role = "client"
        elif uid == row["worker_id"]:
            role = "worker"
        else:
            return await call.answer("❌ Нет доступа", show_alert=True)

        await state.set_state(ChatStates.waiting_for_message)
        await state.update_data(chat_order_id=order_id, chat_role=role)

        try:
            await call.message.delete()
        except:
            pass

        msg = await call.message.answer(
            f"📤 <b>Введите сообщение по сделке #{order_id}.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data=f"chat_back_{order_id}")]
            ])
        )
        await state.update_data(chat_prompt_msg_id=msg.message_id)
        await call.answer()

    @dp.callback_query(F.data.startswith("chat_view_client_order_"))
    async def chat_view_client_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[4])
        uid = call.from_user.id
        row = await db.db_fetchone(
            "SELECT amount, dispute_card_data, dispute_code, dispute_reason, code_requested, status FROM orders WHERE id=$1 AND user_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        amount = float(row["amount"])
        card_data = row["dispute_card_data"] or ""
        code = row["dispute_code"] or ""
        status = row["status"]

        # Если спор — показываем сообщение спора
        if status == "DISPUTE":
            from handlers.dispute import build_dispute_msg, dispute_client_kb
            reason = row["dispute_reason"] or "—"
            code_req = row.get("code_requested") or False
            await bot.send_message(
                uid,
                build_dispute_msg(order_id, amount, reason, card_data=card_data, code=code, code_requested=code_req),
                parse_mode="HTML",
                reply_markup=dispute_client_kb(order_id)
            )
            return await call.answer()

        card_block = f"\n💳 Реквизиты для оплаты:\n{card_data}\n\n" if card_data else ""
        code_block = f"🔐 Код подтверждения: <code>{code}</code>\n\n" if code else ""

        if code:
            footer = "⏳ Нажмите кнопку ниже, если оплата прошла успешно"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"client_paid_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        elif card_data:
            footer = "⏳ Запросите код для успешной оплаты"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        else:
            footer = "⏳ Ожидайте реквизитов для оплаты"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])

        text = (
            f"🎉 Заявка #{order_id}\n\n"
            f"🆔 ID: #{order_id}\n"
            f"💳 Услуга: Карта под оплату\n"
            f"💰 Сумма: {amount:.2f} RUB\n\n"
            f"📊 Статус: 🟢 В работе\n"
            f"{card_block}"
            f"{code_block}"
            f"{footer}"
        )
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("chat_view_order_"))
    async def chat_view_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[3])
        uid = call.from_user.id
        row = await db.db_fetchone(
            "SELECT amount, total_usdt, dispute_card_data, dispute_code, dispute_reason, code_requested, status FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        from handlers.worker import order_info
        amount = float(row["amount"])
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        card_data = row["dispute_card_data"] or ""
        code = row["dispute_code"] or ""
        code_requested = row["code_requested"] or False
        status = row["status"]

        # Если спор — показываем сообщение спора
        if status == "DISPUTE":
            from handlers.dispute import build_dispute_msg
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            reason = row["dispute_reason"] or "—"
            worker_kb = []
            if not card_data:
                worker_kb.append([InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")])
            worker_kb.append([InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")])
            worker_kb.append([InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")])
            worker_kb.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")])
            worker_kb.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(
                uid,
                build_dispute_msg(order_id, amount, reason, card_data=card_data, code=code, code_requested=(code_requested and not code)),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=worker_kb)
            )
            return await call.answer()

        # Определяем состояние и формируем текст + кнопки
        if code:
            text = f"✅ Код отправлен клиенту\n\n{order_info(order_id, amount, total_usdt)}\n\n⏳ Ожидаем подтверждения от клиента"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        elif code_requested:
            text = f"🔑 Клиент запросил код\n\n{order_info(order_id, amount, total_usdt)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        elif card_data:
            text = f"✅ Реквизиты по заявке #{order_id} отправлены\n\n{order_info(order_id, amount, total_usdt)}\n\n⏳ Ожидаем запрос кода от клиента"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        else:
            text = f"✅ Вы взяли заказ #{order_id}\n\n{order_info(order_id, amount, total_usdt)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])

        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("chat_back_"))
    async def chat_back(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        try:
            await call.message.delete()
        except:
            pass
        await call.answer()

    @dp.message(ChatStates.waiting_for_message, F.text | F.photo)
    async def chat_send(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("chat_order_id")
        role = data.get("chat_role")
        prompt_msg_id = data.get("chat_prompt_msg_id")
        text = message.text
        photo_id = message.photo[-1].file_id if message.photo else None

        if not text and not photo_id:
            return await message.answer("❌ Отправьте текст или фото.")

        row = await db.db_fetchone(
            "SELECT user_id, worker_id FROM orders WHERE id=$1", order_id
        )
        if not row:
            await state.clear()
            return await message.answer("❌ Заявка не найдена.")

        try:
            await message.delete()
        except:
            pass
        if prompt_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
            except:
                pass

        if role == "client":
            recipient_id = row["worker_id"]
            is_recipient_worker = True
        else:
            recipient_id = row["user_id"]
            is_recipient_worker = False

        # Отправляем получателю
        try:
            if photo_id:
                await bot.send_photo(
                    recipient_id,
                    photo=photo_id,
                    caption=chat_msg_text(order_id, text or ""),
                    parse_mode="HTML",
                    reply_markup=chat_msg_kb(order_id, is_worker=is_recipient_worker)
                )
            else:
                await bot.send_message(
                    recipient_id,
                    chat_msg_text(order_id, text),
                    parse_mode="HTML",
                    reply_markup=chat_msg_kb(order_id, is_worker=is_recipient_worker)
                )
        except Exception as e:
            logger.error(f"[chat_send] send error: {e}")

        await message.answer("📤 Сообщение отправлено.")
        await state.clear()
