"""
Admin uchun buyruqlar.

KRITIK: bu routerdagi barcha handlerlar F.from_user.id.in_(config.ADMIN_IDS)
filtrini HANDLER FUNKSIYASI ICHIDA emas, balki aiogram FILTER DARAJASIDA
qo'llaydi. Shunda oddiy foydalanuvchi xuddi shu matnli tugmani bossa, aiogram
bu handlerni "mos kelmadi" deb hisoblab, avtomatik user.py dagi handlerga
o'tkazadi.
"""
import asyncio
import time

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import config
import database as db
import keyboards as kb
import services
from states import AdminEdit
from botutils import esc, start_broadcast, BROADCAST

router = Router(name="admin")

# Ushbu router ichidagi HAR BIR handler shu filtrga ega bo'ladi:
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


def _by(callback: CallbackQuery) -> dict:
    """Qaror qabul qilgan adminni jurnalga yozish uchun."""
    return {"by_id": callback.from_user.id, "by_login": f"tg:{callback.from_user.id}"}


async def _append_status(message: Message, suffix: str):
    """Xabar (matnli yoki rasmli) oxiriga holat yozadi va tugmalarni olib tashlaydi."""
    try:
        if message.caption is not None:
            await message.edit_caption(caption=message.html_text + suffix)
        else:
            await message.edit_text(message.html_text + suffix)
    except Exception:
        pass


@router.message(Command("admin"))
async def admin_start(message: Message):
    await message.answer(
        "🛠 Admin panelga xush kelibsiz.",
        reply_markup=kb.admin_main_menu(),
    )


@router.message(F.text == kb.BTN_ADMIN_PANEL_OPEN)
async def open_admin_panel(message: Message):
    await message.answer(
        "Admin panelni ochish uchun quyidagi tugmani bosing:",
        reply_markup=kb.admin_webapp_inline_button(),
    )


@router.message(F.text == kb.BTN_ADMIN_ORDERS)
async def admin_orders(message: Message):
    pending = await db.list_orders(status="pending", limit=10)
    if not pending:
        await message.answer("Hozircha kutilayotgan buyurtmalar yo'q.")
        return
    for o in pending:
        uname = f"@{esc(o['user_username'])}" if o["user_username"] else "username yo'q"
        recipient = esc(o["recipient"]) if o["recipient"] else "o'ziga"
        text = (
            f"Buyurtma nomi: {esc(o['summary'])}\n"
            f"Kim: {esc(o['user_first_name'] or '')} ({uname})\n"
            f"Kimga: {recipient}\n"
            f"ID: {o['user_id']}\n"
            f"Buyurtma ID: <b>{esc(o['id'])}</b>\n"
            f"Qancha to'layapti: ${o['amount_usd']:.2f}"
        )
        await message.answer(text, reply_markup=kb.order_decision_keyboard(o["id"]))


@router.callback_query(F.data.startswith("order_approve:") | F.data.startswith("order_cancel:"))
async def decide_order_cb(callback: CallbackQuery, bot: Bot):
    action, order_id = callback.data.split(":", 1)
    if action == "order_approve":
        result = await services.approve_order(bot, order_id, **_by(callback))
        suffix = "\n\n✅ TASDIQLANDI"
    else:
        result = await services.cancel_order(bot, order_id, **_by(callback))
        suffix = "\n\n❌ BEKOR QILINDI"

    if result == "ok":
        await _append_status(callback.message, suffix)
        await callback.answer()
    elif result == "not_pending":
        await callback.answer("Bu buyurtma allaqachon hal qilingan.", show_alert=True)
    else:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)


