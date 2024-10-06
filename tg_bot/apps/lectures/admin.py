"""
Администрирование
"""

import json
from typing import Any

from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.chat_action import ChatActionSender

from djgram.contrib.admin import AppAdmin, ModelAdmin
from djgram.contrib.admin.action_buttons import AbstractObjectActionButton
from djgram.contrib.admin.rendering import OneLineTextRenderer
from processing.models import Playlist, ProcessedVideo, Video, YtDlpBase

app = AppAdmin(verbose_name="Обработка лекций")


class DownloadYtDlpInfoButton(AbstractObjectActionButton):

    async def click(self, obj: YtDlpBase, callback_query: CallbackQuery, middleware_data: dict[str, Any]) -> None:
        async with ChatActionSender(
            bot=callback_query.bot,
            chat_id=callback_query.message.chat.id,
            action=ChatAction.TYPING,
        ):
            await callback_query.message.answer_document(
                document=BufferedInputFile(
                    file=json.dumps(obj.yt_dlp_info, ensure_ascii=False, indent=2).encode("utf8"),
                    filename="yt_dlp_info.json",
                ),
            )


@app.register
class VideoAdmin(ModelAdmin):
    model = Video
    name = "Видео"
    list_display = ("call:get_title_for_admin",)
    exclude_fields = ("yt_dlp_info",)
    object_action_buttons = (
        DownloadYtDlpInfoButton(button_id="download_yt_dlp_info", title="📥 Получить дополнительную информация"),
    )
    widgets_override = {
        "id": OneLineTextRenderer,
        "source": OneLineTextRenderer,
    }


@app.register
class PlaylistAdmin(VideoAdmin):
    model = Playlist
    name = "Плейлисты"


@app.register
class ProcessedVideoAdmin(ModelAdmin):
    model = ProcessedVideo
    name = "Обработанные видео"
    list_display = ("id",)
