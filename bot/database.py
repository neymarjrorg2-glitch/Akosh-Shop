"""
StarNest — ma'lumotlar bazasi moduli (SQLite, aiosqlite orqali).

Jadvallar:
  users            — foydalanuvchilar
  settings         — key/value sozlamalar (matn, narx, referal foizi, bonus va h.k.)
  channels         — majburiy obuna kanallari
  user_confirms    — kim qaysi kanalga obuna bo'lganini tasdiqlagan
  orders           — buyurtmalar (Stars / Premium)
  admins           — ko'p-adminli tizim (parollar scrypt bilan hashlangan)
  payment_requests — qo'lda to'lov so'rovlari (chek bilan)
  bonus_rewards    — reklama uchun berilgan bonuslar jurnali

MUHIM QOIDALAR (pul bilan ishlash):
  * Balansni kamaytirish faqat try_deduct() orqali — u tekshiruv va yechishni
    BITTA SQL so'rovida bajaradi (ikki marta sarflashning oldini oladi).
  * Buyurtma / to'lov holatini o'zgartirish faqat claim_*() orqali —
    "WHERE status = 'pending'" sharti bilan, shuning uchun bir so'rovni
    ikki marta tasdiqlab (yoki qaytarib) bo'lmaydi. Pul faqat claim muvaffaqiyatli
    bo'lgandan KEYIN o'tkaziladi.

ESLATMA: avtomatik to'lov (checkout.uz) funksiyasi loyihadan olib tashlangan —
faqat qo'lda (chek asosida) balans to'ldirish bor.
"""
import asyncio
import hashlib
import hmac
import logging
import secrets
import time

import aiosqlite

import config

logger = logging.getLogger("starnest.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    joined_at    INTEGER NOT NULL,
    balance      REAL NOT NULL DEFAULT 0,
    invited_by   INTEGER,
    invited_count INTEGER NOT NULL DEFAULT 0,
    earned       REAL NOT NULL DEFAULT 0,
    blocked      INTEGER NOT NULL DEFAULT 0,
    photo_url    TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL,
    title      TEXT,
    invite_link TEXT
);

CREATE TABLE IF NOT EXISTS user_confirms (
    user_id  INTEGER NOT NULL,
    chat_id  TEXT NOT NULL,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    type         TEXT NOT NULL,        -- 'stars' | 'premium'
    summary      TEXT NOT NULL,        -- masalan: "100 Stars" yoki "Telegram Premium — 6 oy"
    recipient    TEXT,                 -- kimga (username), bo'sh bo'lsa — o'ziga
    amount_usd   REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|cancelled
    created_at   INTEGER NOT NULL,
    decided_at   INTEGER,
    decided_by   INTEGER
);

CREATE TABLE IF NOT EXISTS admins (
    login      TEXT PRIMARY KEY,
    password   TEXT NOT NULL,
    is_owner   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount_usd  REAL NOT NULL,
    receipt_file_id TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    created_at  INTEGER NOT NULL,
    decided_at  INTEGER,
    decided_by  INTEGER
);

