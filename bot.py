import asyncio
import os
import re
import sys
import traceback
import aiohttp
import psycopg2
from psycopg2.extras import RealDictCursor
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ===== BOT =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
CRYPTO_API_URL = "https://pay.crypt.bot/api"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== DB =====
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("[YOUR-PASSWORD]", os.getenv("DB_PASSWORD", ""))
print(f"Connecting to DB: {DATABASE_URL[:40] if DATABASE_URL else 'NOT SET'}...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    print("DB connected OK")
except Exception as e:
    print(f"DB CONNECTION ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount REAL,
    status TEXT,
    worker_id BIGINT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS workers (
    user_id BIGINT PRIMARY KEY
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS balances (
    user_id BIGINT PRIMARY KEY,
    balance REAL DEFAULT 0.0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id BIGINT PRIMARY KEY,
    user_id BIGINT,
    amount REAL,
    status TEXT DEFAULT 'active'
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    worker_id BIGINT,
    card_number TEXT,
    expiry TEXT,
    cvv TEXT,
    bank TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# ===== GLOBAL STATE =====
pending_code = {}      # worker_id -> order_id (воркер вводит код)
pending_code_msg = {}  # worker_id -> message_id кнопки "SEND CODE"
waiting = {}           # user_id -> True (пользователь вводит сумму)
waiting_topup = {}     # user_id -> True (пользователь вводит сумму пополнения)
waiting_card = {}      # worker_id -> True (воркер вводит данные карты)
waiting_bank = {}      # worker_id -> dict с данными карты (ждёт название банка)

# ===== WEB (Render fix) =====
async def handle(request):
    return web.Response(text="Bot is running")

async def run_web():
    app = web.Application()
    app.router.add_get("/", handle)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ===== ROLES =====
users_role = {}
workers = set()

def set_role(user_id: int, role: str):
    users_role[user_id] = role

def get_role(user_id: int):
    # Админ всегда админ
    if user_id == ADMIN_ID:
        return "admin"
    return users_role.get(user_id, "user")

def load_workers():
    """Загружает воркеров из БД при старте бота."""
    cur.execute("SELECT user_id FROM workers")
    rows = cur.fetchall()
    for row in rows:
        uid = row[0]
        workers.add(uid)
        users_role[uid] = "worker"

ADMIN_ID = 8538723496

# ===== CRYPTOBOT HELPERS =====
async def crypto_get_rate() -> float:
    """Получает курс USDT/RUB из CryptoBot."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CRYPTO_API_URL}/getExchangeRates",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    for rate in data["result"]:
                        if rate["source"] == "USDT" and rate["target"] == "RUB":
                            return float(rate["rate"])
    except:
        pass
    return 90.0  # fallback курс

async def crypto_create_invoice(amount_usdt: float, user_id: int) -> dict | None:
    """Создаёт инвойс в CryptoBot."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTO_API_URL}/createInvoice",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                json={
                    "asset": "USDT",
                    "amount": str(round(amount_usdt, 2)),
                    "description": f"Пополнение баланса (ID: {user_id})",
                    "expires_in": 900  # 15 минут
                }
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]
    except:
        pass
    return None

async def crypto_check_invoice(invoice_id: int) -> str:
    """Проверяет статус инвойса. Возвращает 'paid', 'active' или 'expired'."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CRYPTO_API_URL}/getInvoices",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                params={"invoice_ids": str(invoice_id)}
            ) as resp:
                data = await resp.json()
                if data.get("ok") and data["result"]["items"]:
                    return data["result"]["items"][0]["status"]
    except:
        pass
    return "unknown"

def get_balance(user_id: int) -> float:
    cur.execute("SELECT balance FROM balances WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0.0

def add_balance(user_id: int, amount: float):
    cur.execute("""
        INSERT INTO balances (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    """, (user_id, amount, amount))

# ===== CARD HELPERS =====
import re

def parse_card(text: str) -> dict | None:
    """Парсит данные карты из текста в любом формате."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    all_text = ' '.join(lines)

    # Номер карты — 16 цифр подряд или с разделителями
    card_number = None
    for line in lines:
        digits = re.sub(r'[\s/\-]', '', line)
        if re.fullmatch(r'\d{16}', digits):
            card_number = digits
            break
    if not card_number:
        match = re.search(r'(\d[\d\s/\-]{14,18}\d)', all_text)
        if match:
            digits = re.sub(r'[\s/\-]', '', match.group(1))
            if len(digits) == 16:
                card_number = digits

    # Срок — MM/YY, MMYY, MM YY
    expiry = None
    for line in lines:
        m = re.fullmatch(r'(\d{2})[/\s]?(\d{2,4})', line)
        if m:
            mm = m.group(1)
            yy = m.group(2)[-2:]
            expiry = f"{mm}/{yy}"
            break
    if not expiry:
        m = re.search(r'\b(\d{2})[/\s](\d{2,4})\b', all_text)
        if m:
            expiry = f"{m.group(1)}/{m.group(2)[-2:]}"

    # CVV — 3 цифры на отдельной строке или после "код"
    cvv = None
    for line in lines:
        m = re.fullmatch(r'\d{3}', line)
        if m and line != (expiry or '').replace('/', '')[:3]:
            cvv = line
            break
    if not cvv:
        m = re.search(r'(?:код|cvv|cvc)[:\s]*(\d{3})', all_text, re.IGNORECASE)
        if m:
            cvv = m.group(1)

    if not card_number:
        return None

    return {"number": card_number, "expiry": expiry or "—", "cvv": cvv or "—"}

# ===== MENU =====
menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="💳 Карта под оплату")]],
    resize_keyboard=True
)

