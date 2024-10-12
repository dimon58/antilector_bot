"""
Обработчики
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from .dialogs import MenuStates, menu_dialog

router = Router()
router.include_router(menu_dialog)


@router.message(Command(commands=["menu"]))
async def start_menu_dialog(message: Message, dialog_manager: DialogManager):
    """
    Запуск диалога меню
    """

    await dialog_manager.start(MenuStates.main_menu, mode=StartMode.RESET_STACK)
