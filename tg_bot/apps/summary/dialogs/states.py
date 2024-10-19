"""
Группы состояний диалогов
"""

from aiogram.fsm.state import State, StatesGroup


# pylint: disable=too-few-public-methods
class LectureSummarizationStates(StatesGroup):
    """
    Состояния диалога конспектирования лекции
    """

    link_or_file = State()
    confirm = State()