# ===== START =====
@dp.message(F.text == "/start")
async def start(message: types.Message):
    role = get_role(message.from_user.id)

    if role == "worker":
        await message.answer("🛠 Вы вошли как WORKER", reply_markup=menu)
    elif role == "admin":
        await message.answer("👑 Вы вошли как администратор", reply_markup=menu)
    else:
        await message.answer(
            "🏠 Главное меню клиента\n\n"
            "Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
            "пополнить номер телефона или оплатить готовый QR-код.\n"
            "Все этапы заявки фиксируются внутри сервиса.\n\n"
            "💼 Комиссия сервиса: 20.00% от суммы заявки, но не меньше 30 RUB\n"
            "🆕 Уникальная карта: дополнительно +10.00%\n"
            "🔳 QR-оплата: скидка по комиссии -8.00%\n"
            "⚡️ Наши работники готовы обрабатывать заявки 24/7",
            reply_markup=menu
        )

# ===== SET WORKER =====
@dp.message(F.text.startswith("/setworker"))
async def set_worker(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) < 2:
        await message.answer("Формат: /setworker 123456789")
        return

    try:
        user_id = int(parts[1])
        workers.add(user_id)
        set_role(user_id, "worker")
        # Сохраняем в БД
        cur.execute("INSERT INTO workers (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        await message.answer(f"✅ Worker назначен: {user_id}")
    except:
        await message.answer("Ошибка ID")


# ===== ЛИЧНЫЙ КАБИНЕТ =====
@dp.message(F.text == "/lk")
async def lk(message: types.Message):
    uid = message.from_user.id
    role = get_role(uid)

    if role in ["worker", "admin"]:
        username = f"@{message.from_user.username}" if message.from_user.username else "нет username"

        text = (
            f"🛠 Профиль работника\n"
            f"Ваш профиль: {username} [{uid}]\n\n"
            f"💼 Финансы\n"
            f"• Доступно для вывода: 0.00 USDT\n"
            f"• Заморожено: 0.00 USDT\n\n"
            f"📊 Статистика\n"
            f"• Обработано заявок: 0 шт\n"
            f"• Объем закрытых заявок: 0.00 USDT\n"
            f"• Выплачено вам: 0.00 USDT\n"
            f"• Обработанная сумма: 0.00 RUB\n"
            f"• Активных заявок: 0 шт"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
            [
                InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")
            ],
            [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="lk_menu")]
        ])

        await message.answer(text, reply_markup=keyboard)

    else:
        text = (
            "🏠 Главное меню клиента\n\n"
            "Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
            "пополнить номер телефона или оплатить готовый QR-код.\n"
            "Все этапы заявки фиксируются внутри сервиса.\n\n"
            "💼 Комиссия сервиса: 20.00% от суммы заявки, но не меньше 30 RUB\n"
            "🆕 Уникальная карта: дополнительно +10.00%\n"
            "🔳 QR-оплата: скидка по комиссии -8.00%\n"
            "⚡️ Наши работники готовы обрабатывать заявки 24/7"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
                InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
            ],
            [
                InlineKeyboardButton(text="📳 Пополнить номер телефона через банк", callback_data="client_phone"),
                InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
            ],
            [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
            [
                InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
                InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
            ],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="client_support")]
        ])

        await message.answer(text, reply_markup=keyboard)

