from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_IDS
from bot.database import crud
from bot.database.crud import MIN_TOPUP_AMOUNT
from bot.keyboards import user_kb
from bot.utils.states import OrderFlow, TopupFlow
from bot.utils.subscription_check import check_all_subscriptions

router = Router(name="user")


# ---------- START ----------

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession, bot: Bot, state: FSMContext):
    await state.clear()

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
        welcome_text = await crud.get_text(session, "welcome_text")
        await message.answer(welcome_text, reply_markup=user_kb.main_menu_kb())
    else:
        await message.answer(
            "📢 <b>Botdan foydalanish uchun quyidagi shartlarni bajaring:</b>\n\n"
            "Har bir havolani bosing, so'ng kerak bo'lsa tasdiqlash tugmasini bosing.\n"
            "Hammasi bajarilgach — pastdagi <b>\"🔄 Tekshirish\"</b> tugmasini bosing.",
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


def _product_caption(product) -> str:
    return (
        f"🤖 <b>{product.name}</b>\n\n"
        f"{product.description}\n\n"
        f"💵 Narxi: <b>{product.price:,.0f} so'm</b>"
    )


@router.callback_query(F.data.startswith("product:"))
async def show_product(callback: CallbackQuery, session: AsyncSession):
    product_id = int(callback.data.split(":")[1])
    product = await crud.get_product(session, product_id)
    if not product or not product.is_active:
        await callback.answer("Bu mahsulot mavjud emas.", show_alert=True)
        return

    caption = _product_caption(product)
    kb = user_kb.product_detail_kb(product.id)

    if product.media_file_id and product.media_type == "photo":
        await callback.message.answer_photo(product.media_file_id, caption=caption, reply_markup=kb)
    elif product.media_file_id and product.media_type == "video":
        await callback.message.answer_video(product.media_file_id, caption=caption, reply_markup=kb)
    else:
        await callback.message.answer(caption, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(callback: CallbackQuery, session: AsyncSession):
    products = await crud.get_active_products(session)
    await callback.message.answer("🤖 <b>Mavjud botlar:</b>", reply_markup=user_kb.catalog_kb(products))
    await callback.answer()


# ---------- BUYURTMA (bot nomi + username so'raladi) ----------

@router.callback_query(F.data.startswith("order:"))
async def start_order(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    await state.update_data(pending_product_id=product_id)
    await state.set_state(OrderFlow.waiting_bot_name)
    await callback.message.answer(
        "🤖 Botingiz uchun xohlagan <b>NOM</b>ni kiriting (masalan: \"Mening Do'konim\"):",
        reply_markup=user_kb.cancel_kb(),
    )
    await callback.answer()


@router.message(F.text == "❌ Bekor qilish")
async def cancel_any_flow(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=user_kb.main_menu_kb())


@router.message(OrderFlow.waiting_bot_name)
async def order_bot_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Iltimos, matn ko'rinishida kiriting.")
        return
    await state.update_data(bot_name=message.text.strip())
    await state.set_state(OrderFlow.waiting_bot_username)
    await message.answer(
        "🔤 Endi botingiz uchun xohlagan <b>USERNAME</b>ni kiriting "
        "(masalan: \"mening_dokonim_bot\"):",
        reply_markup=user_kb.cancel_kb(),
    )


@router.message(OrderFlow.waiting_bot_username)
async def order_bot_username(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text:
        await message.answer("Iltimos, matn ko'rinishida kiriting.")
        return

    data = await state.get_data()
    product_id = data.get("pending_product_id")
    bot_name = data.get("bot_name")
    bot_username = message.text.strip()
    await state.clear()

    product = await crud.get_product(session, product_id)
    if not product:
        await message.answer("Bu mahsulot topilmadi.", reply_markup=user_kb.main_menu_kb())
        return

    await state.update_data(bot_name=bot_name, bot_username=bot_username, pending_product_id=product_id)
    await message.answer(
        f"🛒 <b>{product.name}</b> — {product.price:,.0f} so'm\n\n"
        f"🤖 Bot nomi: {bot_name}\n"
        f"🔤 Username: {bot_username}\n\n"
        f"Buyurtmani tasdiqlaysizmi?",
        reply_markup=user_kb.confirm_order_kb(product.id),
    )


@router.callback_query(F.data.startswith("confirm_order:"))
async def confirm_order(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    product = await crud.get_product(session, product_id)
    user = await crud.get_user(session, callback.from_user.id)

    data = await state.get_data()
    bot_name = data.get("bot_name")
    bot_username = data.get("bot_username")
    await state.clear()

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
    order = await crud.create_order(
        session, user.id, product, custom_nickname=bot_name, custom_username=bot_username
    )

    await callback.message.edit_text(
        f"✅ Buyurtmangiz qabul qilindi! #{order.id}\n\n"
        f"🤖 {product.name}\n"
        f"💵 {product.price:,.0f} so'm\n"
        f"⏳ Bajarilish muddati: 24 soat ichida\n\n"
        f"Admin tez orada siz bilan bog'lanadi."
    )

    admin_text = (
        f"🆕 <b>Yangi buyurtma #{order.id}</b>\n\n"
        f"👤 Mijoz: {user.full_name} (@{user.username or '—'})\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🤖 Mahsulot: {product.name}\n"
        f"💵 Narx: {product.price:,.0f} so'm\n\n"
        f"🏷 Bot nomi: {bot_name}\n"
        f"🔤 Bot username: {bot_username}"
    )
    from bot.keyboards.admin_kb import order_status_kb

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=order_status_kb(order.id, order.status))
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

    for o in orders:
        text = (
            f"🧾 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🤖 Mahsulot: {o.product_name}\n"
            f"💵 Narx: {o.price:,.0f} so'm\n"
        )
        if o.custom_nickname:
            text += f"🏷 Bot nomi: {o.custom_nickname}\n"
        if o.custom_username:
            text += f"🔤 Username: {o.custom_username}\n"
        text += (
            f"📅 Sana: {o.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📌 Holat: {STATUS_LABELS.get(o.status, o.status)}"
        )
        await message.answer(text)


# ---------- REFERRAL ----------

@router.message(F.text == "👥 Referral")
async def show_referral(message: Message, session: AsyncSession, bot: Bot):
    user = await crud.get_user(session, message.from_user.id)
    percent = await crud.get_referral_percent(session)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user.id}"

    text = (
        f"👥 <b>Referral tizimi</b>\n\n"
        f"Do'stlaringizni taklif qiling va ular birinchi marta balans to'ldirganda "
        f"<b>{percent:.0f}%</b> bonus oling!\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
        f"👤 Takliflar: {user.referral_count} ta\n"
        f"💵 Jami topilgan: {user.referral_earned:,.0f} so'm"
    )
    await message.answer(text)


# ---------- BALANS TO'LDIRISH ----------

@router.message(F.text == "💳 Balans to'ldirish")
async def show_topup(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"💳 Balansni to'ldirish uchun miqdorni tanlang (minimal {MIN_TOPUP_AMOUNT:,.0f} so'm):",
        reply_markup=user_kb.topup_amount_kb(),
    )


@router.callback_query(F.data == "topup_custom")
async def topup_custom_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TopupFlow.waiting_custom_amount)
    await callback.message.answer(
        f"✏️ To'ldirmoqchi bo'lgan summani kiriting (minimal {MIN_TOPUP_AMOUNT:,.0f} so'm):",
        reply_markup=user_kb.cancel_kb(),
    )
    await callback.answer()


@router.message(TopupFlow.waiting_custom_amount)
async def topup_custom_amount(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text or not message.text.replace(" ", "").isdigit():
        await message.answer("❗️ Iltimos, faqat raqam kiriting.")
        return

    amount = float(message.text.replace(" ", ""))
    if amount < MIN_TOPUP_AMOUNT:
        await message.answer(f"❗️ Minimal miqdor {MIN_TOPUP_AMOUNT:,.0f} so'm. Qaytadan kiriting:")
        return

    await _start_topup_payment(message, state, session, amount)


@router.callback_query(F.data.startswith("topup:"))
async def request_topup(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    amount = float(callback.data.split(":")[1])
    await callback.answer()
    await _start_topup_payment(callback.message, state, session, amount)


async def _start_topup_payment(message: Message, state: FSMContext, session: AsyncSession, amount: float):
    card_info = await crud.get_text(session, "card_info")
    await state.update_data(topup_amount=amount)
    await state.set_state(TopupFlow.waiting_receipt)
    await message.answer(
        f"💳 <b>{amount:,.0f} so'm</b> miqdorida to'ldirishni tanladingiz.\n\n"
        f"Quyidagi karta raqamiga o'tkazma qiling:\n\n{card_info}\n\n"
        f"✅ To'lovni amalga oshirgach, <b>chek rasmini shu yerga yuboring</b> — "
        f"admin tasdiqlagach, balansingiz avtomatik yangilanadi.",
        reply_markup=user_kb.cancel_kb(),
    )


@router.message(TopupFlow.waiting_receipt, F.photo)
async def topup_receipt_received(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    amount = data.get("topup_amount")
    await state.clear()

    if not amount:
        await message.answer("Xatolik yuz berdi, qaytadan urinib ko'ring.", reply_markup=user_kb.main_menu_kb())
        return

    receipt_file_id = message.photo[-1].file_id
    req = await crud.create_topup_request(session, message.from_user.id, amount, receipt_file_id)

    await message.answer(
        "✅ Chekingiz qabul qilindi! Admin tekshirgach, balansingiz yangilanadi.",
        reply_markup=user_kb.main_menu_kb(),
    )

    from bot.keyboards.admin_kb import topup_confirm_kb

    caption = (
        f"💳 <b>Yangi to'lov so'rovi #{req.id}</b>\n\n"
        f"👤 {message.from_user.full_name} (@{message.from_user.username or '—'})\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"💵 Miqdor: {amount:,.0f} so'm"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, receipt_file_id, caption=caption, reply_markup=topup_confirm_kb(req.id))
        except Exception:
            pass


@router.message(TopupFlow.waiting_receipt)
async def topup_receipt_not_photo(message: Message):
    await message.answer("📸 Iltimos, to'lov chekining RASMINI yuboring.")


# ---------- YORDAM ----------

@router.message(F.text == "🆘 Yordam")
async def show_help(message: Message, session: AsyncSession):
    text = await crud.get_text(session, "help_text")
    await message.answer(text)
