import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import crud
from bot.database.models import MandatorySubscription

logger = logging.getLogger(__name__)


async def check_single_subscription(
    bot: Bot, session: AsyncSession, user_id: int, sub: MandatorySubscription
) -> bool:
    """Bitta obunani tekshiradi. Turi bo'yicha usul farqlanadi:

    - telegram_join: kanalga a'zo bo'lganini Telegram API orqali tekshiradi
    - telegram_request: kanalga a'zo bo'lish shart emas, faqat foydalanuvchi
      "Zayavka tashladim" tugmasini bosgani (tasdiqlagani) tekshiriladi
    - instagram / youtube: tashqi tekshirish imkoni yo'q, faqat foydalanuvchi
      "Bajardim" tugmasini bosgani tekshiriladi
    """
    if sub.platform == "telegram_join":
        if not sub.chat_id:
            logger.warning("Obuna '%s' (id=%s) uchun chat_id kiritilmagan.", sub.title, sub.id)
            return False
        try:
            member = await bot.get_chat_member(chat_id=sub.chat_id, user_id=user_id)
        except TelegramAPIError as e:
            # bot kanalda admin emas, chat topilmadi yoki Telegram vaqtincha javob bermadi -
            # xato bo'lmasligi uchun False qaytaramiz (sababi logda ko'rinadi)
            logger.warning("Obunani tekshirib bo'lmadi (%s, chat_id=%s): %s", sub.title, sub.chat_id, e)
            return False
        if member.status in ("left", "kicked"):
            return False
        if member.status == "restricted":
            # cheklangan foydalanuvchi kanal a'zosi bo'lmasligi ham mumkin
            return bool(getattr(member, "is_member", False))
        return True
    else:
        # telegram_request, instagram, youtube - qo'lda tasdiqlash orqali
        return await crud.is_subscription_confirmed(session, user_id, sub.id)


async def check_all_subscriptions(
    bot: Bot, session: AsyncSession, user_id: int
) -> tuple[bool, list[MandatorySubscription]]:
    """Barcha faol obunalarni tekshiradi.
    Qaytaradi: (hammasi_bajarilganmi, bajarilmagan_obunalar_royxati)"""
    subs = await crud.get_active_subscriptions(session)
    pending = []
    for sub in subs:
        ok = await check_single_subscription(bot, session, user_id, sub)
        if not ok:
            pending.append(sub)
    return len(pending) == 0, pending
