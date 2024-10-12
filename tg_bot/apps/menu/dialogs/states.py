"""
Группы состояний диалогов
"""

from aiogram.fsm.state import State, StatesGroup


class MenuStates(StatesGroup):
    """
    Состояния диалога меню
    """

    main_menu = State()
