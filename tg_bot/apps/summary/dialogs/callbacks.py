"""
Колбеки для диалогов
"""

import logging

from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery
from aiogram.utils.chat_action import ChatActionSender
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.kbd import Button

from djgram.system_configs import MIDDLEWARE_AUTH_USER_KEY
from processing.schema import DownloadData, VideoOrPlaylistForProcessing
from processing.tasks import process_video_or_playlist
from tg_bot.apps.lectures.dialogs.callbacks import DOCUMENT_KEY, IS_PLAYLIST_KEY, MESSAGE_ID_KEY, VIDEO_KEY
from tg_bot.apps.lectures.dialogs.handle_url import URL_KEY

logger = logging.getLogger(__name__)


async def start_processing(
    callback: CallbackQuery,
    button: Button,
    manager: DialogManager,
):
    async with ChatActionSender(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        action=ChatAction.TYPING,
    ):
        task = VideoOrPlaylistForProcessing(
            user_id=manager.middleware_data[MIDDLEWARE_AUTH_USER_KEY].id,
            telegram_chat_id=callback.message.chat.id,
            reply_to_message_id=manager.dialog_data[MESSAGE_ID_KEY],
            download_data=DownloadData(
                url=manager.dialog_data.get(URL_KEY),
                video=manager.dialog_data.get(VIDEO_KEY),
                document=manager.dialog_data.get(DOCUMENT_KEY),
                is_playlist=manager.dialog_data.get(IS_PLAYLIST_KEY, False),
            ),
            for_summary=True,
        )

        task_id = process_video_or_playlist.delay(task.model_dump(mode="json"))

        logger.info("Published video summarization task %s", task_id)

        await callback.bot.send_message(
            text="Добавлено в очередь на обработку",
            chat_id=task.telegram_chat_id,
            reply_to_message_id=task.reply_to_message_id,
        )

    await manager.done(show_mode=ShowMode.SEND)
