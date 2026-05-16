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

# Принудительный сброс буфера для красивых логов в Render
sys.stdout.reconfigure(line_buffering=True)

# Настройка красивого вывода логов в консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logger.info("==> Starting bot initialization...")

from config import BOT_TOKEN
from db import init_db
from handlers.common import register_common, load_workers
from handlers.client import register_client
from handlers.worker import register_worker
from handlers.admin import register_admin
from handlers.apply import register_apply

# Инициализация бота с дефолтным HTML-парсингом (теперь parse_mode внутри функций можно не писать)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# =====================================================================
# РЕГИСТРАЦИЯ ХЭНДЛЕРОВ (ПОРЯДОК ИДЕАЛЕН ДЛЯ КОНВЕЙЕРА AIOGRAM)
# =====================================================================
register_common(dp, bot)  # 1. Сначала база, отмена и команда /start
register_client(dp, bot)  # 2. Логика клиента (меню, заявки, профиль)
register_apply(dp, bot)   # 3. Анкета "Стать исполнителем"
register_worker(dp, bot)  # 4. Профиль воркера и прием заказов
register_admin(dp, bot)   # 5. Админка (всегда в самом низу)


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
    """Самопинг раз в 10 минут, чтобы Render не усыплял бота"""
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
# ГЛАВНЫЙ ЗАПУСК СЕССИИ
# =====================================================================
async def main():
    # Инициализируем ресурсы проекта
    await init_db()
    await load_workers()
    
    # Запускаем фоновые процессы веб-сервера
    asyncio.create_task(keep_alive())
    await run_web()
    
    logger.info("Bot is polling now...")
    try:
        # Запуск лонг-поллинга Telegram
        await dp.start_polling(bot)
    finally:
        # Плавное отключение сессии бота, если Render перезагружает контейнер
        logger.info("Shutting down... Closing bot session.")
        await bot.session.close()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
