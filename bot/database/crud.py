from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_IDS, DEFAULT_REFERRAL_PERCENT, ORDER_DEADLINE_HOURS
from bot.database.models import (
    User,
    BotProduct,
    Order,
    Transaction,
    MandatorySubscription,
    UserSubscriptionConfirmation,
    Setting,
)


# ---------- FOYDALANUVCHI ----------

async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    referred_by: Optional[int] = None,
) -> tuple[User, bool]:
    """Foydalanuvchini qaytaradi, agar mavjud bo'lmasa - yangi yaratadi.
    Ikkinchi qiymat - foydalanuvchi yangi yaratilganini bildiradi (True/False)."""
    user = await session.get(User, user_id)
    if user:
        # profil ma'lumotlarini yangilab turamiz
        user.username = username
        user.full_name = full_name
        await session.commit()
        return user, False

    is_admin = user_id in ADMIN_IDS

    # o'zini-o'zi referral qilishning oldini olish
    if referred_by == user_id:
        referred_by = None

    # taklif qiluvchi haqiqatan mavjudligini tekshiramiz
    if referred_by:
        inviter = await session.get(User, referred_by)
        if not inviter:
            referred_by = None

    user = User(
        id=user_id,
        username=username,
        full_name=full_name,
        referred_by=referred_by,
        is_admin=is_admin,
    )
    session.add(user)
    await session.commit()
    return user, True


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def set_phone(session: AsyncSession, user_id: int, phone: str) -> None:
    user = await session.get(User, user_id)
    if user:
        user.phone = phone
        await session.commit()


async def adjust_balance(
    session: AsyncSession,
    user_id: int,
    amount: float,
    tx_type: str,
    description: Optional[str] = None,
) -> None:
    """Balansni o'zgartiradi (musbat - qo'shish, manfiy - ayirish) va tranzaksiya yozadi."""
    user = await session.get(User, user_id)
    if not user:
        return
    user.balance += amount
    if tx_type == "topup":
        user.total_topped_up += amount
    session.add(Transaction(user_id=user_id, amount=amount, type=tx_type, description=description))
    await session.commit()


async def get_referral_percent(session: AsyncSession) -> float:
    setting = await session.get(Setting, "referral_percent")
    if setting:
        try:
            return float(setting.value)
        except ValueError:
            pass
    return DEFAULT_REFERRAL_PERCENT


async def set_referral_percent(session: AsyncSession, percent: float) -> None:
    setting = await session.get(Setting, "referral_percent")
    if setting:
        setting.value = str(percent)
    else:
        session.add(Setting(key="referral_percent", value=str(percent)))
    await session.commit()


async def apply_referral_bonus_if_first_topup(session: AsyncSession, user: User, topup_amount: float) -> None:
    """Foydalanuvchi birinchi marta balans to'ldirganda, uni taklif qilgan odamga bonus beradi.
    Faqat 1 marta (birinchi to'ldirishda) ishlaydi."""
    if not user.referred_by:
        return

    # avval to'ldirganmi yoki yo'qmi - shu to'ldirishdan OLDINGI holatga qaraymiz
    is_first_topup = user.total_topped_up == topup_amount  # balans shu to'lovdan oldin 0 bo'lgan bo'lsa

    if not is_first_topup:
        return

    inviter = await session.get(User, user.referred_by)
    if not inviter:
        return

    percent = await get_referral_percent(session)
    bonus = round(topup_amount * percent / 100, 2)
    if bonus <= 0:
        return

    inviter.balance += bonus
    inviter.referral_earned += bonus
    inviter.referral_count += 1
    session.add(
        Transaction(
            user_id=inviter.id,
            amount=bonus,
            type="referral_bonus",
            description=f"Referal bonus: {user.id} foydalanuvchidan ({percent}%)",
        )
    )
    await session.commit()


# ---------- KATALOG ----------

async def get_active_products(session: AsyncSession) -> Sequence[BotProduct]:
    result = await session.execute(
        select(BotProduct).where(BotProduct.is_active == True).order_by(BotProduct.id)  # noqa: E712
    )
    return result.scalars().all()