@router.message(F.text == kb.BTN_ADMIN_PAYMENTS)
async def admin_payments(message: Message):
    pending = await db.list_payment_requests(status="pending", limit=10)
    if not pending:
        await message.answer("Hozircha kutilayotgan to'lov so'rovlari yo'q.")
        return
    for pr in pending:
        uname = f"@{esc(pr['user_username'])}" if pr["user_username"] else "username yo'q"
        sana = time.strftime("%d.%m.%Y %H:%M", time.localtime(pr["created_at"]))
        amount = f"${pr['amount_usd']:.2f}" if pr["amount_usd"] else "kiritilmagan"
        caption = (
            f"Order raqami: #{pr['id']}\n"
            f"Sanasi: {sana}\n"
            f"Foydalanuvchi: {esc(pr['user_first_name'] or '')} ({uname}, ID: {pr['user_id']})\n"
            f"Joriy balans: ${pr['user_balance']:.2f}\n"
            f"Qancha to'lov qilgani: {amount}"
        )
        if pr["receipt_file_id"]:
            await message.answer_photo(
                pr["receipt_file_id"], caption=caption,
                reply_markup=kb.payment_decision_keyboard(pr["id"]),
            )
        else:
            await message.answer(caption, reply_markup=kb.payment_decision_keyboard(pr["id"]))


@router.callback_query(F.data.startswith("pay_approve:") | F.data.startswith("pay_reject:"))
async def decide_payment_cb(callback: CallbackQuery, bot: Bot):
    action, pr_id_s = callback.data.split(":", 1)
    try:
        pr_id = int(pr_id_s)
    except ValueError:
        await callback.answer()
        return

    pr = await db.get_payment_request(pr_id)
    if not pr:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return

    if action == "pay_approve":
        amount = float(pr["amount_usd"] or 0)
        if amount <= 0:
            await callback.answer(
                "Summa ko'rsatilmagan. Admin panel (Web App) orqali summani kiritib tasdiqlang.",
                show_alert=True,
            )
            return
        result = await services.approve_payment(bot, pr_id, amount, **_by(callback))
        suffix = "\n\n✅ TASDIQLANDI"
    else:
        result = await services.reject_payment(bot, pr_id, **_by(callback))
        suffix = "\n\n❌ RAD ETILDI"

    if result == "ok":
        await _append_status(callback.message, suffix)
        await callback.answer()
    elif result == "not_pending":
        await callback.answer("Bu so'rov allaqachon hal qilingan.", show_alert=True)
    elif result == "invalid_amount":
        await callback.answer("Summa noto'g'ri. Admin panel orqali tasdiqlang.", show_alert=True)
    else:
        await callback.answer("So'rov topilmadi.", show_alert=True)


@router.message(F.text == kb.BTN_ADMIN_USERS)
async def admin_users(message: Message):
    total = await db.count_users()
    await message.answer(
        f"👥 Jami foydalanuvchilar: {total}\n\n"
        "Foydalanuvchini boshqarish uchun Admin panel (Web App) dan foydalaning — "
        f"{kb.BTN_ADMIN_PANEL_OPEN} tugmasini bosing."
    )


def _on_off(value: str | None) -> str:
    return "yoqilgan" if value == "1" else "o'chirilgan"


@router.message(F.text == kb.BTN_ADMIN_SETTINGS)
async def admin_settings(message: Message):
    s = await db.get_all_settings()
    text = (
        "⚙️ Joriy sozlamalar:\n\n"
        f"⭐️ Star narxi: ${s.get('stars_price_per_unit')} (min: {s.get('min_stars_quantity')} dona)\n"
        f"💎 Premium 3oy: ${s.get('premium_price_3m')}\n"
        f"💎 Premium 6oy: ${s.get('premium_price_6m')}\n"
        f"💎 Premium 9oy: ${s.get('premium_price_9m')}\n"
        f"💎 Premium 12oy: ${s.get('premium_price_12m')}\n"
        f"🤝 Referal foizi: {s.get('ref_percent')}%\n"
        f"🔒 Majburiy obuna: {_on_off(s.get('force_sub_enabled'))}\n"
        f"🎁 Bonus (reklama): {_on_off(s.get('bonus_enabled'))}\n\n"
        "Narxlarni, matnlarni va bonusni o'zgartirish uchun Admin panel (Web App)dan foydalaning.\n"
        "Majburiy obuna kanallari: /channels, /addchannel, /delchannel"
    )
    await message.answer(text, reply_markup=kb.admin_webapp_inline_button())


