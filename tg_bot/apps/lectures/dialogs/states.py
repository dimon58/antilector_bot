"""
Группы состояний диалогов
"""

from aiogram.fsm.state import State, StatesGroup


# pylint: disable=too-few-public-methods
class LectureProcessingStates(StatesGroup):
    """
    Состояния диалога работы с лекциями
    """

    detailed = State()

    link_or_file = State()

    choose_audio_processing_profile = State()
    audio_processing_profiles_description = State()

    choose_unsilence_profile = State()
    unsilence_profiles_description = State()

    confirm = State()
