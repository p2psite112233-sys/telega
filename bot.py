import asyncio
import os
import sys
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

sys.stdout.reconfigure(line_buffering=True)
print("==> Starting bot...", flush=True)

# Теперь ВСЁ на месте: и токен, и ID админа из твоего конфига
from config import BOT_TOKEN, ADMIN_ID
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
from handlers.phone import register_phone

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
register_phone(dp, bot)


# =======================================================
# ВРЕМЕННЫЙ ХЕНДЛЕР ДЛЯ ПАРСИНГА ПРЕМИУМ-ЭМОДЗИ (ТОЛЬКО ДЛЯ АДМИНА)
# =======================================================
@dp.message()
async def get_premium_emoji_id(message: Message):
    # Если пишет не админ, бот просто игнорирует этот хендлер и идет в меню
    if message.from_user.id != ADMIN_ID:
        return True

    # Проверяем, если само сообщение — это один премиум-эмодзи
    if message.custom_emoji_id:
        await message.answer(
            f"💎 <b>ID премиум-эмодзи:</b>\n<code>{message.custom_emoji_id}</code>\n\n"
            f"Строка для кода:\n<code>&lt;tg-emoji emoji-id='{message.custom_emoji_id}'&gt;⭐&lt;/tg-emoji&gt;</code>"
        )
        return

    # Проверяем, если премиум-эмодзи зашиты внутри текста сообщения
    if message.entities:
        for entity in message.entities:
            if entity.type == "custom_emoji":
                await message.answer(
                    f"💎 <b>ID эмодзи из текста:</b>\n<code>{entity.custom_emoji_id}</code>\n\n"
                    f"Строка для кода:\n<code>&lt;tg-emoji emoji-id='{entity.custom_emoji_id}'&gt;⭐&lt;/tg-emoji&gt;</code>"
                )
                return

    # Если админ написал обычный текст, пускаем его дальше в общее меню
    return True
# =======================================================


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
