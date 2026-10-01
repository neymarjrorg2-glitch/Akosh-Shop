"""
Umumiy yordamchilar: xavfsiz xabar yuborish va broadcast (xabar tarqatish).

* safe_send — HTML noto'g'ri bo'lsa oddiy matn sifatida qayta yuboradi,
  Telegram "flood" cheklovida (RetryAfter) kutib turib qayta urinadi,
  hech qachon exception ko'tarmaydi (True/False qaytaradi).
* start_broadcast — bir vaqtda faqat BITTA broadcast, fon vazifasi sifatida,
  soniyasiga ~20 ta xabar tezligida (Telegram limiti ~30/s).
"""
import asyncio
import html
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

import database as db

logger = logging.getLogger("starnest.utils")

esc = html.escape


async def safe_send(bot: Bot, chat_id: int | str, text: str, reply_markup=None) -> bool:
    plain = False
    for _ in range(3):
        try:
            if plain:
                await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=None)
            else:
                await bot.send_message(chat_id, text, reply_markup=reply_markup)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramBadRequest as e:
            if not plain and "parse entities" in str(e).lower():
                plain = True          # noto'g'ri HTML — oddiy matn sifatida yuboramiz
                continue
            logger.warning("Xabar yuborilmadi (%s): %s", chat_id, e)
            return False
        except TelegramForbiddenError:
            return False              # foydalanuvchi botni bloklagan
        except Exception:
            logger.exception("Xabar yuborishda kutilmagan xato (%s)", chat_id)
            return False
    return False


# ---------------------------------------------------------------------------
# Fon vazifalari (HTTP javobni Telegram'ning sekin javobiga bog'lamaslik uchun)
# ---------------------------------------------------------------------------
_bg_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Coroutine'ni fonda ishga tushiradi (havola saqlanadi, xato logga yoziladi)."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _done(t: asyncio.Task):
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception():
            logger.error("Fon vazifasi xatosi: %r", t.exception())

    task.add_done_callback(_done)
    return task


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------
BROADCAST = {"running": False, "total": 0, "sent": 0, "failed": 0, "started_at": 0, "finished_at": 0}
_tasks: set[asyncio.Task] = set()


def start_broadcast(bot: Bot, text: str) -> asyncio.Task | None:
    """Broadcast'ni fon vazifasi sifatida boshlaydi. Boshqasi ishlayotgan bo'lsa None qaytaradi."""
    if BROADCAST["running"]:
        return None
    BROADCAST.update(running=True, total=0, sent=0, failed=0, started_at=int(time.time()), finished_at=0)
    task = asyncio.create_task(_run_broadcast(bot, text))
    _tasks.add(task)                      # havola saqlanmasa, vazifa "axlat yig'ish"da yo'qolishi mumkin
    task.add_done_callback(_tasks.discard)
    return task


async def _run_broadcast(bot: Bot, text: str):
    try:
        users = await db.list_users(limit=1_000_000)
        targets = [u["user_id"] for u in users if not u["blocked"]]
        BROADCAST["total"] = len(targets)
        for uid in targets:
            ok = await safe_send(bot, uid, text)
            BROADCAST["sent" if ok else "failed"] += 1
            await asyncio.sleep(0.05)
    except Exception:
        logger.exception("Broadcast to'xtab qoldi")
    finally:
        BROADCAST.update(running=False, finished_at=int(time.time()))
