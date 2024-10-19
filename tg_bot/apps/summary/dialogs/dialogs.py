"""
Диалоги
"""

import logging
import os

from aiogram.enums import ParseMode
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, SwitchTo, Cancel
from aiogram_dialog.widgets.text import Const

from djgram.configs import DIALOG_DIAGRAMS_DIR, ENABLE_DIALOG_DIAGRAMS_GENERATION
from djgram.utils.diagrams import render_transitions_safe
from tg_bot.apps.lectures.dialogs.callbacks import add_video
from tg_bot.apps.lectures.dialogs.dialogs import BACK_TEXT

from . import callbacks
from .states import LectureSummarizationStates

logger = logging.getLogger(__name__)

lecture_summarization_dialog = Dialog(
    Window(
        Const("Чтобы получить конспект отправьте ссылку или видеофайл"),
        MessageInput(add_video),
        Cancel(Const(BACK_TEXT)),
        state=LectureSummarizationStates.link_or_file,
    ),
    Window(
        Const("Создание конспекта"),
        Button(Const("🚀 Начать обработку"), id="start_processing", on_click=callbacks.start_processing),
        SwitchTo(
            Const(BACK_TEXT),
            id="back_to_url",
            state=LectureSummarizationStates.link_or_file,
        ),
        state=LectureSummarizationStates.confirm,
        parse_mode=ParseMode.MARKDOWN,
    ),
)

if ENABLE_DIALOG_DIAGRAMS_GENERATION:
    render_transitions_safe(
        lecture_summarization_dialog,
        title="Lecture summarization dialog",
        filename=os.path.join(DIALOG_DIAGRAMS_DIR, "lecture_summarization_dialog"),  # noqa: PTH118
    )
    logger.info("Generated diagram for lecture summarization dialog")
