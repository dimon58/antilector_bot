"""
Обработчики
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from .dialogs import LectureProcessingStates, lecture_processing_dialog

router = Router()
router.include_router(lecture_processing_dialog)


@router.message(Command(commands=["lec", "lecture"]))
async def start_lecture_dialog(message: Message, dialog_manager: DialogManager):
    """
    Запускает диалог обработки лекций
    """

    await dialog_manager.start(LectureProcessingStates.link_or_file, mode=StartMode.RESET_STACK)
