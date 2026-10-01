# StarNest — deploy qo'llanmasi (yangilangan versiya)

Bu arxiv StarNest bot + Mini App kodining **tuzatilgan va kengaytirilgan** versiyasini
o'z ichiga oladi. **Avtomatik to'lov (checkout.uz) yo'q** — faqat qo'lda (chek asosidagi)
balans to'ldirish bor.

## Nima o'zgardi (eski versiyaga nisbatan)

**Xavfsizlik:**
- Bot tokeni endi HECH QAYERDA (baza, API javoblari, frontend) saqlanmaydi/ko'rsatilmaydi.
  Eski bazada qolgan token URL'lari `database.init()` da avtomatik tozalanadi.
  **Shunga qaramay, botni ilgari ishga tushirgan bo'lsangiz, BotFather'da tokenni
  `/revoke` orqali darhol yangilang** — u eski bazada/loglarda oshkor bo'lgan bo'lishi mumkin.
- Admin parollari endi `scrypt` bilan hashlanadi (eski ochiq matndagi parollar birinchi
  ishga tushirishda avtomatik hashga o'tkaziladi). Zaif parol (`admin`, 8 belgidan kam va h.k.)
  qabul qilinmaydi.
- Balansni yechish (`try_deduct`) va buyurtma/to'lovni tasdiqlash (`claim_*`) endi ATOMIK —
  ikki marta sarflash yoki ikki marta tasdiqlash imkonsiz.
- Admin panel login'iga urinish limiti (5 ta noto'g'ri urinish / 5 daqiqa, IP va login bo'yicha).
- Chek yuklashda fayl hajmi (5 MB) va turi (JPG/PNG/WEBP) tekshiriladi.
- Barcha sozlamalar (narx, referal foizi, bonus) kiritishda tekshiriladi — noto'g'ri qiymat
  botni yoki API'ni buzolmaydi.
