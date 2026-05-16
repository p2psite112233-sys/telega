"""
Точка входа. Весь код разбит по файлам:
- config.py           — токены, константы
- db.py               — PostgreSQL asyncpg пул
- utils/cards.py      — парсер карт
- utils/crypto.py     — CryptoBot API
- handlers/common.py  — /start, /setworker, базовые стейты и отмена
- handlers/worker.py  — /lk, заявки воркера
- handlers/client.py  — кнопки клиента, оплата
- handlers/apply.py   — анкета "Стать исполнителем"
"""

import asyncio
import logging
import os
import sys
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Принудительный сброс буфера для красивых логов в Render/Docker
sys.stdout.reconfigure(line_buffering=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logger.info("==> Starting bot initialization...")

from config import BOT_TOKEN
from db import init_db, close_db  # Предполагается, что в db.py есть закрытие пула
from handlers.common import register_common, load_workers
from handlers.client import register_client
from handlers.worker import register_worker
from handlers.admin import register_admin
from handlers.apply import register_apply

# Инициализация бота с дефолтным HTML-парсингом
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# =====================================================================
# РЕГИСТРАЦИЯ ХЭНДЛЕРОВ (ПОРЯДОК КРИТИЧЕСКИ ВАЖЕН!)
# =====================================================================
# 1. Сначала общие команды (/start, /cancel)
register_common(dp, bot)
# 2. Затем анкета "Стать исполнителем"
register_apply(dp, bot)
# 3. Затем личный кабинет и логика клиента
register_client(dp, bot)
# 4. Профиль и заявки воркера
register_worker(dp, bot)
# 5. Админ-панель (замыкающая)
register_admin(dp, bot)


# =====================================================================
# WEB СЕРВЕР И КИП-АЛАЙВ ДЛЯ РЕНДЕРА
# =====================================================================
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
    logger.info(f"Web server started on port {port}")

async def keep_alive():
    """Самопинг раз в 10 минут, чтобы Render не усыплял бесплатный контейнер"""
    while True:
        try:
            await asyncio.sleep(600)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://telega-3gkk.onrender.com/",
                    timeout=aiohttp.ClientTimeout(total=5)
                ):
                    logger.info("Keep-alive ping successful")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")


# =====================================================================
# ГЛАВНЫЙ СТАРТ И КОРРЕКТНОЕ ЗАКРЫТИЕ (GRACEFUL SHUTDOWN)
# =====================================================================
async def main():
    # Инициализация ресурсов
    await init_db()
    await load_workers()
    
    # Фоновые задачи
    asyncio.create_task(keep_alive())
    await run_web()
    
    logger.info("Bot is polling now...")
    try:
        # Запуск лонг-поллинга
        await dp.start_polling(bot)
    finally:
        # Корректное закрытие сессий при остановке проекта
        logger.info("Shutting down... Closing active sessions.")
        await bot.session.close()
        try:
            await close_db()
        except NameError:
            pass
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
