# O'zgarishlar (AdsGram + xatolarni tuzatish)

## Yangi
- **AdsGram reklamasi** (`bot/utils/adsgram.py`): katalog, hisob va buyurtmalar bo'limlarida, har bir foydalanuvchiga
  `ADSGRAM_COOLDOWN_SECONDS` (standart 5 daqiqa) ichida bir martadan ko'p emas. Adminlarga ko'rsatilmaydi.
  `ADSGRAM_TOKEN` bo'sh bo'lsa, reklama butunlay o'chiq turadi.
- **Bloklangan foydalanuvchilar** endi butun botdan chetlatiladi (avval faqat `/start` da tekshirilardi).
- **Bot qayta ishga tushgandan keyin buyurtmani davom ettirish**: pulini to'lab, API key/ID kiritishga ulgurmagan mijoz
  deploy'dan keyin token yoki ID yuborsa, oxirgi to'langan buyurtmaga avtomatik ulanadi (FSM holati xotirada saqlangani uchun
  har bir deploy'da o'chib ketardi).

## Pul bilan bog'liq xatolar (eng muhimi)
- Buyurtmani tasdiqlash tugmasi ketma-ket ikki marta bosilsa, ikki buyurtma yaratilishi va balans minusga tushishi mumkin edi.
  Endi pul bitta SQL so'rovda tekshirilib, atomik yechiladi (`crud.charge_balance`).
- Buyurtmani "Bekor qilish" tugmasi qayta bosilsa (yoki xabar bir necha adminga borgani uchun ikkinchi admin bossa),
  pul **ikki marta** qaytarilardi. Endi holat atomik o'zgaradi va pul faqat bir marta qaytadi (`crud.transition_order_status`).
- To'lov so'rovini ikki marta tasdiqlash balansni ikki marta to'ldirardi; rad etilgan so'rovni qayta "tasdiqlash" ham mumkin edi.
  Endi so'rov faqat bir marta ko'rib chiqiladi (`crud.process_topup_request`).
- Balans o'zgartirish SQL darajasida atomik qilindi (bir vaqtda ikki amal bir-birining natijasini bosib ketmaydi).

## Boshqa xatolar
- `admin.py`: mahsulot kartochkasidagi f-string ichida backslash bor edi — Python 3.11 (`.python-version`) da `SyntaxError` beradi.
- `admin.py`: foydalanuvchiga shaxsiy xabar yuborilgandan keyin mavjud bo'lmagan `orders`/`callback` nomlariga murojaat qilinardi
  (har safar `NameError`). Keraksiz kod olib tashlandi.
- Adminning "❌ Bekor qilish" tugmasi ishlamasdi: FSM handlerlari uni oddiy matn deb qabul qilardi
  (masalan, mahsulot nomi "❌ Bekor qilish" bo'lib saqlanardi).
- "Bajardim" tugmasi ketma-ket ikki marta bosilsa, dublikat yozuv paydo bo'lib, foydalanuvchining obuna tekshiruvi
  butunlay ishdan chiqardi (`MultipleResultsFound`). Tuzatildi.
- Ishlatilgan obunani o'chirish FK xatosi bilan yiqilardi. Endi bog'liq tasdiqlash yozuvlari avval o'chiriladi.
- Obunani tekshirishda Telegram API xatolari (`TelegramForbiddenError` va boshqalar) ushlanmasdi; cheklangan (restricted)
  a'zolar noto'g'ri hisoblanardi. Sabablar endi logga yoziladi.
- Adminga buyurtma har safar **ikki marta** kelardi (kod takrorlangan edi).
- Ismida `<` yoki `&` bo'lgan mijozning buyurtma/to'lov xabari HTML xatosi tufayli adminga yetib bormasdi. Ismlar `html.escape` qilindi.
- Bazadan qo'shilgan adminlar buyurtma/to'lov/hosting xabarnomalarini olmasdi (faqat `.env` dagilar olardi).
- FSM holatida (API key, summa, chek kutilayotganda) asosiy menyu tugmalari ishlamay qolardi.
- Matn bo'lmagan xabar (rasm, sticker) yuborilganda bir nechta admin handlerlari `AttributeError` bilan yiqilardi.
- Bir vaqtda ikki `/start` kelganda yangi foydalanuvchini yaratishda `IntegrityError` chiqishi mumkin edi.
- `hosting_reminder_loop` task'iga havola saqlanmagan edi (Python uni o'chirib yuborishi mumkin).
- `cb_check_subs`: tugmalar o'zgarmaganda "message is not modified" xatosi.
