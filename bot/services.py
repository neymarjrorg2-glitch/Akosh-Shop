"""
Buyurtma va to'lovlarni tasdiqlash/rad etish mantig'i — Telegram bot tugmalari ham,
Web App admin paneli ham SHU funksiyalardan foydalanadi (mantiq bir joyda).

Har bir funksiya avval holatni "egallaydi" (claim: pending -> yangi holat, faqat bir marta
muvaffaqiyatli), pul harakati faqat shundan KEYIN bajariladi. Shuning uchun ikki admin yoki
ikki tez bosish natijasida balansga ikki marta pul qo'shilmaydi / qaytarilmaydi.

Natija kodlari: "ok" | "not_found" | "not_pending" | "invalid_amount"
"""
import math

import config
import database as db
from utils import safe_send


def _valid_amount(amount) -> bool:
    try:
        return math.isfinite(amount) and 0 < amount <= config.MAX_TOPUP_USD
    except TypeError:
        return False


# ---------- Buyurtmalar ----------
async def approve_order(bot, order_id: str, by_id: int | None = None, by_login: str | None = None) -> str:
    order = await db.get_order(order_id)
    if not order:
        return "not_found"
    if not await db.claim_order(order["id"], "approved", by_id, by_login):
        return "not_pending"
    await safe_send(bot, order["user_id"], f"✅ Buyurtmangiz {order['id']} tasdiqlandi!")
    return "ok"


async def cancel_order(bot, order_id: str, by_id: int | None = None, by_login: str | None = None) -> str:
    if not await db.get_order(order_id):
        return "not_found"
    # Bekor qilish va pulni qaytarish — bitta tranzaksiyada (yarim holat qolmaydi)
    order = await db.cancel_order_refund(order_id, by_id, by_login)
    if order is None:
        return "not_pending"
    await safe_send(
        bot, order["user_id"],
        f"❌ Buyurtmangiz {order['id']} bekor qilindi. ${order['amount_usd']:.2f} balansingizga qaytarildi.",
    )
    return "ok"


# ---------- To'lov so'rovlari ----------
async def approve_payment(bot, pr_id: int, amount: float, by_id: int | None = None,
                          by_login: str | None = None) -> str:
    pr = await db.get_payment_request(pr_id)
    if not pr:
        return "not_found"
    if not _valid_amount(amount):
        return "invalid_amount"
    amount = round(amount, 2)
    # Tasdiqlash va balansga qo'shish — bitta tranzaksiyada
    if await db.approve_payment_credit(pr_id, amount, by_id, by_login) is None:
        return "not_pending"
    await safe_send(bot, pr["user_id"], f"✅ To'lovingiz tasdiqlandi! Balansga ${amount:.2f} qo'shildi.")
    await _pay_referral_bonus(bot, pr["user_id"], amount)
    return "ok"


async def reject_payment(bot, pr_id: int, by_id: int | None = None, by_login: str | None = None,
                         block_user: bool = False) -> str:
    pr = await db.get_payment_request(pr_id)
    if not pr:
        return "not_found"
    if not await db.claim_payment_request(pr_id, "rejected", by_id, by_login):
        return "not_pending"
    if block_user:      # spam / firibgarlik
        await db.set_blocked(pr["user_id"], True)
    else:
        await safe_send(bot, pr["user_id"], "❌ To'lov so'rovingiz rad etildi. Chekni qaytadan tekshirib yuboring.")
    return "ok"


async def _pay_referral_bonus(bot, payer_id: int, amount: float):
    payer = await db.get_user(payer_id)
    if not payer or not payer["invited_by"]:
        return
    try:
        percent = float(await db.get_setting("ref_percent", "5"))
    except (TypeError, ValueError):
        return
    if not (0 < percent <= 100):
        return
    bonus = round(amount * percent / 100, 4)
    inviter = await db.get_user(payer["invited_by"])
    if bonus <= 0 or not inviter:
        return
    await db.adjust_balance(inviter["user_id"], bonus)
    await db.add_earned(inviter["user_id"], bonus)
    await safe_send(
        bot, inviter["user_id"],
        f"🤝 Do'stingiz balans to'ldirdi — sizga ${bonus:.2f} referal bonus qo'shildi!",
    )
