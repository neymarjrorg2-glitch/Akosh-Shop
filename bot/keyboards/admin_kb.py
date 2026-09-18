from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.database.models import Order, MandatorySubscription


def admin_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Statistika"), KeyboardButton(text="🧾 Buyurtmalar"))
    builder.row(KeyboardButton(text="🤖 Mahsulotlar"), KeyboardButton(text="🔔 Obunalar"))
    builder.row(KeyboardButton(text="👥 Referral sozlamasi"), KeyboardButton(text="💰 Balans boshqarish"))
    builder.row(KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="⬅️ Oddiy menyu"))
    return builder.as_markup(resize_keyboard=True)


def order_status_kb(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Jarayonda", callback_data=f"order_status:{order_id}:in_progress"),
        InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"order_status:{order_id}:done"),
    )
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish (pul qaytadi)", callback_data=f"order_status:{order_id}:cancelled"))
    return builder.as_markup()


def subscriptions_manage_kb(subs: list[MandatorySubscription]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subs:
        builder.row(InlineKeyboardButton(text=f"❌ O'chirish: {sub.title}", callback_data=f"remove_sub:{sub.id}"))
    builder.row(InlineKeyboardButton(text="➕ Yangi obuna qo'shish", callback_data="add_sub"))
    return builder.as_markup()


def subscription_platform_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✈️ Telegram (qo'shilish shart)", callback_data="sub_platform:telegram_join"))
    builder.row(InlineKeyboardButton(text="✈️ Telegram (faqat zayavka)", callback_data="sub_platform:telegram_request"))
    builder.row(InlineKeyboardButton(text="📸 Instagram", callback_data="sub_platform:instagram"))
    builder.row(InlineKeyboardButton(text="▶️ YouTube", callback_data="sub_platform:youtube"))
    return builder.as_markup()