CREATE TABLE IF NOT EXISTS bonus_rewards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount_usd  REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT 'adsgram',
    day         INTEGER NOT NULL,     -- kun raqami (BONUS_TZ_OFFSET_HOURS bo'yicha)
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_pr_status ON payment_requests (status);
CREATE INDEX IF NOT EXISTS idx_pr_user ON payment_requests (user_id);
CREATE INDEX IF NOT EXISTS idx_bonus_user_day ON bonus_rewards (user_id, day);
CREATE INDEX IF NOT EXISTS idx_bonus_day ON bonus_rewards (day);
"""

_DEFAULT_SETTINGS = {
    "stars_price_per_unit": "0.015",   # 1 dona Star narxi, USD
    "premium_price_3m": "24.0",
    "premium_price_6m": "42.0",
    "premium_price_9m": "58.0",
    "premium_price_12m": "74.0",
    "ref_percent": "5",
    "welcome_text": "StarNest botiga xush kelibsiz! ⭐️",
    "force_sub_enabled": "0",
    # --- Bonus (AdsGram rewarded reklama) — admin paneldan boshqariladi ---
    "bonus_enabled": "0",              # standart holatda o'chirilgan
    "bonus_amount_usd": "0.002",       # bitta reklama uchun bonus
    "bonus_daily_limit": "5",          # bir foydalanuvchiga kuniga nechta reklama
    "bonus_cooldown_sec": "60",        # reklamalar orasidagi pauza
    "bonus_daily_budget": "10",        # kuniga jami beriladigan bonus (USD), 0 = cheksiz
    "adsgram_block_id": "",
    # --- Balansni to'ldirish (qo'lda, karta orqali) ---
    "usd_to_uzs_rate": "12700",        # 1 USD = necha so'm — admin panelda yangilab turiladi
    "topup_card_number": "",           # masalan: "9860 1234 5678 9012"
    "topup_card_holder": "",           # masalan: "ALIYEV AZIZ"
    # --- Xarid cheklovlari ---
    "min_stars_quantity": "50",        # bitta buyurtmada eng kam Stars miqdori
}

# Maxfiy sozlamalar — umumiy ro'yxatlarda (get_all_settings) qaytarilmaydi
_SECRET_SETTINGS = {"adsgram_secret"}

_db: aiosqlite.Connection | None = None

# Bir nechta SQL qadamdan iborat amallarni ketma-ket bajarish uchun
_write_lock = asyncio.Lock()
_bonus_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Parollar (scrypt) — faqat stdlib
# ---------------------------------------------------------------------------
_WEAK_PASSWORDS = {"admin", "password", "12345678", "123456789", "qwerty123", "admin123", "parol123"}


def is_weak_password(password: str) -> bool:
    return len(password) < 8 or password.lower() in _WEAK_PASSWORDS


def _hash_password_sync(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def _verify_password_sync(stored: str, password: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, bytes.fromhex(hash_hex))
    except Exception:
        return False


# Mavjud bo'lmagan login uchun ham xuddi shuncha vaqt sarflash (login enumeration'dan himoya)
_DUMMY_HASH = _hash_password_sync("starnest-dummy-password")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_password_sync, password)


# ---------------------------------------------------------------------------
# Init / migratsiyalar
# ---------------------------------------------------------------------------
async def _ensure_column(table: str, column: str, ddl: str):
    cur = await _db.execute(f"PRAGMA table_info({table})")
    cols = [r["name"] for r in await cur.fetchall()]
    if column not in cols:
        await _db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


async def init():
    global _db
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(_SCHEMA)

    # --- Yengil migratsiyalar (eski bazalar uchun) ---
    await _ensure_column("orders", "decided_by_login", "TEXT")
    await _ensure_column("orders", "recipient", "TEXT")
    await _ensure_column("payment_requests", "decided_by_login", "TEXT")
    await _ensure_column("admins", "pw_weak", "INTEGER NOT NULL DEFAULT 0")

    for k, v in _DEFAULT_SETTINGS.items():
        await _db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    # AdsGram reward URL uchun maxfiy kalit (bir marta yaratiladi, admin paneldan yangilanadi)
    await _db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('adsgram_secret', ?)",
        (secrets.token_urlsafe(24),),
    )

    # Eski versiyada foydalanuvchi rasmi URL'iga BOT TOKEN yozilib qolgan — tozalaymiz
    cur = await _db.execute("UPDATE users SET photo_url = NULL WHERE photo_url LIKE '%/file/bot%'")
    if cur.rowcount:
        logger.warning("%d ta foydalanuvchining photo_url maydonidan bot tokeni o'chirildi", cur.rowcount)

    # Ochiq matndagi admin parollarini hashga o'tkazamiz
    cur = await _db.execute("SELECT login, password FROM admins")
    for row in await cur.fetchall():
        if not row["password"].startswith("scrypt$"):
            hashed = await hash_password(row["password"])
            weak = 1 if is_weak_password(row["password"]) else 0
            await _db.execute(
                "UPDATE admins SET password = ?, pw_weak = ? WHERE login = ?", (hashed, weak, row["login"])
            )
            logger.warning("Admin '%s' paroli hashga o'tkazildi", row["login"])

    # Agar bazada birorta ham admin bo'lmasa — env'dagi bosh admin bilan yaratamiz
    cur = await _db.execute("SELECT COUNT(*) AS c FROM admins")
    row = await cur.fetchone()
    if row["c"] == 0:
        if is_weak_password(config.ADMIN_PANEL_PASSWORD):
            raise RuntimeError(
                "ADMIN_PANEL_PASSWORD juda oddiy (kamida 8 belgi bo'lishi va 'admin' kabi bo'lmasligi kerak). "
                "Kuchli parol o'rnatib, qayta ishga tushiring."
            )
        await _db.execute(
            "INSERT INTO admins (login, password, is_owner, created_at, pw_weak) VALUES (?, ?, 1, ?, 0)",
            (config.ADMIN_PANEL_LOGIN, await hash_password(config.ADMIN_PANEL_PASSWORD), int(time.time())),
        )
    await _db.commit()


def db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database hali init() qilinmagan")
    return _db


# ---------- Settings ----------
async def get_setting(key: str, default: str | None = None) -> str | None:
    cur = await db().execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else default


async def get_all_settings(include_secret: bool = False) -> dict:
    cur = await db().execute("SELECT key, value FROM settings")
    rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows if include_secret or r["key"] not in _SECRET_SETTINGS}


async def set_setting(key: str, value: str):
    await db().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    await db().commit()


async def set_settings_many(pairs: dict):
    for k, v in pairs.items():
        await db().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, str(v)),
        )
    await db().commit()


async def regenerate_adsgram_secret() -> str:
    secret = secrets.token_urlsafe(24)
    await set_setting("adsgram_secret", secret)
    return secret


# ---------- Users ----------
def safe_photo_url(url) -> str | None:
    """Faqat oddiy https rasm manzillarini qabul qiladi.
    Telegram file API (bot tokeni bor) URL'lari HECH QACHON saqlanmaydi/qaytarilmaydi."""
    if not url or not isinstance(url, str):
        return None
    if not url.startswith("https://") or len(url) > 500:
        return None
    if "/file/bot" in url or "api.telegram.org" in url:
        return None
    return url


async def upsert_user(user_id: int, username: str | None, first_name: str | None,
                      photo_url: str | None = None, invited_by: int | None = None) -> aiosqlite.Row:
    photo_url = safe_photo_url(photo_url)
    cur = await db().execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    existing = await cur.fetchone()
    if existing:
        await db().execute(
            "UPDATE users SET username = ?, first_name = ?, "
            "photo_url = COALESCE(?, photo_url) WHERE user_id = ?",
            (username, first_name, photo_url, user_id),
        )
        await db().commit()
        return await get_user(user_id)

    # Taklif qilgan odam bazada bo'lishi shart (mavjud bo'lmagan ID bilan soxtalashtirib bo'lmaydi)
    if invited_by is not None and (invited_by == user_id or not await get_user(invited_by)):
        invited_by = None

    cur = await db().execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, invited_by, photo_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, first_name, int(time.time()), invited_by, photo_url),
    )
    if cur.rowcount == 1 and invited_by:
        await db().execute(
            "UPDATE users SET invited_count = invited_count + 1 WHERE user_id = ?", (invited_by,)
        )
    await db().commit()
    return await get_user(user_id)


