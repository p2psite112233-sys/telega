import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import TRANSFER_BANNER_FILE_ID
from utils.crypto import crypto_get_rate
from handlers.common import broadcast_order

logger = logging.getLogger(__name__)


class PhoneStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_phone = State()


def register_phone(dp, bot):

    @dp.callback_query(F.data == "client_phone")
    async def phone_start(call: types.CallbackQuery, state: FSMContext):
        try:
            await call.message.delete()
        except:
            pass
        await state.set_state(PhoneStates.waiting_for_amount)
        msg = await call.message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                "<b>📱 Пополнить номер</b>\n\n"
                "<blockquote>Введите сумму пополнения за один номер телефона. "
                "После этого отправьте номер телефона.</blockquote>\n\n"
                "💸 Сумма за 1 номер: в рублях\n"
                "Пример: <b>500</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)
        await call.answer()

    @dp.message(PhoneStates.waiting_for_amount)
    async def phone_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            return await message.answer("❌ Введите корректную сумму, например <b>500</b>", parse_mode="HTML")

        data = await state.get_data()
        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await state.update_data(amount=amount)
        await state.set_state(PhoneStates.waiting_for_phone)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                "<b>📱 Пополнить номер</b>\n\n"
                "<blockquote>Отправьте номер телефона. "
                "Убедитесь в правильности написания номера.</blockquote>\n\n"
                "Пример: <b>+79001234567</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(PhoneStates.waiting_for_phone)
    async def phone_number(message: types.Message, state: FSMContext):
        phone = message.text.strip()
        data = await state.get_data()
        amount = data["amount"]

        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        commission = max(round(amount * 0.20, 2), 30)
        total = round(amount + commission, 2)
        rate = await crypto_get_rate()
        total_usdt = round(total / rate, 4)

        await state.update_data(phone=phone, commission=commission, total=total, total_usdt=total_usdt)

        await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<b>🧾 Предпросмотр заявки</b>\n\n"
                f"Номер заявки: <code>будет присвоен после подтверждения</code>\n"
                f"Метод: Пополнение номера через банк\n\n"
                f"📱 Номер: <code>{phone}</code>\n"
                f"💰 Пополнить на: {amount:.2f} RUB\n\n"
                f"💼 Комиссия: {commission:.2f} RUB\n"
                f"💎 Итого: {total:.2f} RUB\n"
                f"💸 Списание: {total_usdt:.4f} USDT\n\n"
                f"<blockquote>Нажмите «Подтвердить» для создания заявки.</blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data="phone_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.callback_query(F.data == "phone_confirm")
    async def phone_confirm(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        data = await state.get_data()
        amount = data["amount"]
        phone = data["phone"]
        commission = data["commission"]
        total = data["total"]
        total_usdt = data["total_usdt"]
        amount_usdt = round(total_usdt * amount / total, 4) if total else 0.0

        order_id = await db.create_order_safe(uid, amount, total_usdt, amount_usdt, False)
        if order_id == 0:
            balance = await db.get_balance(uid)
            await state.clear()
            try:
                await call.message.delete()
            except:
                pass
            return await call.message.answer(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💸 Необходимо: {total_usdt:.4f} USDT ({total:.2f} RUB)\n"
                f"💰 Ваш баланс: {balance:.2f} USDT",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )

        await db.db_execute(
            "UPDATE orders SET transfer_type=$1, transfer_phone=$2 WHERE id=$3",
            "phone", phone, order_id
        )
        await state.clear()
        try:
            await call.message.delete()
        except:
            pass

        client_msg = await call.message.answer(
            f"⚡️ <b>#{order_id} · Пополнение номера</b>\n\n"
            f"💰 {amount:.2f} RUB\n\n"
            f"📱 Номер: <code>{phone}</code>\n\n"
            f"🟡 Новая · 👨‍💻 Исполнитель назначается\n\n"
            f"⏳ Ожидайте — скоро свяжемся с вами",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", client_msg.message_id, order_id)

        text_order = (
            f"⚡️ <b>Новая заявка #{order_id} · Пополнение номера</b>\n\n"
            f"💰 {amount:.2f} RUB\n"
            f"📱 <b>Номер:</b> <code>{phone}</code>\n\n"
            f"🔐 <b>Резерв:</b> {total_usdt:.4f} USDT\n"
            f"⏱ Время на принятие: 1500 сек"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
        ])
        await broadcast_order(bot, text_order, kb, order_id=order_id)
        await call.answer()
