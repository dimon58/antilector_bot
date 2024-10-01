"""
Колбеки для диалогов
"""

import logging

from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Select

from djgram.system_configs import MIDDLEWARE_AUTH_USER_KEY
from processing.schema import VideoOrPlaylistForProcessing
from processing.tasks import process_video_or_playlist
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpContentType

from .handle_url import URL_KEY, handle_url
from .states import LectureProcessingStates

VIDEO_KEY = "video"
DOCUMENT_KEY = "document"
MESSAGE_ID_KEY = "message_id"
IS_PLAYLIST_KEY = "is_playlist"

AUDIO_PROCESSING_PROFILE_ID_KEY = "audio_processing_profile_id"

logger = logging.getLogger(__name__)


async def handle_video(message: Message, manager: DialogManager):
    manager.dialog_data[VIDEO_KEY] = message.video.model_dump(mode="json")

    await manager.switch_to(LectureProcessingStates.choose_audio_processing_profile)


async def handle_document(message: Message, manager: DialogManager):
    if message.document.mime_type is None or not message.document.mime_type.startswith("video/"):
        await message.reply("Можно преобразовать только видеофайл")
        return

    manager.dialog_data[DOCUMENT_KEY] = message.document.model_dump(mode="json")

    await manager.switch_to(LectureProcessingStates.choose_audio_processing_profile)


async def add_video(message: Message, message_input: MessageInput, manager: DialogManager):
    async with ChatActionSender(
        bot=message.bot,
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
    ):
        if message.text is not None:
            _type = await handle_url(message, manager)
            manager.dialog_data.pop(VIDEO_KEY, None)
            manager.dialog_data.pop(DOCUMENT_KEY, None)

            if _type is not None:
                manager.dialog_data[MESSAGE_ID_KEY] = message.message_id
                manager.dialog_data[IS_PLAYLIST_KEY] = _type == YtDlpContentType.PLAYLIST
            return

        if message.video is not None:
            await handle_video(message, manager)
            manager.dialog_data.pop(URL_KEY, None)
            manager.dialog_data.pop(DOCUMENT_KEY, None)
            manager.dialog_data[MESSAGE_ID_KEY] = message.message_id
            return

        if message.document is not None:
            await handle_document(message, manager)
            manager.dialog_data.pop(URL_KEY, None)
            manager.dialog_data.pop(VIDEO_KEY, None)
            manager.dialog_data[MESSAGE_ID_KEY] = message.message_id
            return

        await message.answer("Отправьте ссылку или видеофайл")


async def select_audio_processing_profile(
    callback: CallbackQuery,
    widget: Select,
    manager: DialogManager,
    audio_processing_profile_id: str,
):
    manager.dialog_data[AUDIO_PROCESSING_PROFILE_ID_KEY] = int(audio_processing_profile_id)

    task = VideoOrPlaylistForProcessing(
        url=manager.dialog_data.get(URL_KEY),
        video=manager.dialog_data.get(VIDEO_KEY),
        document=manager.dialog_data.get(DOCUMENT_KEY),
        user_id=manager.middleware_data[MIDDLEWARE_AUTH_USER_KEY].id,
        telegram_chat_id=callback.message.chat.id,
        telegram_message_id=manager.dialog_data[MESSAGE_ID_KEY],
        audio_processing_profile_id=int(audio_processing_profile_id),
        is_playlist=manager.dialog_data.get(IS_PLAYLIST_KEY, False),
    )

    task_id = process_video_or_playlist.delay(task.model_dump(mode="json"))

    logger.info("Published video processing task %s", task_id)

    await callback.bot.send_message(
        text="Добавлено в очередь на обработку",
        chat_id=task.telegram_chat_id,
        reply_to_message_id=task.telegram_message_id,
    )
