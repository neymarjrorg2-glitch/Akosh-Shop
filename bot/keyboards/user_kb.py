from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from bot.database.models import BotProduct, MandatorySubscription


def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🤖 Botlar katalogi"), KeyboardButton(text="👤 Hisobim"))
    builder.row(KeyboardButton(text="💳 Balans to'ldirish"), KeyboardButton(text="🧾 Buyurtmalarim"))
    builder.row(KeyboardButton(text="👥 Referral"), KeyboardButton(text="🆘 Yordam"))
    return builder.as_markup(resize_keyboard=True)


def phone_request_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 Raqamni yuborish", request_contact=True))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def subscriptions_kb(subs: list[MandatorySubscription]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subs:
        icon = {
            "telegram_join": "✈️",
            "telegram_request": "✈️",
            "instagram": "📸",
            "youtube": "▶️",
        }.get(sub.platform, "🔗")
        builder.row(InlineKeyboardButton(text=f"{icon} {sub.title}", url=sub.url))

        if sub.platform in ("telegram_request", "instagram", "youtube"):
            label = "✅ Zayavka tashladim" if sub.platform == "telegram_request" else "✅ Bajardim"
            builder.row(InlineKeyboardButton(text=label, callback_data=f"confirm_sub:{sub.id}"))

    builder.row(InlineKeyboardButton(text="🔄 Tekshirish", callback_data="check_subs"))
    return builder.as_markup()


def catalog_kb(products: list[BotProduct]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        builder.row(InlineKeyboardButton(text=f"{p.name} — {p.price:,.0f} so'm", callback_data=f"product:{p.id}"))
    return builder.as_markup()


def product_detail_kb(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🛒 Buyurtma berish", callback_data=f"order:{product_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_catalog"))
    return builder.as_markup()


def confirm_order_kb(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"confirm_order:{product_id}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="back_to_catalog"),
    )
    return builder.as_markup()


def topup_amount_kb() -> InlineKeyboardMarkup:
    amounts = [10_000, 25_000, 50_000, 100_000, 250_000, 500_000]
    builder = InlineKeyboardBuilder()
    for a in amounts:
        builder.button(text=f"{a:,.0f} so'm", callback_data=f"topup:{a}")
    builder.adjust(2)
    return builder.as_markup()
