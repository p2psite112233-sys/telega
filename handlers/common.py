import asyncio
import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID, BANNER_FILE_ID, CARD_BANNER_FILE_ID, ORDER_BANNER_FILE_ID, WELCOME_STICKER_ID
from utils.crypto import crypto_get_rate, crypto_create_invoice, crypto_check_invoice
from utils.cards import parse_card
from utils.shared import get_role, set_role, workers

logger = logging.getLogger(__name__)

# Хранит ID сообщений рассылки: {order_id: {worker_id: message_id}}
broadcast_msgs: dict = {}

# --- FSM СОСТОЯНИЯ ---
class ClientStates(StatesGroup):
    waiting_for_topup_amount = State()
    waiting_for_order_unique = State()
    waiting_for_order_amount = State()

class WorkerRegStates(StatesGroup):
    waiting_for_card_data = State()
    waiting_for_bank_name = State()
    waiting_for_experience = State()
    waiting_for_extra_info = State()
    waiting_for_next_step = State()

# --- КЛАВИАТУРЫ ---
menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="💳 Карта под оплату")]],
    resize_keyboard=True
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def broadcast_order(bot: Bot, text: str, kb: InlineKeyboardMarkup, order_id: int = None):
    """Рассылка воркерам с защитой от лимитов Telegram"""
    for w_id in workers:
        try:
            msg = await bot.send_message(w_id, text, reply_markup=kb, parse_mode="HTML")
            if order_id is not None:
                if order_id not in broadcast_msgs:
                    broadcast_msgs[order_id] = {}
                broadcast_msgs[order_id][w_id] = msg.message_id
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
    async def get_photo_id(message: types.Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state is not None:
            return
        if message.from_user.id == ADMIN_ID:
            file_id = message.photo[-1].file_id
            await message.answer(f"file_id:\n<code>{file_id}</code>", parse_mode="HTML")

    @dp.message(F.sticker)
    async def get_sticker_id(message: types.Message):
        if message.from_user.id == ADMIN_ID:
            await message.answer(f"sticker_id:\n<code>{message.sticker.file_id}</code>", parse_mode="HTML")

    CHANNEL_ID = "@sendpaid_channel"

    async def check_subscription(uid: int) -> bool:
        try:
            member = await bot.get_chat_member(CHANNEL_ID, uid)
            return member.status not in ("left", "kicked")
        except:
            return False

    @dp.message(F.text == "/start")
    async def start(message: types.Message, state: FSMContext):
        await state.clear()
        uid = message.from_user.id
        role = get_role(uid)

        await db.db_execute(
            "INSERT INTO balances (user_id, balance, frozen) VALUES ($1, 0, 0) ON CONFLICT DO NOTHING",
            uid
        )

        # Сохраняем реферера если пришёл по ссылке
        args = message.text.split()
        if len(args) > 1:
            try:
                referrer_id = int(args[1])
                if referrer_id != uid:
                    res = await db.db_execute(
                        "INSERT INTO referrals (referrer_id, referred_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        referrer_id, uid
                    )
                    if "INSERT 0 1" in res:
                        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
                        try:
                            await bot.send_message(
                                referrer_id,
                                f"🎉 По вашей реферальной ссылке зарегистрировался {username}!"
                            )
                        except:
                            pass
            except:
                pass

        # Проверка подписки (только для клиентов, не для воркеров/админов)
        if role not in ["worker", "admin"]:
            is_subscribed = await check_subscription(uid)
            if not is_subscribed:
                await message.answer_sticker(WELCOME_STICKER_ID)
                await message.answer(
                    "👋 Добро пожаловать в <b>Send$Paid</b>!\n\n"
                    "Для использования бота необходимо подписаться на наш канал.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📢 Подписаться", url="https://t.me/sendpaid_channel")],
                        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
                    ])
                )
                return

        if role in ["worker", "admin"]:
            worker_text = (
                "<b>🏠 Главное меню работника</b>\n\n"
                "<blockquote>Здесь вы получаете заявки на выдачу карты, переводы на карту/СБП, "
                "оплату QR-кодов или пополнение номеров.\n"
                "Бот выступает гарантом и фиксирует все действия.</blockquote>\n\n"
                "💸 Ваша доля от комиссии: <b>80.00%</b>\n"
                "🧾 Доля сервиса от комиссии: <b>20.00%</b>\n"
                "✅ Вы сами выбираете, какую заявку взять в работу"
            )
            worker_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Доступные заявки", callback_data="lk_available")],
                [InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="lk_home")],
                [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")]
            ])
            return await message.answer_photo(photo=BANNER_FILE_ID, caption=worker_text, reply_markup=worker_kb, parse_mode="HTML")

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

    @dp.callback_query(F.data == "check_sub")
    async def check_sub(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        is_subscribed = await check_subscription(uid)
        if not is_subscribed:
            return await call.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        await call.message.delete()
        # Показываем главное меню
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
        await call.message.answer_photo(photo=BANNER_FILE_ID, caption=text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "client_topup")
    async def topup_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(ClientStates.waiting_for_topup_amount)
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(
            "💳 <b>Пополнение баланса</b>\n\n"
            "Введите сумму пополнения в рублях.\n\n"
            "💸 Минимальная сумма: <b>100 RUB</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
            ])
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
        try:
            await call.message.delete()
        except:
            pass
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
                ],
                [InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data.in_({"card_unique_yes", "card_unique_no"}))
    async def order_unique_selected(call: types.CallbackQuery, state: FSMContext):
        current = await state.get_state()
        if current == ClientStates.waiting_for_order_amount:
            return await call.answer("⏳ Уже обрабатывается", show_alert=False)
        unique = call.data == "card_unique_yes"
        await state.set_state(ClientStates.waiting_for_order_amount)
        extra = " (+5% за уникальность)" if unique else ""
        try:
            await call.message.delete()
        except:
            pass
        msg = await call.message.answer_photo(
            photo=ORDER_BANNER_FILE_ID,
            caption=(
                f"<b>💳 Карта под оплату</b>\n\n"
                f"<blockquote>Введите сумму в RUB, на которую нужна карта.\n"
                f"После подтверждения исполнитель отправит реквизиты для оплаты.</blockquote>\n\n"
                f"💸 Сумма заявки: в рублях{extra}\nПример: <b>500</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")]
            ])
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
                f"💰 Ваш баланс: {balance:.2f} USDT",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )

        row = await db.db_fetchone(
            "INSERT INTO orders (user_id, amount, status, total_usdt, amount_usdt, is_unique) VALUES ($1, $2, 'NEW', $3, $4, $5) RETURNING id",
            uid, rub, total_usdt, amount_usdt, unique
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
        await broadcast_order(bot, text_order, kb, order_id=order_id)
        asyncio.create_task(order_timeout(bot, order_id, uid, total_usdt))

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


# --- ГЛОБАЛЬНЫЙ МУСОРЩИК ---

async def cleanup_expired_orders(bot: Bot):
    while True:
        await asyncio.sleep(300)
        try:
            expired = await db.db_fetchall(
                "SELECT id, user_id, total_usdt, client_message_id FROM orders WHERE status='NEW' AND created_at < NOW() - INTERVAL '25 minutes'"
            )
            for order in expired:
                res = await db.db_execute(
                    "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status='NEW'", order["id"]
                )
                if "UPDATE 0" in res:
                    continue
                await db.unfreeze_back(order["user_id"], float(order["total_usdt"] or 0))
                broadcast_msgs.pop(order["id"], None)
                logger.info(f"Cleanup: Order #{order['id']} cancelled")
                try:
                    if order["client_message_id"]:
                        await bot.edit_message_text(
                            chat_id=order["user_id"],
                            message_id=order["client_message_id"],
                            text=f"⏰ Заявка #{order['id']} отменена\n\nНикто не взял заявку в течение 25 минут.\n💰 Средства возвращены на баланс."
                        )
                except:
                    try:
                        await bot.send_message(order["user_id"], f"⏰ Заявка #{order['id']} отменена.\n💰 Средства возвращены на баланс.")
                    except:
                        pass
        except Exception as e:
            logger.error(f"[cleanup] error: {e}")


# --- ТАЙМЕР ЗАЯВКИ ---

async def order_timeout(bot: Bot, order_id: int, user_id: int, total_usdt: float):
    await asyncio.sleep(1500)
    res = await db.db_execute(
        "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status='NEW'", order_id
    )
    if "UPDATE 0" in res:
        broadcast_msgs.pop(order_id, None)
        return  # Уже взята или отменена
    await db.unfreeze_back(user_id, total_usdt)
    # Редактируем сообщения у воркеров
    msgs = broadcast_msgs.pop(order_id, {})
    for w_id, msg_id in msgs.items():
        try:
            await bot.edit_message_text(
                chat_id=w_id,
                message_id=msg_id,
                text=f"❌ Заявка #{order_id} — срок истёк\n\nКлиент не дождался исполнителя."
            )
            await asyncio.sleep(0.05)
        except:
            pass
    # Уведомляем клиента
    try:
        row = await db.db_fetchone("SELECT client_message_id FROM orders WHERE id=$1", order_id)
        if row and row["client_message_id"]:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=row["client_message_id"],
                text=f"⏰ Заявка #{order_id} отменена\n\nНикто не взял заявку в течение 25 минут.\n💰 Средства возвращены на баланс."
            )
    except Exception as e:
        logger.error(f"[order_timeout] edit error: {e}")
        try:
            await bot.send_message(user_id, f"⏰ Заявка #{order_id} отменена — никто не взял в течение 25 минут.\n💰 Средства возвращены на баланс.")
        except:
            pass


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
                # Начисляем 3% рефереру
                try:
                    ref_row = await db.db_fetchone(
                        "SELECT referrer_id FROM referrals WHERE referred_id=$1", user_id
                    )
                    if ref_row and ref_row["referrer_id"]:
                        bonus = round(to_credit * 0.03, 4)
                        await db.add_balance(ref_row["referrer_id"], bonus)
                        await bot.send_message(
                            ref_row["referrer_id"],
                            f"🎁 Реферальный бонус!\n\nВаш реферал пополнил баланс.\n💎 Начислено: +{bonus:.4f} USDT"
                        )
                except Exception as e:
                    logger.error(f"[referral bonus] error: {e}")
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
