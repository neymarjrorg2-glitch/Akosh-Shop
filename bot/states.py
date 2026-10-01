from aiogram.fsm.state import State, StatesGroup


class AdminEdit(StatesGroup):
    waiting_broadcast_text = State()


class UserFlow(StatesGroup):
    waiting_receipt = State()
