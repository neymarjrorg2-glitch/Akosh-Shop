import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from bot.config import ADMIN_IDS
from bot.database.engine import async_session
from bot.database.models import User

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Har bir so'rovga DB session ulaydi va bloklangan foydalanuvchilarni to'xtatadi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["session"] = session

            tg_user = data.get("event_from_user")
            if tg_user and isinstance(event, Update):
                user = await session.get(User, tg_user.id)
                if user and user.is_blocked and not user.is_admin and tg_user.id not in ADMIN_IDS:
                    await self._notify_blocked(event)
                    return None

            return await handler(event, data)

    @staticmethod
    async def _notify_blocked(event: Update) -> None:
        text = "⛔️ Siz botdan foydalanish huquqidan mahrum qilingansiz."
        try:
            if event.message:
                await event.message.answer(text)
            elif event.callback_query:
                await event.callback_query.answer(text, show_alert=True)
        except Exception as e:
            logger.debug("Bloklangan foydalanuvchiga xabar yuborilmadi: %s", e)
