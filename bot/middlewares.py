"""aiogram middleware'lari."""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

import config
import database as db


class BlockedUserMiddleware(BaseMiddleware):
    """Admin tomonidan bloklangan foydalanuvchining barcha xabar va tugmalarini to'xtatadi
    (oldin bloklash faqat Web App API'da ishlardi, botning o'zida emas)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and user.id not in config.ADMIN_IDS:
            row = await db.get_user(user.id)
            if row and row["blocked"]:
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("🚫 Siz bloklangansiz.")
                return None
        return await handler(event, data)