# ===== ЗАГЛУШКИ КНОПОК ЛК =====
@dp.callback_query(
    (F.data.startswith("lk_") | F.data.startswith("client_") | F.data.startswith("cards_") | F.data.startswith("card_"))
    & ~F.data.startswith("client_paid_")
)
async def lk_buttons(call: types.CallbackQuery):
    if call.data == "client_card":
        waiting[call.from_user.id] = True
        await call.message.answer(
            "💳 Карта под оплату\n\n"
            "Введите сумму в RUB, на которую нужна карта.\n"
            "После подтверждения работник отправит реквизиты для оплаты.\n\n"
            "💸 Сумма заявки: в рублях\n"
            "Пример: 500"
        )
        return await call.answer()

    if call.data == "client_topup":
        waiting_topup[call.from_user.id] = True
        await call.message.answer(
            "💳 Пополнение баланса\n\n"
            "Введите сумму пополнения в рублях.\n"
            "После оплаты инвойса баланс зачислится автоматически.\n\n"
            "💸 Сумма пополнения: в рублях"
        )
        return await call.answer()

    if call.data == "client_profile":
        uid = call.from_user.id
        username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
        balance = get_balance(uid)

        # Статистика из БД
        cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=%s AND status='DONE'", (uid,))
        closed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=%s AND status='IN_PROGRESS'", (uid,))
        active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM invoices WHERE user_id=%s AND status='paid'", (uid,))
        paid_count = cur.fetchone()[0]

        text = (
            f"👤 Профиль клиента\n"
            f"Ваш профиль: {username} [{uid}]\n\n"
            f"💼 Финансы\n"
            f"• Доступно на балансе: {balance:.2f} USDT\n"
            f"• Заморожено в заявках: 0.00 USDT\n\n"
            f"📊 Статистика\n"
            f"• Закрыто заявок: {closed} шт\n"
            f"• Активных заявок: {active} шт\n"
            f"• Объем закрытых заявок: 0.00 USDT\n"
            f"• Возвращено после споров: 0.00 USDT\n"
            f"• Приглашено по ссылке: 0 чел\n"
            f"• Реферальный доход: 0.00 USDT\n"
            f"• Успешных пополнений: {paid_count} шт\n"
            f"• Операций в истории: 0 шт"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="client_ref")],
            [InlineKeyboardButton(text="📚 История", callback_data="client_history")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
        ])

        await call.message.answer(text, reply_markup=keyboard)
        return await call.answer()

    if call.data == "client_back_menu":
        uid = call.from_user.id
        text = (
            "🏠 Главное меню клиента\n\n"
            "Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
            "пополнить номер телефона или оплатить готовый QR-код.\n"
            "Все этапы заявки фиксируются внутри сервиса.\n\n"
            "💼 Комиссия сервиса: 20.00% от суммы заявки, но не меньше 30 RUB\n"
            "🆕 Уникальная карта: дополнительно +10.00%\n"
            "🔳 QR-оплата: скидка по комиссии -8.00%\n"
            "⚡️ Наши работники готовы обрабатывать заявки 24/7"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
                InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
            ],
            [
                InlineKeyboardButton(text="📳 Пополнить номер телефона через банк", callback_data="client_phone"),
                InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
            ],
            [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
            [
                InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
                InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
            ],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="client_support")]
        ])
        await call.message.answer(text, reply_markup=keyboard)
        return await call.answer()

    if call.data == "lk_cards":
        uid = call.from_user.id
        cur.execute("SELECT id, card_number, expiry FROM cards WHERE worker_id=%s", (uid,))
        cards = cur.fetchall()

        card_count = len(cards)

        # Каждая карта — отдельная кнопка с маскировкой
        card_buttons = []
        for card in cards:
            cid, number, expiry = card
            masked = f"{number[:6]}{'*'*6}{number[-4:]} · {expiry}"
            card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{cid}")])

        card_buttons.append([InlineKeyboardButton(text="🔎 Поиск", callback_data="cards_search")])
        card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
        card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)

        await call.message.answer(
            f"💳 Управление картами\n\n"
            f"Здесь вы храните свои карты для быстрых отправок в заявках.\n"
            f"Выберите карту из списка или добавьте новую.\n\n"
            f"💼 Сохранено карт: {card_count}",
            reply_markup=keyboard
        )
        return await call.answer()

    if call.data == "cards_add":
        waiting_card[call.from_user.id] = True
        await call.message.answer(
            "➕ Добавление карты\n\n"
            "Карта сохранится в вашем профиле и появится в общем списке.\n"
            "Любой лишний текст бот сохранит как название карты.\n\n"
            "💳 Отправьте данные карты в любом удобном виде.\n"
            "Бот сам найдет номер карты, срок и код (3 цифры).\n\n"
            "Поддерживаются варианты:\n"
            "1111222233334444\n"
            "1111 1111 1111 1111\n"
            "1111/1111/1111/1111\n"
            "00/00 или 00 00\n"
            "Код: 000"
        )
        return await call.answer()

    if call.data == "lk_home":
        uid = call.from_user.id
        username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
        text = (
            f"🛠 Профиль работника\n"
            f"Ваш профиль: {username} [{uid}]\n\n"
            f"💼 Финансы\n"
            f"• Доступно для вывода: 0.00 USDT\n"
            f"• Заморожено: 0.00 USDT\n\n"
            f"📊 Статистика\n"
            f"• Обработано заявок: 0 шт\n"
            f"• Объем закрытых заявок: 0.00 USDT\n"
            f"• Выплачено вам: 0.00 USDT\n"
            f"• Обработанная сумма: 0.00 RUB\n"
            f"• Активных заявок: 0 шт"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
            [
                InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")
            ],
            [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="lk_menu")]
        ])
        await call.message.answer(text, reply_markup=keyboard)
        return await call.answer()

    # Просмотр карты
    if call.data.startswith("card_view_"):
        card_id = int(call.data.split("_")[2])
        row = cur.execute(
            "SELECT card_number, expiry, cvv, bank, created_at FROM cards WHERE id=%s AND worker_id=%s",
            (card_id, call.from_user.id)
        )
        row = cur.fetchone()

        if not row:
            return await call.answer("❌ Карта не найдена", show_alert=True)

        number, expiry, cvv, bank, created_at = row

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"card_delete_{card_id}")],
            [InlineKeyboardButton(text="◀️ К списку карт", callback_data="lk_cards")],
            [InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")]
        ])

        await call.message.answer(
            f"💳 Карточка карты\n\n"
            f"Полные реквизиты карты для использования в заявках.\n\n"
            f"💳 Номер: {number}\n"
            f"📅 Срок: {expiry}\n"
            f"🔐 Код: {cvv}\n"
            f"🏦 Банк: {bank}\n"
            f"🕒 Добавлена: {created_at}",
            reply_markup=keyboard
        )
        return await call.answer()

    # Удаление карты
    if call.data.startswith("card_delete_"):
        card_id = int(call.data.split("_")[2])
        cur.execute(
            "DELETE FROM cards WHERE id=%s AND worker_id=%s",
            (card_id, call.from_user.id)
        )
    
        await call.answer("✅ Карта удалена", show_alert=True)

        # Возвращаем к списку карт
        uid = call.from_user.id
        cur.execute("SELECT id, card_number, expiry FROM cards WHERE worker_id=%s", (uid,))
        cards = cur.fetchall()

        card_buttons = []
        for card in cards:
            cid, number, expiry = card
            masked = f"{number[:6]}{'*'*6}{number[-4:]} · {expiry}"
            card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{cid}")])

        card_buttons.append([InlineKeyboardButton(text="🔎 Поиск", callback_data="cards_search")])
        card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
        card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
        await call.message.answer(
            f"💳 Управление картами\n\n"
            f"Здесь вы храните свои карты для быстрых отправок в заявках.\n"
            f"Выберите карту из списка или добавьте новую.\n\n"
            f"💼 Сохранено карт: {len(cards)}",
            reply_markup=keyboard
        )
        return

    await call.answer("🚧 Раздел в разработке", show_alert=True)

