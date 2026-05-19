import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from utils.crypto import crypto_get_rate

logger = logging.getLogger(__name__)


class TransferStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_phone = State()
    waiting_for_bank = State()


def register_transfer(dp, bot):

    @dp.callback_query(F.data == "client_transfer")
    async def transfer_start(call: types.CallbackQuery):
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            "<b>🏦 Перевод на карту</b>\n\n"
            "<blockquote>Выберите тип перевода. Исполнитель переведёт нужную сумму "
            "на указанные реквизиты.</blockquote>\n\n"
            "Выберите тип перевода:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="📲 СБП", callback_data="transfer_sbp"),
                    InlineKeyboardButton(text="💳 По номеру карты", callback_data="transfer_card")
                ],
                [InlineKeyboardButton(text="🏠 Назад", callback_data="client_back_menu")]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data == "transfer_sbp")
    async def transfer_sbp(call: types.CallbackQuery, state: FSMContext):
        try:
            await call.message.delete()
        except:
            pass
        await state.set_state(TransferStates.waiting_for_amount)
        await state.update_data(transfer_type="sbp")
        await call.message.answer(
            "<b>📲 Перевод по СБП</b>\n\n"
            "Введите сумму перевода в рублях.\n\n"
            "Пример: <b>1000</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await call.answer()

    @dp.message(TransferStates.waiting_for_amount)
    async def process_transfer_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            return await message.answer("❌ Введите корректную сумму, например <b>1000</b>", parse_mode="HTML")

        await state.update_data(amount=amount)
        await state.set_state(TransferStates.waiting_for_phone)
        await message.answer(
            "<b>📱 Номер телефона</b>\n\n"
            "Введите номер телефона получателя.\n\n"
            "Пример: <b>+79001234567</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.message(TransferStates.waiting_for_phone)
    async def process_transfer_phone(message: types.Message, state: FSMContext):
        phone = message.text.strip()
        await state.update_data(phone=phone)
        await state.set_state(TransferStates.waiting_for_bank)
        await message.answer(
            "<b>🏦 Банк получателя</b>\n\n"
            "Введите название банка получателя.\n\n"
            "Пример: <b>Сбербанк</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.message(TransferStates.waiting_for_bank)
    async def process_transfer_bank(message: types.Message, state: FSMContext):
        bank = message.text.strip()
        data = await state.get_data()
        amount = data["amount"]
        phone = data["phone"]

        commission = max(round(amount * 0.20, 2), 30)
        total = round(amount + commission, 2)

        rate = await crypto_get_rate()
        total_usdt = round(total / rate, 4)

        await state.update_data(bank=bank, commission=commission, total=total, total_usdt=total_usdt)

        await message.answer(
            f"<b>📋 Подтверждение заявки</b>\n\n"
            f"💸 <b>Тип:</b> Перевод по СБП\n"
            f"💰 <b>Сумма перевода:</b> {amount:.2f} RUB\n"
            f"📱 <b>Номер телефона:</b> <code>{phone}</code>\n"
            f"🏦 <b>Банк:</b> {bank}\n\n"
            f"💼 <b>Комиссия сервиса:</b> {commission:.2f} RUB\n"
            f"💎 <b>Итого к оплате:</b> {total:.2f} RUB (~{total_usdt:.4f} USDT)\n\n"
            f"<blockquote>Нажмите «Подтвердить» для создания заявки.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data="transfer_sbp_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.callback_query(F.data == "transfer_sbp_confirm")
    async def transfer_sbp_confirm(call: types.CallbackQuery, state: FSMContext):
        await call.answer("🚧 Раздел в разработке", show_alert=True)

    @dp.callback_query(F.data == "transfer_card")
    async def transfer_card(call: types.CallbackQuery):
        await call.answer("🚧 Раздел в разработке", show_alert=True)
