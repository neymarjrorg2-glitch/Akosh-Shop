from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    waiting_phone = State()  # majburiy obunadan keyin telefon tasdiqlash


class OrderFlow(StatesGroup):
    waiting_bot_name = State()      # xohlagan bot nomi (nickname)
    waiting_bot_username = State()  # xohlagan bot username'i


class TopupFlow(StatesGroup):
    waiting_custom_amount = State()
    waiting_receipt = State()


class AdminAddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    category = State()
    media = State()


class AdminEditProduct(StatesGroup):
    waiting_value = State()  # tahrirlanayotgan maydon uchun yangi qiymat


class AdminAddSubscription(StatesGroup):
    platform = State()
    title = State()
    url = State()
    chat_id = State()


class AdminReferralPercent(StatesGroup):
    percent = State()


class AdminBroadcast(StatesGroup):
    content = State()


class AdminManageUsers(StatesGroup):
    search_id = State()
    balance_amount = State()


class AdminManageAdmins(StatesGroup):
    add_id = State()


class AdminEditText(StatesGroup):
    waiting_value = State()  # tahrirlanayotgan matn kaliti uchun yangi qiymat