async def get_user(user_id: int) -> aiosqlite.Row | None:
    cur = await db().execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return await cur.fetchone()


async def list_users(offset: int = 0, limit: int = 50, search: str | None = None):
    if search:
        like = "%" + search.replace("%", "").replace("_", "") + "%"
        cur = await db().execute(
            "SELECT * FROM users WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? "
            "OR first_name LIKE ? ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (like, like, like, limit, offset),
        )
    else:
        cur = await db().execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?", (limit, offset)
        )
    return await cur.fetchall()


async def count_users() -> int:
    cur = await db().execute("SELECT COUNT(*) AS c FROM users")
    row = await cur.fetchone()
    return row["c"]


async def set_blocked(user_id: int, blocked: bool):
    await db().execute("UPDATE users SET blocked = ? WHERE user_id = ?", (1 if blocked else 0, user_id))
    await db().commit()


async def adjust_balance(user_id: int, delta: float) -> float:
    """Balansni oshiradi (yoki kamaytiradi). Yangi balansni qaytaradi.
    Balansni KAMAYTIRISH uchun (sarflash) try_deduct() dan foydalaning."""
    await db().execute(
        "UPDATE users SET balance = ROUND(balance + ?, 4) WHERE user_id = ?", (delta, user_id)
    )
    await db().commit()
    user = await get_user(user_id)
    return user["balance"] if user else 0.0


