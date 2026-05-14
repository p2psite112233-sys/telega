import asyncio
import os
import sqlite3
import aiohttp
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
conn = sqlite3.connect("bot.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT,
    worker_id INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS workers (
    user_id INTEGER PRIMARY KEY
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS balances (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0.0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    amount REAL,
    status TEXT DEFAULT 'active'
)
""")
conn.commit()

# ===== GLOBAL STATE =====
pending_code = {}      # worker_id -> order_id (воркер вводит код)
pending_code_msg = {}  # worker_id -> message_id кнопки "SEND CODE"
waiting = {}           # user_id -> True (пользователь вводит сумму)
waiting_topup = {}     # user_id -> True (пользователь вводит сумму пополнения)

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
    rows = cur.execute("SELECT user_id FROM workers").fetchall()
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
    row = cur.execute("SELECT balance FROM balances WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else 0.0

def add_balance(user_id: int, amount: float):
    cur.execute("""
        INSERT INTO balances (user_id, balance) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    """, (user_id, amount, amount))
    conn.commit()

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
        cur.execute("INSERT OR IGNORE INTO workers (user_id) VALUES (?)", (user_id,))
        conn.commit()
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
@dp.callback_query(F.data.startswith("lk_") | F.data.startswith("client_"))
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
            "Введите сумму пополнения в USDT.\n"
            "После оплаты инвойса баланс зачислится автоматически.\n\n"
            "💸 Сумма пополнения: в USDT"
        )
        return await call.answer()

    if call.data == "client_profile":
        uid = call.from_user.id
        username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
        balance = get_balance(uid)

        # Статистика из БД
        closed = cur.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='DONE'", (uid,)
        ).fetchone()[0]
        active = cur.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='IN_PROGRESS'", (uid,)
        ).fetchone()[0]
        paid_count = cur.execute(
            "SELECT COUNT(*) FROM invoices WHERE user_id=? AND status='paid'", (uid,)
        ).fetchone()[0]

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
            "SELECT user_id FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()

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
            amount_usdt = float(text)
        except:
            return await message.answer("❌ Введите число, например 10")

        if amount_usdt <= 0:
            return await message.answer("❌ Сумма должна быть больше 0")

        waiting_topup[uid] = False

        # Получаем курс
        rate = await crypto_get_rate()
        amount_rub = round(amount_usdt * rate, 2)
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
            "INSERT OR IGNORE INTO invoices (invoice_id, user_id, amount) VALUES (?, ?, ?)",
            (invoice_id, uid, to_credit)
        )
        conn.commit()

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Оплатить инвойс", url=pay_url)]
        ])

        await message.answer(
            f"🧾 Счёт на пополнение #{invoice_id}\n\n"
            f"Оплатите инвойс, после чего баланс будет зачислен автоматически.\n\n"
            f"💰 Сумма: {amount_usdt:.2f} USDT (~{amount_rub:.2f} RUB)\n"
            f"Комиссия пополнения: {commission:.2f} USDT\n"
            f"💎 К зачислению: {to_credit:.2f} USDT\n"
            f"🕒 Проверка оплаты: каждые 10 секунд в течение 15 минут",
            reply_markup=keyboard
        )

        # Запускаем проверку оплаты в фоне
        asyncio.create_task(check_payment_loop(uid, invoice_id, to_credit))
        return

    # --- 3. Пользователь вводит сумму заявки ---
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
    conn.commit()

    order_id = cur.lastrowid

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
            row = cur.execute(
                "SELECT status FROM invoices WHERE invoice_id=?", (invoice_id,)
            ).fetchone()
            if row and row[0] == "active":
                add_balance(user_id, to_credit)
                cur.execute(
                    "UPDATE invoices SET status='paid' WHERE invoice_id=?", (invoice_id,)
                )
                conn.commit()
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
                "UPDATE invoices SET status='expired' WHERE invoice_id=?", (invoice_id,)
            )
            conn.commit()
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
        "UPDATE orders SET status='IN_PROGRESS', worker_id=? WHERE id=?",
        (call.from_user.id, order_id)
    )
    conn.commit()

    row = cur.execute(
        "SELECT user_id FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not row:
        return await call.answer("❌ Заявка не найдена", show_alert=True)

    user_id = row[0]

    client_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔑 Запросить код",
                callback_data=f"request_code_{order_id}"
            )
        ]
    ])

    await bot.send_message(
        user_id,
        f"🟢 Ваша заявка #{order_id} принята в работу\n\n"
        f"👨‍💻 Исполнитель уже занимается вашим заказом\n"
        f"⏳ Ожидайте завершения",
        reply_markup=client_keyboard
    )

    await call.answer("Взял в работу ❤️")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Заявка принята🔥")

# ===== REQUEST CODE =====
@dp.callback_query(F.data.startswith("request_code_"))
async def request_code(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])

    row = cur.execute(
        "SELECT worker_id FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

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

# ===== MAIN =====
async def main():
    load_workers()  # Загружаем воркеров из БД
    await run_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
