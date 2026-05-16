"""
Точка входа. Порядок регистрации хендлеров изменен для корректной работы админки.
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

# Настройка вывода логов
sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from config import BOT_TOKEN
from db import init_db
from handlers.common import register_common, load_workers
from handlers.client import register_client
from handlers.worker import register_worker
from handlers.admin import register_admin
from handlers.apply import register_apply

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# =====================================================================
# РЕГИСТРАЦИЯ ХЭНДЛЕРОВ (ПРИОРИТЕТ: АДМИН -> ОСТАЛЬНЫЕ)
# =====================================================================
# Админка ПЕРВОЙ, чтобы её кнопки (stats, бан и т.д.) не перехватывались клиентом
register_admin(dp, bot)  
register_common(dp, bot)
register_apply(dp, bot)
register_worker(dp, bot)
register_client(dp, bot)

# =====================================================================
# WEB СЕРВЕР ДЛЯ RENDER
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
    """Самопинг раз в 10 минут по твоему адресу на Render"""
    while True:
        try:
            await asyncio.sleep(600)
            async with aiohttp.ClientSession() as session:
                # Твой адрес подставлен сюда:
                async with session.get(
                    "https://telega-3gkk.onrender.com/",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        logger.info("Keep-alive ping: OK (200)")
                    else:
                        logger.warning(f"Keep-alive ping: Status {resp.status}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")

# =====================================================================
# ГЛАВНЫЙ ЗАПУСК
# =====================================================================
async def main():
    # Инициализируем БД и список воркеров
    await init_db()
    await load_workers()
    
    # Запускаем фоновые задачи
    asyncio.create_task(run_web())
    asyncio.create_task(keep_alive())
    
    logger.info("Бот запущен. Начинаю опрос Telegram (Polling)...")
    try:
        # skip_updates=True игнорирует старые нажатия кнопок при перезапуске
        await dp.start_polling(bot, skip_updates=True)
    finally:
        logger.info("Закрытие сессии бота...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
