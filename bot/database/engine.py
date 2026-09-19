import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import DATABASE_URL
from bot.database.models import Base

logger = logging.getLogger(__name__)

# Ko'p foydalanuvchi bir vaqtda ishlatganda ulanish yetishmasligining oldini olish uchun
# pool kattalashtirilgan va "chirigan" ulanishlar avtomatik yangilanadi.
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # har bir so'rovdan oldin ulanish tirikligini tekshiradi
    pool_recycle=1800,    # 30 daqiqada bir ulanishlarni yangilaydi (Railway uzoq turgan ulanishni uzib qo'yishi mumkin)
    pool_size=20,
    max_overflow=20,
)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Yangi ustun qo'shilganda eski (mavjud) jadvallar avtomatik yangilanmaydi
# (SQLAlchemy create_all faqat YO'Q jadvallarni yaratadi). Shuning uchun
# har bir yangi ustun uchun "ADD COLUMN IF NOT EXISTS" ishlatamiz - bu xavfsiz,
# chunki ustun allaqachon bo'lsa hech narsa qilmaydi, yo'q bo'lsa qo'shadi.
MIGRATIONS = [
    "ALTER TABLE bot_products ADD COLUMN IF NOT EXISTS media_file_id VARCHAR(256)",
    "ALTER TABLE bot_products ADD COLUMN IF NOT EXISTS media_type VARCHAR(16)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS custom_nickname VARCHAR(128)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS custom_username VARCHAR(128)",
    "ALTER TABLE orders ALTER COLUMN product_id DROP NOT NULL",
    "ALTER TABLE settings ALTER COLUMN value TYPE TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_qualified BOOLEAN DEFAULT FALSE",
]


async def init_db() -> None:
    """Barcha jadvallarni (agar mavjud bo'lmasa) yaratadi, so'ng yetishmayotgan ustunlarni qo'shadi."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Har bir migratsiya statement'i ALOHIDA tranzaksiyada ishga tushiriladi -
    # biri xato bersa (masalan ustun allaqachon boshqacha holatda bo'lsa),
    # bu qolgan statement'larning bajarilishiga to'sqinlik qilmaydi.
    for statement in MIGRATIONS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        except Exception as e:
            logger.warning("Migratsiya qatori bajarilmadi (ehtimol allaqachon qo'llanilgan): %s | %s", statement, e)
