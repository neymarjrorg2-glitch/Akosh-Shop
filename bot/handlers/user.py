import math

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import config
import database as db
import keyboards as kb
import force_sub
from states import UserFlow
from botutils import safe_send

router = Router(name="user")


async def _send_force_sub(message: Message, channels):
    await message.answer(
        "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng "
        "\"✅ Tekshirish\" tugmasini bosing:",
        reply_markup=kb.force_sub_keyboard(channels),
    )


def _parse_amount(caption: str) -> float:
    """Chek izohidagi summani ajratib oladi. Noto'g'ri/haddan katta qiymat -> 0 (admin qo'lda kiritadi)."""
    for token in caption.replace(",", ".").split():
        try:
            value = float(token.strip("$"))
        except ValueError:
            continue
        if math.isfinite(value) and 0 < value <= config.MAX_TOPUP_USD:
            return round(value, 2)
    return 0.0


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    invited_by = None
    if command.args and command.args.startswith("ref_"):
        try:
            ref_id = int(command.args.removeprefix("ref_"))
            if ref_id != message.from_user.id:
                invited_by = ref_id
        except ValueError:
            pass

    # DIQQAT: foydalanuvchi rasmi URL'i bu yerda olinmaydi. Telegram file API manzili
    # bot tokenini o'z ichiga oladi — uni bazaga yozish tokenni oshkor qiladi.
    # Rasm Web App orqali (initData ichidagi photo_url) xavfsiz holda keladi.
    await db.upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        invited_by=invited_by,
    )

    channels = await force_sub.get_unsubscribed_channels(message.bot, message.from_user.id)
    if channels:
        await _send_force_sub(message, channels)
        return

    welcome_text = await db.get_setting("welcome_text", "StarNest botiga xush kelibsiz!")
    is_admin = message.from_user.id in config.ADMIN_IDS
    markup = kb.admin_main_menu() if is_admin else kb.user_main_menu()
    try:
        await message.answer(welcome_text, reply_markup=markup)
    except TelegramBadRequest:
        # Admin matnga noto'g'ri HTML yozgan bo'lsa ham /start ishlashda davom etadi
        await message.answer(welcome_text, reply_markup=markup, parse_mode=None)


@router.callback_query(F.data == "check_sub")
async def check_sub_cb(callback: CallbackQuery):
    channels = await force_sub.get_unsubscribed_channels(callback.bot, callback.from_user.id)
    if channels:
        await callback.answer("Hali barcha kanallarga obuna bo'lmagansiz.", show_alert=True)
        return
    for ch in await db.list_channels():
        await db.confirm_sub(callback.from_user.id, ch["chat_id"])
    is_admin = callback.from_user.id in config.ADMIN_IDS
    await callback.message.delete()
    await callback.message.answer(
        "✅ Rahmat! Endi botdan to'liq foydalanishingiz mumkin.",
        reply_markup=kb.admin_main_menu() if is_admin else kb.user_main_menu(),
    )
    await callback.answer()


# Admin router botga birinchi ro'yxatdan o'tkaziladi (bot.py) va uning barcha handlerlari
# ADMIN_IDS filtri bilan himoyalangan. BTN_BUY tugmasi uchun admin.py da alohida handler yo'q —
# shuning uchun bu tugma admin uchun ham, oddiy foydalanuvchi uchun ham shu yerdagi handlerga tushadi.
@router.message(F.text == kb.BTN_BUY)
async def buy_menu(message: Message):
    channels = await force_sub.get_unsubscribed_channels(message.bot, message.from_user.id)
    if channels:
        await _send_force_sub(message, channels)
        return
    await message.answer(
        "Stars yoki Telegram Premium sotib olish uchun quyidagi tugmani bosing 👇",
        reply_markup=kb.webapp_inline_button(),
    )


@router.message(F.text == kb.BTN_BALANCE)
async def show_balance(message: Message):
    user = await db.get_user(message.from_user.id)
    balance = user["balance"] if user else 0
    await message.answer(f"💰 Sizning balansingiz: <b>${balance:.2f}</b>")


