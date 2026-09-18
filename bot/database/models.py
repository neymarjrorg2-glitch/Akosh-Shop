from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    balance: Mapped[float] = mapped_column(Float, default=0)
    total_topped_up: Mapped[float] = mapped_column(Float, default=0)

    referred_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    referral_earned: Mapped[float] = mapped_column(Float, default=0)
    referral_count: Mapped[int] = mapped_column(Integer, default=0)

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # DB orqali qo'shilgan qo'shimcha admin
    subscriptions_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BotProduct(Base):
    __tablename__ = "bot_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # reklama uchun: rasm yoki video (<=60s)
    media_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # "photo" | "video"

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    product_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_products.id"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(128))
    price: Mapped[float] = mapped_column(Float)

    # foydalanuvchi o'zi xohlagan bot nomi va username'i (BotFather orqali sozlash uchun)
    custom_nickname: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    custom_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # pending -> in_progress -> done / cancelled
    status: Mapped[str] = mapped_column(String(32), default="pending")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)

    # topup, order_payment, referral_bonus, refund, admin_adjust
    type: Mapped[str] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TopupRequest(Base):
    """Foydalanuvchi balans to'ldirish uchun chek yuborgan so'rovlar."""

    __tablename__ = "topup_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    receipt_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # pending -> approved / rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    processed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class MandatorySubscription(Base):
    __tablename__ = "mandatory_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # telegram_join, telegram_request, instagram, youtube
    platform: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(256))

    # telegram_join uchun: @channel_username yoki -100xxxxxxxxxx
    chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class UserSubscriptionConfirmation(Base):
    __tablename__ = "user_subscription_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    subscription_id: Mapped[int] = mapped_column(Integer, ForeignKey("mandatory_subscriptions.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Umumiy kalit-qiymat sozlamalari: referral_percent, card_info, help_text, welcome_text va h.k."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
