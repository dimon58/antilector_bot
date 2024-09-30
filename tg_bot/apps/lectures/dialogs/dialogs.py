"""
Диалоги
"""

import logging
import operator
import os

from aiogram.enums import ParseMode
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Back, Cancel, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from djgram.configs import DIALOG_DIAGRAMS_DIR, ENABLE_DIALOG_DIAGRAMS_GENERATION
from djgram.utils.diagrams import render_transitions_safe

from . import callbacks, getters
from .states import LectureProcessingStates

logger = logging.getLogger(__name__)
BACK_TEXT = "Назад"

lecture_processing_dialog = Dialog(
    Window(
        Const("Чтобы удалить тишину из лекции отправьте ссылку или видеофайл"),
        MessageInput(callbacks.add_video),
        SwitchTo(Const("Подробнее"), id="detailed", state=LectureProcessingStates.detailed),
        Cancel(Const(BACK_TEXT)),
        state=LectureProcessingStates.link_or_file,
        preview_add_transitions=[
            SwitchTo(
                Const("choose_audio_quality"),
                "choose_audio_quality",
                state=LectureProcessingStates.choose_audio_processing_profile,
            ),
        ],
    ),
    Window(
        Const(
            "Вы можете отправить ссылку на почти 2000 популярных видеохостингов"
            " (youtube, вконтакте, rutube, публичное видео на лектории фопф и т.д.).\n"
            " А так же можете отправить видеофайл. Поддерживаются все популярные форматы."
            " Получившиеся лекции будут с вырезанными перерывами и сильно ускоренными фрагментами без речи\n"
            "\n"
            "Технические подробности:\n"
            "- Многоканальное аудио объединяется в одноканальное\n"
            "- Частота дискретизации аудио будет составлять 48 кГц"
            "- Корректная работа с видеофайлами, в которых более одного видеопотока не гарантируется"
            " (в большинстве случаев останется только 1 поток)\n"
            "- Частота кадров сохраняется\n"
            "- Максимально разрешение видеофайлов, скачиваемых по ссылке 1080p\n"
            "- Видео кодируется с помощью hevc"
        ),
        Back(Const(BACK_TEXT)),
        state=LectureProcessingStates.detailed,
    ),
    Window(
        Const("Выберите профиль звука"),
        Select(
            Format("{item[1]}"),
            id=getters.AUDIO_PROFILE_KEY,
            item_id_getter=operator.itemgetter(0),
            items=getters.AUDIO_PROFILES_KEY,
            on_click=callbacks.select_audio_processing_profile,
        ),
        SwitchTo(
            Const("Описание профилей"),
            id="detailed",
            state=LectureProcessingStates.audio_processing_profiles_description,
        ),
        SwitchTo(Const(BACK_TEXT), id="back_to_video_input", state=LectureProcessingStates.link_or_file),
        state=LectureProcessingStates.choose_audio_processing_profile,
        getter=getters.get_audio_processing_profiles,
    ),
    Window(
        Format(f"{{{getters.AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY}}}"),
        Back(Const(BACK_TEXT)),
        state=LectureProcessingStates.audio_processing_profiles_description,
        getter=getters.get_audio_processing_profiles_description,
        parse_mode=ParseMode.MARKDOWN,
    ),
)

if ENABLE_DIALOG_DIAGRAMS_GENERATION:
    render_transitions_safe(
        lecture_processing_dialog,
        title="Lecture processing dialog",
        filename=os.path.join(DIALOG_DIAGRAMS_DIR, "lecture_processing_dialog"),  # noqa: PTH118
    )
    logger.info("Generated diagram for lecture processing dialog")
