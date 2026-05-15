"""
Точка входа. Весь код разбит по файлам:
- config.py        — токены, константы
- db.py            — PostgreSQL, таблицы, хелперы
- utils/cards.py   — парсер карт
- utils/crypto.py  — CryptoBot API
- handlers/common.py  — /start, /setworker, text_handler
- handlers/worker.py  — /lk, заявки воркера
- handlers/client.py  — кнопки клиента, оплата
"""
import asyncio
import os
import sys
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher

sys.stdout.reconfigure(line_buffering=True)
print("==> Starting bot...", flush=True)

from config import BOT_TOKEN
import db
from handlers.common import register_common, load_workers
from handlers.worker import register_worker
from handlers.client import register_client

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

register_client(dp, bot)
register_worker(dp, bot)
register_common(dp, bot)


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

async def keep_alive():
    while True:
        try:
            await asyncio.sleep(600)
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        "https://telega-7hqb.onrender.com/",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ):
                        pass
                except:
                    pass
        except:
            pass

async def main():
    load_workers()
    asyncio.create_task(keep_alive())
    await run_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