# ===== NEW ORDER =====
@dp.message(F.text == "💳 Карта под оплату")
async def new_order(message: types.Message):
    waiting[message.from_user.id] = True

    await message.answer(
        "💳 Карта под оплату\n\n"
        "Введите сумму в RUB, на которую нужна карта.\n"
        "После подтверждения работник отправит реквизиты для оплаты.\n\n"
        "💸 Сумма заявки: в рублях\n"
        "Пример: 500"
    )

# ===== УНИВЕРСАЛЬНЫЙ ХЕНДЛЕР ТЕКСТА =====
# ВАЖНО: один хендлер для всех текстов, кроме команд и кнопки меню.
# Порядок проверки: сначала воркер (вводит код), потом юзер (вводит сумму).
@dp.message(F.text & ~F.text.startswith("/") & (F.text != "💳 Карта под оплату"))
async def text_handler(message: types.Message):
    uid = message.from_user.id

    # --- 1. Воркер вводит код для клиента ---
    if uid in pending_code:
        order_id = pending_code.pop(uid)
        code = message.text.strip()

        row = cur.execute(
            "SELECT user_id FROM orders WHERE id=%s",
            (order_id,)
        )
        row = cur.fetchone()

        if not row or not row[0]:
            return await message.answer("❌ Ошибка: пользователь не найден")

        user_id = row[0]

        try:
            await bot.send_message(
                user_id,
                f"🔐 Ваш код: {code}"
            )
        except:
            return await message.answer("❌ Не удалось отправить код клиенту")

        # Удаляем сообщение воркера с кодом
        try:
            await message.delete()
        except:
            pass

        # Удаляем сообщение с кнопкой "SEND CODE"
        btn_msg_id = pending_code_msg.pop(uid, None)
        if btn_msg_id:
            try:
                await bot.delete_message(uid, btn_msg_id)
            except:
                pass

        return await message.answer("✅ Код отправлен клиенту")

    # --- 2. Пользователь вводит сумму пополнения ---
    if waiting_topup.get(uid):
        text = message.text.strip()
        try:
            amount_rub = float(text)
        except:
            return await message.answer("❌ Введите число, например 1000")

        if amount_rub <= 0:
            return await message.answer("❌ Сумма должна быть больше 0")

        waiting_topup[uid] = False

        # Получаем курс и конвертируем RUB → USDT
        rate = await crypto_get_rate()
        amount_usdt = round(amount_rub / rate, 2)
        commission = round(amount_usdt * 0.03, 2)
        to_credit = round(amount_usdt - commission, 2)

        # Создаём инвойс
        invoice = await crypto_create_invoice(amount_usdt, uid)
        if not invoice:
            return await message.answer("❌ Ошибка создания инвойса. Попробуйте позже.")

        invoice_id = invoice["invoice_id"]
        pay_url = invoice["bot_invoice_url"]

        # Сохраняем инвойс в БД
        cur.execute(
            "INSERT INTO invoices (invoice_id, user_id, amount) VALUES (?, ?, ?)",
            (invoice_id, uid, to_credit)
        )
    
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Оплатить инвойс", url=pay_url)]
        ])

        await message.answer(
            f"🧾 Счёт на пополнение #{invoice_id}\n\n"
            f"Оплатите инвойс, после чего баланс будет зачислен автоматически.\n\n"
            f"💰 Сумма: {amount_rub:.2f} RUB (~{amount_usdt:.2f} USDT)\n"
            f"Комиссия пополнения: {commission:.2f} USDT\n"
            f"💎 К зачислению: {to_credit:.2f} USDT\n"
            f"🕒 Проверка оплаты: каждые 10 секунд в течение 15 минут",
            reply_markup=keyboard
        )

        # Запускаем проверку оплаты в фоне
        asyncio.create_task(check_payment_loop(uid, invoice_id, to_credit))
        return

    # --- 3. Воркер вводит данные карты ---
    if waiting_card.get(uid):
        waiting_card[uid] = False
        card = parse_card(message.text)
        if not card:
            return await message.answer("❌ Не удалось найти номер карты. Попробуйте ещё раз — нажмите '➕ Добавить карту'")

        waiting_bank[uid] = card
        return await message.answer(
            f"✅ Карта распознана:\n\n"
            f"💳 Номер: {card['number']}\n"
            f"📅 Срок: {card['expiry']}\n"
            f"🔐 CVV: {card['cvv']}\n\n"
            f"🏦 Введите название банка:"
        )

    # --- 4. Воркер вводит название банка ---
    if uid in waiting_bank:
        card = waiting_bank.pop(uid)
        bank = message.text.strip()

        cur.execute(
            "INSERT INTO cards (worker_id, card_number, expiry, cvv, bank) VALUES (?, ?, ?, ?, ?)",
            (uid, card["number"], card["expiry"], card["cvv"], bank)
        )
    
        card_count = cur.execute(
            "SELECT COUNT(*) FROM cards WHERE worker_id=?", (uid,)
        )
        cur.fetchone()[0]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="cards_add")],
            [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
        ])

        return await message.answer(
            f"✅ Карта сохранена!\n\n"
            f"💳 {card['number']}\n"
            f"🏦 Банк: {bank}\n"
            f"📅 Срок: {card['expiry']}\n\n"
            f"💼 Всего карт: {card_count}",
            reply_markup=keyboard
        )

    # --- 5. Пользователь вводит сумму заявки ---
    if not waiting.get(uid):
        return

    text = message.text.strip()

    try:
        rub = float(text)
    except:
        return await message.answer("❌ Введите число, например 500")

    waiting[uid] = False

    usdt = round(rub / 63.7, 2)
    total = round(rub * 1.2, 2)

    cur.execute(
        "INSERT INTO orders (user_id, amount, status, worker_id) VALUES (?, ?, ?, ?)",
        (uid, rub, "NEW", None)
    )

    order_id = cur.fetchone()[0]

    text_order = (
        f"📥 Новая заявка #{order_id}\n\n"
        f"💳 Метод: Карта под оплату\n"
        f"💰 Сумма: {rub:.2f} RUB\n"
        f"💎 Итог: {total:.2f} RUB\n"
        f"🔐 Резерв: {usdt} USDT\n\n"
        f"⏱ Время на принятие: 1500 сек"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Взять в работу", callback_data=f"take_{order_id}")]
    ])

    # рассылка воркерам
    for w in workers:
        try:
            await bot.send_message(w, text_order, reply_markup=keyboard)
        except:
            pass

    await message.answer(
        f"🎉 Заявка принята в обработку\n\n"
        f"🆔 ID: #{order_id}\n"
        f"💳 Услуга: Карта под оплату\n"
        f"💰 Сумма: {rub:.2f} RUB\n\n"
        f"📊 Статус: NEW\n"
        f"👨‍💻 Исполнитель: назначается\n\n"
        f"⏳ Ожидайте — мы уже взяли вашу заявку в работу и скоро свяжемся с вами"
    )

