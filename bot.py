import asyncio
import os
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ===== BOT =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

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
conn.commit()

# ===== GLOBAL STATE =====
pending_code = {}      # worker_id -> order_id (воркер вводит код)
pending_code_msg = {}  # worker_id -> message_id кнопки "SEND CODE"
waiting = {}           # user_id -> True (пользователь вводит сумму)

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
                f"🔐 ВАШ КОД:\n\n{code}\n\n📥 Заявка #{order_id}"
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

    # --- 2. Пользователь вводит сумму заявки ---
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
    await call.message.edit_text(call.message.text + "\n\n🟢 В РАБОТЕ")

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
                text="📤 SEND CODE",
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