async def try_deduct(user_id: int, amount: float) -> bool:
    """Balansdan `amount` ni ATOMIK yechadi. Yetarli mablag' bo'lmasa False qaytaradi.
    Tekshiruv va yechish bitta SQL so'rovida — bir vaqtda kelgan so'rovlar balansdan ko'p sarflay olmaydi."""
    amount = round(amount, 4)
    if amount <= 0:
        return False
    cur = await db().execute(
        "UPDATE users SET balance = ROUND(balance - ?, 4) WHERE user_id = ? AND balance >= ?",
        (amount, user_id, amount),
    )
    await db().commit()
    return cur.rowcount == 1


async def add_earned(user_id: int, amount: float):
    await db().execute(
        "UPDATE users SET earned = ROUND(earned + ?, 4) WHERE user_id = ?", (amount, user_id)
    )
    await db().commit()


async def top_referrers(limit: int = 20):
    cur = await db().execute(
        "SELECT * FROM users WHERE invited_count > 0 ORDER BY earned DESC LIMIT ?", (limit,)
    )
    return await cur.fetchall()


# ---------- Channels (majburiy obuna) ----------
async def add_channel(chat_id: str, title: str, invite_link: str):
    await db().execute(
        "INSERT INTO channels (chat_id, title, invite_link) VALUES (?, ?, ?)",
        (chat_id, title, invite_link),
    )
    await db().commit()


async def remove_channel(channel_id: int):
    await db().execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    await db().commit()


async def list_channels():
    cur = await db().execute("SELECT * FROM channels")
    return await cur.fetchall()


async def confirm_sub(user_id: int, chat_id: str):
    await db().execute(
        "INSERT OR IGNORE INTO user_confirms (user_id, chat_id) VALUES (?, ?)",
        (user_id, chat_id),
    )
    await db().commit()


# ---------- Orders ----------
async def create_order(user_id: int, type_: str, summary: str, amount_usd: float,
                       recipient: str | None = None) -> aiosqlite.Row:
    async with _write_lock:
        cur = await db().execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 0) AS m FROM orders"
        )
        row = await cur.fetchone()
        order_id = f"ORD-{row['m'] + 1:05d}"
        await db().execute(
            "INSERT INTO orders (id, user_id, type, summary, recipient, amount_usd, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (order_id, user_id, type_, summary, recipient, amount_usd, int(time.time())),
        )
        await db().commit()
    return await get_order(order_id)


async def create_order_paid(user_id: int, type_: str, summary: str, amount_usd: float,
                            recipient: str | None = None) -> aiosqlite.Row | None:
    """Balansdan yechish va buyurtma yaratishni BITTA tranzaksiyada bajaradi.
    Mablag' yetmasa None qaytaradi. Orada xato bo'lsa — hammasi bekor qilinadi (pul yo'qolmaydi)."""
    amount_usd = round(amount_usd, 4)
    async with _write_lock:
        try:
            cur = await db().execute(
                "UPDATE users SET balance = ROUND(balance - ?, 4) WHERE user_id = ? AND balance >= ?",
                (amount_usd, user_id, amount_usd),
            )
            if cur.rowcount != 1:
                await db().rollback()
                return None
            cur = await db().execute(
                "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 0) AS m FROM orders"
            )
            row = await cur.fetchone()
            order_id = f"ORD-{row['m'] + 1:05d}"
            await db().execute(
                "INSERT INTO orders (id, user_id, type, summary, recipient, amount_usd, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (order_id, user_id, type_, summary, recipient, amount_usd, int(time.time())),
            )
            await db().commit()
        except Exception:
            await db().rollback()
            raise
    return await get_order(order_id)


