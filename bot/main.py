import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.database.engine import init_db
from bot.middlewares import DatabaseMiddleware
from bot.handlers import user as user_handlers
from bot.handlers import admin as admin_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env faylida yoki Railway sozlamalarida ko'rsating.")

    await init_db()
    logger.info("Ma'lumotlar bazasi tayyor.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(DatabaseMiddleware())

    # Admin routerini birinchi ulaymiz, shunda admin tugmalari
    # oddiy foydalanuvchi handlerlari bilan to'qnashmaydi
    dp.include_router(admin_handlers.router)
    dp.include_router(user_handlers.router)

    logger.info("Bot ishga tushdi.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
