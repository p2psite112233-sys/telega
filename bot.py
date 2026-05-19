import asyncio
import os
import sys
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
sys.stdout.reconfigure(line_buffering=True)
print("==> Starting bot...", flush=True)
from config import BOT_TOKEN
from db import init_db
from handlers.common import register_common, load_workers, cleanup_expired_orders
from handlers.worker import register_worker
from handlers.client import register_client
from handlers.admin import register_admin
from handlers.apply import register_apply
from handlers.dispute import register_dispute
from handlers.chat import register_chat
from handlers.withdraw import register_withdraw
from handlers.transfer import register_transfer

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Порядок важен!
register_admin(dp, bot)
register_dispute(dp, bot)  # Спор первым — FSM фото
register_chat(dp, bot)
register_client(dp, bot)
register_apply(dp, bot)
register_worker(dp, bot)
register_withdraw(dp, bot)
register_transfer(dp, bot)
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
                        "https://telega-3gkk.onrender.com/",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ):
                        pass
                except:
                    pass
        except:
            pass

async def main():
    await init_db()
    await load_workers()
    asyncio.create_task(keep_alive())
    asyncio.create_task(run_web())
    asyncio.create_task(cleanup_expired_orders(bot))
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