- Bloklangan foydalanuvchi endi botning HECH bir tugmasidan foydalana olmaydi (oldin faqat
  Web App API'da ishlagan).

**Ishonchlilik:**
- Broadcast fon vazifasi sifatida ishlaydi (HTTP so'rovni bloklamaydi), noto'g'ri HTML
  bo'lsa oddiy matn sifatida qayta yuboradi, `RetryAfter` ni hurmat qiladi.
- Admin panel sessiyasi tugaganda (401) avtomatik login oynasiga qaytadi.
- `/api/me` polling endi 3 soniyada emas, 15 soniyada va faqat ekran ochiq bo'lganda.
- Buyurtma/to'lov ID'lari bir vaqtda kelgan so'rovlarda ham takrorlanmaydi.
- SQLite `WAL` rejimida ishlaydi (parallel o'qish/yozish uchun).

**Yangi: Bonus (AdsGram reklama).** Mini App'da yangi "🎁 Bonus" tabi qo'shildi —
foydalanuvchi rewarded reklama ko'rib, balansga kichik summa qo'shib oladi. Batafsil
pastda, "5-bo'lim" da.

## Oxirgi tuzatishlar

- **Python 3.12 dan past versiyada ishlamay qolish xatosi** (f-string ichida backslash) tuzatildi;
  Python versiyasi `.python-version` bilan qotirildi.
- **Pul oqimlari to'liq atomik:** balansdan yechish + buyurtma yaratish, buyurtmani bekor qilish +
  pulni qaytarish, to'lovni tasdiqlash + balansga qo'shish — har biri BITTA tranzaksiyada
  (jarayon o'rtada to'xtasa ham pul yo'qolmaydi / ikki marta qo'shilmaydi).
- **Buyurtma "Kimga":** "O'zimga" — foydalanuvchining o'z username'i avtomatik yoziladi,
  "Boshqaga" — kiritilgan username. Username'i bo'lmagan foydalanuvchi "O'zimga" bilan
  buyurtma bera olmaydi (aniq xabar chiqadi).
- Stars miqdori maydoniga endi son erkin yoziladi (oldin har harfda minimumga qaytib ketardi).
- Balans to'ldirishda maksimal summa tekshiriladi (jimgina 0 ga aylanib ketmasin).
- Botdagi "Balansni to'ldirish" tugmasi endi karta raqami, egasi va kursni ko'rsatadi.
- Majburiy obuna kanallarini boshqarish buyruqlari qo'shildi (oldin kanal qo'shishning iloji yo'q edi).
- Admin buyurtma xabarlari fonda yuboriladi (Telegram sekin bo'lsa ilova qotib qolmaydi).
- Login limiti: IP `X-Forwarded-For` ning oxirgi (proksi qo'shgan) qiymatidan olinadi.
- Mini App'da qolgan so'nggi emojilar SVG ikonkaga almashtirildi; xabar (Toast) taymeri tuzatildi.

## 1. Bot service (Railway)

- **Root Directory:** `bot`
- **Python:** 3.12 (`bot/.python-version` faylida belgilangan; Railway'da kerak bo'lsa `NIXPACKS_PYTHON_VERSION=3.12` ham qo'ying)
- **Start command:** `python bot.py`
- **Volume:** Mount Path `/data` — SHART, bo'lmasa har deploy'da baza o'chib ketadi

### Environment variables:
```
BOT_TOKEN=<BotFather'dan olingan token — avval /revoke qiling, keyin yangisini oling>
ADMIN_IDS=<bosh admin(lar)ning Telegram ID'si, vergul bilan>
WEBAPP_URL=<webapp service'ning to'liq domeni, https:// bilan>
WEBAPP_ORIGIN=<xuddi shu domen — CORS uchun>
DB_PATH=/data/starnest.db
ADMIN_PANEL_LOGIN=<bosh admin login (faqat birinchi ishga tushirishda)>
ADMIN_PANEL_PASSWORD=<KUCHLI parol, kamida 8 belgi, "admin" kabi oddiy bo'lmasin>
ADMIN_PANEL_SECRET=<tasodifiy uzun qator, masalan: openssl rand -hex 32>
```
Ixtiyoriy: `MAX_RECEIPT_BYTES`, `MAX_TOPUP_USD`, `MAX_PENDING_PAYMENTS`, `PORT`.

## 2. Webapp service (Railway)

- **Root Directory:** `webapp`
- **Build command:** `npm install && npm run build`
- **Start command:** `npm run preview`

### Environment variables:
```
VITE_API_URL=<bot service'ning to'liq domeni, https:// bilan>
VITE_BOT_USERNAME=<botingizning @username'i, @ belgisiz — referal havolasi uchun>
```

**MUHIM:** bu qiymatlar build vaqtida kodga "quyiladi". O'zgartirsangiz —
albatta to'liq **Redeploy** qiling, oddiy Restart yetarli emas.

## 3. Ishga tushirish tartibi

1. Avval **bot service**'ni deploy qiling (u o'z domenini oladi).
2. Shu domenni `webapp` service'ning `VITE_API_URL` iga yozing va deploy qiling.
3. Webapp domenini `bot` service'ning `WEBAPP_URL` va `WEBAPP_ORIGIN` iga yozing va bot
   service'ni qayta deploy qiling.
4. @BotFather'da botingiz uchun Menu Button yoki Mini App URL sifatida webapp domenini bering.
5. Botga `/start` yuboring — agar `ADMIN_IDS` ichida bo'lsangiz, admin menyu ko'rinadi.
6. Admin panelni ochish: bot menyusidagi "Admin panelni ochish" tugmasi, yoki
   to'g'ridan-to'g'ri `<webapp-domen>?admin=1`.
7. Birinchi kirishda `ADMIN_PANEL_LOGIN` / `ADMIN_PANEL_PASSWORD` bilan kiring.
   **Darhol Sozlamalar bo'limidan parolni yangilang.**

## 4. Muhim eslatmalar

- Bot va backend **bitta process**da ishlaydi (`bot.py`) — aiogram polling + aiohttp server
  parallel.
- Majburiy obuna (`force_sub_enabled`) standart holatda **o'chirilgan**. Kanallar botda
  admin buyruqlari bilan boshqariladi: `/channels` (ro'yxat), `/addchannel @kanal` (qo'shish —
  bot kanalda ADMIN bo'lishi shart), `/delchannel RAQAM`. Yoqish: Admin panel → Sozlamalar.
- Real-vaqt yangilanish oralig'i: webapp har 15 soniyada, faqat ekran ochiq bo'lganda,
  `/api/me` ni qayta so'raydi.
- Avto to'lov (checkout.uz) butunlay olib tashlangan.
- Railway'da Volume ulanmagan bo'lsa, har deployda baza yo'qoladi — buni albatta tekshiring.

## 5. Bonus (AdsGram) — sozlash tartibi

1. [adsgram.ai](https://adsgram.ai) da hisob oching, botingiz uchun **Block** yarating va
   uning **Block ID** sini oling.
2. Admin panel → **Bonus** bo'limini oching:
   - "Yoqilgan" qutisini belgilang,
   - Block ID'ni kiriting,
   - bitta reklama uchun bonus summasini, kunlik limitni, pauzani va (xohlasangiz) kunlik
     umumiy byudjetni sozlang,
   - "Saqlash" tugmasini bosing.
3. Shu bo'limda ko'rsatilgan **Reward postback URL** ni nusxalab, AdsGram dashboardida shu
   Block uchun reward/postback maydoniga joylashtiring. Bu URL maxfiy kalit bilan
   himoyalangan — faqat AdsGram serveri bonusni berishi mumkin, frontend orqali emas.
4. Kalitni istalgan vaqt "Kalitni yangilash" tugmasi bilan bekor qilib, yangisini
   olishingiz mumkin (masalan, eski URL kimgadir oshkor bo'lgan deb gumon qilsangiz).

**Muhim: bonus summasi AdsGram bir ko'rish uchun to'laydigan summadan kichik bo'lishi
kerak**, aks holda botingiz zarar qiladi. Avval AdsGram dashboardida o'zbek trafigining
haqiqiy daromadini ko'ring, keyin summani belgilang. Kunlik byudjet maydoni umumiy
xarajatni yuqori chegaralab qo'yish uchun.

Reklama qo'yilmagan joylar (qasddan): to'lov cheki yuklash oqimi, buyurtma
tasdiqlandi/bekor qilindi xabarlari, `/start`, admin panel, broadcast — pul bilan
ishlaydigan oqimlarda reklama ishonchni pasaytiradi.

## 6. Tuzilma

```
starnest_full/
├── bot/
│   ├── bot.py, config.py, database.py, webserver.py
│   ├── keyboards.py, states.py, force_sub.py
│   ├── utils.py         — xavfsiz xabar yuborish, broadcast fon vazifasi
│   ├── middlewares.py   — bloklangan foydalanuvchini botda ham to'xtatish
│   ├── services.py      — buyurtma/to'lov qarorlarini atomik bajarish (bot va API baravar ishlatadi)
│   └── handlers/{user.py, admin.py}
└── webapp/
    ├── .env.example
    ├── index.html, package.json, vite.config.js
    └── src/{main.jsx, StarNestApp.jsx, index.css}
```