# ===== ПРОВЕРКА ОПЛАТЫ =====
async def check_payment_loop(user_id: int, invoice_id: int, to_credit: float):
    """Проверяет оплату каждые 10 секунд в течение 15 минут."""
    for _ in range(90):  # 90 * 10 сек = 15 минут
        await asyncio.sleep(10)
        status = await crypto_check_invoice(invoice_id)

        if status == "paid":
            # Проверяем что не зачислили уже
            cur.execute(
                "SELECT status FROM invoices WHERE invoice_id=%s", (invoice_id,)
            )
            row = cur.fetchone()
            if row and row[0] == "active":
                add_balance(user_id, to_credit)
                cur.execute(
                    "UPDATE invoices SET status='paid' WHERE invoice_id=%s", (invoice_id,)
                )
                balance = get_balance(user_id)
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ Баланс пополнен!\n\n"
                        f"💎 Зачислено: {to_credit:.2f} USDT\n"
                        f"💰 Текущий баланс: {balance:.2f} USDT"
                    )
                except:
                    pass
            return

        if status == "expired":
            cur.execute(
                "UPDATE invoices SET status='expired' WHERE invoice_id=%s", (invoice_id,)
            )
            try:
                await bot.send_message(
                    user_id,
                    f"❌ Инвойс #{invoice_id} истёк. Создайте новый через /lk"
                )
            except:
                pass
            return

