"""
StarNest — REST API backend (aiohttp). bot.py ichida aiogram polling bilan
bitta process'da, parallel ravishda ishga tushadi.

ESLATMA: avtomatik to'lov (checkout.uz) olib tashlangan — bu yerda faqat
qo'lda (chek asosidagi) to'lov oqimi bor.

Bonus (AdsGram): foydalanuvchiga bonus FAQAT AdsGram serveri bizning
/api/adsgram/reward manzilimizga (maxfiy kalit bilan) so'rov yuborganda beriladi.
Frontend "reklama ko'rildi" degani bilan balans oshmaydi.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import math
import re
import time
import urllib.parse

from aiogram.types import BufferedInputFile
from aiohttp import web

import config
import database as db
import force_sub
import keyboards as kb
import services
import botutils
from botutils import esc, safe_send

logger = logging.getLogger("starnest.web")

routes = web.RouteTableDef()

_USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{3,32}$")
_ADMIN_LOGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{0,32}$")


# ---------------------------------------------------------------------------
# Token yordamchilari — imzolangan token (HMAC), baza shart emas
# ---------------------------------------------------------------------------

def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_user_token(user_id: int) -> str:
    expires = int(time.time()) + config.USER_TOKEN_TTL_HOURS * 3600
    payload = f"u:{user_id}:{expires}"
    return f"{payload}:{_sign(payload, config.USER_TOKEN_SECRET)}"


def verify_user_token(token: str) -> int | None:
    try:
        prefix, uid, expires, sig = token.split(":")
        payload = f"{prefix}:{uid}:{expires}"
        if prefix != "u" or not hmac.compare_digest(_sign(payload, config.USER_TOKEN_SECRET), sig):
            return None
        if int(expires) < time.time():
            return None
        return int(uid)
    except Exception:
        return None


def make_admin_token(login: str) -> str:
    expires = int(time.time()) + config.ADMIN_TOKEN_TTL_HOURS * 3600
    payload = f"a:{login}:{expires}"
    return f"{payload}:{_sign(payload, config.ADMIN_TOKEN_SECRET)}"


def verify_admin_token(token: str) -> str | None:
    try:
        prefix, login, expires, sig = token.split(":")
        payload = f"{prefix}:{login}:{expires}"
        if prefix != "a" or not hmac.compare_digest(_sign(payload, config.ADMIN_TOKEN_SECRET), sig):
            return None
        if int(expires) < time.time():
            return None
        return login
    except Exception:
        return None


def verify_telegram_init_data(init_data: str) -> dict | None:
    """Telegram initData imzosini tekshiradi (rasmiy algoritm)."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        auth_date = int(parsed.get("auth_date", "0"))
        if time.time() - auth_date > 86400:  # 24 soatdan eski initData qabul qilinmaydi
            return None
        return parsed
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Kichik yordamchilar
# ---------------------------------------------------------------------------

def json_response(data, status: int = 200):
    return web.json_response(data, status=status)


def _http(cls, code: str, **extra):
    """JSON tanali HTTP xato (raise qilish uchun)."""
    return cls(text=json.dumps({"error": code, **extra}), content_type="application/json")


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise _http(web.HTTPBadRequest, "invalid_json")
    if not isinstance(body, dict):
        raise _http(web.HTTPBadRequest, "invalid_json")
    return body


def _to_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_int(value) -> int | None:
    f = _to_float(value)
    if f is None or f != int(f):
        return None
    return int(f)


def _qint(request: web.Request, name: str, default: int, lo: int, hi: int) -> int:
    v = _to_int(request.query.get(name, default))
    if v is None:
        raise _http(web.HTTPBadRequest, f"invalid_{name}")
    return max(lo, min(hi, v))


def _setting_float(s: dict, key: str, default: float) -> float:
    v = _to_float(s.get(key))
    return default if v is None else v


def _setting_int(s: dict, key: str, default: int) -> int:
    v = _to_int(s.get(key))
    return default if v is None else v


def _public_user(row) -> dict:
    d = dict(row)
    d["photo_url"] = db.safe_photo_url(d.get("photo_url"))
    return d


def _client_ip(request: web.Request) -> str:
    # Proksi (Railway) haqiqiy IP'ni ro'yxat OXIRIGA qo'shadi; birinchi qiymatni mijozning o'zi yozishi mumkin
    fwd = request.headers.get("X-Forwarded-For", "")
    parts = [p.strip() for p in fwd.split(",") if p.strip()]
    return parts[-1] if parts else (request.remote or "?")


def _result_response(result: str):
    if result == "ok":
        return json_response({"ok": True})
    status = 404 if result == "not_found" else 400
    return json_response({"error": result}, status)


