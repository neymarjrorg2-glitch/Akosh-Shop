import asyncio
import logging
import time

import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import (
    ADMIN_IDS,
    ADSGRAM_BLOCK_ID,
    ADSGRAM_COOLDOWN_SECONDS,
    ADSGRAM_LANGUAGE,
    ADSGRAM_TOKEN,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.adsgram.ai/advbot"

_last_shown: dict[int, float] = {}
_tasks: set[asyncio.Task] = set()  # task'lar "yo'qolib" qolmasligi uchun havola saqlaymiz


async def _fetch_ad(user_id: int) -> dict | None:
    params = {"tgid": user_id, "blockid": ADSGRAM_BLOCK_ID, "token": ADSGRAM_TOKEN}
    if ADSGRAM_LANGUAGE:
        params["language"] = ADSGRAM_LANGUAGE

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(API_URL, params=params) as resp:
                if resp.status != 200:
                    return None  # hozir bu foydalanuvchi uchun reklama yo'q
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("AdsGram so'rovida xatolik (user_id=%s): %s", user_id, e)
        return None

    if not isinstance(data, dict) or not data.get("text_html"):
        return None
    return data


async def _send_ad(bot: Bot, user_id: int) -> None:
    ad = await _fetch_ad(user_id)
    if not ad:
        return

    rows = []
    if ad.get("click_url"):
        rows.append([InlineKeyboardButton(text=ad.get("button_name") or "Ochish", url=ad["click_url"])])
    if ad.get("reward_url") and ad.get("button_reward_name"):
        rows.append([InlineKeyboardButton(text=ad["button_reward_name"], url=ad["reward_url"])])
    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

    text = ad["text_html"]
    try:
        # protect_content=True — AdsGram talabi: reklamani forward qilib bo'lmasin
        if ad.get("image_url") and len(text) <= 1024:
            try:
                await bot.send_photo(
                    user_id, ad["image_url"], caption=text, reply_markup=kb, protect_content=True
                )
                return
            except Exception:
                pass  # rasm yuborilmasa, oddiy matn sifatida yuboramiz
        await bot.send_message(user_id, text, reply_markup=kb, protect_content=True)
    except Exception as e:
        logger.warning("Reklamani yuborib bo'lmadi (user_id=%s): %s", user_id, e)


def maybe_show_ad(bot: Bot, user_id: int) -> None:
    """Fonda reklama yuboradi (handlerni sekinlashtirmaydi).
    Cooldown o'tmagan bo'lsa, admin bo'lsa yoki AdsGram sozlanmagan bo'lsa - hech narsa qilmaydi."""
    if not (ADSGRAM_TOKEN and ADSGRAM_BLOCK_ID):
        return
    if user_id in ADMIN_IDS:
        return

    now = time.monotonic()
    last = _last_shown.get(user_id)
    if last is not None and now - last < ADSGRAM_COOLDOWN_SECONDS:
        return
    _last_shown[user_id] = now

    task = asyncio.create_task(_send_ad(bot, user_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
