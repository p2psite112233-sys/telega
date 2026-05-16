import asyncio
import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID, BANNER_FILE_ID, CARD_BANNER_FILE_ID
from utils.crypto import crypto_get_rate, crypto_create_invoice, crypto_check_invoice
from utils.cards import parse_card
from utils.shared import get_role, set_role, workers

logger = logging.getLogger(__name__)

# --- FSM СОСТОЯНИЯ ---
class ClientStates(StatesGroup):
    waiting_for_topup_amount = State()
    waiting_for_order_unique = State()
    waiting_for_order_amount = State()

class WorkerRegStates(StatesGroup):
    waiting_for_card_data = State()
    waiting_for_bank_name = State()

# --- КЛАВИАТУРЫ ---
menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="💳 Карта под оплату")]],
    resize_keyboard=True
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def broadcast_order(bot: Bot, text: str, kb: InlineKeyboardMarkup):
    """Рассылка воркерам с защитой от лимитов Telegram"""
    for w_id in workers:
        try:
            await bot.send_message(w_id, text, reply_markup=kb, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Broadcast error to {w_id}: {e}")

async def load_workers():
    rows = await db.load_workers_from_db()
    for uid in rows:
        set_role(uid, "worker")
    print(f"Loaded {len(workers)} workers")

# --- ХЕНДЛЕРЫ ---

def register_common(dp, bot: Bot):

    @dp.message(F.photo)
    async def get_photo_id(message: types.Message):
        if message.from_user.id == ADMIN_ID:
            file_id = message.photo[-1].file_id
            await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")

    @dp.message(F.text == "/start")
    async def start(message: types.Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        role = get_role(uid)

        if role in ["worker", "admin"]:
            return await message.answer(f"🛠 Режим: {role.upper()}", reply_markup=menu)

        text = (
            "<b>🏠 Send$Paid — Главное меню</b>\n\n"
            "<blockquote>Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
            "пополнить номер телефона или оплатить готовый QR-код.\n"
            "Все этапы заявки фиксируются внутри сервиса.</blockquote>\n\n"
            "💼 Комиссия сервиса: <b>20%</b> от суммы, но не меньше 30 RUB\n"
            "🆕 Уникальная карта: дополнительно <b>+5%</b>\n"
            "🔳 QR-оплата: скидка по комиссии <b>-8%</b>\n"
            "⚡️ Работаем <b>24/7</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
                InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
            ],
            [
                InlineKeyboardButton(text="📳 Пополнить номер", callback_data="client_phone"),
                InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
            ],
            [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
            [
                InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
                InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
            ],
            [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")]
        ])
        await message.answer_photo(photo=BANNER_FILE_ID, caption=text, reply_markup=kb, parse_mode="HTML")

    # --- ЛОГИКА ПОПОЛНЕНИЯ ---

    @dp.callback_query(F.data == "client_topup")
    async def topup_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(ClientStates.waiting_for_topup_amount)
        await call.message.answer(
            "💳 <b>Пополнение баланса</b>\n\n"
            "Введите сумму пополнения в рублях.\n\n"
            "💸 Минимальная сумма: <b>100 RUB</b>",
            parse_mode="HTML"
        )
        await call.answer()

    @dp.message(ClientStates.waiting_for_topup_amount)
    async def process_topup_amount(message: types.Message, state: FSMContext):
        try:
            amount_rub = float(message.text.strip())
            if amount_rub < 100:
                return await message.answer("❌ Минимальная сумма — 100 RUB")
        except ValueError:
            return await message.answer("❌ Введите число, например 1000")

        await state.clear()
        rate = await crypto_get_rate()
        amount_usdt = round(amount_rub / rate, 2)
        commission = round(amount_usdt * 0.03, 2)
        to_credit = round(amount_usdt - commission, 2)

        invoice = await crypto_create_invoice(amount_usdt, message.from_user.id)
        if not invoice:
            return await message.answer("❌ Ошибка создания инвойса. Попробуйте позже.")

        invoice_id = invoice["invoice_id"]
        pay_url = invoice["bot_invoice_url"]

        await db.db_execute(
            "INSERT INTO invoices (invoice_id, user_id, amount, status) VALUES ($1, $2, $3, 'active') ON CONFLICT DO NOTHING",
            invoice_id, message.from_user.id, to_credit
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Оплатить инвойс", url=pay_url)]
        ])
        await message.answer(
            f"🧾 Счёт на пополнение #{invoice_id}\n\n"
            f"💰 Сумма: {amount_rub:.2f} RUB (~{amount_usdt:.2f} USDT)\n"
            f"Комиссия: {commission:.2f} USDT\n"
            f"💎 К зачислению: {to_credit:.2f} USDT\n"
            f"🕒 Проверка: каждые 10 сек в течение 15 минут",
            reply_markup=kb
        )
        asyncio.create_task(check_payment_loop(bot, message.from_user.id, invoice_id, to_credit))

    # --- ЛОГИКА СОЗДАНИЯ ЗАКАЗА ---

    @dp.callback_query(F.data == "client_card")
    async def order_start(call: types.CallbackQuery, state: FSMContext):
        await call.message.answer_photo(
            photo=CARD_BANNER_FILE_ID,
            caption=(
                "<b>💳 Карта под оплату</b>\n\n"
                "<blockquote>Вам нужна уникальная карта?\n"
                "Уникальная карта — карта которую никто кроме вас не использовал.\n"
                "Дополнительная комиссия: <b>+5%</b></blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да (+5%)", callback_data="card_unique_yes"),
                    InlineKeyboardButton(text="❌ Нет", callback_data="card_unique_no")
                ]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data.in_({"card_unique_yes", "card_unique_no"}))
    async def order_unique_selected(call: types.CallbackQuery, state: FSMContext):
        unique = call.data == "card_unique_yes"
        await state.set_state(ClientStates.waiting_for_order_amount)
        extra = " (+5% за уникальность)" if unique else ""
        try:
            await call.message.delete()
        except:
            pass
        msg = await call.message.answer(
            f"<b>💳 Карта под оплату</b>\n\n"
            f"<blockquote>Введите сумму в RUB, на которую нужна карта.\n"
            f"После подтверждения исполнитель отправит реквизиты для оплаты.</blockquote>\n\n"
            f"💸 Сумма заявки: в рублях{extra}\nПример: <b>500</b>",
            parse_mode="HTML"
        )
        await state.update_data(unique=unique, sum_msg_id=msg.message_id)
        await call.answer()

    @dp.message(ClientStates.waiting_for_order_amount)
    async def process_order_amount(message: types.Message, state: FSMContext):
        try:
            rub = float(message.text.strip())
            if rub <= 0:
                raise ValueError
        except ValueError:
            return await message.answer("❌ Введите корректную сумму, например 500")

        uid = message.from_user.id
        data = await state.get_data()
        unique = data.get("unique", False)
        sum_msg_id = data.get("sum_msg_id")
        await state.clear()

        # Удаляем сообщение с суммой и введённое число
        try:
            await message.delete()
        except:
            pass
        if sum_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=sum_msg_id)
            except:
                pass

        if unique:
            commission = max(round(rub * 0.25, 2), 30)
        else:
            commission = max(round(rub * 0.20, 2), 30)
        total = round(rub + commission, 2)

        rate = await crypto_get_rate()
        total_usdt = round(total / rate, 4)
        amount_usdt = round(rub / rate, 4)  # Чистая сумма без комиссии

        if not await db.freeze_balance(uid, total_usdt):
            balance = await db.get_balance(uid)
            return await message.answer(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💸 Необходимо: {total_usdt:.4f} USDT ({total:.2f} RUB)\n"
                f"💰 Ваш баланс: {balance:.2f} USDT\n\n"
                f"Пополните баланс через 🤑 Пополнить баланс"
            )

        row = await db.db_fetchone(
            "INSERT INTO orders (user_id, amount, status, total_usdt, amount_usdt) VALUES ($1, $2, 'NEW', $3, $4) RETURNING id",
            uid, rub, total_usdt, amount_usdt
        )
        order_id = row["id"]

        unique_text = "✅ Уникальная карта" if unique else "❌ Обычная карта"

        client_msg = await message.answer(
            f"🎉 Заявка принята в обработку\n\n"
            f"🆔 ID: #{order_id}\n"
            f"💳 Услуга: Карта под оплату\n"
            f"💰 Сумма: {rub:.2f} RUB\n"
            f"💎 К оплате: {total:.2f} RUB\n"
            f"🃏 {unique_text}\n\n"
            f"📊 Статус: 🟡 Новая\n"
            f"👨‍💻 Исполнитель: назначается\n\n"
            f"⏳ Ожидайте — скоро свяжемся с вами",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")]
            ])
        )
        await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", client_msg.message_id, order_id)

        text_order = (
            f"📥 <b>Новая заявка #{order_id}</b>\n\n"
            f"💳 <b>Услуга:</b> Карта под оплату\n"
            f"🃏 {unique_text}\n\n"
            f"💰 <b>Сумма перевода:</b> {rub:.2f} RUB\n"
            f"💎 <b>Клиент оплатит:</b> {total:.2f} RUB\n\n"
            f"🔐 <b>Резерв:</b> {total_usdt:.4f} USDT\n"
            f"⏱ Время на принятие: 1500 сек"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
        ])
        await broadcast_order(bot, text_order, kb)

    # --- ДОБАВЛЕНИЕ КАРТЫ ВОРКЕРОМ ---

    @dp.message(WorkerRegStates.waiting_for_card_data)
    async def process_card_data(message: types.Message, state: FSMContext):
        card = parse_card(message.text)
        if not card:
            return await message.answer("❌ Не удалось найти номер карты. Попробуйте ещё раз.")
        await state.update_data(card=card)
        await state.set_state(WorkerRegStates.waiting_for_bank_name)
        await message.answer(
            f"✅ Карта распознана:\n\n"
            f"💳 Номер: {card['number']}\n"
            f"📅 Срок: {card['expiry']}\n"
            f"🔐 CVV: {card['cvv']}\n\n"
            f"🏦 Введите название банка:"
        )

    @dp.message(WorkerRegStates.waiting_for_bank_name)
    async def process_bank_name(message: types.Message, state: FSMContext):
        data = await state.get_data()
        card = data.get("card")
        bank = message.text.strip()
        uid = message.from_user.id

        await db.db_execute(
            "INSERT INTO cards (worker_id, card_number, expiry, cvv, bank) VALUES ($1, $2, $3, $4, $5)",
            uid, card["number"], card["expiry"], card["cvv"], bank
        )
        row = await db.db_fetchone("SELECT COUNT(*) FROM cards WHERE worker_id=$1", uid)
        card_count = row["count"] if row else 0
        await state.clear()

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="cards_add")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
        ])
        await message.answer(
            f"✅ Карта сохранена!\n\n"
            f"💳 {card['number']}\n"
            f"🏦 Банк: {bank}\n"
            f"📅 Срок: {card['expiry']}\n\n"
            f"💼 Всего карт: {card_count}",
            reply_markup=keyboard
        )

    # --- АДМИН-КОМАНДЫ ---

    @dp.message(F.text.startswith("/setworker"))
    async def cmd_set_worker(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        try:
            target_id = int(message.text.split()[1])
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            set_role(target_id, "worker")
            await message.answer(f"✅ ID {target_id} теперь WORKER")
        except:
            await message.answer("Ошибка. Пример: /setworker 12345")


# --- ЦИКЛ ПРОВЕРКИ ОПЛАТЫ ---

async def check_payment_loop(bot: Bot, user_id: int, invoice_id: int, to_credit: float):
    for _ in range(90):
        await asyncio.sleep(10)
        status = await crypto_check_invoice(invoice_id)

        if status == "paid":
            res = await db.db_execute(
                "UPDATE invoices SET status='paid' WHERE invoice_id=$1 AND status='active'",
                invoice_id
            )
            if "UPDATE 1" in res:
                await db.add_balance(user_id, to_credit)
                balance = await db.get_balance(user_id)
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ Баланс пополнен!\n\n"
                        f"💎 Зачислено: {to_credit:.2f} USDT\n"
                        f"💰 Текущий баланс: {balance:.2f} USDT"
                    )
                except Exception as e:
                    logger.error(f"[payment_loop] notify error: {e}")
            return

        if status == "expired":
            await db.db_execute("UPDATE invoices SET status='expired' WHERE invoice_id=$1", invoice_id)
            try:
                await bot.send_message(user_id, f"❌ Инвойс #{invoice_id} истёк. Создайте новый.")
            except:
                pass
            return