async def get_order(order_id: str) -> aiosqlite.Row | None:
    cur = await db().execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    return await cur.fetchone()


async def list_orders_for_user(user_id: int):
    cur = await db().execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    )
    return await cur.fetchall()


async def list_orders(status: str | None = None, offset: int = 0, limit: int = 50):
    """Admin ro'yxati uchun — buyurtmani foydalanuvchi ma'lumotlari bilan birga qaytaradi
    (admin buyurtmani ko'rib, KIMGA tegishli ekanini alohida so'rov qilmasdan ko'rishi uchun)."""
    base = (
        "SELECT o.*, u.username AS user_username, u.first_name AS user_first_name, "
        "u.balance AS user_balance, u.blocked AS user_blocked "
        "FROM orders o LEFT JOIN users u ON u.user_id = o.user_id "
    )
    if status:
        cur = await db().execute(
            base + "WHERE o.status = ? ORDER BY o.created_at ASC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cur = await db().execute(
            base + "ORDER BY o.created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        )
    return await cur.fetchall()


async def claim_order(order_id: str, status: str, by_id: int | None = None,
                      by_login: str | None = None) -> bool:
    """Buyurtmani 'pending' holatidan `status` ga o'tkazadi. Faqat BIRINCHI chaqiruv True qaytaradi."""
    cur = await db().execute(
        "UPDATE orders SET status = ?, decided_at = ?, decided_by = ?, decided_by_login = ? "
        "WHERE id = ? AND status = 'pending'",
        (status, int(time.time()), by_id, by_login, order_id),
    )
    await db().commit()
    return cur.rowcount == 1


async def cancel_order_refund(order_id: str, by_id: int | None = None,
                              by_login: str | None = None) -> aiosqlite.Row | None:
    """Buyurtmani bekor qiladi va pulni qaytaradi — bitta tranzaksiyada.
    Faqat 'pending' buyurtma uchun ishlaydi; aks holda None."""
    async with _write_lock:
        try:
            cur = await db().execute(
                "UPDATE orders SET status = 'cancelled', decided_at = ?, decided_by = ?, decided_by_login = ? "
                "WHERE id = ? AND status = 'pending'",
                (int(time.time()), by_id, by_login, order_id),
            )
            if cur.rowcount != 1:
                await db().rollback()
                return None
            order = await get_order(order_id)
            await db().execute(
                "UPDATE users SET balance = ROUND(balance + ?, 4) WHERE user_id = ?",
                (order["amount_usd"], order["user_id"]),
            )
            await db().commit()
        except Exception:
            await db().rollback()
            raise
    return order


# ---------- Admins ----------
async def get_admin(login: str) -> aiosqlite.Row | None:
    cur = await db().execute("SELECT * FROM admins WHERE login = ?", (login,))
    return await cur.fetchone()


async def list_admins():
    cur = await db().execute("SELECT login, is_owner, created_at FROM admins")
    return await cur.fetchall()


async def verify_admin_login(login: str, password: str) -> aiosqlite.Row | None:
    """Login/parolni tekshiradi. Muvaffaqiyatli bo'lsa admin qatorini qaytaradi."""
    admin = await get_admin(login)
    stored = admin["password"] if admin else _DUMMY_HASH
    ok = await asyncio.to_thread(_verify_password_sync, stored, password)
    if not (admin and ok):
        return None
    weak = 1 if is_weak_password(password) else 0
    if admin["pw_weak"] != weak:
        await db().execute("UPDATE admins SET pw_weak = ? WHERE login = ?", (weak, login))
        await db().commit()
    return await get_admin(login)


async def add_admin(login: str, password: str, is_owner: bool = False):
    hashed = await hash_password(password)
    await db().execute(
        "INSERT INTO admins (login, password, is_owner, created_at, pw_weak) VALUES (?, ?, ?, ?, ?)",
        (login, hashed, 1 if is_owner else 0, int(time.time()), 1 if is_weak_password(password) else 0),
    )
    await db().commit()


async def set_admin_password(login: str, new_password: str):
    hashed = await hash_password(new_password)
    await db().execute(
        "UPDATE admins SET password = ?, pw_weak = ? WHERE login = ?",
        (hashed, 1 if is_weak_password(new_password) else 0, login),
    )
    await db().commit()


async def remove_admin(login: str):
    await db().execute("DELETE FROM admins WHERE login = ?", (login,))
    await db().commit()


# ---------- Payment requests (qo'lda to'lov) ----------
async def create_payment_request(user_id: int, amount_usd: float, receipt_file_id: str | None) -> aiosqlite.Row:
    async with _write_lock:
        cur = await db().execute(
            "INSERT INTO payment_requests (user_id, amount_usd, receipt_file_id, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, amount_usd, receipt_file_id, int(time.time())),
        )
        await db().commit()
        pr_id = cur.lastrowid
    return await get_payment_request(pr_id)


async def set_payment_receipt(pr_id: int, receipt_file_id: str):
    await db().execute(
        "UPDATE payment_requests SET receipt_file_id = ? WHERE id = ?", (receipt_file_id, pr_id)
    )
    await db().commit()


async def count_pending_payments(user_id: int) -> int:
    cur = await db().execute(
        "SELECT COUNT(*) AS c FROM payment_requests WHERE user_id = ? AND status = 'pending'", (user_id,)
    )
    row = await cur.fetchone()
    return row["c"]


async def get_payment_request(pr_id: int) -> aiosqlite.Row | None:
    cur = await db().execute("SELECT * FROM payment_requests WHERE id = ?", (pr_id,))
    return await cur.fetchone()


async def list_payment_requests(status: str | None = None, offset: int = 0, limit: int = 50):
    """Admin ro'yxati uchun — to'lov so'rovini foydalanuvchi ma'lumotlari bilan birga qaytaradi."""
    base = (
        "SELECT p.*, u.username AS user_username, u.first_name AS user_first_name, "
        "u.balance AS user_balance, u.blocked AS user_blocked "
        "FROM payment_requests p LEFT JOIN users u ON u.user_id = p.user_id "
    )
    if status:
        cur = await db().execute(
            base + "WHERE p.status = ? ORDER BY p.created_at ASC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    else:
        cur = await db().execute(
            base + "ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    return await cur.fetchall()


async def claim_payment_request(pr_id: int, status: str, by_id: int | None = None,
                                by_login: str | None = None, amount_usd: float | None = None) -> bool:
    """To'lov so'rovini 'pending' holatidan `status` ga o'tkazadi (faqat birinchi chaqiruv True).
    Tasdiqlashda admin kiritgan yakuniy summa ham yozib qo'yiladi."""
    cur = await db().execute(
        "UPDATE payment_requests SET status = ?, decided_at = ?, decided_by = ?, decided_by_login = ?, "
        "amount_usd = COALESCE(?, amount_usd) WHERE id = ? AND status = 'pending'",
        (status, int(time.time()), by_id, by_login, amount_usd, pr_id),
    )
    await db().commit()
    return cur.rowcount == 1


async def approve_payment_credit(pr_id: int, amount_usd: float, by_id: int | None = None,
                                 by_login: str | None = None) -> aiosqlite.Row | None:
    """To'lovni tasdiqlaydi va balansga pul qo'shadi — bitta tranzaksiyada.
    Faqat 'pending' so'rov uchun ishlaydi; aks holda None."""
    amount_usd = round(amount_usd, 2)
    async with _write_lock:
        try:
            cur = await db().execute(
                "UPDATE payment_requests SET status = 'approved', decided_at = ?, decided_by = ?, "
                "decided_by_login = ?, amount_usd = ? WHERE id = ? AND status = 'pending'",
                (int(time.time()), by_id, by_login, amount_usd, pr_id),
            )
            if cur.rowcount != 1:
                await db().rollback()
                return None
            pr = await get_payment_request(pr_id)
            await db().execute(
                "UPDATE users SET balance = ROUND(balance + ?, 4) WHERE user_id = ?",
                (amount_usd, pr["user_id"]),
            )
            await db().commit()
        except Exception:
            await db().rollback()
            raise
    return pr


# ---------- Bonus (reklama uchun) ----------
def bonus_day_key(ts: float | None = None) -> int:
    ts = time.time() if ts is None else ts
    return int((ts + config.BONUS_TZ_OFFSET_HOURS * 3600) // 86400)


async def grant_bonus(user_id: int, amount: float, daily_limit: int, cooldown_sec: int,
                      daily_budget: float, source: str = "adsgram") -> dict:
    """Bonusni tekshiruvlar bilan bir tranzaksiyada beradi.
    Qaytaradi: {"ok": bool, "reason": str | None, "balance": float | None}"""
    amount = round(amount, 4)
    if amount <= 0:
        return {"ok": False, "reason": "invalid_amount", "balance": None}
    now = int(time.time())
    day = bonus_day_key(now)

    async with _bonus_lock:
        user = await get_user(user_id)
        if not user:
            return {"ok": False, "reason": "no_user", "balance": None}
        if user["blocked"]:
            return {"ok": False, "reason": "blocked", "balance": None}

        cur = await db().execute(
            "SELECT COUNT(*) AS c FROM bonus_rewards WHERE user_id = ? AND day = ?", (user_id, day)
        )
        used_today = (await cur.fetchone())["c"]
        if used_today >= daily_limit:
            return {"ok": False, "reason": "daily_limit", "balance": None}

        cur = await db().execute("SELECT MAX(created_at) AS last FROM bonus_rewards WHERE user_id = ?", (user_id,))
        last = (await cur.fetchone())["last"]
        if last is not None and now - last < cooldown_sec:
            return {"ok": False, "reason": "cooldown", "balance": None}

        if daily_budget > 0:
            cur = await db().execute(
                "SELECT COALESCE(SUM(amount_usd), 0) AS s FROM bonus_rewards WHERE day = ?", (day,)
            )
            spent = (await cur.fetchone())["s"]
            if spent + amount > daily_budget + 1e-9:
                return {"ok": False, "reason": "budget", "balance": None}

        try:
            await db().execute(
                "INSERT INTO bonus_rewards (user_id, amount_usd, source, day, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, source, day, now),
            )
            await db().execute(
                "UPDATE users SET balance = ROUND(balance + ?, 4) WHERE user_id = ?", (amount, user_id)
            )
            await db().commit()
        except Exception:
            await db().rollback()
            raise

    user = await get_user(user_id)
    return {"ok": True, "reason": None, "balance": user["balance"] if user else None}


async def bonus_user_state(user_id: int) -> dict:
    day = bonus_day_key()
    cur = await db().execute(
        "SELECT COUNT(*) AS c FROM bonus_rewards WHERE user_id = ? AND day = ?", (user_id, day)
    )
    used_today = (await cur.fetchone())["c"]
    cur = await db().execute(
        "SELECT MAX(created_at) AS last, COALESCE(SUM(amount_usd), 0) AS total "
        "FROM bonus_rewards WHERE user_id = ?", (user_id,)
    )
    row = await cur.fetchone()
    return {"used_today": used_today, "last_at": row["last"] or 0, "total_earned": round(row["total"], 4)}


async def bonus_stats() -> dict:
    day = bonus_day_key()
    cur = await db().execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(amount_usd), 0) AS s FROM bonus_rewards WHERE day = ?", (day,)
    )
    today = await cur.fetchone()
    cur = await db().execute("SELECT COUNT(*) AS c, COALESCE(SUM(amount_usd), 0) AS s FROM bonus_rewards")
    total = await cur.fetchone()
    return {
        "today_count": today["c"], "today_total": round(today["s"], 4),
        "total_count": total["c"], "total_paid": round(total["s"], 4),
    }


async def list_recent_bonus(limit: int = 20):
    cur = await db().execute(
        "SELECT b.id, b.user_id, b.amount_usd, b.created_at, u.username, u.first_name "
        "FROM bonus_rewards b LEFT JOIN users u ON u.user_id = b.user_id "
        "ORDER BY b.id DESC LIMIT ?", (limit,)
    )
    return await cur.fetchall()
