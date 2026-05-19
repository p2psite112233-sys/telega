import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from utils.crypto import crypto_create_check

logger = logging.getLogger(__name__)


class WithdrawStates(StatesGroup):
    waiting_for_amount = State()


def register_withdraw(dp, bot):

    @dp.callback_query(F.data == "lk_withdraw")
    async def lk_withdraw(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        balance = await db.get_balance(uid)
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            f"💸 <b>Вывод средств</b>\n\n"
            f"💰 Доступно: <b>{balance:.2f} USDT</b>\n\n"
            f"Введите сумму для вывода (минимум 1 USDT):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
        await state.set_state(WithdrawStates.waiting_for_amount)
        await call.answer()

    @dp.message(WithdrawStates.waiting_for_amount)
    async def process_withdraw_amount(message: types.Message, state: FSMContext):
        uid = message.from_user.id
        try:
            amount = float(message.text.strip().replace(",", "."))
            if amount < 1:
                return await message.answer("❌ Минимальная сумма вывода — 1 USDT")
        except ValueError:
            return await message.answer("❌ Введите число, например 10.5")

        # Атомарно списываем — защита от race condition
        res = await db.db_execute(
            "UPDATE balances SET balance = balance - $1 WHERE user_id=$2 AND balance >= $1",
            amount, uid
        )
        if not res or "UPDATE 1" not in res:
            current_balance = await db.get_balance(uid)
            return await message.answer(
                f"❌ Недостаточно средств!\n\n"
                f"💰 Доступно: {current_balance:.2f} USDT"
            )

        # Создаём чек
        check = await crypto_create_check(amount)
        if not check:
            # Возвращаем баланс если чек не создался
            await db.db_execute(
                "UPDATE balances SET balance = balance + $1 WHERE user_id=$2",
                amount, uid
            )
            await state.clear()
            # Пробуем получить детали ошибки
            from utils.crypto import crypto_create_check_debug
            error_info = await crypto_create_check_debug(amount)
            return await message.answer(f"❌ Ошибка создания чека:\n<code>{error_info}</code>", parse_mode="HTML")

        # Сохраняем вывод в БД
        await db.db_execute(
            "INSERT INTO withdrawals (worker_id, amount) VALUES ($1, $2)",
            uid, amount
        )

        check_url = check.get("bot_check_url") or check.get("check_url", "")
        await state.clear()
        await message.answer(
            f"✅ Чек создан!\n\n"
            f"💸 Сумма: {amount:.2f} USDT\n\n"
            f"Активируйте чек по ссылке ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Получить USDT", url=check_url)],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
