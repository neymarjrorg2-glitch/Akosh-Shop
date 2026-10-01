"""
StarNest bot — konfiguratsiya moduli.
Barcha environment variable'lar shu yerda o'qiladi. Boshqa hech qaysi fayl
os.environ ga to'g'ridan-to'g'ri murojaat qilmaydi — hammasi shu modul orqali.
"""
import hashlib
import os


def _get(name: str, default: str = "", required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Majburiy environment variable topilmadi: {name}")
    return val


def _get_int_list(name: str) -> list[int]:
    raw = os.environ.get(name, "")
    result = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError:
                pass
    return result


# --- Telegram ---
BOT_TOKEN: str = _get("BOT_TOKEN", required=True)
ADMIN_IDS: list[int] = _get_int_list("ADMIN_IDS")

# --- Web App ---
WEBAPP_URL: str = _get("WEBAPP_URL", required=True).rstrip("/")
WEBAPP_ORIGIN: str = _get("WEBAPP_ORIGIN", WEBAPP_URL).rstrip("/")

# --- Database ---
DB_PATH: str = _get("DB_PATH", "/data/starnest.db")

# --- Birinchi (bosh) admin — faqat bazada admin bo'lmasa ishlatiladi ---
# Parol kamida 8 belgi bo'lishi va "admin" kabi oddiy parol bo'lmasligi shart.
ADMIN_PANEL_LOGIN: str = _get("ADMIN_PANEL_LOGIN", "admin")
ADMIN_PANEL_PASSWORD: str = _get("ADMIN_PANEL_PASSWORD", "admin")
ADMIN_PANEL_SECRET: str = _get("ADMIN_PANEL_SECRET", required=True)

# Token imzolash kalitlari ADMIN_PANEL_SECRET dan alohida-alohida hosil qilinadi
# (oldin foydalanuvchi tokeni BOT_TOKEN bilan imzolanardi).
USER_TOKEN_SECRET: str = hashlib.sha256(b"starnest-user:" + ADMIN_PANEL_SECRET.encode()).hexdigest()
ADMIN_TOKEN_SECRET: str = hashlib.sha256(b"starnest-admin:" + ADMIN_PANEL_SECRET.encode()).hexdigest()

# --- HTTP server ---
PORT: int = int(_get("PORT", "8080"))

# --- Token muddati (soat) ---
USER_TOKEN_TTL_HOURS = 24 * 7
ADMIN_TOKEN_TTL_HOURS = 24 * 3

# --- Cheklovlar ---
MAX_RECEIPT_BYTES: int = int(_get("MAX_RECEIPT_BYTES", str(5 * 1024 * 1024)))  # chek rasmi, 5 MB
MAX_TOPUP_USD: float = float(_get("MAX_TOPUP_USD", "10000"))                   # bitta to'ldirish uchun maks. summa
MAX_PENDING_PAYMENTS: int = int(_get("MAX_PENDING_PAYMENTS", "5"))             # bitta foydalanuvchining kutilayotgan so'rovlari

# --- Bonus (reklama) ---
# "Kun" chegarasi shu vaqt zonasi bo'yicha hisoblanadi (Toshkent = UTC+5).
BONUS_TZ_OFFSET_HOURS: int = int(_get("BONUS_TZ_OFFSET_HOURS", "5"))
