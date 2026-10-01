from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo,
)
import config

# --- Matnlar (bir joyda — admin va user handlerlar filter sifatida shu bilan solishtiradi) ---
BTN_BUY = "⭐️Stars va Premium sotib olish"
BTN_BALANCE = "💰 Balans"
BTN_TOPUP = "➕ Balansni to'ldirish"
BTN_REFERRAL = "🤝 Referal"
BTN_HELP = "❓ Yordam"

BTN_ADMIN_ORDERS = "📦 Buyurtmalar"
BTN_ADMIN_PAYMENTS = "💳 To'lov so'rovlari"
BTN_ADMIN_USERS = "👥 Foydalanuvchilar"
BTN_ADMIN_SETTINGS = "⚙️ Sozlamalar"
BTN_ADMIN_BROADCAST = "📢 Xabar yuborish"
BTN_ADMIN_PANEL_OPEN = "🛠 Admin panelni ochish"


def user_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BUY)],
            [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_TOPUP)],
            [KeyboardButton(text=BTN_REFERRAL), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def admin_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BUY)],
            [KeyboardButton(text=BTN_ADMIN_ORDERS), KeyboardButton(text=BTN_ADMIN_PAYMENTS)],
            [KeyboardButton(text=BTN_ADMIN_USERS), KeyboardButton(text=BTN_ADMIN_SETTINGS)],
            [KeyboardButton(text=BTN_ADMIN_BROADCAST)],
            [KeyboardButton(text=BTN_ADMIN_PANEL_OPEN)],
        ],
        resize_keyboard=True,
    )


def webapp_inline_button(path: str = "") -> InlineKeyboardMarkup:
    """Faqat shu inline tugma orqali ochilganda Telegram haqiqiy initData beradi."""
    url = f"{config.WEBAPP_URL}{path}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🛍 Ochish", web_app=WebAppInfo(url=url))]]
    )


def admin_webapp_inline_button() -> InlineKeyboardMarkup:
    url = f"{config.WEBAPP_URL}?admin=1"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🛠 Admin panel", web_app=WebAppInfo(url=url))]]
    )


def force_sub_keyboard(channels) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["invite_link"])] for c in channels]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_decision_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"order_approve:{order_id}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order_cancel:{order_id}"),
    ]])


def payment_decision_keyboard(pr_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay_approve:{pr_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay_reject:{pr_id}"),
    ]])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="fsm_cancel")
    ]])
