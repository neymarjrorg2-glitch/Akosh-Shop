"""
StarNest bot — kirish nuqtasi.
aiogram (polling) va aiohttp (REST API) BITTA process ichida, parallel
ravishda ishga tushadi (asyncio.gather orqali).
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

import config
import database as db
import webserver
from handlers import admin as admin_handlers
from handlers import user as user_handlers
from middlewares import BlockedUserMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("starnest")


async def run_bot(bot: Bot, dp: Dispatcher):
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


async def run_webserver(bot: Bot):
    app = webserver.create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()
    logger.info(f"HTTP server {config.PORT}-portda ishga tushdi")
    # Runner tirik turishi uchun cheksiz kutamiz
    await asyncio.Event().wait()


async def main():
    await db.init()
    logger.info("Baza tayyor: %s", config.DB_PATH)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Bloklangan foydalanuvchilar botning hech bir tugmasidan foydalana olmaydi
    dp.message.outer_middleware(BlockedUserMiddleware())
    dp.callback_query.outer_middleware(BlockedUserMiddleware())

    # MUHIM: admin router birinchi ro'yxatdan o'tkaziladi — shunda admin uchun
    # mo'ljallangan matnli tugmalar avval admin.py filtridan o'tadi, mos kelmasa
    # aiogram avtomatik user.py dagi handlerga o'tkazadi.
    dp.include_router(admin_handlers.router)
    dp.include_router(user_handlers.router)

    await asyncio.gather(
        run_bot(bot, dp),
        run_webserver(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