# ===== TAKE ORDER =====
@dp.callback_query(F.data.startswith("take_"))
async def take(call: types.CallbackQuery):
    role = get_role(call.from_user.id)

    if role not in ["worker", "admin"]:
        return await call.answer("Нет доступа", show_alert=True)

    order_id = int(call.data.split("_")[1])

    cur.execute(
        "UPDATE orders SET status='IN_PROGRESS', worker_id=%s WHERE id=%s",
        (call.from_user.id, order_id)
    )

    row = cur.execute(
        "SELECT user_id FROM orders WHERE id=%s",
        (order_id,)
    )
    row = cur.fetchone()

    if not row:
        return await call.answer("❌ Заявка не найдена", show_alert=True)

    user_id = row[0]

    client_keyboard = None

    await bot.send_message(
        user_id,
        f"🟢 Ваша заявка #{order_id} принята в работу\n\n"
        f"👨‍💻 Исполнитель уже занимается вашим заказом\n"
        f"⏳ Ожидайте реквизитов для оплаты"
    )

    # Кнопка для воркера — отправить реквизиты
    worker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")]
    ])

    await call.answer("Взял в работу ❤️")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Заявка принята🔥", reply_markup=worker_keyboard)

# ===== SEND REQUISITES — выбор карты =====
@dp.callback_query(F.data.startswith("send_req_"))
async def send_req(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])
    uid = call.from_user.id

    cur.execute("SELECT id, card_number, expiry, bank FROM cards WHERE worker_id=%s", (uid,))
    cards = cur.fetchall()

    if not cards:
        return await call.answer("❌ У вас нет карт. Добавьте карту в /lk", show_alert=True)

    card_buttons = []
    for card in cards:
        cid, number, expiry, bank = card
        masked = f"{number[:6]}{'*'*6}{number[-4:]} · {bank}"
        card_buttons.append([
            InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"req_card_{order_id}_{cid}")
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)

    await call.message.answer(
        f"💳 Выберите карту для заявки #{order_id}:",
        reply_markup=keyboard
    )
    await call.answer()

