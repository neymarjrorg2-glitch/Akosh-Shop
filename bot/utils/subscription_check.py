from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import crud
from bot.database.models import MandatorySubscription


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
        try:
            member = await bot.get_chat_member(chat_id=sub.chat_id, user_id=user_id)
            return member.status not in ("left", "kicked")
        except TelegramBadRequest:
            # bot kanalda admin emas yoki chat topilmadi - xato bo'lmasligi uchun False qaytaramiz
            return False
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
