from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from bot.config import ADMIN_IDS
from bot.database import crud
from bot.database.crud import TEXT_LABELS
from bot.keyboards import admin_kb, user_kb
from bot.utils.states import (
    AdminAddProduct,
    AdminEditProduct,
    AdminAddSubscription,
    AdminReferralPercent,
    AdminBroadcast,
    AdminManageUsers,
    AdminManageAdmins,
    AdminEditText,
)

router = Router(name="admin")


async def require_admin(event_user_id: int, session: AsyncSession) -> bool:
    return await crud.is_user_admin(session, event_user_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    await message.answer("🔧 <b>Admin panel</b>", reply_markup=admin_kb.admin_menu_kb())


@router.message(F.text == "⬅️ Oddiy menyu")
async def back_to_user_menu(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    await message.answer("Asosiy menyu 👇", reply_markup=user_kb.main_menu_kb())


# ---------- STATISTIKA ----------

@router.message(F.text == "📊 Statistika")
async def show_stats(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    s = await crud.get_stats(session)
    text = (
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {s['total_users']}\n"
        f"🆕 Bugun qo'shilgan: {s['today_users']}\n\n"
        f"💰 Foydalanuvchilardagi jami balans: {s['total_balance']:,.0f} so'm\n"
        f"📈 Jami to'ldirilgan: {s['total_topup']:,.0f} so'm\n\n"
        f"🧾 Jami buyurtmalar: {s['total_orders']}\n"
        f"⏳ Kutilayotgan: {s['pending_orders']}\n"
        f"🔄 Jarayonda: {s['in_progress_orders']}\n"
        f"✅ Bajarilgan: {s['done_orders']}"
    )
    await message.answer(text)


# ---------- BUYURTMALAR (pending + in_progress) ----------

@router.message(F.text == "🧾 Buyurtmalar")
async def list_orders(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    orders = await crud.get_active_orders(session)
    if not orders:
        await message.answer("Faol buyurtmalar yo'q.")
        return

    for o in orders:
        user = await crud.get_user(session, o.user_id)
        text = (
            f"🧾 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🤖 {o.product_name} — {o.price:,.0f} so'm\n"
            f"👤 Mijoz: {user.full_name if user else '—'} (@{user.username if user else '—'})\n"
            f"🆔 ID: <code>{o.user_id}</code>\n"
        )
        if o.api_key:
            text += f"🔑 API key: <code>{o.api_key}</code>\n"
        if o.admin_telegram_id:
            text += f"🆔 Bot admin ID: <code>{o.admin_telegram_id}</code>\n"
        if o.hosting_price and o.hosting_price > 0:
            text += f"🖥 Hosting: {o.hosting_price:,.0f} so'm/oy\n"
        text += (
            f"📅 {o.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📌 Holat: {o.status}"
        )
        await message.answer(text, reply_markup=admin_kb.order_status_kb(o.id, o.status))


@router.callback_query(F.data.startswith("order_status:"))
async def change_order_status(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return

    _, order_id_str, status = callback.data.split(":")
    order_id = int(order_id_str)

    order = await crud.update_order_status(session, order_id, status)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return

    if status == "cancelled":
        await crud.adjust_balance(
            session, order.user_id, order.price, "refund", description=f"Bekor qilingan buyurtma #{order.id}"
        )

    if status == "done":
        await crud.activate_hosting_on_done(session, order)

    if status == "in_progress":
        await callback.message.edit_reply_markup(reply_markup=admin_kb.order_status_kb(order.id, "in_progress"))
    else:
        await callback.message.edit_text(callback.message.text + f"\n\n➡️ Yangi holat: {status}")

    status_text = {
        "in_progress": "🔄 Buyurtmangiz jarayonga qabul qilindi.",
        "done": "✅ Buyurtmangiz bajarildi! Xaridingiz uchun rahmat.",
        "cancelled": "❌ Buyurtmangiz bekor qilindi. Pulingiz balansingizga qaytarildi.",
    }.get(status, f"Buyurtma holati: {status}")

    if status == "done" and order.hosting_price and order.hosting_price > 0 and order.hosting_next_due:
        status_text += (
            f"\n\n🖥 Birinchi oy hosting narxga kiritilgan. Keyingi to'lov sanasi: "
            f"{order.hosting_next_due.strftime('%d.%m.%Y')}. Shu sanagacha hosting to'lovini amalga oshiring, "
            f"aks holda botingiz hostingdan uziladi."
        )

    try:
        await bot.send_message(order.user_id, f"#{order.id}\n{status_text}")
    except Exception:
        pass
    await callback.answer("Yangilandi")


# ---------- MAHSULOTLAR (to'liq boshqarish) ----------

@router.message(F.text == "🤖 Mahsulotlar")
async def list_products(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    products = await crud.get_all_products(session)
    await message.answer(
        "🤖 <b>Mahsulotlar</b> (🟢 faol / ⚪️ nofaol):" if products else "Hozircha mahsulot yo'q.",
        reply_markup=admin_kb.products_manage_kb(products),
    )


async def _show_product_admin(message_or_callback, session: AsyncSession, product_id: int, edit: bool = False):
    product = await crud.get_product(session, product_id)
    if not product:
        return
    status = "🟢 Faol" if product.is_active else "⚪️ Nofaol"
    text = (
        f"🤖 <b>{product.name}</b>\n\n"
        f"{product.description}\n\n"
        f"💵 Narxi: {product.price:,.0f} so'm\n"
        f"🖥 Hosting: {product.hosting_price:,.0f} so'm/oy\n"
        f"🏷 Kategoriya: {product.category or '—'}\n"
        f"📌 Holati: {status}\n"
        f"🖼 Media: {'bor' if product.media_file_id else 'yo\u02bcq'}"
    )
    kb = admin_kb.product_detail_admin_kb(product)
    if hasattr(message_or_callback, "edit_text") and edit:
        try:
            await message_or_callback.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message_or_callback.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("padmin:"))
async def product_admin_detail(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    product_id = int(callback.data.split(":")[1])
    await _show_product_admin(callback.message, session, product_id)
    await callback.answer()


@router.callback_query(F.data == "padmin_back")
async def product_admin_back(callback: CallbackQuery, session: AsyncSession):
    products = await crud.get_all_products(session)
    await callback.message.answer(
        "🤖 <b>Mahsulotlar</b> (🟢 faol / ⚪️ nofaol):" if products else "Hozircha mahsulot yo'q.",
        reply_markup=admin_kb.products_manage_kb(products),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ptoggle:"))
async def product_toggle(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    product_id = int(callback.data.split(":")[1])
    await crud.toggle_product(session, product_id)
    await _show_product_admin(callback.message, session, product_id)
    await callback.answer("Yangilandi")


@router.callback_query(F.data.startswith("pdelete_confirm:"))
async def product_delete_confirm(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    product_id = int(callback.data.split(":")[1])
    result = await crud.delete_product(session, product_id)
    if result == "deleted":
        await callback.message.edit_text("🗑 Mahsulot butunlay o'chirildi.")
    elif result == "deactivated":
        await callback.message.edit_text(
            "⚠️ Bu mahsulotga bog'liq buyurtmalar bor edi, shuning uchun butunlay o'chirilmadi — "
            "o'rniga sotuvdan olib qo'yildi (nofaol holatga o'tkazildi)."
        )
    else:
        await callback.message.edit_text("Mahsulot topilmadi.")
    await callback.answer()


@router.callback_query(F.data.startswith("pdelete:"))
async def product_delete_ask(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    product_id = int(callback.data.split(":")[1])
    await callback.message.answer(
        "❗️ Mahsulotni rostdan o'chirmoqchimisiz?", reply_markup=admin_kb.confirm_delete_kb(product_id)
    )
    await callback.answer()


FIELD_PROMPTS = {
    "name": "✏️ Yangi nomni kiriting:",
    "description": "✏️ Yangi tavsifni kiriting:",
    "price": "✏️ Yangi narxni kiriting (faqat raqam):",
    "hosting_price": "✏️ Yangi oylik hosting narxini kiriting (faqat raqam, hosting bo'lmasa 0 yozing):",
    "category": "✏️ Yangi kategoriyani kiriting (yoki \"-\"):",
    "media": "🖼 Yangi rasm yoki video (60 soniyagacha) yuboring:",
}


@router.callback_query(F.data.startswith("pedit:"))
async def product_edit_start(callback: CallbackQuery, state: FSMContext):
    _, product_id_str, field = callback.data.split(":")
    await state.update_data(product_id=int(product_id_str), field=field)
    await state.set_state(AdminEditProduct.waiting_value)
    await callback.message.answer(FIELD_PROMPTS[field], reply_markup=admin_kb.cancel_kb())
    await callback.answer()


@router.message(AdminEditProduct.waiting_value, F.text)
async def product_edit_value_text(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    field = data.get("field")
    product_id = data.get("product_id")

    if field == "media":
        await message.answer("🖼 Iltimos, RASM yoki VIDEO yuboring (matn emas).")
        return

    value = message.text.strip()
    if field in ("price", "hosting_price"):
        if not value.replace(".", "", 1).isdigit():
            await message.answer("❗️ Faqat raqam kiriting.")
            return
        value = float(value)
    elif field == "category" and value == "-":
        value = None

    await crud.update_product_field(session, product_id, field, value)
    await state.clear()
    await message.answer("✅ Yangilandi.", reply_markup=admin_kb.admin_menu_kb())
    await _show_product_admin(message, session, product_id)


@router.message(AdminEditProduct.waiting_value, F.photo)
async def product_edit_value_photo(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if data.get("field") != "media":
        await message.answer("❗️ Bu maydon uchun rasm emas, matn yuboring.")
        return
    product_id = data.get("product_id")
    await crud.update_product_field(session, product_id, "media_file_id", message.photo[-1].file_id)
    await crud.update_product_field(session, product_id, "media_type", "photo")
    await state.clear()
    await message.answer("✅ Rasm yangilandi.", reply_markup=admin_kb.admin_menu_kb())
    await _show_product_admin(message, session, product_id)


@router.message(AdminEditProduct.waiting_value, F.video)
async def product_edit_value_video(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    if data.get("field") != "media":
        await message.answer("❗️ Bu maydon uchun video emas, matn yuboring.")
        return
    if message.video.duration and message.video.duration > 60:
        await message.answer("❗️ Video 60 soniyadan oshmasligi kerak. Qisqaroq video yuboring.")
        return
    product_id = data.get("product_id")
    await crud.update_product_field(session, product_id, "media_file_id", message.video.file_id)
    await crud.update_product_field(session, product_id, "media_type", "video")
    await state.clear()
    await message.answer("✅ Video yangilandi.", reply_markup=admin_kb.admin_menu_kb())
    await _show_product_admin(message, session, product_id)


@router.callback_query(F.data == "padmin_add")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminAddProduct.name)
    await callback.message.answer("🤖 Yangi mahsulot nomini kiriting:", reply_markup=admin_kb.cancel_kb())
    await callback.answer()


@router.message(AdminAddProduct.name)
async def add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminAddProduct.description)
    await message.answer("📝 Tavsifini kiriting:")


@router.message(AdminAddProduct.description)
async def add_product_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AdminAddProduct.price)
    await message.answer("💵 Narxini kiriting (faqat raqam, so'mda):")


@router.message(AdminAddProduct.price)
async def add_product_price(message: Message, state: FSMContext):
    if not message.text.replace(".", "", 1).isdigit():
        await message.answer("❗️ Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(price=float(message.text))
    await state.set_state(AdminAddProduct.hosting_price)
    await message.answer(
        "🖥 Oylik hosting narxini kiriting (faqat raqam, so'mda).\n"
        "Agar hosting kerak bo'lmasa, 0 deb yozing:"
    )


@router.message(AdminAddProduct.hosting_price)
async def add_product_hosting_price(message: Message, state: FSMContext):
    if not message.text.replace(".", "", 1).isdigit():
        await message.answer("❗️ Iltimos, faqat raqam kiriting (hosting kerak bo'lmasa 0).")
        return
    await state.update_data(hosting_price=float(message.text))
    await state.set_state(AdminAddProduct.category)
    await message.answer("🏷 Kategoriyasini kiriting (yoki \"-\" deb yozing):")


@router.message(AdminAddProduct.category)
async def add_product_category(message: Message, state: FSMContext):
    category = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(category=category)
    await state.set_state(AdminAddProduct.media)
    await message.answer(
        "🖼 Reklama uchun rasm yoki video (60 soniyagacha) yuboring.\n"
        "Agar kerak bo'lmasa, pastdagi tugmani bosing:",
        reply_markup=user_kb.skip_media_kb(),
    )


@router.message(AdminAddProduct.media, F.text == "➡️ O'tkazib yuborish")
async def add_product_media_skip(message: Message, state: FSMContext, session: AsyncSession):
    await _finish_add_product(message, state, session, media_file_id=None, media_type=None)


@router.message(AdminAddProduct.media, F.photo)
async def add_product_media_photo(message: Message, state: FSMContext, session: AsyncSession):
    await _finish_add_product(message, state, session, media_file_id=message.photo[-1].file_id, media_type="photo")


@router.message(AdminAddProduct.media, F.video)
async def add_product_media_video(message: Message, state: FSMContext, session: AsyncSession):
    if message.video.duration and message.video.duration > 60:
        await message.answer("❗️ Video 60 soniyadan oshmasligi kerak. Qisqaroq video yuboring.")
        return
    await _finish_add_product(message, state, session, media_file_id=message.video.file_id, media_type="video")


async def _finish_add_product(message: Message, state: FSMContext, session: AsyncSession, media_file_id, media_type):
    data = await state.get_data()
    product = await crud.add_product(
        session,
        name=data["name"],
        description=data["description"],
        price=data["price"],
        hosting_price=data.get("hosting_price", 0),
        category=data.get("category"),
        media_file_id=media_file_id,
        media_type=media_type,
    )
    await state.clear()
    hosting_line = f"\n🖥 Hosting: {product.hosting_price:,.0f} so'm/oy" if product.hosting_price else ""
    await message.answer(
        f"✅ Mahsulot qo'shildi!\n\n#{product.id} — {product.name} — {product.price:,.0f} so'm{hosting_line}",
        reply_markup=admin_kb.admin_menu_kb(),
    )


# ---------- MAJBURIY OBUNALAR ----------

PLATFORM_LABELS = {
    "telegram_join": "✈️ Telegram (qo'shilish shart)",
    "telegram_request": "✈️ Telegram (faqat zayavka)",
    "instagram": "📸 Instagram",
    "youtube": "▶️ YouTube",
}


@router.message(F.text == "🔔 Obunalar")
async def list_subscriptions(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    subs = await crud.get_active_subscriptions(session)
    if not subs:
        await message.answer("Hozircha majburiy obuna yo'q.", reply_markup=admin_kb.subscriptions_manage_kb(subs))
        return

    lines = ["🔔 <b>Majburiy obunalar ro'yxati:</b>\n"]
    for i, sub in enumerate(subs, start=1):
        lines.append(f"{i}. {PLATFORM_LABELS.get(sub.platform, sub.platform)}\n   {sub.title} — {sub.url}")
    await message.answer("\n\n".join(lines), reply_markup=admin_kb.subscriptions_manage_kb(subs))


@router.callback_query(F.data == "add_sub")
async def add_sub_start(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    await callback.message.answer("Obuna turini tanlang:", reply_markup=admin_kb.subscription_platform_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("sub_platform:"))
async def add_sub_platform(callback: CallbackQuery, state: FSMContext):
    platform = callback.data.split(":")[1]
    await state.update_data(platform=platform)
    await state.set_state(AdminAddSubscription.title)
    await callback.message.answer("📝 Nomini kiriting (masalan: \"Bizning kanal\"):", reply_markup=admin_kb.cancel_kb())
    await callback.answer()


@router.message(AdminAddSubscription.title)
async def add_sub_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AdminAddSubscription.url)
    await message.answer("🔗 Havolasini kiriting (https://t.me/... yoki instagram/youtube havolasi):")


@router.message(AdminAddSubscription.url)
async def add_sub_url(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    await state.update_data(url=message.text)

    if data["platform"] == "telegram_join":
        await state.set_state(AdminAddSubscription.chat_id)
        await message.answer(
            "🆔 Kanal username yoki chat_id kiriting (masalan @mychannel).\n"
            "❗️ Bot shu kanalda ADMIN bo'lishi shart, aks holda a'zolikni tekshira olmaydi."
        )
        return

    data = await state.get_data()
    sub = await crud.add_subscription(session, platform=data["platform"], title=data["title"], url=data["url"])
    await state.clear()
    await message.answer(f"✅ Obuna qo'shildi: {sub.title}", reply_markup=admin_kb.admin_menu_kb())


@router.message(AdminAddSubscription.chat_id)
async def add_sub_chat_id(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    sub = await crud.add_subscription(
        session, platform=data["platform"], title=data["title"], url=data["url"], chat_id=message.text.strip()
    )
    await state.clear()
    await message.answer(f"✅ Obuna qo'shildi: {sub.title}", reply_markup=admin_kb.admin_menu_kb())


@router.callback_query(F.data.startswith("remove_sub:"))
async def remove_sub(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    sub_id = int(callback.data.split(":")[1])
    await crud.remove_subscription(session, sub_id)
    subs = await crud.get_active_subscriptions(session)
    await callback.message.answer(
        "🔔 <b>Majburiy obunalar ro'yxati:</b>" if subs else "Hozircha majburiy obuna yo'q.",
        reply_markup=admin_kb.subscriptions_manage_kb(subs),
    )
    await callback.answer("O'chirildi")


# ---------- REFERRAL SOZLAMASI ----------

@router.message(F.text == "👥 Referral sozlamasi")
async def referral_settings(message: Message, session: AsyncSession, state: FSMContext):
    if not await require_admin(message.from_user.id, session):
        return
    percent = await crud.get_referral_percent(session)
    await state.set_state(AdminReferralPercent.percent)
    await message.answer(
        f"Hozirgi referral foizi: <b>{percent:.0f}%</b>\n\nYangi foizni kiriting:",
        reply_markup=admin_kb.cancel_kb(),
    )


@router.message(AdminReferralPercent.percent)
async def set_referral_percent(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.replace(".", "", 1).isdigit():
        await message.answer("❗️ Faqat raqam kiriting.")
        return
    await crud.set_referral_percent(session, float(message.text))
    await state.clear()
    await message.answer(f"✅ Referral foizi {message.text}% ga o'zgartirildi.", reply_markup=admin_kb.admin_menu_kb())


# ---------- TO'LOVLARNI TASDIQLASH ----------

@router.message(F.text == "💳 To'lovlarni tasdiqlash")
async def list_topup_requests(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    requests = await crud.get_pending_topup_requests(session)
    if not requests:
        await message.answer("Hozircha tasdiqlanmagan to'lov so'rovlari yo'q.")
        return

    for req in requests:
        user = await crud.get_user(session, req.user_id)
        caption = (
            f"💳 <b>To'lov so'rovi #{req.id}</b>\n\n"
            f"👤 {user.full_name if user else '—'} (@{user.username if user else '—'})\n"
            f"🆔 ID: <code>{req.user_id}</code>\n"
            f"💵 Miqdor: {req.amount:,.0f} so'm"
        )
        if req.receipt_file_id:
            await message.answer_photo(req.receipt_file_id, caption=caption, reply_markup=admin_kb.topup_confirm_kb(req.id))
        else:
            await message.answer(caption, reply_markup=admin_kb.topup_confirm_kb(req.id))


@router.callback_query(F.data.startswith("topup_approve:"))
async def topup_approve(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    request_id = int(callback.data.split(":")[1])
    req = await crud.process_topup_request(session, request_id, approve=True, admin_id=callback.from_user.id)
    if not req:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return

    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n✅ TASDIQLANDI")
    try:
        await bot.send_message(
            req.user_id, f"✅ To'lov so'rovingiz (#{req.id}, {req.amount:,.0f} so'm) tasdiqlandi! Balansingiz yangilandi."
        )
    except Exception:
        pass
    await callback.answer("Tasdiqlandi, balans yangilandi")


@router.callback_query(F.data.startswith("topup_reject:"))
async def topup_reject(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    request_id = int(callback.data.split(":")[1])
    req = await crud.process_topup_request(session, request_id, approve=False, admin_id=callback.from_user.id)
    if not req:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return

    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n❌ BEKOR QILINDI")
    try:
        await bot.send_message(
            req.user_id, f"❌ To'lov so'rovingiz (#{req.id}, {req.amount:,.0f} so'm) rad etildi. Admin bilan bog'laning."
        )
    except Exception:
        pass
    await callback.answer("Rad etildi")


# ---------- ADMINLARNI BOSHQARISH ----------

@router.message(F.text == "🤵🏼‍♂️ Admin")
async def show_admins(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    db_admins = await crud.get_db_admins(session)
    text_lines = ["🤵🏼‍♂️ <b>Adminlar ro'yxati</b>\n"]
    for admin_id in ADMIN_IDS:
        text_lines.append(f"👑 <code>{admin_id}</code> — asosiy admin (o'chirib bo'lmaydi)")
    for user in db_admins:
        if user.id in ADMIN_IDS:
            continue
        text_lines.append(f"🔹 <code>{user.id}</code> — @{user.username or '—'}")
    await message.answer("\n".join(text_lines), reply_markup=admin_kb.admins_manage_kb(db_admins, ADMIN_IDS))


@router.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminManageAdmins.add_id)
    await callback.message.answer(
        "🆔 Yangi admin qilinadigan foydalanuvchining Telegram ID raqamini kiriting.\n"
        "❗️ Bu foydalanuvchi avval botga kamida bir marta /start yozgan bo'lishi kerak.",
        reply_markup=admin_kb.cancel_kb(),
    )
    await callback.answer()


@router.message(AdminManageAdmins.add_id)
async def admin_add_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam (ID) kiriting.")
        return
    new_admin_id = int(message.text)
    user = await crud.add_admin(session, new_admin_id)
    await state.clear()
    if not user:
        await message.answer(
            "❗️ Bunday foydalanuvchi topilmadi — u avval botga /start yozishi kerak.",
            reply_markup=admin_kb.admin_menu_kb(),
        )
        return
    await message.answer(f"✅ {new_admin_id} endi admin.", reply_markup=admin_kb.admin_menu_kb())


@router.callback_query(F.data.startswith("admin_remove:"))
async def admin_remove(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    admin_id = int(callback.data.split(":")[1])
    removed = await crud.remove_admin(session, admin_id)
    if removed:
        await callback.answer("Admin olib tashlandi")
    else:
        await callback.answer("Bu adminni olib tashlab bo'lmaydi.", show_alert=True)
    db_admins = await crud.get_db_admins(session)
    try:
        await callback.message.edit_reply_markup(reply_markup=admin_kb.admins_manage_kb(db_admins, ADMIN_IDS))
    except Exception:
        pass


@router.callback_query(F.data == "noop")
async def noop_cb(callback: CallbackQuery):
    await callback.answer()


# ---------- MATNNI O'ZGARTIRISH ----------

@router.message(F.text == "📝 Matnni o'zgartirish")
async def text_edit_menu(message: Message, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    await message.answer("📝 Qaysi matnni o'zgartirmoqchisiz?", reply_markup=admin_kb.text_edit_kb())


@router.callback_query(F.data.startswith("tedit:"))
async def text_edit_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    key = callback.data.split(":")[1]
    current = await crud.get_text(session, key)
    await state.update_data(text_key=key)
    await state.set_state(AdminEditText.waiting_value)
    await callback.message.answer(
        f"Hozirgi qiymat ({TEXT_LABELS.get(key, key)}):\n\n{current}\n\n"
        f"Yangi matnni kiriting (HTML teglar: &lt;b&gt;, &lt;i&gt; ishlatsa bo'ladi):",
        reply_markup=admin_kb.cancel_kb(),
    )
    await callback.answer()


@router.message(AdminEditText.waiting_value)
async def text_edit_finish(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    key = data.get("text_key")
    await crud.set_text(session, key, message.html_text or message.text)
    await state.clear()
    await message.answer(f"✅ {TEXT_LABELS.get(key, key)} yangilandi.", reply_markup=admin_kb.admin_menu_kb())


# ---------- FOYDALANUVCHILARNI BOSHQARISH ----------

@router.message(F.text == "👤 Foydalanuvchilarni boshqarish")
async def manage_users_start(message: Message, state: FSMContext, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    await state.set_state(AdminManageUsers.search_id)
    await message.answer("🆔 Qidirilayotgan foydalanuvchining Telegram ID raqamini kiriting:", reply_markup=admin_kb.cancel_kb())


async def _show_user_admin_card(message: Message, session: AsyncSession, user_id: int):
    user = await crud.get_user(session, user_id)
    if not user:
        await message.answer("❗️ Bunday foydalanuvchi topilmadi.", reply_markup=admin_kb.admin_menu_kb())
        return
    orders = await crud.get_user_orders(session, user_id)
    text = (
        f"👤 <b>Foydalanuvchi ma'lumotlari</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Ism: {user.full_name or '—'}\n"
        f"🔤 Username: @{user.username or '—'}\n"
        f"📱 Telefon: {user.phone or '—'}\n\n"
        f"💰 Balans: {user.balance:,.0f} so'm\n"
        f"📈 Jami to'ldirgan: {user.total_topped_up:,.0f} so'm\n"
        f"🧾 Buyurtmalar: {len(orders)} ta\n"
        f"👥 Referrallar: {user.referral_count} ta ({user.referral_earned:,.0f} so'm)\n\n"
        f"🚦 Holat: {'🚫 Bloklangan' if user.is_blocked else '✅ Faol'}\n"
        f"📅 Ro'yxatdan o'tgan: {user.created_at.strftime('%d.%m.%Y')}"
    )

    hosted = await crud.get_user_hosted_orders(session, user_id)
    if hosted:
        text += "\n\n🖥 <b>Hosting qilingan botlari:</b>"
        for o in hosted:
            due = o.hosting_next_due.strftime("%d.%m.%Y") if o.hosting_next_due else "—"
            state_icon = "🟢" if o.hosting_active else "🔴 uzilgan"
            text += f"\n#{o.id} {o.product_name} — {state_icon} — muddat: {due}"

    await message.answer(text, reply_markup=admin_kb.user_manage_kb(user))


@router.message(AdminManageUsers.search_id)
async def manage_users_search(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam (ID) kiriting.")
        return
    await state.clear()
    await _show_user_admin_card(message, session, int(message.text))


@router.callback_query(F.data.startswith("umoney:"))
async def user_money_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    _, user_id_str, direction = callback.data.split(":")
    await state.update_data(target_user_id=int(user_id_str), direction=direction)
    await state.set_state(AdminManageUsers.balance_amount)
    verb = "qo'shmoqchi" if direction == "plus" else "ayirmoqchi"
    await callback.message.answer(f"💰 Qancha so'm {verb} bo'lsangiz, kiriting:", reply_markup=admin_kb.cancel_kb())
    await callback.answer()


@router.message(AdminManageUsers.balance_amount)
async def user_money_finish(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.replace(".", "", 1).isdigit():
        await message.answer("❗️ Faqat raqam kiriting.")
        return
    data = await state.get_data()
    user_id = data["target_user_id"]
    direction = data["direction"]
    amount = float(message.text)
    if direction == "minus":
        amount = -amount

    await crud.adjust_balance(session, user_id, amount, "admin_adjust", description="Admin tomonidan qo'lda")
    await state.clear()
    await message.answer(f"✅ Balans o'zgartirildi: {amount:+,.0f} so'm", reply_markup=admin_kb.admin_menu_kb())
    await _show_user_admin_card(message, session, user_id)


@router.callback_query(F.data.startswith("uban:"))
async def user_ban(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await crud.set_user_blocked(session, user_id, True)
    await callback.answer("Bloklandi")
    await _show_user_admin_card(callback.message, session, user_id)


@router.callback_query(F.data.startswith("uunban:"))
async def user_unban(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await crud.set_user_blocked(session, user_id, False)
    await callback.answer("Blokdan chiqarildi")
    await _show_user_admin_card(callback.message, session, user_id)


@router.callback_query(F.data.startswith("uorders:"))
async def user_orders_view(callback: CallbackQuery, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    orders = await crud.get_user_orders(session, user_id)
    if not orders:
        await callback.message.answer("Bu foydalanuvchida buyurtmalar yo'q.")
        await callback.answer()
        return
    for o in orders:
        text = f"#{o.id} — {o.product_name} — {o.price:,.0f} so'm — {o.status}"
        if o.api_key:
            text += f"\n🔑 <code>{o.api_key}</code>"
        if o.admin_telegram_id:
            text += f"\n🆔 Admin ID: <code>{o.admin_telegram_id}</code>"
        if o.status == "done" and o.hosting_price and o.hosting_price > 0:
            due = o.hosting_next_due.strftime("%d.%m.%Y") if o.hosting_next_due else "—"
            active = "🟢 faol" if o.hosting_active else "🔴 uzilgan"
            text += f"\n🖥 Hosting: {o.hosting_price:,.0f} so'm/oy — {active} — muddat: {due}"
            await callback.message.answer(text, reply_markup=admin_kb.order_hosting_kb(o.id))
        else:
            await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.startswith("hostpay:"))
async def hosting_mark_paid(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    order_id = int(callback.data.split(":")[1])
    order = await crud.renew_hosting(session, order_id)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    await callback.answer("Hosting +1 oyga uzaytirildi")
    await callback.message.answer(
        f"✅ #{order.id} buyurtmasi uchun hosting yangilandi. Keyingi muddat: "
        f"{order.hosting_next_due.strftime('%d.%m.%Y')}"
    )
    try:
        await bot.send_message(
            order.user_id,
            f"✅ #{order.id} botingiz uchun hosting to'lovi qabul qilindi. "
            f"Keyingi to'lov sanasi: {order.hosting_next_due.strftime('%d.%m.%Y')}",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("hostoff:"))
async def hosting_disable(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    order_id = int(callback.data.split(":")[1])
    order = await crud.disable_hosting(session, order_id)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    await callback.answer("Hosting o'chirildi")
    await callback.message.answer(f"🚫 #{order.id} buyurtmasi uchun hosting o'chirildi.")
    try:
        await bot.send_message(
            order.user_id, f"⚠️ #{order.id} botingizning hostingi admin tomonidan o'chirildi."
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("umsg:"))
async def user_message_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await require_admin(callback.from_user.id, session):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminManageUsers.message_text)
    await callback.message.answer(
        f"✉️ {user_id} foydalanuvchisiga yuboriladigan xabarni yozing:", reply_markup=admin_kb.cancel_kb()
    )
    await callback.answer()


@router.message(AdminManageUsers.message_text)
async def user_message_finish(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    await state.clear()

    try:
        await bot.send_message(user_id, message.html_text or message.text)
        await message.answer("✅ Xabar yuborildi.", reply_markup=admin_kb.admin_menu_kb())
    except Exception:
        await message.answer(
            "❗️ Xabar yuborilmadi (foydalanuvchi botni bloklagan bo'lishi mumkin).",
            reply_markup=admin_kb.admin_menu_kb(),
        )
    lines = [f"🧾 <b>{user_id} foydalanuvchining buyurtmalari:</b>\n"]
    for o in orders:
        lines.append(f"#{o.id} — {o.product_name} — {o.price:,.0f} so'm — {o.status}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ---------- XABAR YUBORISH (BROADCAST) ----------

@router.message(F.text == "📢 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext, session: AsyncSession):
    if not await require_admin(message.from_user.id, session):
        return
    await state.set_state(AdminBroadcast.content)
    await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:", reply_markup=admin_kb.cancel_kb())


@router.message(AdminBroadcast.content)
async def broadcast_send(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    from sqlalchemy import select
    from bot.database.models import User

    await state.clear()
    result = await session.execute(select(User.id).where(User.is_blocked == False))  # noqa: E712
    user_ids = result.scalars().all()

    sent, failed = 0, 0
    status_msg = await message.answer(f"📤 Yuborilmoqda... (0/{len(user_ids)})")

    for i, uid in enumerate(user_ids, start=1):
        try:
            await bot.send_message(uid, message.html_text or message.text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegram flood-control'ga tushib qolmaslik uchun (~20 xabar/soniya)
        if i % 25 == 0:
            try:
                await status_msg.edit_text(f"📤 Yuborilmoqda... ({i}/{len(user_ids)})")
            except Exception:
                pass

    await status_msg.edit_text(f"✅ Yakunlandi!\n\nYuborildi: {sent}\nXato: {failed}")
    await message.answer("Admin panel 👇", reply_markup=admin_kb.admin_menu_kb())