@router.message(F.text == kb.BTN_TOPUP)
async def topup_start(message: Message, state: FSMContext):
    channels = await force_sub.get_unsubscribed_channels(message.bot, message.from_user.id)
    if channels:
        await _send_force_sub(message, channels)
        return

    s = await db.get_all_settings()
    card = (s.get("topup_card_number") or "").strip()
    holder = (s.get("topup_card_holder") or "").strip()
    try:
        rate = float(s.get("usd_to_uzs_rate") or 0)
    except ValueError:
        rate = 0.0

    if not card:
        await message.answer("Hozircha to'lov kartasi sozlanmagan. Iltimos, admin bilan bog'laning.")
        return

    lines = ["Balansni to'ldirish uchun quyidagi kartaga pul o'tkazing:\n", f"Karta: <code>{card}</code>"]
    if holder:
        lines.append(f"Egasi: {holder}")
    if rate > 0:
        lines.append(f"Kurs: 1$ = {rate:,.0f} so'm".replace(",", " "))
    lines.append(
        "\nSo'ng to'lov chekining rasmini shu yerga yuboring (izohga summani $ da yozishingiz mumkin). "
        "Admin tekshirib, balansingizga mablag' qo'shadi."
    )
    await message.answer("\n".join(lines), reply_markup=kb.cancel_keyboard())
    await state.set_state(UserFlow.waiting_receipt)


@router.message(UserFlow.waiting_receipt, F.photo)
async def topup_receipt_received(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    if await db.count_pending_payments(message.from_user.id) >= config.MAX_PENDING_PAYMENTS:
        await message.answer("⏳ Sizda tekshirilmagan so'rovlar ko'p. Avval ular ko'rib chiqilishini kuting.")
        return

    receipt_file_id = message.photo[-1].file_id
    # Foydalanuvchi summani izohda yozgan bo'lishi mumkin, aks holda 0 —
    # admin summani qo'lda kiritadi (chek yozuvida ko'rsatilgan summani ko'rib).
    amount = _parse_amount(message.caption or "")

    pr = await db.create_payment_request(message.from_user.id, amount, receipt_file_id)
    await message.answer("✅ Chekingiz qabul qilindi, admin tez orada tekshiradi.")

    cap = f"💳 Yangi to'lov so'rovi #{pr['id']}\nFoydalanuvchi: {message.from_user.id}"
    if amount:
        cap += f"\nTaxminiy summa: ${amount:.2f}"
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, receipt_file_id, caption=cap,
                                 reply_markup=kb.payment_decision_keyboard(pr["id"]))
        except Exception:
            pass


@router.message(UserFlow.waiting_receipt)
async def topup_receipt_missing(message: Message):
    await message.answer("Iltimos, to'lov chekining RASMINI yuboring 🖼")


@router.message(F.text == kb.BTN_REFERRAL)
async def referral_info(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start buyrug'ini yuboring.")
        return
    ref_percent = await db.get_setting("ref_percent", "5")
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    await message.answer(
        "🤝 <b>Referal dasturi</b>\n\n"
        f"Do'stlaringiz sizning havolangiz orqali botga kirsa va balans to'ldirsa, "
        f"siz to'ldirilgan summaning <b>{ref_percent}%</b>ini bonus sifatida olasiz.\n\n"
        f"👥 Taklif qilinganlar: {user['invited_count']}\n"
        f"💵 Jami ishlab topilgan: ${user['earned']:.2f}\n\n"
        f"🔗 Sizning havolangiz:\n<code>{link}</code>"
    )


@router.message(F.text == kb.BTN_HELP)
async def help_cmd(message: Message):
    await message.answer(
        "❓ <b>Yordam</b>\n\n"
        f"{kb.BTN_BUY} — Stars yoki Premium sotib olish (ilova ichida 🎁 Bonus bo'limida reklama ko'rib bonus olishingiz mumkin)\n"
        f"{kb.BTN_BALANCE} — joriy balansingizni ko'rish\n"
        f"{kb.BTN_TOPUP} — balansni chek orqali to'ldirish\n"
        f"{kb.BTN_REFERRAL} — do'stlaringizni taklif qilib bonus oling\n\n"
        "Savollar bo'lsa, admin bilan bog'laning."
    )


@router.callback_query(F.data == "fsm_cancel")
async def cancel_fsm_user(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()
