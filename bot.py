import asyncio
import logging
import os
import sys
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Настройка логирования
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

async def main():
    # 1. Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # 2. Инициализация ресурсов
    await init_db()
    await load_workers()

    # 3. РЕГИСТРАЦИЯ ХЕНДЛЕРОВ (КРИТИЧЕСКИЙ ПОРЯДОК)
    # Сначала админ, потом общие команды, потом всё остальное
    register_admin(dp, bot)   # САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ
    register_common(dp, bot)  # Базовые команды (/start, /cancel)
    register_apply(dp, bot)   # Анкеты (FSM)
    register_worker(dp, bot)  # Личный кабинет воркера
    register_client(dp, bot)  # Логика клиента (в самом низу)

    # 4. Настройка Web-сервера для Render (Keep-alive)
    asyncio.create_task(run_web())
    asyncio.create_task(keep_alive())

    logger.info("Бот запущен и готов к работе!")
    
    try:
        # 5. Запуск пуллинга
        # skip_updates=True полезно при дебаге, чтобы бот не отвечал на старые нажатия
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()

# --- Вспомогательные функции для Render ---

async def handle(request):
    return web.Response(text="Bot is alive")

async def run_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def keep_alive():
    """Самопинг раз в 10 минут, чтобы Render не 'усыплял' бота"""
    while True:
        try:
            await asyncio.sleep(600)
            async with aiohttp.ClientSession() as session:
                # Замени URL на свой адрес на Render
                async with session.get("https://твой-адрес.onrender.com/") as resp:
                    if resp.status == 200:
                        logger.info("Keep-alive: OK")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
