from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_IDS
from bot.database import crud
from bot.keyboards import admin_kb, user_kb
from bot.utils.states import (
    AdminAddProduct,
    AdminAddSubscription,
    AdminBalanceAdjust,
    AdminReferralPercent,
    AdminBroadcast,
)

router = Router(name="admin")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔧 <b>Admin panel</b>", reply_markup=admin_kb.admin_menu_kb())


@router.message(F.text == "⬅️ Oddiy menyu")
async def back_to_user_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Asosiy menyu 👇", reply_markup=user_kb.main_menu_kb())


# ---------- STATISTIKA ----------

@router.message(F.text == "📊 Statistika")
async def show_stats(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
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
        f"✅ Bajarilgan: {s['done_orders']}"
    )
    await message.answer(text)


# ---------- BUYURTMALAR ----------

@router.message(F.text == "🧾 Buyurtmalar")
async def list_orders(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        return
    orders = await crud.get_orders_by_status(session, "pending")
    if not orders:
        await message.answer("Kutilayotgan buyurtmalar yo'q.")
        return
    for o in orders:
        await message.answer(
            f"#{o.id} — {o.product_name} — {o.price:,.0f} so'm\n"
            f"Mijoz ID: <code>{o.user_id}</code>",
            reply_markup=admin_kb.order_status_kb(o.id),
        )


@router.callback_query(F.data.startswith("order_status:"))
async def change_order_status(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    if not is_admin(callback.from_user.id):
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

    await callback.message.edit_text(callback.message.text + f"\n\n➡️ Holat: {status}")

    status_text = {
        "in_progress": "🔄 Buyurtmangiz jarayonga qabul qilindi.",
        "done": "✅ Buyurtmangiz bajarildi! Xaridingiz uchun rahmat.",
        "cancelled": "❌ Buyurtmangiz bekor qilindi. Pulingiz balansingizga qaytarildi.",
    }.get(status, f"Buyurtma holati: {status}")

    try:
        await bot.send_message(order.user_id, f"#{order.id}\n{status_text}")
    except Exception:
        pass
    await callback.answer("Yangilandi")


# ---------- MAHSULOTLAR ----------

@router.message(F.text == "🤖 Mahsulotlar")
async def list_products(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        return
    products = await crud.get_active_products(session)
    lines = ["🤖 <b>Mahsulotlar:</b>\n"]
    for p in products:
        lines.append(f"#{p.id} — {p.name} — {p.price:,.0f} so'm")
    lines.append("\nYangi mahsulot qo'shish uchun: /addproduct")
    await message.answer("\n".join(lines))


@router.message(Command("addproduct"))
async def add_product_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminAddProduct.name)
    await message.answer("🤖 Yangi mahsulot nomini kiriting:")


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
    await state.set_state(AdminAddProduct.category)
    await message.answer("🏷 Kategoriyasini kiriting (yoki \"-\" deb yozing):")


@router.message(AdminAddProduct.category)
async def add_product_category(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    category = None if message.text.strip() == "-" else message.text.strip()

    product = await crud.add_product(
        session, name=data["name"], description=data["description"], price=data["price"], category=category
    )
    await state.clear()
    await message.answer(
        f"✅ Mahsulot qo'shildi!\n\n#{product.id} — {product.name} — {product.price:,.0f} so'm",
        reply_markup=admin_kb.admin_menu_kb(),
    )


# ---------- MAJBURIY OBUNALAR ----------

@router.message(F.text == "🔔 Obunalar")
async def list_subscriptions(message: Message, session: AsyncSession):
    if not is_admin(message.from_user.id):
        return
    subs = await crud.get_active_subscriptions(session)
    await message.answer(
        "🔔 <b>Majburiy obunalar:</b>" if subs else "Hozircha majburiy obuna yo'q.",
        reply_markup=admin_kb.subscriptions_manage_kb(subs),
    )


@router.callback_query(F.data == "add_sub")
async def add_sub_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.answer("Obuna turini tanlang:", reply_markup=admin_kb.subscription_platform_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("sub_platform:"))
async def add_sub_platform(callback: CallbackQuery, state: FSMContext):
    platform = callback.data.split(":")[1]
    await state.update_data(platform=platform)
    await state.set_state(AdminAddSubscription.title)
    await callback.message.answer("📝 Nomini kiriting (masalan: \"Bizning kanal\"):")
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
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    sub_id = int(callback.data.split(":")[1])
    await crud.remove_subscription(session, sub_id)
    subs = await crud.get_active_subscriptions(session)
    await callback.message.edit_text(
        "🔔 <b>Majburiy obunalar:</b>" if subs else "Hozircha majburiy obuna yo'q.",
        reply_markup=admin_kb.subscriptions_manage_kb(subs),
    )
    await callback.answer("O'chirildi")


# ---------- REFERRAL SOZLAMASI ----------

@router.message(F.text == "👥 Referral sozlamasi")
async def referral_settings(message: Message, session: AsyncSession, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    percent = await crud.get_referral_percent(session)
    await state.set_state(AdminReferralPercent.percent)
    await message.answer(f"Hozirgi referral foizi: <b>{percent:.0f}%</b>\n\nYangi foizni kiriting:")


@router.message(AdminReferralPercent.percent)
async def set_referral_percent(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.replace(".", "", 1).isdigit():
        await message.answer("❗️ Faqat raqam kiriting.")
        return
    await crud.set_referral_percent(session, float(message.text))
    await state.clear()
    await message.answer(f"✅ Referral foizi {message.text}% ga o'zgartirildi.", reply_markup=admin_kb.admin_menu_kb())


# ---------- BALANS BOSHQARISH ----------

@router.message(F.text == "💰 Balans boshqarish")
async def balance_manage_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminBalanceAdjust.user_id)
    await message.answer("🆔 Foydalanuvchi ID raqamini kiriting:")


@router.message(AdminBalanceAdjust.user_id)
async def balance_manage_user(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam (ID) kiriting.")
        return
    user = await crud.get_user(session, int(message.text))
    if not user:
        await message.answer("❗️ Bunday foydalanuvchi topilmadi.")
        return
    await state.update_data(user_id=user.id)
    await state.set_state(AdminBalanceAdjust.amount)
    await message.answer(
        f"Hozirgi balans: {user.balance:,.0f} so'm\n\n"
        f"Necha so'm qo'shish/ayirish kerak? (ayirish uchun oldiga \"-\" qo'ying, masalan -5000)"
    )


@router.message(AdminBalanceAdjust.amount)
async def balance_manage_amount(message: Message, state: FSMContext, session: AsyncSession):
    try:
        amount = float(message.text.replace(" ", ""))
    except ValueError:
        await message.answer("❗️ Noto'g'ri format. Masalan: 50000 yoki -5000")
        return

    data = await state.get_data()
    user_id = data["user_id"]

    tx_type = "topup" if amount > 0 else "admin_adjust"
    await crud.adjust_balance(session, user_id, amount, tx_type, description="Admin tomonidan qo'lda")

    if amount > 0:
        user = await crud.get_user(session, user_id)
        await crud.apply_referral_bonus_if_first_topup(session, user, amount)

    await state.clear()
    await message.answer(f"✅ Balans yangilandi: {amount:+,.0f} so'm", reply_markup=admin_kb.admin_menu_kb())


# ---------- XABAR YUBORISH (BROADCAST) ----------

@router.message(F.text == "📢 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminBroadcast.content)
    await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:")


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
            await bot.send_message(uid, message.text)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            try:
                await status_msg.edit_text(f"📤 Yuborilmoqda... ({i}/{len(user_ids)})")
            except Exception:
                pass

    await status_msg.edit_text(f"✅ Yakunlandi!\n\nYuborildi: {sent}\nXato: {failed}")
