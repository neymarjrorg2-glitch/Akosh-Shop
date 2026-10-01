"""
Majburiy obuna tekshiruvi. `force_sub_enabled` sozlamasi yoqilgan bo'lsa,
foydalanuvchi barcha kanallarga obuna bo'lmaguncha botdan foydalana olmaydi.
Bot va Web App API ikkalasi ham shu funksiyadan foydalanadi.
"""
import logging

from aiogram import Bot

import database as db

logger = logging.getLogger("starnest.force_sub")


async def get_unsubscribed_channels(bot: Bot, user_id: int):
    enabled = await db.get_setting("force_sub_enabled", "0")
    if enabled != "1":
        return []

    channels = await db.list_channels()
    if not channels:
        return []

    unsubscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
            if member.status in ("left", "kicked"):
                unsubscribed.append(ch)
        except Exception as e:
            # Bot kanalda admin bo'lmasa yoki chat topilmasa tekshirib bo'lmaydi.
            # Butun botni qulflab qo'ymaslik uchun bunday kanal e'tiborsiz qoldiriladi
            # (obuna talab qilinmaydi), lekin xato logga yoziladi.
            logger.warning("Kanal %s tekshirilmadi (bot kanalda adminmi?): %s", ch["chat_id"], e)
            continue
    return unsubscribed
