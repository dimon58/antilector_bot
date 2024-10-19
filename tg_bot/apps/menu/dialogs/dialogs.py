"""
Диалоги
"""

import logging
import os

from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.kbd import Start
from aiogram_dialog.widgets.text import Const

from djgram.configs import DIALOG_DIAGRAMS_DIR, ENABLE_DIALOG_DIAGRAMS_GENERATION
from djgram.utils.diagrams import render_transitions_safe
from tg_bot.apps.lectures.dialogs.states import LectureProcessingStates
from tg_bot.apps.summary.dialogs.states import LectureSummarizationStates

from .states import MenuStates

logger = logging.getLogger(__name__)

menu_dialog = Dialog(
    Window(
        Const("Главное меню"),
        Start(Const("Сократить лекцию"), id="shorten_lecture", state=LectureProcessingStates.link_or_file),
        Start(Const("Конспектировать лекцию"), id="summarize_lecture", state=LectureSummarizationStates.link_or_file),
        state=MenuStates.main_menu,
    ),
)

if ENABLE_DIALOG_DIAGRAMS_GENERATION:
    render_transitions_safe(
        menu_dialog,
        title="Menu dialog",
        filename=os.path.join(DIALOG_DIAGRAMS_DIR, "menu_dialog"),  # noqa: PTH118
    )
    logger.info("Generated diagram for menu dialog")
