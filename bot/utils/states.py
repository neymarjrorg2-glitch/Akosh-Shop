from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    waiting_phone = State()  # buyurtma berishdan oldin telefon so'ralganda


class AdminAddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    category = State()


class AdminAddSubscription(StatesGroup):
    platform = State()
    title = State()
    url = State()
    chat_id = State()


class AdminBalanceAdjust(StatesGroup):
    user_id = State()
    amount = State()


class AdminReferralPercent(StatesGroup):
    percent = State()


class AdminBroadcast(StatesGroup):
    content = State()
