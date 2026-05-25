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
    client_waiting_for_amount = State()

def register_withdraw(dp, bot):

    # ───── ВОРКЕР ─────

    @dp.callback_query(F.data == "lk_withdraw")
    async def lk_withdraw(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        balance = await db.get_balance(uid)
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> <b>Вывод средств</b>\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Доступно: <b>{balance:.2f} USDT</b>\n\n"
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
                return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Минимальная сумма вывода — 1 USDT")
        except ValueError:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите число, например 10.5")

        res = await db.db_execute(
            "UPDATE balances SET balance = balance - $1 WHERE user_id=$2 AND balance >= $1",
            amount, uid
        )
        if not res or "UPDATE 1" not in res:
            current_balance = await db.get_balance(uid)
            return await message.answer(
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Недостаточно средств!\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Доступно: {current_balance:.2f} USDT"
            )

        payout = round(amount * 0.97, 4)
        check = await crypto_create_check(payout)
        if not check:
            await db.db_execute(
                "UPDATE balances SET balance = balance + $1 WHERE user_id=$2",
                amount, uid
            )
            await state.clear()
            from utils.crypto import crypto_create_check_debug
            error_info = await crypto_create_check_debug(amount)
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Ошибка создания чека:\n<code>{error_info}</code>", parse_mode="HTML")

        await db.db_execute(
            "INSERT INTO withdrawals (worker_id, amount) VALUES ($1, $2)",
            uid, amount
        )
        check_url = check.get("bot_check_url") or check.get("check_url", "")
        await state.clear()
        await message.answer(
           f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Чек создан!\n\n"
            f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Запрошено: {amount:.4f} USDT\n"
            f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> К получению: {payout:.4f} USDT (за вычетом 3% комиссии)\n\n"
            f"Активируйте чек по ссылке ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Получить USDT", url=check_url)],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )

    # ───── КЛИЕНТ ─────

    @dp.callback_query(F.data == "client_withdraw")
    async def client_withdraw_start(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        balance = await db.get_balance(uid)
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> <b>Вывод средств</b>\n\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Доступно: <b>{balance:.2f} USDT</b>\n\n"
            f"Введите сумму для вывода (минимум 1 USDT):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        )
        await state.set_state(WithdrawStates.client_waiting_for_amount)
        await call.answer()

    @dp.message(WithdrawStates.client_waiting_for_amount)
    async def client_process_withdraw(message: types.Message, state: FSMContext):
        uid = message.from_user.id
        try:
            amount = float(message.text.strip().replace(",", "."))
            if amount < 1:
                return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Минимальная сумма вывода — 1 USDT")
        except ValueError:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите число, например 10.5")

        res = await db.db_execute(
            "UPDATE balances SET balance = balance - $1 WHERE user_id=$2 AND balance >= $1",
            amount, uid
        )
        if not res or "UPDATE 1" not in res:
            current_balance = await db.get_balance(uid)
            return await message.answer(
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Недостаточно средств!\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Доступно: {current_balance:.2f} USDT"
            )

        payout = round(amount * 0.97, 4)
        check = await crypto_create_check(payout)
        if not check:
            await db.db_execute(
                "UPDATE balances SET balance = balance + $1 WHERE user_id=$2",
                amount, uid
            )
            await state.clear()
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Ошибка создания чека. Попробуйте позже.")

        check_url = check.get("bot_check_url") or check.get("check_url", "")
        await state.clear()
        await message.answer(
            f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Чек создан!\n\n"
            f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Запрошено: {amount:.4f} USDT\n"
            f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> К получению: {payout:.4f} USDT (за вычетом 3% комиссии)\n\n"
            f"Активируйте чек по ссылке ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Получить USDT", url=check_url)],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
        )