async def get_product(session: AsyncSession, product_id: int) -> Optional[BotProduct]:
    return await session.get(BotProduct, product_id)


async def add_product(
    session: AsyncSession, name: str, description: str, price: float, category: Optional[str] = None
) -> BotProduct:
    product = BotProduct(name=name, description=description, price=price, category=category)
    session.add(product)
    await session.commit()
    return product


async def toggle_product(session: AsyncSession, product_id: int) -> Optional[BotProduct]:
    product = await session.get(BotProduct, product_id)
    if product:
        product.is_active = not product.is_active
        await session.commit()
    return product


# ---------- BUYURTMALAR ----------

async def create_order(session: AsyncSession, user_id: int, product: BotProduct) -> Order:
    deadline = datetime.utcnow() + timedelta(hours=ORDER_DEADLINE_HOURS)
    order = Order(
        user_id=user_id,
        product_id=product.id,
        product_name=product.name,
        price=product.price,
        deadline=deadline,
    )
    session.add(order)
    await session.commit()
    return order


async def get_user_orders(session: AsyncSession, user_id: int) -> Sequence[Order]:
    result = await session.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    return result.scalars().all()


async def get_orders_by_status(session: AsyncSession, status: str) -> Sequence[Order]:
    result = await session.execute(
        select(Order).where(Order.status == status).order_by(Order.created_at)
    )
    return result.scalars().all()


async def update_order_status(
    session: AsyncSession, order_id: int, status: str, admin_note: Optional[str] = None
) -> Optional[Order]:
    order = await session.get(Order, order_id)
    if order:
        order.status = status
        if admin_note:
            order.admin_note = admin_note
        await session.commit()
    return order


# ---------- MAJBURIY OBUNALAR ----------

async def get_active_subscriptions(session: AsyncSession) -> Sequence[MandatorySubscription]:
    result = await session.execute(
        select(MandatorySubscription)
        .where(MandatorySubscription.is_active == True)  # noqa: E712
        .order_by(MandatorySubscription.order_index)
    )
    return result.scalars().all()


async def add_subscription(
    session: AsyncSession, platform: str, title: str, url: str, chat_id: Optional[str] = None
) -> MandatorySubscription:
    sub = MandatorySubscription(platform=platform, title=title, url=url, chat_id=chat_id)
    session.add(sub)
    await session.commit()
    return sub


async def remove_subscription(session: AsyncSession, sub_id: int) -> None:
    sub = await session.get(MandatorySubscription, sub_id)
    if sub:
        await session.delete(sub)
        await session.commit()


async def confirm_subscription(session: AsyncSession, user_id: int, sub_id: int) -> None:
    existing = await session.execute(
        select(UserSubscriptionConfirmation).where(
            UserSubscriptionConfirmation.user_id == user_id,
            UserSubscriptionConfirmation.subscription_id == sub_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    session.add(UserSubscriptionConfirmation(user_id=user_id, subscription_id=sub_id))
    await session.commit()


async def is_subscription_confirmed(session: AsyncSession, user_id: int, sub_id: int) -> bool:
    result = await session.execute(
        select(UserSubscriptionConfirmation).where(
            UserSubscriptionConfirmation.user_id == user_id,
            UserSubscriptionConfirmation.subscription_id == sub_id,
        )
    )
    return result.scalar_one_or_none() is not None


# ---------- STATISTIKA ----------

async def get_stats(session: AsyncSession) -> dict:
    total_users = await session.scalar(select(func.count(User.id)))
    total_balance = await session.scalar(select(func.sum(User.balance))) or 0
    total_topup = await session.scalar(select(func.sum(User.total_topped_up))) or 0
    total_orders = await session.scalar(select(func.count(Order.id)))
    pending_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "pending"))
    done_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "done"))

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_users = await session.scalar(select(func.count(User.id)).where(User.created_at >= today_start))

    return {
        "total_users": total_users or 0,
        "today_users": today_users or 0,
        "total_balance": total_balance,
        "total_topup": total_topup,
        "total_orders": total_orders or 0,
        "pending_orders": pending_orders or 0,
        "done_orders": done_orders or 0,
    }
