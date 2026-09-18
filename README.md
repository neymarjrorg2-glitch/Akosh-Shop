# Telegram Bot Do'koni

Balans to'ldirish, katalogdan bot tanlash, buyurtma berish, majburiy obuna
(Telegram/Instagram/YouTube) va referral tizimi bilan to'liq ishlaydigan
Telegram bot.

## Texnologiyalar
- Python 3.11+ / aiogram 3
- PostgreSQL (SQLAlchemy 2.0 + asyncpg)

## Loyiha tuzilmasi

```
bot/
  main.py              — botni ishga tushiradi
  config.py            — .env dan sozlamalarni o'qiydi
  middlewares.py        — har bir so'rovga DB session ulaydi
  database/
    models.py           — jadvallar (User, BotProduct, Order, Transaction, ...)
    engine.py            — DB ulanishi
    crud.py               — DB bilan ishlash funksiyalari
  handlers/
    user.py               — foydalanuvchi oqimi (start, katalog, buyurtma, referral)
    admin.py               — admin panel (statistika, buyurtmalar, mahsulotlar, obunalar)
  keyboards/
    user_kb.py, admin_kb.py — tugmalar
  utils/
    states.py               — FSM holatlari
    subscription_check.py    — majburiy obunani tekshirish logikasi
```

## 1. Lokal ishga tushirish (sinov uchun)

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env faylini oching va BOT_TOKEN, ADMIN_IDS, DATABASE_URL ni to'ldiring

python -m bot.main
```

## 2. Railway'ga joylashtirish

1. **GitHub'ga yuklang**: bu loyihani GitHub repositoriyaga push qiling.
2. **Railway'da yangi loyiha**: railway.app → "New Project" → "Deploy from GitHub repo" → repozitoriyangizni tanlang.
3. **PostgreSQL qo'shing**: loyiha ichida "New" → "Database" → "Add PostgreSQL".
   Railway avtomatik `DATABASE_URL` o'zgaruvchisini yaratadi va botga ulaydi.
4. **Environment Variables** (bot xizmati sozlamalarida):
   - `BOT_TOKEN` — BotFather'dan olingan token
   - `ADMIN_IDS` — sizning Telegram ID raqamingiz (@userinfobot orqali bilib oling), bir nechta bo'lsa vergul bilan: `123456,987654`
   - `DEFAULT_REFERRAL_PERCENT` — ixtiyoriy, standart 5
5. Railway `Procfile`ni avtomatik aniqlaydi (`worker: python -m bot.main`) va botni ishga tushiradi.
6. Loglarni "Deployments" bo'limidan kuzatishingiz mumkin — "Bot ishga tushdi." yozuvi chiqsa, hammasi tayyor.

## Muhim eslatmalar

- **Telegram kanalga qo'shilishni tekshirish** ("telegram_join" turi) ishlashi uchun
  **bot shu kanalda ADMIN** bo'lishi shart, aks holda Telegram API a'zolikni tekshirishga ruxsat bermaydi.
- **Instagram/YouTube va "faqat zayavka" turidagi Telegram obunalar** — bular tashqi
  tekshirilmaydi, foydalanuvchi "Bajardim" tugmasini bosgani hisobga olinadi (bu Telegram
  Bot API imkoniyatlaridan kelib chiqqan holat).
- **To'lov tizimi**: hozirda Click/Payme API ulanmagan — foydalanuvchi miqdorni tanlaydi,
  admin xabar oladi va balansni "💰 Balans boshqarish" orqali qo'lda tasdiqlaydi. Agar avtomatik
  to'lov (Click/Payme API) kerak bo'lsa, buni alohida qo'shib berish mumkin.
- **Referral bonusi** faqat foydalanuvchi birinchi marta balans to'ldirganda beriladi,
  foiz miqdorini admin istalgan vaqt o'zgartira oladi.
- Bot birinchi marta ishga tushganda barcha jadvallarni PostgreSQL'da **avtomatik yaratadi**
  (`init_db()` orqali) — qo'lda migratsiya kerak emas.

## Keyingi qadamlar (ixtiyoriy kengaytirishlar)
- Click/Payme to'lov API integratsiyasi (avtomatik balans to'ldirish)
- Mahsulotlarga rasm/video qo'shish (`image_url` maydoni allaqachon bazada bor)
- Ko'p darajali adminlar (menejer, texnik xodim huquqlari)
- Har bir foydalanuvchining referral zanjiri chuqurroq tahlili
