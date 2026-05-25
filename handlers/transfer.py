import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import TRANSFER_BANNER_FILE_ID, TRANSFER_SELECT_BANNER_FILE_ID
from utils.crypto import crypto_get_rate
from handlers.common import broadcast_order

logger = logging.getLogger(__name__)


class TransferStates(StatesGroup):
    # СБП
    waiting_for_amount = State()
    waiting_for_phone = State()
    waiting_for_bank = State()
    waiting_for_name = State()
    # По номеру карты
    card_waiting_for_amount = State()
    card_waiting_for_card_number = State()
    card_waiting_for_bank = State()
    card_waiting_for_name = State()


def register_transfer(dp, bot):

    @dp.callback_query(F.data == "client_transfer")
    async def transfer_start(call: types.CallbackQuery):
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer_photo(
            photo=TRANSFER_SELECT_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> <b>Перевод на карту</b>\n\n"
                "<blockquote>Выберите тип перевода. Исполнитель переведёт нужную сумму "
                "на указанные реквизиты.</blockquote>\n\n"
                "Выберите тип перевода:"
            ),
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

    # ───────────────── СБП ─────────────────

    @dp.callback_query(F.data == "transfer_sbp")
    async def transfer_sbp(call: types.CallbackQuery, state: FSMContext):
        try:
            await call.message.delete()
        except:
            pass
        await state.set_state(TransferStates.waiting_for_amount)
        await state.update_data(transfer_type="sbp")
        msg = await call.message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5278304890257436355'>📲</tg-emoji> <b>Перевод по СБП</b>\n\n"
                "<blockquote>Введите сумму перевода в рублях.</blockquote>\n\n"
                "Пример: <b>1000</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)
        await call.answer()

    @dp.message(TransferStates.waiting_for_amount)
    async def process_transfer_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите корректную сумму, например <b>1000</b>", parse_mode="HTML")

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
        await state.set_state(TransferStates.waiting_for_phone)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <b>Номер телефона</b>\n\n"
                "<blockquote>Введите номер телефона получателя.</blockquote>\n\n"
                "Пример: <b>+79001234567</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.waiting_for_phone)
    async def process_transfer_phone(message: types.Message, state: FSMContext):
        phone = message.text.strip()
        data = await state.get_data()
        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await state.update_data(phone=phone)
        await state.set_state(TransferStates.waiting_for_bank)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> <b>Банк получателя</b>\n\n"
                "<blockquote>Введите название банка получателя.</blockquote>\n\n"
                "Пример: <b>Сбербанк</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.waiting_for_bank)
    async def process_transfer_bank(message: types.Message, state: FSMContext):
        bank = message.text.strip()
        data = await state.get_data()
        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await state.update_data(bank=bank)
        await state.set_state(TransferStates.waiting_for_name)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Имя получателя</b>\n\n"
                "<blockquote>Введите имя и отчество получателя.</blockquote>\n\n"
                "Пример: <b>Иван Иванович</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.waiting_for_name)
    async def process_transfer_name(message: types.Message, state: FSMContext):
        name = message.text.strip()
        data = await state.get_data()
        amount = data["amount"]
        phone = data["phone"]
        bank = data["bank"]

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

        await state.update_data(name=name, commission=commission, total=total, total_usdt=total_usdt)

        await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> <b>Подтверждение заявки</b>\n\n"
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Перевод по СБП\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводим:\n"
                f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{phone}</code>\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Комиссия: {commission:.2f} RUB\n"
                f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> Итого: {total:.2f} RUB (~{total_usdt:.4f} USDT)\n\n"
                f"<blockquote>Нажмите «Подтвердить» для создания заявки.</blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data="transfer_sbp_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.callback_query(F.data == "transfer_sbp_confirm")
    async def transfer_sbp_confirm(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        data = await state.get_data()
        amount = data["amount"]
        phone = data["phone"]
        bank = data["bank"]
        name = data["name"]
        total_usdt = data["total_usdt"]
        total = data["total"]
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
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Недостаточно средств на балансе!\n\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Необходимо: {total_usdt:.4f} USDT ({total:.2f} RUB)\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Ваш баланс: {balance:.2f} USDT",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )

        await db.db_execute(
            "UPDATE orders SET transfer_type=$1, transfer_phone=$2, transfer_bank=$3, transfer_recipient_name=$4 WHERE id=$5",
            "sbp", phone, bank, name, order_id
        )
        await state.clear()
        try:
            await call.message.delete()
        except:
            pass

        client_msg = await call.message.answer(
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по СБП</b>\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
            f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводим:\n"
            f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{phone}</code>\n"
            f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
            f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
            f"<tg-emoji emoji-id='5278753302023004775'>🟡</tg-emoji> Новая · <tg-emoji emoji-id='5275979556308674886'>👨‍💻</tg-emoji> Исполнитель назначается\n\n"
            f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте — скоро свяжемся с вами",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", client_msg.message_id, order_id)

        text_order = (
            f"<tg-emoji emoji-id='5443127283898405358'>📥</tg-emoji> <b>Новая заявка #{order_id}</b>\n\n"
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Перевод по СБП\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> <b>Сумма:</b> {amount:.2f} RUB\n"
            f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <b>Телефон:</b> <code>{phone}</code>\n"
            f"<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> <b>Банк:</b> {bank}\n"
            f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Получатель:</b> {name}\n\n"
            f"<tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> <b>Резерв:</b> {total_usdt:.4f} USDT\n"
            f"<tg-emoji emoji-id='5276412364458059956'>⏱</tg-emoji> Время на принятие: 1500 сек"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
        ])
        await broadcast_order(bot, text_order, kb, order_id=order_id)
        await call.answer()

    # ───────────────── ПО НОМЕРУ КАРТЫ ─────────────────

    @dp.callback_query(F.data == "transfer_card")
    async def transfer_card(call: types.CallbackQuery, state: FSMContext):
        try:
            await call.message.delete()
        except:
            pass
        await state.set_state(TransferStates.card_waiting_for_amount)
        await state.update_data(transfer_type="card")
        msg = await call.message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <b>Перевод по номеру карты</b>\n\n"
                "<blockquote>Введите сумму перевода в рублях.</blockquote>\n\n"
                "Пример: <b>1000</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)
        await call.answer()

    @dp.message(TransferStates.card_waiting_for_amount)
    async def card_process_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите корректную сумму, например <b>1000</b>", parse_mode="HTML")

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
        await state.set_state(TransferStates.card_waiting_for_card_number)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <b>Номер карты получателя</b>\n\n"
                "<blockquote>Введите номер карты получателя.</blockquote>\n\n"
                "Пример: <b>4276 1234 5678 9012</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.card_waiting_for_card_number)
    async def card_process_card_number(message: types.Message, state: FSMContext):
        card_number = message.text.strip()
        data = await state.get_data()
        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await state.update_data(card_number=card_number)
        await state.set_state(TransferStates.card_waiting_for_bank)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> <b>Банк получателя</b>\n\n"
                "<blockquote>Введите название банка получателя.</blockquote>\n\n"
                "Пример: <b>Сбербанк</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.card_waiting_for_bank)
    async def card_process_bank(message: types.Message, state: FSMContext):
        bank = message.text.strip()
        data = await state.get_data()
        try:
            await bot.delete_message(message.chat.id, data.get("last_msg_id"))
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await state.update_data(bank=bank)
        await state.set_state(TransferStates.card_waiting_for_name)
        msg = await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Имя получателя</b>\n\n"
                "<blockquote>Введите имя и отчество получателя.</blockquote>\n\n"
                "Пример: <b>Иван Иванович</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Отмена", callback_data="client_back_menu")]
            ])
        )
        await state.update_data(last_msg_id=msg.message_id)

    @dp.message(TransferStates.card_waiting_for_name)
    async def card_process_name(message: types.Message, state: FSMContext):
        name = message.text.strip()
        data = await state.get_data()
        amount = data["amount"]
        card_number = data["card_number"]
        bank = data["bank"]

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

        await state.update_data(name=name, commission=commission, total=total, total_usdt=total_usdt)

        await message.answer_photo(
            photo=TRANSFER_BANNER_FILE_ID,
            caption=(
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> <b>Подтверждение заявки</b>\n\n"
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Перевод по номеру карты\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводим:\n"
                f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{card_number}</code>\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
                f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Комиссия: {commission:.2f} RUB\n"
                f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> Итого: {total:.2f} RUB (~{total_usdt:.4f} USDT)\n\n"
                f"<blockquote>Нажмите «Подтвердить» для создания заявки.</blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить", callback_data="transfer_card_confirm")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
            ])
        )

    @dp.callback_query(F.data == "transfer_card_confirm")
    async def transfer_card_confirm(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        data = await state.get_data()
        amount = data["amount"]
        card_number = data["card_number"]
        bank = data["bank"]
        name = data["name"]
        total_usdt = data["total_usdt"]
        total = data["total"]
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
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Недостаточно средств на балансе!\n\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Необходимо: {total_usdt:.4f} USDT ({total:.2f} RUB)\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Ваш баланс: {balance:.2f} USDT",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )

        await db.db_execute(
            "UPDATE orders SET transfer_type=$1, transfer_phone=$2, transfer_bank=$3, transfer_recipient_name=$4 WHERE id=$5",
            "card", card_number, bank, name, order_id
        )
        await state.clear()
        try:
            await call.message.delete()
        except:
            pass

        client_msg = await call.message.answer(
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Перевод по номеру карты</b>\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
            f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводим:\n"
            f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{card_number}</code>\n"
            f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {bank}\n"
            f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {name}\n\n"
            f"<tg-emoji emoji-id='5278753302023004775'>🟡</tg-emoji> Новая · <tg-emoji emoji-id='5275979556308674886'>👨‍💻</tg-emoji> Исполнитель назначается\n\n"
            f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте — скоро свяжемся с вами",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", client_msg.message_id, order_id)

        text_order = (
            f"<tg-emoji emoji-id='5443127283898405358'>📥</tg-emoji> <b>Новая заявка #{order_id}</b>\n\n"
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Перевод по номеру карты\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> <b>Сумма:</b> {amount:.2f} RUB\n"
            f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <b>Номер карты:</b> <code>{card_number}</code>\n"
            f"<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> <b>Банк:</b> {bank}\n"
            f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Получатель:</b> {name}\n\n"
            f"<tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> <b>Резерв:</b> {total_usdt:.4f} USDT\n"
            f"<tg-emoji emoji-id='5276412364458059956'>⏱</tg-emoji> Время на принятие: 1500 сек"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
        ])
        await broadcast_order(bot, text_order, kb, order_id=order_id)
        await call.answer()
