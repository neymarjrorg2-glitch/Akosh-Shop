import calendar
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_IDS, DEFAULT_REFERRAL_PERCENT, ORDER_DEADLINE_HOURS
from bot.database.models import (
    User,
    BotProduct,
    Order,
    Transaction,
    TopupRequest,
    MandatorySubscription,
    UserSubscriptionConfirmation,
    Setting,
)

MIN_TOPUP_AMOUNT = 5000


# ---------- FOYDALANUVCHI ----------

async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    referred_by: Optional[int] = None,
) -> tuple[User, bool]:
    user = await session.get(User, user_id)
    if user:
        user.username = username
        user.full_name = full_name
        await session.commit()
        return user, False

    is_admin = user_id in ADMIN_IDS

    if referred_by == user_id:
        referred_by = None

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


async def set_user_blocked(session: AsyncSession, user_id: int, blocked: bool) -> Optional[User]:
    user = await session.get(User, user_id)
    if user:
        user.is_blocked = blocked
        await session.commit()
    return user


async def adjust_balance(
    session: AsyncSession,
    user_id: int,
    amount: float,
    tx_type: str,
    description: Optional[str] = None,
) -> None:
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


async def mark_referral_qualified(session: AsyncSession, user: User) -> Optional[User]:
    """Foydalanuvchi majburiy obuna + telefon tasdiqlashni bajargach chaqiriladi.
    Taklif qiluvchining referral_count'ini +1 qiladi (pul emas, faqat hisob).
    Qaytaradi: taklif qiluvchi (agar bo'lsa), aks holda None."""
    if not user.referred_by or user.referral_qualified:
        return None

    inviter = await session.get(User, user.referred_by)
    if not inviter:
        return None

    user.referral_qualified = True
    inviter.referral_count += 1
    await session.commit()
    return inviter


async def apply_referral_bonus_if_first_topup(session: AsyncSession, user: User, topup_amount: float) -> None:
    """Foydalanuvchi birinchi marta balans to'ldirganda, uni taklif qilgan odamga PUL bonus beradi.
    Faqat referral_qualified bo'lgan (obuna+telefonni tasdiqlagan) foydalanuvchilar uchun ishlaydi."""
    if not user.referred_by or not user.referral_qualified:
        return

    is_first_topup = user.total_topped_up == topup_amount  # to'lovdan oldin 0 bo'lgan bo'lsa

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
    session.add(
        Transaction(
            user_id=inviter.id,
            amount=bonus,
            type="referral_bonus",
            description=f"Referal bonus: {user.id} foydalanuvchidan ({percent}%)",
        )
    )
    await session.commit()


# ---------- UMUMIY SOZLAMALAR (matnlar va h.k.) ----------

DEFAULT_TEXTS = {
    "card_info": "💳 0000 0000 0000 0000",
    "help_text": (
        "🆘 <b>Yordam</b>\n\n"
        "Savol yoki muammo bo'lsa, admin bilan bog'laning.\n"
        "Buyurtmangiz holatini \"🧾 Buyurtmalarim\" bo'limidan kuzatishingiz mumkin."
    ),
    "welcome_text": "✅ Xush kelibsiz! Botdan to'liq foydalanishingiz mumkin.",
}

TEXT_LABELS = {
    "card_info": "💳 Karta ma'lumotlari",
    "help_text": "🆘 Yordam matni",
    "welcome_text": "👋 Salomlashuv matni",
}


async def get_text(session: AsyncSession, key: str) -> str:
    setting = await session.get(Setting, key)
    if setting:
        return setting.value
    return DEFAULT_TEXTS.get(key, "")