# --- Login urinishlarini cheklash (xotirada) ---
_LOGIN_WINDOW_SEC = 300
_LOGIN_MAX_FAILS = 5
_fail_log: dict[str, list[float]] = {}


def _login_limited(keys: list[str]) -> bool:
    now = time.time()
    for k in keys:
        recent = [t for t in _fail_log.get(k, []) if now - t < _LOGIN_WINDOW_SEC]
        if recent:
            _fail_log[k] = recent
        else:
            _fail_log.pop(k, None)
        if len(recent) >= _LOGIN_MAX_FAILS:
            return True
    return False


def _login_fail(keys: list[str]):
    now = time.time()
    if len(_fail_log) > 5000:   # xotira cheksiz o'smasligi uchun
        _fail_log.clear()
    for k in keys:
        _fail_log.setdefault(k, []).append(now)


def _login_clear(keys: list[str]):
    for k in keys:
        _fail_log.pop(k, None)


# ---------------------------------------------------------------------------
# Middleware'lar
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
    resp.headers["Access-Control-Allow-Origin"] = config.WEBAPP_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Vary"] = "Origin"
    return resp


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Kutilmagan xatolar JSON 500 bo'lib qaytadi (ichki tafsilotlar oshkor bo'lmaydi)."""
    try:
        return await handler(request)
    except (web.HTTPException, asyncio.CancelledError):
        raise
    except Exception:
        logger.exception("API xatosi: %s %s", request.method, request.path)
        return json_response({"error": "server_error"}, 500)


def _bearer(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def _require_user(request: web.Request):
    """Foydalanuvchi qatorini qaytaradi (token yaroqsiz yoki bloklangan bo'lsa xato)."""
    token = _bearer(request)
    user_id = verify_user_token(token) if token else None
    if user_id is None:
        raise _http(web.HTTPUnauthorized, "unauthorized")
    user = await db.get_user(user_id)
    if not user or user["blocked"]:
        raise _http(web.HTTPForbidden, "blocked")
    return user


async def _require_admin(request: web.Request):
    """Admin qatorini qaytaradi. O'chirilgan adminning eski tokeni ham ishlamaydi."""
    token = _bearer(request)
    login = verify_admin_token(token) if token else None
    admin = await db.get_admin(login) if login else None
    if admin is None:
        raise _http(web.HTTPUnauthorized, "unauthorized")
    return admin


async def _force_sub_block(request: web.Request, user_id: int):
    """Majburiy obuna yoqilgan bo'lsa, obuna bo'lmaganlarga API'dan ham foydalanishni yopadi."""
    channels = await force_sub.get_unsubscribed_channels(request.app["bot"], user_id)
    if channels:
        raise _http(
            web.HTTPForbidden, "force_sub",
            channels=[{"title": c["title"], "url": c["invite_link"]} for c in channels],
        )


# ---------------------------------------------------------------------------
# Foydalanuvchi tomoni
# ---------------------------------------------------------------------------

@routes.post("/api/auth")
async def api_auth(request: web.Request):
    body = await _json_body(request)
    init_data = body.get("initData", "")
    parsed = verify_telegram_init_data(init_data) if isinstance(init_data, str) else None
    if not parsed:
        return json_response({"error": "invalid initData"}, 401)

    try:
        user_json = json.loads(parsed.get("user", "{}"))
    except ValueError:
        return json_response({"error": "invalid user"}, 401)
    user_id = user_json.get("id")
    if not isinstance(user_id, int):
        return json_response({"error": "invalid user"}, 401)

    invited_by = None
    start_param = parsed.get("start_param", "")
    if start_param.startswith("ref_"):
        try:
            rid = int(start_param.removeprefix("ref_"))
            if rid != user_id:
                invited_by = rid
        except ValueError:
            pass

    user = await db.upsert_user(
        user_id, user_json.get("username"), user_json.get("first_name"),
        photo_url=user_json.get("photo_url"), invited_by=invited_by,
    )
    if user["blocked"]:
        return json_response({"error": "blocked"}, 403)

    return json_response({"token": make_user_token(user_id), "user": _public_user(user)})


@routes.get("/api/me")
async def api_me(request: web.Request):
    user = await _require_user(request)
    return json_response({"user": _public_user(user)})


@routes.get("/api/orders/mine")
async def api_orders_mine(request: web.Request):
    user = await _require_user(request)
    orders = await db.list_orders_for_user(user["user_id"])
    return json_response({"orders": [dict(o) for o in orders]})


@routes.get("/api/pricing")
async def api_pricing(request: web.Request):
    s = await db.get_all_settings()
    return json_response({
        "stars_price_per_unit": _setting_float(s, "stars_price_per_unit", 0.015),
        "min_stars_quantity": _setting_int(s, "min_stars_quantity", 50),
        "premium_price_3m": _setting_float(s, "premium_price_3m", 24.0),
        "premium_price_6m": _setting_float(s, "premium_price_6m", 42.0),
        "premium_price_9m": _setting_float(s, "premium_price_9m", 58.0),
        "premium_price_12m": _setting_float(s, "premium_price_12m", 74.0),
        "ref_percent": _setting_float(s, "ref_percent", 5),
        # Balansni to'ldirish uchun — front bu qiymatlar bilan so'mga aylantiradi va
        # karta raqamini ko'rsatadi. Karta hali kiritilmagan bo'lsa frontend buni bildiradi.
        "usd_to_uzs_rate": _setting_float(s, "usd_to_uzs_rate", 12700),
        "topup_card_number": s.get("topup_card_number", ""),
        "topup_card_holder": s.get("topup_card_holder", ""),
        "max_topup_usd": config.MAX_TOPUP_USD,
    })


@routes.get("/api/leaderboard")
async def api_leaderboard(request: web.Request):
    """Ochiq: eng ko'p referal bonus ishlaganlar reytingi (auth shart emas)."""
    top = await db.top_referrers(limit=20)
    return json_response({
        "leaderboard": [
            {
                "first_name": u["first_name"],
                "username": u["username"],
                "photo_url": db.safe_photo_url(u["photo_url"]),
                "invited_count": u["invited_count"],
                "earned": u["earned"],
            }
            for u in top
        ]
    })


@routes.post("/api/orders")
async def api_create_order(request: web.Request):
    user = await _require_user(request)
    user_id = user["user_id"]
    await _force_sub_block(request, user_id)
    body = await _json_body(request)

    type_ = body.get("type")
    if type_ not in ("stars", "premium"):
        return json_response({"error": "invalid type"}, 400)

    s = await db.get_all_settings()

    # Kimga: bo'sh bo'lsa — buyurtma beruvchining O'Z username'i (o'zimga),
    # aks holda kiritilgan username (boshqaga).
    recipient = str(body.get("recipient") or "").strip()
    if not recipient:
        if not user["username"]:
            return json_response({"error": "username_required"}, 400)
        recipient = user["username"]
    if not _USERNAME_RE.match(recipient):
        return json_response({"error": "invalid_recipient"}, 400)
    recipient = "@" + recipient.lstrip("@")
    is_self = bool(user["username"]) and recipient.lower() == "@" + user["username"].lower()

    if type_ == "stars":
        min_qty = _setting_int(s, "min_stars_quantity", 50)
        qty = _to_int(body.get("quantity"))
        if qty is None or not (min_qty <= qty <= 100_000):
            return json_response({"error": "invalid_quantity", "min_quantity": min_qty}, 400)
        price = qty * _setting_float(s, "stars_price_per_unit", 0.015)
        summary = f"{qty} Stars"
    else:
        duration = str(body.get("duration"))
        price_key = {"3": "premium_price_3m", "6": "premium_price_6m",
                     "9": "premium_price_9m", "12": "premium_price_12m"}.get(duration)
        if not price_key:
            return json_response({"error": "invalid duration"}, 400)
        price = _setting_float(s, price_key, 0.0)
        summary = f"Telegram Premium — {duration} oy"

    price = round(price, 4)
    if price <= 0:
        return json_response({"error": "invalid_price"}, 400)   # noto'g'ri sozlangan narx bepul buyurtma bermasin

    # Balansdan yechish + buyurtma yaratish BITTA tranzaksiyada (yechilib, buyurtma yaratilmay qolmaydi)
    order = await db.create_order_paid(user_id, type_, summary, price, recipient=recipient)
    if order is None:
        fresh = await db.get_user(user_id)
        return json_response(
            {"error": "insufficient_balance", "balance": fresh["balance"], "required": price}, 400
        )

    uname = "@" + esc(user["username"]) if user["username"] else "username yo'q"
    whom = esc(recipient) + (" (o'ziga)" if is_self else "")
    text = (
        f"📦 Yangi buyurtma <b>{esc(order['id'])}</b>\n"
        f"Kim: {esc(user['first_name'] or '')} ({uname}), ID: {user_id}\n"
        f"Kimga: {whom}\n"
        f"Nima: {esc(summary)}\nSumma: ${price:.2f}"
    )

    # Adminlarga xabar fonda yuboriladi — foydalanuvchi Telegram'ni kutib qolmaydi
    bot = request.app["bot"]
    markup = kb.order_decision_keyboard(order["id"])
    for admin_id in config.ADMIN_IDS:
        botutils.spawn(safe_send(bot, admin_id, text, reply_markup=markup))

    return json_response({"order": dict(order)})


def _image_kind(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@routes.post("/api/payments")
async def api_create_payment(request: web.Request):
    """Qo'lda to'lov so'rovi — multipart/form-data: amount_usd (ixtiyoriy), receipt (rasm fayl)."""
    user = await _require_user(request)
    user_id = user["user_id"]
    await _force_sub_block(request, user_id)

    if await db.count_pending_payments(user_id) >= config.MAX_PENDING_PAYMENTS:
        return json_response({"error": "too_many_pending"}, 429)
    if not request.content_type.startswith("multipart/"):
        return json_response({"error": "invalid_request"}, 400)

    reader = await request.multipart()
    amount_usd = 0.0
    receipt: bytes | None = None

    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name == "amount_usd":
            v = _to_float((await field.text())[:32])
            if v is not None and 0 < v <= config.MAX_TOPUP_USD:
                amount_usd = round(v, 2)
        elif field.name == "receipt":
            data = bytearray()
            while True:
                chunk = await field.read_chunk(64 * 1024)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > config.MAX_RECEIPT_BYTES:      # xotirani to'ldirib yubormaslik uchun
                    return json_response({"error": "file_too_large"}, 413)
            receipt = bytes(data)

    if not receipt:
        return json_response({"error": "receipt_required"}, 400)
    if _image_kind(receipt) is None:
        return json_response({"error": "invalid_file"}, 400)

    pr = await db.create_payment_request(user_id, amount_usd, None)
    caption = f"💳 Yangi to'lov so'rovi #{pr['id']}\nFoydalanuvchi: {user_id}"
    if amount_usd:
        caption += f"\nTaxminiy summa: ${amount_usd:.2f}"

    # Chekni to'g'ridan-to'g'ri adminlarga yuboramiz (foydalanuvchi chatiga xabar tushmaydi,
    # foydalanuvchi botni bloklagan bo'lsa ham ishlaydi). Birinchi muvaffaqiyatli yuborishdan
    # olingan file_id boshqa adminlar uchun va bazada saqlash uchun ishlatiladi.
    bot = request.app["bot"]
    file_id = None
    for admin_id in config.ADMIN_IDS:
        try:
            photo = file_id or BufferedInputFile(receipt, filename="receipt.jpg")
            msg = await bot.send_photo(admin_id, photo, caption=caption,
                                       reply_markup=kb.payment_decision_keyboard(pr["id"]))
            if not file_id:
                file_id = msg.photo[-1].file_id
                await db.set_payment_receipt(pr["id"], file_id)
        except Exception as e:
            logger.warning("Chek adminga (%s) yuborilmadi: %s", admin_id, e)

    if not file_id:
        # Hech bir adminga yetib bormadi — so'rov "osilib" qolmasin, foydalanuvchi qayta urinsin
        await db.claim_payment_request(pr["id"], "rejected", None, "system:delivery_failed")
        return json_response({"error": "receipt_failed"}, 502)

    pr = await db.get_payment_request(pr["id"])
    return json_response({"payment_request": dict(pr)})


# ---------- Bonus (foydalanuvchi tomoni) ----------

@routes.get("/api/bonus/status")
async def api_bonus_status(request: web.Request):
    user = await _require_user(request)
    s = await db.get_all_settings()
    block_id = (s.get("adsgram_block_id") or "").strip()
    enabled = s.get("bonus_enabled") == "1" and bool(block_id)

    daily_limit = _setting_int(s, "bonus_daily_limit", 5)
    cooldown = _setting_int(s, "bonus_cooldown_sec", 60)
    state = await db.bonus_user_state(user["user_id"])
    now = int(time.time())
    next_at = state["last_at"] + cooldown if state["last_at"] else 0

    channels = await force_sub.get_unsubscribed_channels(request.app["bot"], user["user_id"]) if enabled else []

    return json_response({
        "enabled": enabled,
        "block_id": block_id if enabled else "",
        "amount": _setting_float(s, "bonus_amount_usd", 0.0),
        "daily_limit": daily_limit,
        "used_today": state["used_today"],
        "remaining": max(0, daily_limit - state["used_today"]),
        "cooldown_sec": cooldown,
        "next_available_at": next_at if next_at > now else 0,
        "total_earned": state["total_earned"],
        "server_time": now,
        "force_sub": [{"title": c["title"], "url": c["invite_link"]} for c in channels],
    })


@routes.get("/api/adsgram/reward")
@routes.post("/api/adsgram/reward")
async def api_adsgram_reward(request: web.Request):
    """AdsGram serveri reklama to'liq ko'rilgach shu manzilga so'rov yuboradi:
       /api/adsgram/reward?userid=[userId]&secret=<maxfiy kalit>
    Bonus faqat kalit to'g'ri bo'lganda beriladi. Rad etilgan holatlar ham 200 qaytaradi
    (AdsGram qayta-qayta urinib ko'rmasligi uchun), sabab javob ichida."""
    secret = request.query.get("secret", "")
    expected = await db.get_setting("adsgram_secret", "") or ""
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        logger.warning("AdsGram reward: noto'g'ri kalit (%s)", _client_ip(request))
        return json_response({"error": "forbidden"}, 403)

    user_id = _to_int(request.query.get("userid"))
    if user_id is None:
        return json_response({"error": "invalid_userid"}, 400)

    s = await db.get_all_settings()
    if s.get("bonus_enabled") != "1":
        return json_response({"ok": False, "reason": "disabled"})

    bot = request.app["bot"]
    if await force_sub.get_unsubscribed_channels(bot, user_id):
        return json_response({"ok": False, "reason": "force_sub"})

    result = await db.grant_bonus(
        user_id,
        amount=_setting_float(s, "bonus_amount_usd", 0.0),
        daily_limit=_setting_int(s, "bonus_daily_limit", 5),
        cooldown_sec=_setting_int(s, "bonus_cooldown_sec", 60),
        daily_budget=_setting_float(s, "bonus_daily_budget", 0.0),
    )
    if not result["ok"]:
        logger.info("Bonus berilmadi (user %s): %s", user_id, result["reason"])
        if result["reason"] == "budget":
            logger.warning("Kunlik bonus byudjeti tugadi")
    return json_response({"ok": result["ok"], "reason": result["reason"]})


# ---------------------------------------------------------------------------
# Admin tomoni
# ---------------------------------------------------------------------------

@routes.post("/api/admin/login")
async def api_admin_login(request: web.Request):
    body = await _json_body(request)
    login = str(body.get("login", ""))[:64]
    password = str(body.get("password", ""))[:200]

    keys = [f"ip:{_client_ip(request)}", f"login:{login.lower()}"]
    if _login_limited(keys):
        return json_response({"error": "too_many_attempts"}, 429)

    admin = await db.verify_admin_login(login, password)
    if not admin:
        _login_fail(keys)
        return json_response({"error": "invalid credentials"}, 401)

    _login_clear(keys)
    return json_response({
        "token": make_admin_token(admin["login"]),
        "login": admin["login"],
        "is_owner": bool(admin["is_owner"]),
        "weak_password": bool(admin["pw_weak"]),
    })


@routes.get("/api/admin/verify")
async def api_admin_verify(request: web.Request):
    admin = await _require_admin(request)
    return json_response({
        "login": admin["login"],
        "is_owner": bool(admin["is_owner"]),
        "weak_password": bool(admin["pw_weak"]),
    })


@routes.post("/api/admin/change-password")
async def api_admin_change_password(request: web.Request):
    admin = await _require_admin(request)
    body = await _json_body(request)
    current = str(body.get("current_password", ""))[:200]
    new = str(body.get("new_password", ""))[:200]

    keys = [f"login:{admin['login'].lower()}"]
    if _login_limited(keys):
        return json_response({"error": "too_many_attempts"}, 429)
    if not await db.verify_admin_login(admin["login"], current):
        _login_fail(keys)
        return json_response({"error": "wrong_password"}, 400)
    if db.is_weak_password(new) or new == current:
        return json_response({"error": "weak_password"}, 400)

    await db.set_admin_password(admin["login"], new)
    _login_clear(keys)
    return json_response({"ok": True})


# --- online-holat (buyurtma bildirishnomasini boshqarish uchun) ---
_online_admins: dict[str, float] = {}


@routes.post("/api/admin/heartbeat")
async def api_admin_heartbeat(request: web.Request):
    admin = await _require_admin(request)
    _online_admins[admin["login"]] = time.time()
    return json_response({"ok": True})


@routes.post("/api/admin/leave")
async def api_admin_leave(request: web.Request):
    admin = await _require_admin(request)
    _online_admins.pop(admin["login"], None)
    return json_response({"ok": True})


@routes.get("/api/admin/pricing")
async def api_admin_get_pricing(request: web.Request):
    await _require_admin(request)
    return json_response(await db.get_all_settings())     # maxfiy kalit bu ro'yxatda yo'q


def _validate_pricing(body: dict) -> tuple[dict, str | None]:
    out: dict[str, str] = {}
    for key in ("stars_price_per_unit", "premium_price_3m",
                "premium_price_6m", "premium_price_9m", "premium_price_12m"):
        if key in body:
            v = _to_float(body[key])
            if v is None or not (0 < v <= 100_000):
                return {}, f"invalid_{key}"
            out[key] = str(round(v, 6))
    if "min_stars_quantity" in body:
        v = _to_int(body["min_stars_quantity"])
        if v is None or not (1 <= v <= 100_000):
            return {}, "invalid_min_stars_quantity"
        out["min_stars_quantity"] = str(v)
    if "ref_percent" in body:
        v = _to_float(body["ref_percent"])
        if v is None or not (0 <= v <= 100):
            return {}, "invalid_ref_percent"
        out["ref_percent"] = str(round(v, 4))
    if "welcome_text" in body:
        text = str(body["welcome_text"]).strip()
        if not (1 <= len(text) <= 2000):
            return {}, "invalid_welcome_text"
        out["welcome_text"] = text
    if "force_sub_enabled" in body:
        out["force_sub_enabled"] = "1" if str(body["force_sub_enabled"]).lower() in ("1", "true") else "0"
    if "usd_to_uzs_rate" in body:
        v = _to_float(body["usd_to_uzs_rate"])
        if v is None or not (1000 <= v <= 1_000_000):
            return {}, "invalid_usd_to_uzs_rate"
        out["usd_to_uzs_rate"] = str(round(v, 2))
    if "topup_card_number" in body:
        digits = re.sub(r"\D", "", str(body["topup_card_number"]))
        if digits and not (12 <= len(digits) <= 19):
            return {}, "invalid_card_number"
        # Ko'rinishni chiroyli qilib (4 tadan guruhlab) saqlaymiz, raqam bo'lmasa bo'sh qoldiramiz
        out["topup_card_number"] = " ".join(digits[i:i + 4] for i in range(0, len(digits), 4)) if digits else ""
    if "topup_card_holder" in body:
        holder = str(body["topup_card_holder"]).strip()[:80]
        out["topup_card_holder"] = holder
    return out, None


@routes.post("/api/admin/pricing")
async def api_admin_set_pricing(request: web.Request):
    await _require_admin(request)
    body = await _json_body(request)
    to_set, err = _validate_pricing(body)
    if err:
        return json_response({"error": err}, 400)
    await db.set_settings_many(to_set)
    return json_response({"ok": True})


# ---------- Bonus (admin tomoni) ----------

def _bonus_settings_view(s: dict) -> dict:
    return {
        "enabled": s.get("bonus_enabled") == "1",
        "amount": _setting_float(s, "bonus_amount_usd", 0.0),
        "daily_limit": _setting_int(s, "bonus_daily_limit", 5),
        "cooldown_sec": _setting_int(s, "bonus_cooldown_sec", 60),
        "daily_budget": _setting_float(s, "bonus_daily_budget", 0.0),
        "block_id": s.get("adsgram_block_id", ""),
    }


@routes.get("/api/admin/bonus")
async def api_admin_get_bonus(request: web.Request):
    await _require_admin(request)
    s = await db.get_all_settings(include_secret=True)
    recent = await db.list_recent_bonus(20)
    return json_response({
        "settings": _bonus_settings_view(s),
        "secret": s.get("adsgram_secret", ""),
        "reward_path": "/api/adsgram/reward",
        "stats": await db.bonus_stats(),
        "recent": [dict(r) for r in recent],
    })


@routes.post("/api/admin/bonus")
async def api_admin_set_bonus(request: web.Request):
    await _require_admin(request)
    body = await _json_body(request)

    amount = _to_float(body.get("amount"))
    if amount is None or not (0 < amount <= 100):
        return json_response({"error": "invalid_amount"}, 400)
    daily_limit = _to_int(body.get("daily_limit"))
    if daily_limit is None or not (0 <= daily_limit <= 1000):
        return json_response({"error": "invalid_daily_limit"}, 400)
    cooldown = _to_int(body.get("cooldown_sec"))
    if cooldown is None or not (0 <= cooldown <= 86_400):
        return json_response({"error": "invalid_cooldown"}, 400)
    budget = _to_float(body.get("daily_budget"))
    if budget is None or not (0 <= budget <= 1_000_000):
        return json_response({"error": "invalid_daily_budget"}, 400)
    block_id = str(body.get("block_id", "")).strip()
    if not _BLOCK_ID_RE.match(block_id):
        return json_response({"error": "invalid_block_id"}, 400)
    enabled = bool(body.get("enabled"))
    if enabled and not block_id:
        return json_response({"error": "block_id_required"}, 400)

    await db.set_settings_many({
        "bonus_enabled": "1" if enabled else "0",
        "bonus_amount_usd": str(round(amount, 4)),
        "bonus_daily_limit": str(daily_limit),
        "bonus_cooldown_sec": str(cooldown),
        "bonus_daily_budget": str(round(budget, 2)),
        "adsgram_block_id": block_id,
    })
    return json_response({"ok": True})


@routes.post("/api/admin/bonus/regenerate-secret")
async def api_admin_regenerate_secret(request: web.Request):
    admin = await _require_admin(request)
    secret = await db.regenerate_adsgram_secret()
    logger.warning("AdsGram maxfiy kaliti yangilandi (admin: %s)", admin["login"])
    return json_response({"ok": True, "secret": secret})


# ---------- Buyurtmalar / to'lovlar (admin) ----------

@routes.get("/api/admin/orders")
async def api_admin_orders(request: web.Request):
    await _require_admin(request)
    status = request.query.get("status") or None
    offset = _qint(request, "offset", 0, 0, 1_000_000)
    limit = _qint(request, "limit", 50, 1, 200)
    orders = await db.list_orders(status=status, offset=offset, limit=limit)
    return json_response({"orders": [dict(o) for o in orders]})


@routes.post("/api/admin/orders/{order_id}/{decision}")
async def api_admin_decide_order(request: web.Request):
    admin = await _require_admin(request)
    order_id = request.match_info["order_id"]
    decision = request.match_info["decision"]
    if decision not in ("approve", "cancel"):
        return json_response({"error": "invalid decision"}, 400)

    bot = request.app["bot"]
    fn = services.approve_order if decision == "approve" else services.cancel_order
    return _result_response(await fn(bot, order_id, by_login=admin["login"]))


@routes.get("/api/admin/users")
async def api_admin_users(request: web.Request):
    await _require_admin(request)
    offset = _qint(request, "offset", 0, 0, 1_000_000)
    limit = _qint(request, "limit", 50, 1, 200)
    search = (request.query.get("search") or "")[:64] or None
    users = await db.list_users(offset=offset, limit=limit, search=search)
    total = await db.count_users()
    return json_response({"users": [_public_user(u) for u in users], "total": total})


@routes.post("/api/admin/users/{user_id}/block")
async def api_admin_block_user(request: web.Request):
    await _require_admin(request)
    user_id = _to_int(request.match_info["user_id"])
    if user_id is None or not await db.get_user(user_id):
        return json_response({"error": "not_found"}, 404)
    body = await _json_body(request)
    await db.set_blocked(user_id, bool(body.get("blocked", True)))
    return json_response({"ok": True})


@routes.post("/api/admin/users/{user_id}/adjust-balance")
async def api_admin_adjust_balance(request: web.Request):
    await _require_admin(request)
    user_id = _to_int(request.match_info["user_id"])
    if user_id is None or not await db.get_user(user_id):
        return json_response({"error": "not_found"}, 404)
    body = await _json_body(request)
    delta = _to_float(body.get("delta"))
    if delta is None or delta == 0 or abs(delta) > 100_000:
        return json_response({"error": "invalid_delta"}, 400)
    if delta < 0:
        if not await db.try_deduct(user_id, -delta):        # balansni manfiyga tushirmaydi
            return json_response({"error": "insufficient_balance"}, 400)
        new_balance = (await db.get_user(user_id))["balance"]
    else:
        new_balance = await db.adjust_balance(user_id, delta)
    return json_response({"ok": True, "balance": new_balance})


@routes.post("/api/admin/users/{user_id}/message")
async def api_admin_message_user(request: web.Request):
    await _require_admin(request)
    user_id = _to_int(request.match_info["user_id"])
    if user_id is None:
        return json_response({"error": "not_found"}, 404)
    body = await _json_body(request)
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 4000:
        return json_response({"error": "invalid_text"}, 400)
    if not await safe_send(request.app["bot"], user_id, text):
        return json_response({"error": "send_failed"}, 400)
    return json_response({"ok": True})


@routes.get("/api/admin/payments")
async def api_admin_payments(request: web.Request):
    await _require_admin(request)
    status = request.query.get("status") or None
    offset = _qint(request, "offset", 0, 0, 1_000_000)
    limit = _qint(request, "limit", 50, 1, 200)
    payments = await db.list_payment_requests(status=status, offset=offset, limit=limit)
    return json_response({"payments": [dict(p) for p in payments]})


@routes.get("/api/admin/payments/{pr_id}/receipt")
async def api_admin_payment_receipt(request: web.Request):
    """Foydalanuvchi yuklagan chek rasmini admin panelda ko'rsatish uchun — Telegram'dan
    SERVER TOMONIDA yuklab, brauzerga uzatadi (bot tokeni hech qachon brauzerga chiqmaydi)."""
    await _require_admin(request)
    pr_id = _to_int(request.match_info["pr_id"])
    pr = await db.get_payment_request(pr_id) if pr_id is not None else None
    if not pr or not pr["receipt_file_id"]:
        return json_response({"error": "not_found"}, 404)

    bot = request.app["bot"]
    try:
        try:
            buf = await bot.download(pr["receipt_file_id"])
        except AttributeError:
            tg_file = await bot.get_file(pr["receipt_file_id"])
            buf = await bot.download_file(tg_file.file_path)
        data = buf.read() if hasattr(buf, "read") else bytes(buf)
    except Exception:
        logger.exception("Chek Telegram'dan yuklanmadi (pr %s)", pr_id)
        return json_response({"error": "receipt_unavailable"}, 502)

    kind = _image_kind(data) or "jpeg"
    return web.Response(body=data, content_type=f"image/{kind}",
                        headers={"Cache-Control": "private, max-age=600"})


@routes.post("/api/admin/payments/{pr_id}/{decision}")
async def api_admin_decide_payment(request: web.Request):
    admin = await _require_admin(request)
    pr_id = _to_int(request.match_info["pr_id"])
    decision = request.match_info["decision"]
    if pr_id is None or decision not in ("approve", "reject", "block"):
        return json_response({"error": "invalid decision"}, 400)

    pr = await db.get_payment_request(pr_id)
    if not pr:
        return json_response({"error": "not_found"}, 404)

    bot = request.app["bot"]
    login = admin["login"]

    if decision == "approve":
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        amount = _to_float(body.get("amount_usd", pr["amount_usd"]))
        result = await services.approve_payment(bot, pr_id, amount if amount is not None else 0.0, by_login=login)
    else:
        result = await services.reject_payment(bot, pr_id, by_login=login, block_user=(decision == "block"))
    return _result_response(result)


# ---------- Broadcast ----------

@routes.post("/api/admin/broadcast")
async def api_admin_broadcast(request: web.Request):
    await _require_admin(request)
    body = await _json_body(request)
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 4000:
        return json_response({"error": "invalid_text"}, 400)
    if botutils.start_broadcast(request.app["bot"], text) is None:
        return json_response({"error": "already_running"}, 409)
    return json_response({"ok": True, "started": True})


@routes.get("/api/admin/broadcast/status")
async def api_admin_broadcast_status(request: web.Request):
    await _require_admin(request)
    return json_response(dict(botutils.BROADCAST))


# ---------- Adminlar ----------

@routes.get("/api/admin/admins")
async def api_admin_list_admins(request: web.Request):
    await _require_admin(request)
    admins = await db.list_admins()
    return json_response({"admins": [dict(a) for a in admins]})


@routes.post("/api/admin/admins")
async def api_admin_add_admin(request: web.Request):
    requester = await _require_admin(request)
    if not requester["is_owner"]:
        return json_response({"error": "only owner can add admins"}, 403)
    body = await _json_body(request)
    new_login = str(body.get("login", "")).strip()
    new_password = str(body.get("password", ""))[:200]
    if not _ADMIN_LOGIN_RE.match(new_login):
        return json_response({"error": "invalid_login"}, 400)
    if db.is_weak_password(new_password):
        return json_response({"error": "weak_password"}, 400)
    if await db.get_admin(new_login):
        return json_response({"error": "already exists"}, 400)
    await db.add_admin(new_login, new_password, is_owner=False)
    return json_response({"ok": True})


@routes.delete("/api/admin/admins/{login}")
async def api_admin_remove_admin(request: web.Request):
    requester = await _require_admin(request)
    if not requester["is_owner"]:
        return json_response({"error": "only owner can remove admins"}, 403)
    target_login = request.match_info["login"]
    target = await db.get_admin(target_login)
    if not target:
        return json_response({"error": "not_found"}, 404)
    if target["is_owner"]:
        return json_response({"error": "cannot remove owner"}, 400)
    await db.remove_admin(target_login)
    return json_response({"ok": True})


# ---------------------------------------------------------------------------
# App yaratish
# ---------------------------------------------------------------------------

def create_app(bot) -> web.Application:
    app = web.Application(middlewares=[cors_middleware, error_middleware], client_max_size=2 * 1024 * 1024)
    app["bot"] = bot
    app.add_routes(routes)

    async def health(request):
        return web.Response(text="ok")

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    return app