# ===== SEND REQUISITES — отправка клиенту =====
@dp.callback_query(F.data.startswith("req_card_"))
async def req_card(call: types.CallbackQuery):
    parts = call.data.split("_")
    order_id = int(parts[2])
    card_id = int(parts[3])

    row = cur.execute(
        "SELECT card_number, expiry, cvv, bank FROM cards WHERE id=%s AND worker_id=%s",
        (card_id, call.from_user.id)
    )
    row = cur.fetchone()

    if not row:
        return await call.answer("❌ Карта не найдена", show_alert=True)

    number, expiry, cvv, bank = row

    user_row = cur.execute(
        "SELECT user_id FROM orders WHERE id=%s", (order_id,)
    )
    row = cur.fetchone()

    if not user_row:
        return await call.answer("❌ Заявка не найдена", show_alert=True)

    user_id = user_row[0]

    try:
        await bot.send_message(
            user_id,
            f"💳 Реквизиты для оплаты\n\n"
            f"🏦 Банк: {bank}\n"
            f"💳 Номер карты: {number}\n"
            f"📅 Срок: {expiry}\n"
            f"🔐 CVV: {cvv}\n\n"
            f"📥 Заявка #{order_id}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")]
            ])
        )
    except:
        return await call.answer("❌ Не удалось отправить реквизиты", show_alert=True)

    await call.answer("✅ Реквизиты отправлены клиенту", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ Реквизиты по заявке #{order_id} отправлены клиенту",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order_id}")]
        ])
    )

# ===== REQUEST CODE =====
@dp.callback_query(F.data.startswith("request_code_"))
async def request_code(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])

    row = cur.execute(
        "SELECT worker_id FROM orders WHERE id=%s",
        (order_id,)
    )
    row = cur.fetchone()

    if not row or row[0] is None:
        return await call.answer("❌ Нет исполнителя", show_alert=True)

    worker_id = row[0]

    worker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📥 Отправить код",
                callback_data=f"send_code_{order_id}"
            )
        ]
    ])

    await bot.send_message(
        worker_id,
        f"🔑 Клиент запросил код\n\n📥 Заявка #{order_id}",
        reply_markup=worker_keyboard
    )

    await call.answer("Запрос отправлен 📩")