async def set_text(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(Setting, key)
    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()


# ---------- KATALOG ----------

async def get_active_products(session: AsyncSession) -> Sequence[BotProduct]:
    result = await session.execute(
        select(BotProduct).where(BotProduct.is_active == True).order_by(BotProduct.id)  # noqa: E712
    )
    return result.scalars().all()


async def get_all_products(session: AsyncSession) -> Sequence[BotProduct]:
    result = await session.execute(select(BotProduct).order_by(BotProduct.id))
    return result.scalars().all()


async def get_product(session: AsyncSession, product_id: int) -> Optional[BotProduct]:
    return await session.get(BotProduct, product_id)


async def add_product(
    session: AsyncSession,
    name: str,
    description: str,
    price: float,
    hosting_price: float = 0,
    category: Optional[str] = None,
    media_file_id: Optional[str] = None,
    media_type: Optional[str] = None,
) -> BotProduct:
    product = BotProduct(
        name=name,
        description=description,
        price=price,
        hosting_price=hosting_price,
        category=category,
        media_file_id=media_file_id,
        media_type=media_type,
    )
    session.add(product)
    await session.commit()
    return product


async def update_product_field(session: AsyncSession, product_id: int, field: str, value) -> Optional[BotProduct]:
    product = await session.get(BotProduct, product_id)
    if product and hasattr(product, field):
        setattr(product, field, value)
        await session.commit()
    return product


async def toggle_product(session: AsyncSession, product_id: int) -> Optional[BotProduct]:
    product = await session.get(BotProduct, product_id)
    if product:
        product.is_active = not product.is_active
        await session.commit()
    return product


async def delete_product(session: AsyncSession, product_id: int) -> str:
    """Mahsulotni butunlay o'chirishga urinadi. Agar unga buyurtmalar bog'liq bo'lsa,
    o'rniga faqat yashiradi (deaktiv qiladi). Natija: "deleted" yoki "deactivated"."""
    product = await session.get(BotProduct, product_id)
    if not product:
        return "not_found"
    try:
        await session.delete(product)
        await session.commit()
        return "deleted"
    except IntegrityError:
        await session.rollback()
        product = await session.get(BotProduct, product_id)
        product.is_active = False
        await session.commit()
        return "deactivated"


# ---------- BUYURTMALAR ----------

async def create_order(
    session: AsyncSession,
    user_id: int,
    product: BotProduct,
    api_key: Optional[str] = None,
) -> Order:
    deadline = datetime.utcnow() + timedelta(hours=ORDER_DEADLINE_HOURS)
    order = Order(
        user_id=user_id,
        product_id=product.id,
        product_name=product.name,
        price=product.price,
        api_key=api_key,
        hosting_price=product.hosting_price,
        deadline=deadline,
    )
    session.add(order)
    await session.commit()
    return order


def add_months(dt: datetime, months: int = 1) -> datetime:
    """Berilgan sanaga N oy qo'shadi, oyning kunlar soni farqini hisobga oladi
    (masalan 31-yanvar + 1 oy = 28/29-fevral)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


async def activate_hosting_on_done(session: AsyncSession, order: Order) -> None:
    """Buyurtma 'bajarildi' deb belgilanganda, agar hosting narxi bo'lsa,
    keyingi to'lov sanasini (1 oydan keyin) belgilaydi."""
    if order.hosting_price and order.hosting_price > 0:
        order.hosting_next_due = add_months(datetime.utcnow(), 1)
        order.hosting_active = True
        order.hosting_reminder_sent = False
        await session.commit()


async def renew_hosting(session: AsyncSession, order_id: int) -> Optional[Order]:
    """Admin hosting to'lovi qilinganini qayd etganda chaqiriladi - muddatni 1 oyga uzaytiradi."""
    order = await session.get(Order, order_id)
    if not order:
        return None
    base = order.hosting_next_due if order.hosting_next_due and order.hosting_next_due > datetime.utcnow() else datetime.utcnow()
    order.hosting_next_due = add_months(base, 1)
    order.hosting_active = True
    order.hosting_reminder_sent = False
    await session.commit()
    return order


async def disable_hosting(session: AsyncSession, order_id: int) -> Optional[Order]:
    order = await session.get(Order, order_id)
    if order:
        order.hosting_active = False
        await session.commit()
    return order


async def get_orders_for_hosting_reminder(session: AsyncSession) -> Sequence[Order]:
    """3 kun ichida to'lov muddati kelayotgan, hali eslatma yuborilmagan buyurtmalar."""
    now = datetime.utcnow()
    soon = now + timedelta(days=3)
    result = await session.execute(
        select(Order).where(
            Order.hosting_active == True,  # noqa: E712
            Order.hosting_reminder_sent == False,  # noqa: E712
            Order.hosting_next_due.isnot(None),
            Order.hosting_next_due <= soon,
            Order.hosting_next_due > now,
        )
    )
    return result.scalars().all()


async def get_overdue_hosting_orders(session: AsyncSession) -> Sequence[Order]:
    """Muddati o'tib ketgan, hali faol (uzilmagan) hosting buyurtmalari."""
    now = datetime.utcnow()
    result = await session.execute(
        select(Order).where(
            Order.hosting_active == True,  # noqa: E712
            Order.hosting_next_due.isnot(None),
            Order.hosting_next_due <= now,
        )
    )
    return result.scalars().all()


async def mark_hosting_reminder_sent(session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if order:
        order.hosting_reminder_sent = True
        await session.commit()


async def get_user_hosted_orders(session: AsyncSession, user_id: int) -> Sequence[Order]:
    """Foydalanuvchining hosting narxi bor va bajarilgan buyurtmalari (uning "botlari")."""
    result = await session.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.status == "done",
            Order.hosting_price > 0,
        ).order_by(Order.created_at.desc())
    )
    return result.scalars().all()


