"""
Обработчики
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager

from .dialogs import LectureSummarizationStates, lecture_summarization_dialog

router = Router()
router.include_router(lecture_summarization_dialog)


@router.message(Command(commands=["sum", "summary"]))
async def start_lecture_summarization_dialog(message: Message, dialog_manager: DialogManager):
    """
    Начать диалог конспектирования лекций
    """

    await dialog_manager.start(LectureSummarizationStates.link_or_file)
