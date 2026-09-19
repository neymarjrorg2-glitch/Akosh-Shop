import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from bot.config import ADMIN_IDS
from bot.database import crud
from bot.database.engine import async_session

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # har 6 soatda tekshiradi


async def _check_once(bot: Bot) -> None:
    async with async_session() as session:
        # 1) 3 kun ichida muddati kelayotgan, hali eslatma yuborilmagan buyurtmalar
        reminder_orders = await crud.get_orders_for_hosting_reminder(session)
        for order in reminder_orders:
            days_left = (order.hosting_next_due - datetime.utcnow()).days
            try:
                await bot.send_message(
                    order.user_id,
                    f"⏰ <b>Hosting muddati tugashiga {max(days_left, 0)} kun qoldi!</b>\n\n"
                    f"🤖 Bot: {order.product_name} (#{order.id})\n"
                    f"💵 Oylik hosting narxi: {order.hosting_price:,.0f} so'm\n"
                    f"📅 Muddat: {order.hosting_next_due.strftime('%d.%m.%Y')}\n\n"
                    f"❗️ Agar shu sanagacha to'lov qilmasangiz, botingiz hostingdan uziladi. "
                    f"To'lov qilish uchun admin bilan bog'laning.",
                )
            except Exception as e:
                logger.warning("Hosting eslatmasi yuborilmadi (user_id=%s): %s", order.user_id, e)
            await crud.mark_hosting_reminder_sent(session, order.id)

        # 2) Muddati allaqachon o'tib ketgan buyurtmalar - hostingdan uziladi
        overdue_orders = await crud.get_overdue_hosting_orders(session)
        for order in overdue_orders:
            await crud.disable_hosting(session, order.id)
            try:
                await bot.send_message(
                    order.user_id,
                    f"🚫 <b>Hosting to'xtatildi</b>\n\n"
                    f"🤖 Bot: {order.product_name} (#{order.id})\n\n"
                    f"To'lov muddati o'tib ketgani sababli botingiz hostingdan uzildi. "
                    f"Qayta faollashtirish uchun admin bilan bog'laning.",
                )
            except Exception as e:
                logger.warning("Hosting uzilishi haqida xabar yuborilmadi (user_id=%s): %s", order.user_id, e)

            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🚫 Buyurtma #{order.id} ({order.product_name}, mijoz ID: {order.user_id}) "
                        f"to'lov qilinmagani uchun hostingdan avtomatik uzildi.",
                    )
                except Exception:
                    pass


async def hosting_reminder_loop(bot: Bot) -> None:
    """Fonda doimiy ishlaydi: hosting muddatlarini tekshirib, eslatma yuboradi
    va muddati o'tganlarni avtomatik uzadi. Botning asosiy ishlashiga xalaqit bermaydi."""
    while True:
        try:
            await _check_once(bot)
        except Exception as e:
            logger.exception("Hosting tekshiruvida xatolik: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
