import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

_raw_db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///local.db")

# Railway PostgreSQL "postgresql://" ko'rinishida beradi,
# lekin asyncpg drayveri uchun "postgresql+asyncpg://" kerak.
if _raw_db_url.startswith("postgresql://"):
    DATABASE_URL = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_db_url.startswith("postgres://"):
    DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_db_url

DEFAULT_REFERRAL_PERCENT = float(os.getenv("DEFAULT_REFERRAL_PERCENT", "5"))

# Buyurtma bajarilishi uchun standart muddat (soatda)
ORDER_DEADLINE_HOURS = 24
