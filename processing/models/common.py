import logging

import pydantic
from aiogram import Bot
from aiogram.enums import ParseMode
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import sqltypes
from sqlalchemy_file.storage import StorageManager

from configs import (
    ORIGINAL_VIDEO_STORAGE,
    PROCESSED_VIDEO_STORAGE,
    PROCESSED_VIDEO_CONTAINER,
    ORIGINAL_VIDEO_CONTAINER,
    THUMBNAILS_CONTAINER,
    THUMBNAILS_STORAGE,
)
from djgram.contrib.communication.broadcast import broadcast
from djgram.db.pydantic_field import ImmutablePydanticField
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict
from ..schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


def setup_storage():
    logger.info("Setting up storages")

    StorageManager.add_storage(ORIGINAL_VIDEO_STORAGE, ORIGINAL_VIDEO_CONTAINER)
    StorageManager.add_storage(PROCESSED_VIDEO_STORAGE, PROCESSED_VIDEO_CONTAINER)
    StorageManager.add_storage(THUMBNAILS_STORAGE, THUMBNAILS_CONTAINER)


class Waiter(pydantic.BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    telegram_chat_id: int | str
    reply_to_message_id: int | None = None

    @classmethod
    def from_task(cls, video_or_playlist_for_processing: VideoOrPlaylistForProcessing) -> "Waiter":
        return cls(
            user_id=video_or_playlist_for_processing.user_id,
            telegram_chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        )


class Waitable:
    waiters: Mapped[list[Waiter]] = mapped_column(
        sqltypes.ARRAY(ImmutablePydanticField(Waiter)),
        default=[],
        server_default="{}",
        nullable=False,
        doc="Список чатов для рассылки состояния обработки",
    )

    def has_waiter(self, telegram_chat_id: int | str):

        for waiter in self.waiters:
            if waiter.telegram_chat_id == telegram_chat_id:
                return True

        return False

    def add_if_not_in_waiters_from_task(self, video_or_playlist_for_processing: VideoOrPlaylistForProcessing) -> bool:
        """
        Добавляет в список ожидающих

        Возвращает True, если реально добавлен, False, если пользователь уже был в списке
        """

        if self.has_waiter(video_or_playlist_for_processing.telegram_chat_id):
            return False

        logger.info("New waiter %s for %s", video_or_playlist_for_processing.telegram_chat_id, self)
        self.waiters.append(Waiter.from_task(video_or_playlist_for_processing))
        return True

    async def broadcast_text_for_waiters(
        self,
        bot: Bot,
        text: str,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview: bool = True,
        **kwargs,
    ):

        chat_ids = []
        per_chat_kwargs = []

        for waiter in self.waiters:
            chat_ids.append(waiter.telegram_chat_id)
            per_chat_kwargs.append({"reply_to_message_id": waiter.reply_to_message_id})

        return await broadcast(
            bot.send_message,
            chat_ids=chat_ids,
            count=len(self.waiters),
            text=text,
            per_chat_kwargs=per_chat_kwargs,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            **kwargs,
        )
