from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_IDS
from bot.database import crud
from bot.keyboards import user_kb
from bot.utils.states import OrderFlow
from bot.utils.subscription_check import check_all_subscriptions

router = Router(name="user")


# ---------- START ----------

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession, bot: Bot):
    referred_by = None
    if command.args and command.args.isdigit():
        referred_by = int(command.args)

    user, is_new = await crud.get_or_create_user(
        session,
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        referred_by=referred_by,
    )

    if user.is_blocked:
        await message.answer("⛔️ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return

    await show_subscription_gate_or_menu(message, session, bot, user_id=user.id)


async def show_subscription_gate_or_menu(message: Message, session: AsyncSession, bot: Bot, user_id: int):
    all_ok, pending = await check_all_subscriptions(bot, session, user_id)

    if all_ok:
        user = await crud.get_user(session, user_id)
        if user and not user.subscriptions_verified:
            user.subscriptions_verified = True
            await session.commit()
        await message.answer(
            "✅ Xush kelibsiz! Botdan to'liq foydalanishingiz mumkin.",
            reply_markup=user_kb.main_menu_kb(),
        )
    else:
        await message.answer(
            "📢 Botdan foydalanish uchun quyidagilarni bajaring:\n\n"
            "Har birini bosing, so'ng pastdagi <b>\"🔄 Tekshirish\"</b> tugmasini bosing.",
            reply_markup=user_kb.subscriptions_kb(pending),
        )


@router.callback_query(F.data == "check_subs")
async def cb_check_subs(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    all_ok, pending = await check_all_subscriptions(bot, session, callback.from_user.id)

    if all_ok:
        user = await crud.get_user(session, callback.from_user.id)
        if user and not user.subscriptions_verified:
            user.subscriptions_verified = True
            await session.commit()
        await callback.message.edit_text("✅ Barcha shartlar bajarildi!")
        await callback.message.answer("Asosiy menyu 👇", reply_markup=user_kb.main_menu_kb())
    else:
        await callback.answer("❗️ Hali bajarilmagan shartlar bor.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=user_kb.subscriptions_kb(pending))


@router.callback_query(F.data.startswith("confirm_sub:"))
async def cb_confirm_sub(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    sub_id = int(callback.data.split(":")[1])
    await crud.confirm_subscription(session, callback.from_user.id, sub_id)
    await callback.answer("✅ Qabul qilindi")

    all_ok, pending = await check_all_subscriptions(bot, session, callback.from_user.id)
    if all_ok:
        user = await crud.get_user(session, callback.from_user.id)
        if user and not user.subscriptions_verified:
            user.subscriptions_verified = True
            await session.commit()
        await callback.message.edit_text("✅ Barcha shartlar bajarildi!")
        await callback.message.answer("Asosiy menyu 👇", reply_markup=user_kb.main_menu_kb())
    else:
        await callback.message.edit_reply_markup(reply_markup=user_kb.subscriptions_kb(pending))


async def _require_subscription(message: Message, session: AsyncSession, bot: Bot) -> bool:
    """True qaytarsa - foydalanuvchi davom etishi mumkin. False bo'lsa, obuna talab qilingan."""
    all_ok, pending = await check_all_subscriptions(bot, session, message.from_user.id)
    if not all_ok:
        await message.answer(
            "📢 Davom etishdan oldin quyidagilarni bajaring:",
            reply_markup=user_kb.subscriptions_kb(pending),
        )
        return False
    return True


# ---------- KATALOG ----------

@router.message(F.text == "🤖 Botlar katalogi")
async def show_catalog(message: Message, session: AsyncSession, bot: Bot):
    if not await _require_subscription(message, session, bot):
        return

    products = await crud.get_active_products(session)
    if not products:
        await message.answer("Hozircha katalogda botlar yo'q. Keyinroq qayta urinib ko'ring.")
        return

    await message.answer("🤖 <b>Mavjud botlar:</b>", reply_markup=user_kb.catalog_kb(products))


@router.callback_query(F.data.startswith("product:"))
async def show_product(callback: CallbackQuery, session: AsyncSession):
    product_id = int(callback.data.split(":")[1])
    product = await crud.get_product(session, product_id)
    if not product or not product.is_active:
        await callback.answer("Bu mahsulot mavjud emas.", show_alert=True)
        return

    text = (
        f"🤖 <b>{product.name}</b>\n\n"
        f"{product.description}\n\n"
        f"💵 Narxi: <b>{product.price:,.0f} so'm</b>"
    )
    await callback.message.edit_text(text, reply_markup=user_kb.product_detail_kb(product.id))


@router.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(callback: CallbackQuery, session: AsyncSession):
    products = await crud.get_active_products(session)
    await callback.message.edit_text("🤖 <b>Mavjud botlar:</b>", reply_markup=user_kb.catalog_kb(products))


# ---------- BUYURTMA ----------

@router.callback_query(F.data.startswith("order:"))
async def start_order(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    user = await crud.get_user(session, callback.from_user.id)

    if not user.phone:
        await state.update_data(pending_product_id=product_id)
        await state.set_state(OrderFlow.waiting_phone)
        await callback.message.answer(
            "📱 Buyurtma berish uchun avval telefon raqamingizni ulashing:",
            reply_markup=user_kb.phone_request_kb(),
        )
        await callback.answer()
        return

    await _ask_order_confirmation(callback.message, session, product_id)
    await callback.answer()


async def _ask_order_confirmation(message: Message, session: AsyncSession, product_id: int):
    product = await crud.get_product(session, product_id)
    if not product:
        await message.answer("Bu mahsulot topilmadi.")
        return
    await message.answer(
        f"🛒 <b>{product.name}</b> — {product.price:,.0f} so'm\n\nBuyurtmani tasdiqlaysizmi?",
        reply_markup=user_kb.confirm_order_kb(product.id),
    )


@router.message(OrderFlow.waiting_phone, F.contact)
async def phone_received(message: Message, session: AsyncSession, state: FSMContext):
    await crud.set_phone(session, message.from_user.id, message.contact.phone_number)
    await message.answer("✅ Raqam qabul qilindi.", reply_markup=user_kb.main_menu_kb())

    data = await state.get_data()
    product_id = data.get("pending_product_id")
    await state.clear()

    if product_id:
        await _ask_order_confirmation(message, session, product_id)


@router.callback_query(F.data.startswith("confirm_order:"))
async def confirm_order(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    product_id = int(callback.data.split(":")[1])
    product = await crud.get_product(session, product_id)
    user = await crud.get_user(session, callback.from_user.id)

    if not product or not product.is_active:
        await callback.answer("Bu mahsulot endi mavjud emas.", show_alert=True)
        return

    if user.balance < product.price:
        missing = product.price - user.balance
        await callback.message.edit_text(
            f"❗️ Balansingiz yetarli emas.\n\n"
            f"Kerak: {product.price:,.0f} so'm\n"
            f"Balansingiz: {user.balance:,.0f} so'm\n"
            f"Yetishmayapti: {missing:,.0f} so'm\n\n"
            f"Balansni to'ldiring: \"💳 Balans to'ldirish\""
        )
        return

    await crud.adjust_balance(
        session, user.id, -product.price, "order_payment", description=f"Buyurtma: {product.name}"
    )
    order = await crud.create_order(session, user.id, product)

    await callback.message.edit_text(
        f"✅ Buyurtmangiz qabul qilindi!\n\n"
        f"🤖 {product.name}\n"
        f"💵 {product.price:,.0f} so'm\n"
        f"⏳ Bajarilish muddati: 24 soat ichida\n\n"
        f"Admin tez orada siz bilan bog'lanadi."
    )

    # Adminlarga xabar
    admin_text = (
        f"🆕 <b>Yangi buyurtma #{order.id}</b>\n\n"
        f"👤 Mijoz: {user.full_name} (@{user.username or '—'})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📱 Tel: {user.phone or '—'}\n"
        f"🤖 Mahsulot: {product.name}\n"
        f"💵 Narx: {product.price:,.0f} so'm"
    )
    from bot.keyboards.admin_kb import order_status_kb

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=order_status_kb(order.id))
        except Exception:
            pass


# ---------- HISOBIM ----------

@router.message(F.text == "👤 Hisobim")
async def show_account(message: Message, session: AsyncSession):
    user = await crud.get_user(session, message.from_user.id)
    orders = await crud.get_user_orders(session, message.from_user.id)

    text = (
        f"👤 <b>Hisobim</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💰 Balans: <b>{user.balance:,.0f} so'm</b>\n"
        f"🧾 Buyurtmalar: {len(orders)} ta\n"
        f"👥 Referrallar: {user.referral_count} ta\n"
        f"💵 Referraldan topilgan: {user.referral_earned:,.0f} so'm\n"
        f"📈 Jami to'ldirilgan: {user.total_topped_up:,.0f} so'm"
    )
    await message.answer(text)


# ---------- BUYURTMALARIM ----------

STATUS_LABELS = {
    "pending": "⏳ Kutilmoqda",
    "in_progress": "🔄 Jarayonda",
    "done": "✅ Bajarildi",
    "cancelled": "❌ Bekor qilindi",
}


@router.message(F.text == "🧾 Buyurtmalarim")
async def show_orders(message: Message, session: AsyncSession):
    orders = await crud.get_user_orders(session, message.from_user.id)
    if not orders:
        await message.answer("Sizda hali buyurtmalar yo'q.")
        return

    lines = ["🧾 <b>Buyurtmalaringiz:</b>\n"]
    for o in orders:
        lines.append(
            f"#{o.id} — {o.product_name} — {o.price:,.0f} so'm — {STATUS_LABELS.get(o.status, o.status)}"
        )
    await message.answer("\n".join(lines))


# ---------- REFERRAL ----------

@router.message(F.text == "👥 Referral")
async def show_referral(message: Message, session: AsyncSession, bot: Bot):
    user = await crud.get_user(session, message.from_user.id)
    percent = await crud.get_referral_percent(session)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user.id}"

    text = (
        f"👥 <b>Referral tizimi</b>\n\n"
        f"Do'stlaringizni taklif qiling va ular balans to'ldirganda "
        f"<b>{percent:.0f}%</b> bonus oling!\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Takliflar: {user.referral_count} ta\n"
        f"💵 Jami topilgan: {user.referral_earned:,.0f} so'm"
    )
    await message.answer(text)


# ---------- BALANS TO'LDIRISH ----------

@router.message(F.text == "💳 Balans to'ldirish")
async def show_topup(message: Message):
    await message.answer(
        "💳 Balansni to'ldirish uchun miqdorni tanlang.\n\n"
        "To'lov qilingandan so'ng, chekni admin bilan ulashing — balans qo'lda tasdiqlangach hisobingizga tushadi.",
        reply_markup=user_kb.topup_amount_kb(),
    )


@router.callback_query(F.data.startswith("topup:"))
async def request_topup(callback: CallbackQuery, bot: Bot):
    amount = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"💳 Siz <b>{amount:,.0f} so'm</b> miqdorida to'ldirishni tanladingiz.\n\n"
        f"Quyidagi karta raqamiga o'tkazma qiling, so'ng chekni shu botga (yoki adminga) yuboring:\n\n"
        f"💳 <code>0000 0000 0000 0000</code>\n\n"
        f"To'lov tasdiqlangach, balansingiz avtomatik yangilanadi."
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💳 <b>To'ldirish so'rovi</b>\n\n"
                f"👤 {callback.from_user.full_name} (@{callback.from_user.username or '—'})\n"
                f"🆔 ID: <code>{callback.from_user.id}</code>\n"
                f"💵 Miqdor: {amount:,.0f} so'm\n\n"
                f"Tasdiqlash uchun: \"💰 Balans boshqarish\" bo'limidan foydalaning.",
            )
        except Exception:
            pass
    await callback.answer()


# ---------- YORDAM ----------

@router.message(F.text == "🆘 Yordam")
async def show_help(message: Message):
    await message.answer(
        "🆘 <b>Yordam</b>\n\n"
        "Savol yoki muammo bo'lsa, quyidagi admin bilan bog'laning.\n"
        "Buyurtmangiz holatini \"🧾 Buyurtmalarim\" bo'limidan kuzatishingiz mumkin."
    )
