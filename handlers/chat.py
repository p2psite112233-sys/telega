import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db

logger = logging.getLogger(__name__)


def order_info(order_id: int, amount: float, total_usdt: float, unique: bool = False) -> str:
    commission = max(round(amount * (0.25 if unique else 0.20), 2), 30)
    total_rub = round(amount + commission, 2)
    amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
    commission_usdt = round(total_usdt - amount_usdt, 4)
    worker_net_usdt = round(commission_usdt * 0.8, 4)
    worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)
    unique_text = f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Уникальная" if unique else f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Обычная"
    return (
        f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
        f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB · {unique_text}\n\n"
        f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Детали сделки:\n"
        f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
        f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
        f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Итого к зачислению: {worker_total_usdt:.4f} USDT\n"
        f"▸ <tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> Средства зарезервированы"
    )
    
def order_info_transfer(order_id, amount, total_usdt, transfer_type, phone_or_card, bank="", name=""):
    commission = max(round(amount * 0.20, 2), 30)
    total_rub = round(amount + commission, 2)
    amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
    commission_usdt = round(total_usdt - amount_usdt, 4)
    worker_net_usdt = round(commission_usdt * 0.8, 4)
    worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)

    if transfer_type == "sbp":
        type_label = "Перевод по СБП"
        req = f"▸ 📱 <code>{phone_or_card}</code>"
        extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n"
    elif transfer_type == "card":
        type_label = "Перевод по номеру карты"
        req = f"▸ 💳 <code>{phone_or_card}</code>"
        extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n"
    else:  # phone
        type_label = "Пополнение номера"
        req = f"▸ 📱 <code>{phone_or_card}</code>"
        extra = ""

    return (
        f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · {type_label}</b>\n\n"
        f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
        f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Реквизиты:\n"
        f"{req}\n"
        f"{extra}\n"
        f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Детали сделки:\n"
        f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
        f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
        f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> К зачислению: {worker_total_usdt:.4f} USDT"
    )


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
        row = await db.db_fetchone("SELECT user_id, worker_id FROM orders WHERE id=$1", order_id)
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
            f"<tg-emoji emoji-id='5443127283898405358'>📤</tg-emoji> <b>Введите сообщение по сделке #{order_id}.</b>",
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
        row = await db.db_fetchone("SELECT user_id, worker_id FROM orders WHERE id=$1", order_id)
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

    @dp.callback_query(F.data.startswith("chat_back_"), ChatStates.waiting_for_message)
    async def chat_back(call: types.CallbackQuery, state: FSMContext):
        await call.answer()
        data = await state.get_data()
        prompt_msg_id = data.get("chat_prompt_msg_id")
        await state.clear()
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        try:
            await call.message.delete()
        except:
            pass
        if prompt_msg_id:
            try:
                await bot.delete_message(chat_id=call.message.chat.id, message_id=prompt_msg_id)
            except:
                pass

        row = await db.db_fetchone("SELECT user_id, worker_id, status FROM orders WHERE id=$1", order_id)
        if not row:
            return

        status = row["status"]
        if status in ("DONE", "CANCELLED"):
            status_text = "✅ Завершена" if status == "DONE" else "❌ Отменена"
            await bot.send_message(
                uid,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Заявка #{order_id} · {status_text}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu" if uid == row["user_id"] else "lk_home")]
                ])
            )
            return

        if uid == row["worker_id"]:
            await bot.send_message(uid, f"<tg-emoji emoji-id='5197269100878907942'>📄</tg-emoji> Открываю заявку...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=f"chat_view_order_{order_id}")]
            ]))
        else:
            await bot.send_message(uid, f"<tg-emoji emoji-id='5197269100878907942'>📄</tg-emoji> Открываю заявку...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=f"chat_view_client_order_{order_id}")]
            ]))

    @dp.callback_query(F.data.startswith("chat_view_client_order_"))
    async def chat_view_client_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[4])
        uid = call.from_user.id

        try:
            await call.message.delete()
        except:
            pass

        row = await db.db_fetchone(
            "SELECT amount, total_usdt, dispute_card_data, dispute_code, dispute_reason, code_requested, status, "
            "transfer_type, transfer_phone, transfer_bank, transfer_recipient_name "
            "FROM orders WHERE id=$1 AND user_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        amount = float(row["amount"])
        total_usdt = float(row["total_usdt"] or 0)
        card_data = row["dispute_card_data"] or ""
        code = row["dispute_code"] or ""
        status = row["status"]
        transfer_type = row["transfer_type"]

        # Завершена
        if status == "DONE":
            client_balance_new = await db.get_balance(uid)
            if transfer_type == "sbp":
                phone_or_card = row["transfer_phone"] or ""
                bank = row["transfer_bank"] or ""
                name = row["transfer_recipient_name"] or ""
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по СБП</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                    f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{phone_or_card}</code>\n"
                    f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                    f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                    f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!\n"
                    f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT"
                )
            elif transfer_type == "card":
                phone_or_card = row["transfer_phone"] or ""
                bank = row["transfer_bank"] or ""
                name = row["transfer_recipient_name"] or ""
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по номеру карты</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                    f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{phone_or_card}</code>\n"
                    f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                    f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                    f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!\n"
                    f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT"
                )
            elif transfer_type == "phone":
                phone = row["transfer_phone"] or ""
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n"
                    f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> Номер: <code>{phone}</code>\n\n"
                    f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!\n"
                    f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT"
                )
            else:
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Итог сделки:\n"
                    f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Оплата подтверждена\n"
                    f"▸ <tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Остаток баланса: {client_balance_new:.2f} USDT\n\n"
                    f"<tg-emoji emoji-id='5406926593698312391'>🎉</tg-emoji> Спасибо за использование Send$Paid!"
                )
            await bot.send_message(uid, text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ]))
            return await call.answer()

        # Отменена
        if status == "CANCELLED":
            await bot.send_message(uid,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id}</b> · <tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Заявка отменена",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ]))
            return await call.answer()

        # Спор
        if status == "DISPUTE":
            from handlers.dispute import build_dispute_msg, dispute_client_kb
            reason = row["dispute_reason"] or "—"
            code_req = row.get("code_requested") or False
            await bot.send_message(
                uid,
                build_dispute_msg(order_id, amount, reason, card_data=card_data, code=code, code_requested=code_req,
                                  transfer_type=transfer_type,
                                  transfer_phone=row["transfer_phone"] or "",
                                  transfer_bank=row["transfer_bank"] or "",
                                  transfer_name=row["transfer_recipient_name"] or ""),
                parse_mode="HTML",
                reply_markup=dispute_client_kb(order_id, transfer_type=transfer_type)
            )
            return await call.answer()

        # phone — в работе
        if transfer_type == "phone":
            phone = row["transfer_phone"] or ""
            text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n"
                f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> Номер: <code>{phone}</code>\n\n"
                f"<tg-emoji emoji-id='5278611606756942667'>🟢</tg-emoji> В работе · <tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте пополнения"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"client_paid_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return await call.answer()

        # СБП или перевод по карте — в работе
        if transfer_type in ("sbp", "card"):
            phone_or_card = row["transfer_phone"] or ""
            bank = row["transfer_bank"] or ""
            name = row["transfer_recipient_name"] or ""
            if transfer_type == "sbp":
                type_label = "Перевод по СБП"
                req_line = f"▸ 📱 <code>{phone_or_card}</code>"
            else:
                type_label = "Перевод по номеру карты"
                req_line = f"▸ 💳 <code>{phone_or_card}</code>"
            text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · {type_label}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводим:\n"
                f"{req_line}\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                f"<tg-emoji emoji-id='5278611606756942667'>🟢</tg-emoji> В работе · <tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте перевода от исполнителя"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Перевод получен", callback_data=f"client_paid_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return await call.answer()

        # Карта под оплату — в работе
        card_block = f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Реквизиты для оплаты:\n{card_data}\n\n" if card_data else ""
        code_block = f"<tg-emoji emoji-id='5397782960512444700'>🔑</tg-emoji> Код подтверждения: <code>{code}</code>\n\n" if code else ""
        if code:
            footer = "<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Нажмите кнопку ниже, если оплата прошла успешно"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"client_paid_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        elif card_data:
            footer = "<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Запросите код для успешной оплаты"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        else:
            footer = "<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте реквизитов для оплаты"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        text = (
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
            f"{card_block}{code_block}{footer}"
        )
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("chat_view_order_"))
    async def chat_view_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[3])
        uid = call.from_user.id

        try:
            await call.message.delete()
        except:
            pass

        row = await db.db_fetchone(
            "SELECT amount, total_usdt, dispute_card_data, dispute_code, dispute_reason, code_requested, status, is_unique, "
            "transfer_type, transfer_phone, transfer_bank, transfer_recipient_name "
            "FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        amount = float(row["amount"])
        total_usdt = float(row["total_usdt"] or 0)
        card_data = row["dispute_card_data"] or ""
        code = row["dispute_code"] or ""
        reason = row["dispute_reason"] or "—"
        code_req_flag = row["code_requested"] or False
        status = row["status"]
        is_unique = row["is_unique"] or False
        transfer_type = row["transfer_type"]

        # Завершена
        if status == "DONE":
            commission = max(round(amount * 0.20, 2), 30)
            total_rub = round(amount + commission, 2)
            amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
            commission_usdt = round(total_usdt - amount_usdt, 4)
            worker_net_usdt = round(commission_usdt * 0.8, 4)
            worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)

            if transfer_type == "sbp":
                phone_or_card = row["transfer_phone"] or ""
                bank = row["transfer_bank"] or ""
                name = row["transfer_recipient_name"] or ""
               text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по СБП</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                    f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{phone_or_card}</code>\n"
                    f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                    f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                    f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                    f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                    f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
                )
            elif transfer_type == "card":
                phone_or_card = row["transfer_phone"] or ""
                bank = row["transfer_bank"] or ""
                name = row["transfer_recipient_name"] or ""
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по номеру карты</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                    f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{phone_or_card}</code>\n"
                    f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                    f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                    f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                    f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                    f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
                )
            elif transfer_type == "phone":
                phone = row["transfer_phone"] or ""
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n"
                    f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> Номер: <code>{phone}</code>\n\n"
                    f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                    f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                    f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
                )
            else:
                unique_text = f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Уникальная" if is_unique else f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Обычная"
                text = (
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB · {unique_text}\n\n"
                    f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                    f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                    f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                    f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
                )
            await bot.send_message(uid, text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ]))
            return await call.answer()

        # Отменена
        if status == "CANCELLED":
            await bot.send_message(uid,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id}</b> · <tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Заявка отменена",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ]))
            return await call.answer()

        # Спор
        if status == "DISPUTE":
            from handlers.dispute import build_dispute_msg
            worker_kb = []
            if transfer_type in ("sbp", "card", "phone"):
                worker_kb.append([InlineKeyboardButton(text="✅ Выполнено", callback_data=f"sbp_done_{order_id}")])
            else:
                if not card_data:
                    worker_kb.append([InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")])
                worker_kb.append([InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")])
            worker_kb.append([InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")])
            worker_kb.append([InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")])
            worker_kb.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(
                uid,
                build_dispute_msg(order_id, amount, reason, card_data=card_data, code=code,
                                  code_requested=(code_req_flag and not code),
                                  transfer_type=transfer_type,
                                  transfer_phone=row["transfer_phone"] or "",
                                  transfer_bank=row["transfer_bank"] or "",
                                  transfer_name=row["transfer_recipient_name"] or ""),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=worker_kb)
            )
            return await call.answer()

        # phone — в работе для воркера
        if transfer_type == "phone":
            phone = row["transfer_phone"] or ""
            commission = max(round(amount * 0.20, 2), 30)
            total_rub = round(amount + commission, 2)
            amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
            commission_usdt = round(total_usdt - amount_usdt, 4)
            worker_net_usdt = round(commission_usdt * 0.8, 4)
            worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)
            text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Реквизиты:\n"
                f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{phone}</code>\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Детали сделки:\n"
                f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> К зачислению: {worker_total_usdt:.4f} USDT"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"sbp_done_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return await call.answer()

        # СБП или перевод по карте — в работе
        if transfer_type in ("sbp", "card"):
            phone_or_card = row["transfer_phone"] or ""
            bank = row["transfer_bank"] or ""
            name = row["transfer_recipient_name"] or ""
            text = order_info_transfer(order_id, amount, total_usdt, transfer_type, phone_or_card, bank, name)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Перевод выполнен", callback_data=f"sbp_done_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return await call.answer()

        # Карта под оплату — в работе
        if code:
           text = (
                f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Статус:\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Код отправлен\n"
                f"▸ <tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ждём подтверждения клиента"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        elif code_req_flag:
            text = (
                f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Статус:\n"
                f"▸ <tg-emoji emoji-id='5397782960512444700'>🔑</tg-emoji> Клиент запросил код"
        )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        elif card_data:
            text = (
                f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Статус:\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Реквизиты отправлены\n"
                f"▸ <tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ждём запрос кода"
        )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        else:
            text = f"{order_info(order_id, amount, total_usdt, unique=is_unique)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
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

        row = await db.db_fetchone("SELECT user_id, worker_id FROM orders WHERE id=$1", order_id)
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

        try:
            if photo_id:
                await bot.send_photo(
                    recipient_id, photo=photo_id,
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

        view_cb = f"chat_view_order_{order_id}" if role == "worker" else f"chat_view_client_order_{order_id}"
        await state.clear()
        await message.answer(
            f"<tg-emoji emoji-id='5443127283898405358'>📤</tg-emoji> Сообщение отправлено.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=view_cb)]
            ])
        )