async def get_order(session: AsyncSession, order_id: int) -> Optional[Order]:
    return await session.get(Order, order_id)


async def set_order_api_key(session: AsyncSession, order_id: int, api_key: str) -> Optional[Order]:
    order = await session.get(Order, order_id)
    if order:
        order.api_key = api_key
        await session.commit()
    return order


async def set_order_admin_id(session: AsyncSession, order_id: int, admin_telegram_id: str) -> Optional[Order]:
    order = await session.get(Order, order_id)
    if order:
        order.admin_telegram_id = admin_telegram_id
        await session.commit()
    return order


async def get_user_orders(session: AsyncSession, user_id: int) -> Sequence[Order]:
    result = await session.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    return result.scalars().all()


async def get_active_orders(session: AsyncSession) -> Sequence[Order]:
    """Admin uchun: hali yakunlanmagan (pending yoki in_progress) buyurtmalar."""
    result = await session.execute(
        select(Order).where(Order.status.in_(["pending", "in_progress"])).order_by(Order.created_at)
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


# ---------- TO'LOV (TOPUP) SO'ROVLARI ----------

async def create_topup_request(
    session: AsyncSession, user_id: int, amount: float, receipt_file_id: Optional[str] = None
) -> TopupRequest:
    req = TopupRequest(user_id=user_id, amount=amount, receipt_file_id=receipt_file_id)
    session.add(req)
    await session.commit()
    return req


async def get_topup_request(session: AsyncSession, request_id: int) -> Optional[TopupRequest]:
    return await session.get(TopupRequest, request_id)


async def get_pending_topup_requests(session: AsyncSession) -> Sequence[TopupRequest]:
    result = await session.execute(
        select(TopupRequest).where(TopupRequest.status == "pending").order_by(TopupRequest.created_at)
    )
    return result.scalars().all()


async def process_topup_request(
    session: AsyncSession, request_id: int, approve: bool, admin_id: int
) -> Optional[TopupRequest]:
    req = await session.get(TopupRequest, request_id)
    if not req or req.status != "pending":
        return req

    req.status = "approved" if approve else "rejected"
    req.processed_at = datetime.utcnow()
    req.processed_by = admin_id
    await session.commit()

    if approve:
        await adjust_balance(session, req.user_id, req.amount, "topup", description=f"To'lov so'rovi #{req.id}")
        user = await get_user(session, req.user_id)
        if user:
            await apply_referral_bonus_if_first_topup(session, user, req.amount)

    return req


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


# ---------- ADMINLAR ----------

async def is_user_admin(session: AsyncSession, user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    user = await session.get(User, user_id)
    return bool(user and user.is_admin)


async def add_admin(session: AsyncSession, user_id: int) -> Optional[User]:
    user = await session.get(User, user_id)
    if not user:
        return None
    user.is_admin = True
    await session.commit()
    return user


async def remove_admin(session: AsyncSession, user_id: int) -> bool:
    """DB orqali qo'shilgan adminni olib tashlaydi. ENV (asosiy) adminlarni olib tashlab bo'lmaydi."""
    if user_id in ADMIN_IDS:
        return False
    user = await session.get(User, user_id)
    if user and user.is_admin:
        user.is_admin = False
        await session.commit()
        return True
    return False


async def get_db_admins(session: AsyncSession) -> Sequence[User]:
    result = await session.execute(select(User).where(User.is_admin == True))  # noqa: E712
    return result.scalars().all()


# ---------- STATISTIKA ----------

async def get_stats(session: AsyncSession) -> dict:
    total_users = await session.scalar(select(func.count(User.id)))
    total_balance = await session.scalar(select(func.sum(User.balance))) or 0
    total_topup = await session.scalar(select(func.sum(User.total_topped_up))) or 0
    total_orders = await session.scalar(select(func.count(Order.id)))
    pending_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "pending"))
    in_progress_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == "in_progress"))
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
        "in_progress_orders": in_progress_orders or 0,
        "done_orders": done_orders or 0,
    }
