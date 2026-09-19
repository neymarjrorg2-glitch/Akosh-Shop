from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.database.crud import TEXT_LABELS
from bot.database.models import MandatorySubscription, BotProduct, User


def admin_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Statistika"), KeyboardButton(text="🧾 Buyurtmalar"))
    builder.row(KeyboardButton(text="🤖 Mahsulotlar"), KeyboardButton(text="🔔 Obunalar"))
    builder.row(KeyboardButton(text="👥 Referral sozlamasi"), KeyboardButton(text="💳 To'lovlarni tasdiqlash"))
    builder.row(KeyboardButton(text="👤 Foydalanuvchilarni boshqarish"), KeyboardButton(text="🤵🏼‍♂️ Admin"))
    builder.row(KeyboardButton(text="📝 Matnni o'zgartirish"), KeyboardButton(text="📢 Xabar yuborish"))
    builder.row(KeyboardButton(text="⬅️ Oddiy menyu"))
    return builder.as_markup(resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Bekor qilish"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# ---------- BUYURTMALAR ----------

def order_status_kb(order_id: int, current_status: str = "pending") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if current_status == "pending":
        builder.row(
            InlineKeyboardButton(text="🔄 Jarayonga olish", callback_data=f"order_status:{order_id}:in_progress"),
        )
    builder.row(InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"order_status:{order_id}:done"))
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish (pul qaytadi)", callback_data=f"order_status:{order_id}:cancelled"))
    return builder.as_markup()


# ---------- MAHSULOTLAR ----------

def products_manage_kb(products: list[BotProduct]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        status = "🟢" if p.is_active else "⚪️"
        builder.row(InlineKeyboardButton(text=f"{status} {p.name} — {p.price:,.0f} so'm", callback_data=f"padmin:{p.id}"))
    builder.row(InlineKeyboardButton(text="➕ Yangi mahsulot qo'shish", callback_data="padmin_add"))
    return builder.as_markup()


def product_detail_admin_kb(product: BotProduct) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Nomi", callback_data=f"pedit:{product.id}:name"),
        InlineKeyboardButton(text="✏️ Tavsifi", callback_data=f"pedit:{product.id}:description"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Narxi", callback_data=f"pedit:{product.id}:price"),
        InlineKeyboardButton(text="✏️ Hosting narxi", callback_data=f"pedit:{product.id}:hosting_price"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Kategoriya", callback_data=f"pedit:{product.id}:category"),
        InlineKeyboardButton(text="🖼 Rasm/Video", callback_data=f"pedit:{product.id}:media"),
    )
    toggle_label = "⏸ Sotuvdan olish" if product.is_active else "▶️ Sotuvga qaytarish"
    builder.row(InlineKeyboardButton(text=toggle_label, callback_data=f"ptoggle:{product.id}"))
    builder.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"pdelete:{product.id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="padmin_back"))
    return builder.as_markup()


def confirm_delete_kb(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"pdelete_confirm:{product_id}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"padmin:{product_id}"),
    )
    return builder.as_markup()


# ---------- OBUNALAR ----------

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


# ---------- TO'LOVLARNI TASDIQLASH ----------

def topup_confirm_kb(request_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"topup_approve:{request_id}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"topup_reject:{request_id}"),
    )
    return builder.as_markup()


# ---------- ADMINLAR ----------

def admins_manage_kb(db_admins: list[User], env_admin_ids: set[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for admin_id in env_admin_ids:
        builder.row(InlineKeyboardButton(text=f"👑 {admin_id} (asosiy)", callback_data="noop"))
    for user in db_admins:
        if user.id in env_admin_ids:
            continue
        builder.row(InlineKeyboardButton(text=f"❌ {user.id} ni olib tashlash", callback_data=f"admin_remove:{user.id}"))
    builder.row(InlineKeyboardButton(text="➕ Yangi admin qo'shish", callback_data="admin_add"))
    return builder.as_markup()


# ---------- MATNNI O'ZGARTIRISH ----------

def text_edit_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in TEXT_LABELS.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"tedit:{key}"))
    return builder.as_markup()


# ---------- FOYDALANUVCHILARNI BOSHQARISH ----------

def user_manage_kb(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Balans qo'shish", callback_data=f"umoney:{user.id}:plus"),
        InlineKeyboardButton(text="➖ Balans ayirish", callback_data=f"umoney:{user.id}:minus"),
    )
    if user.is_blocked:
        builder.row(InlineKeyboardButton(text="♻️ Blokdan chiqarish", callback_data=f"uunban:{user.id}"))
    else:
        builder.row(InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"uban:{user.id}"))
    builder.row(InlineKeyboardButton(text="🧾 Buyurtmalarini ko'rish", callback_data=f"uorders:{user.id}"))
    builder.row(InlineKeyboardButton(text="✉️ Shaxsan xabar yuborish", callback_data=f"umsg:{user.id}"))
    return builder.as_markup()


def order_hosting_kb(order_id: int) -> InlineKeyboardMarkup:
    """Foydalanuvchining bitta buyurtmasi uchun hosting boshqaruvi (to'landi / o'chirish)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Hosting to'landi (+1 oy)", callback_data=f"hostpay:{order_id}"),
        InlineKeyboardButton(text="🚫 Hostingni o'chirish", callback_data=f"hostoff:{order_id}"),
    )
    return builder.as_markup()