# ===== SEND CODE =====
@dp.callback_query(F.data.startswith("send_code_"))
async def send_code(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])

    # запоминаем заявку и message_id кнопки за воркером
    pending_code[call.from_user.id] = order_id
    pending_code_msg[call.from_user.id] = call.message.message_id

    await bot.send_message(
        call.from_user.id,
        "🔐 Введите код для клиента одним сообщением:"
    )

    await call.answer()

# ===== WORKER PAID — воркер видит оплату =====
@dp.callback_query(F.data.startswith("worker_confirm_"))
async def worker_confirm(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])
    worker_id = call.from_user.id

    row = cur.execute(
        "SELECT user_id, amount, status FROM orders WHERE id=%s AND worker_id=%s",
        (order_id, worker_id)
    )
    row = cur.fetchone()

    if not row:
        return await call.answer("❌ Заявка не найдена", show_alert=True)

    user_id, amount, status = row

    if status == "DONE":
        return await call.answer("✅ Заявка уже завершена", show_alert=True)

    total = round(amount * 1.2, 2)
    rate = await crypto_get_rate()
    total_usdt = round(total / rate, 4)

    # Уведомляем клиента
    try:
        await bot.send_message(
            user_id,
            f"💰 Исполнитель подтвердил получение оплаты!\n\n"
            f"📥 Заявка #{order_id}\n"
            f"💸 К списанию: {total_usdt:.4f} USDT ({total:.2f} RUB)\n\n"
            f"Подтвердите оплату:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"client_paid_{order_id}_{total_usdt}")]
            ])
        )
    except:
        return await call.answer("❌ Не удалось отправить уведомление клиенту", show_alert=True)

    await call.answer("✅ Запрос отправлен клиенту", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"⏳ Ожидаем подтверждения от клиента по заявке #{order_id}")

# ===== CLIENT PAID — клиент подтверждает =====
@dp.callback_query(F.data.startswith("client_paid_"))
async def client_paid(call: types.CallbackQuery):
    parts = call.data.split("_")
    order_id = int(parts[2])
    total_usdt = float(parts[3])
    uid = call.from_user.id

    row = cur.execute(
        "SELECT worker_id, amount, status FROM orders WHERE id=%s AND user_id=%s",
        (order_id, uid)
    )
    row = cur.fetchone()

    if not row:
        return await call.answer("❌ Заявка не найдена", show_alert=True)

    worker_id, amount, status = row

    if status == "DONE":
        return await call.answer("✅ Заявка уже завершена", show_alert=True)

    # Проверяем баланс клиента
    client_balance = get_balance(uid)
    if client_balance < total_usdt:
        return await call.answer(
            f"❌ Недостаточно средств. Ваш баланс: {client_balance:.4f} USDT",
            show_alert=True
        )

    # Списываем с клиента
    cur.execute("UPDATE balances SET balance = balance - %s WHERE user_id=%s", (total_usdt, uid))

    # Зачисляем воркеру
    cur.execute("""
        INSERT INTO balances (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    """, (worker_id, total_usdt, total_usdt))

    # Закрываем заявку
    cur.execute("UPDATE orders SET status='DONE' WHERE id=%s", (order_id,))

    client_balance_new = get_balance(uid)
    worker_balance = get_balance(worker_id)

    await call.answer("✅ Оплата подтверждена!", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ Заявка #{order_id} завершена!\n\n"
        f"💸 Списано: {total_usdt:.4f} USDT\n"
        f"💰 Ваш баланс: {client_balance_new:.4f} USDT"
    )

    # Уведомляем воркера
    try:
        await bot.send_message(
            worker_id,
            f"✅ Заявка #{order_id} завершена!\n\n"
            f"💎 Зачислено: {total_usdt:.4f} USDT\n"
            f"💰 Ваш баланс: {worker_balance:.4f} USDT"
        )
    except:
        pass

# ===== MAIN =====
async def main():
    load_workers()  # Загружаем воркеров из БД
    await run_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