# ---------- Majburiy obuna kanallari ----------
@router.message(Command("channels"))
async def admin_channels(message: Message):
    channels = await db.list_channels()
    if not channels:
        await message.answer(
            "Majburiy obuna kanallari yo'q.\n\n"
            "Qo'shish: <code>/addchannel @kanal_username</code> yoki <code>/addchannel -1001234567890</code>\n"
            "(bot avval kanalga ADMIN qilib qo'shilgan bo'lishi kerak)"
        )
        return
    lines = [f"{c['id']}. {esc(c['title'] or c['chat_id'])} — {esc(c['invite_link'] or '')}" for c in channels]
    await message.answer(
        "Majburiy obuna kanallari:\n\n" + "\n".join(lines) +
        "\n\nO'chirish: <code>/delchannel RAQAM</code>", disable_web_page_preview=True,
    )


@router.message(Command("addchannel"))
async def admin_add_channel(message: Message, command: CommandObject, bot: Bot):
    ref = (command.args or "").strip()
    if not ref:
        await message.answer("Foydalanish: <code>/addchannel @kanal_username</code> yoki <code>/addchannel -100...</code>")
        return
    if not ref.startswith("-") and not ref.startswith("@"):
        ref = "@" + ref
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception:
        await message.answer("Kanal topilmadi. Username/ID to'g'riligini va bot kanalga qo'shilganini tekshiring.")
        return
    if me.status not in ("administrator", "creator"):
        await message.answer("Bot bu kanalda ADMIN emas — obunani tekshira olmaydi. Avval botni kanalga admin qiling.")
        return

    link = f"https://t.me/{chat.username}" if chat.username else None
    if not link:
        try:
            link = await bot.export_chat_invite_link(chat.id)
        except Exception:
            await message.answer("Taklif havolasini olib bo'lmadi. Botga 'havola yaratish' huquqini bering.")
            return

    if any(c["chat_id"] == str(chat.id) for c in await db.list_channels()):
        await message.answer("Bu kanal allaqachon qo'shilgan.")
        return
    await db.add_channel(str(chat.id), chat.title or ref, link)
    await message.answer(
        f"Kanal qo'shildi: {esc(chat.title or ref)}\n"
        "Majburiy obunani yoqish uchun Admin panel → Sozlamalar bo'limidan foydalaning."
    )


@router.message(Command("delchannel"))
async def admin_del_channel(message: Message, command: CommandObject):
    try:
        channel_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("Foydalanish: <code>/delchannel RAQAM</code> (raqamni /channels dan oling)")
        return
    if not any(c["id"] == channel_id for c in await db.list_channels()):
        await message.answer("Bunday raqamli kanal topilmadi.")
        return
    await db.remove_channel(channel_id)
    await message.answer("Kanal o'chirildi.")


@router.message(F.text == kb.BTN_ADMIN_BROADCAST)
async def admin_broadcast_start(message: Message, state: FSMContext):
    await message.answer("📢 Barchaga yuboriladigan xabar matnini kiriting:", reply_markup=kb.cancel_keyboard())
    await state.set_state(AdminEdit.waiting_broadcast_text)


@router.message(AdminEdit.waiting_broadcast_text, F.text)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    task = start_broadcast(bot, message.text)
    if task is None:
        await message.answer("⏳ Hozir boshqa xabar yuborilmoqda. Tugashini kuting.")
        return

    status_msg = await message.answer("Yuborilmoqda... 0")
    while BROADCAST["running"]:
        await asyncio.sleep(3)
        done = BROADCAST["sent"] + BROADCAST["failed"]
        try:
            await status_msg.edit_text(f"Yuborilmoqda... {done}/{BROADCAST['total']}")
        except Exception:
            pass
    await status_msg.edit_text(f"✅ Tugadi. Yuborildi: {BROADCAST['sent']}, xato: {BROADCAST['failed']}")


@router.callback_query(F.data == "fsm_cancel")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()
