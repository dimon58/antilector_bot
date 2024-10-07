import logging
from contextlib import suppress
from pathlib import Path

import aiogram
import pydantic
from aiogram import Bot
from aiogram.enums import ChatAction, ParseMode
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from pydantic import ConfigDict
from sqlalchemy import ForeignKey, Table, Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import sqltypes
from sqlalchemy_file import FileField, File
from sqlalchemy_file.storage import StorageManager

from configs import ORIGINAL_VIDEO_STORAGE, PROCESSED_VIDEO_STORAGE, PROCESSED_VIDEO_CONTAINER, ORIGINAL_VIDEO_CONTAINER
from djgram.contrib.communication.broadcast import broadcast
from djgram.db.models import BaseModel, TimeTrackableBaseModel
from djgram.db.pydantic_field import ImmutablePydanticField
from djgram.utils.input_file_ext import S3FileInput
from tools.audio_processing.pipeline import AudioPipeline
from tools.video_processing.actions.unsilence_actions import TIME_SAVINGS_REAL_KEY, UnsilenceAction
from tools.video_processing.pipeline import VideoPipelineStatistics
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict
from .representation import silence_remove_done_report
from .schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


def setup_storage():
    logger.info("Setting up storages")

    with suppress(RuntimeError):
        StorageManager.add_storage(ORIGINAL_VIDEO_STORAGE, ORIGINAL_VIDEO_CONTAINER)

    with suppress(RuntimeError):
        StorageManager.add_storage(PROCESSED_VIDEO_STORAGE, PROCESSED_VIDEO_CONTAINER)


class ProfileBase(TimeTrackableBaseModel):
    __abstract__ = True

    slug: Mapped[str] = mapped_column(doc="Название профиля для технических нужд", unique=True, index=True)
    name: Mapped[str] = mapped_column(doc="Название профиля")
    description: Mapped[str] = mapped_column(doc="Описание профиля")


class AudioProcessingProfile(ProfileBase):
    audio_pipeline: Mapped[AudioPipeline] = mapped_column(
        ImmutablePydanticField(AudioPipeline, should_frozen=False),
        nullable=False,
        doc="Audio processing pipeline",
    )


class UnsilenceProfile(ProfileBase):
    name: Mapped[str]
    description: Mapped[str]

    unsilence_action: Mapped[UnsilenceAction] = mapped_column(
        ImmutablePydanticField(UnsilenceAction, should_frozen=False),
        doc="Unsilence action",
    )


class Waiter(pydantic.BaseModel):
    model_config = ConfigDict(frozen=True)

    telegram_chat_id: int | str
    reply_to_message_id: int | None = None

    @classmethod
    def from_task(cls, video_or_playlist_for_processing: VideoOrPlaylistForProcessing) -> "Waiter":
        return cls(
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

    def add_if_not_in_waiters(self, telegram_chat_id: int | str, reply_to_message_id: int | None = None) -> bool:
        """
        Добавляет в список ожидающих

        Возвращает True, если реально добавлен, False, если пользователь уже был в списке
        """
        if self.has_waiter(telegram_chat_id):
            return False

        logger.info("New waiter %s for %s", telegram_chat_id, self)
        self.waiters.append(
            Waiter(
                telegram_chat_id=telegram_chat_id,
                reply_to_message_id=reply_to_message_id,
            )
        )
        return True

    def add_if_not_in_waiters_from_task(self, video_or_playlist_for_processing: VideoOrPlaylistForProcessing) -> bool:
        return self.add_if_not_in_waiters(
            telegram_chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        )

    async def broadcast_text_for_waiters(self, bot: Bot, text: str):

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
        )


class YtDlpBase:
    source: Mapped[str] = mapped_column(
        sqltypes.String,
        nullable=False,
        doc="Источник видео: file, youtube, vk и т.д. "
        "Полный список https://github.com/yt-dlp/yt-dlp/tree/master/yt_dlp/extractor",
    )

    yt_dlp_info: Mapped[YtDlpInfoDict] = mapped_column(JSONB(), nullable=False, doc="Информация из yt dlp")

    def get_title_for_admin(self):
        return f"{self.source}: {self.yt_dlp_info["title"]}"


playlist_video_table = Table(
    "playlist_video",
    BaseModel.metadata,
    Column("playlist_id", ForeignKey("playlist.id"), primary_key=True),
    Column("video_id", ForeignKey("video.id"), primary_key=True),
)


class Playlist(YtDlpBase, TimeTrackableBaseModel):
    id: Mapped[str] = mapped_column(
        sqltypes.String,
        nullable=False,
        primary_key=True,
        doc="Playlist id",
    )

    videos: Mapped[set["Video"]] = relationship(
        back_populates="playlists", secondary=playlist_video_table, cascade="all,delete"
    )


class Video(Waitable, YtDlpBase, TimeTrackableBaseModel):
    id: Mapped[str] = mapped_column(
        sqltypes.String,
        nullable=False,
        primary_key=True,
        doc="Video id",
    )

    playlists: Mapped[set[Playlist]] = relationship(
        back_populates="videos", secondary=playlist_video_table, cascade="all,delete"
    )

    file: Mapped[File | None] = mapped_column(
        FileField(upload_storage=ORIGINAL_VIDEO_STORAGE),
        doc="Сам видеофайл. None в случае, когда файл в процессе скачивания",
    )


class ProcessedVideo(Waitable, TimeTrackableBaseModel):
    __table_args__ = (
        UniqueConstraint(
            "original_video_id", "audio_processing_profile_id", "unsilence_profile_id", name="uniq_pipeline"
        ),
    )

    original_video_id: Mapped[str] = mapped_column(ForeignKey(Video.id), index=True)
    original_video: Mapped[Video] = relationship(Video)

    audio_processing_profile_id: Mapped[int] = mapped_column(ForeignKey(AudioProcessingProfile.id), index=True)
    audio_processing_profile: Mapped[AudioProcessingProfile] = relationship(AudioProcessingProfile)

    unsilence_profile_id: Mapped[int] = mapped_column(ForeignKey(UnsilenceProfile.id), index=True)
    unsilence_profile: Mapped[UnsilenceProfile] = relationship(UnsilenceProfile)

    processing_stats: Mapped[VideoPipelineStatistics | None] = mapped_column(
        ImmutablePydanticField(VideoPipelineStatistics, should_frozen=False)
    )

    file: Mapped[File | None] = mapped_column(
        FileField(upload_storage=PROCESSED_VIDEO_STORAGE),
        doc="Сам видеофайл. None в случае, когда видео в процессе обработки",
    )
    telegram_file: Mapped[aiogram.types.Video | None] = mapped_column(
        ImmutablePydanticField(aiogram.types.Video),
        doc="Отправленный файл в телеграм",
    )

    def get_caption(self):
        yt_dlp_info = self.original_video.yt_dlp_info

        original_url = yt_dlp_info.get("webpage_url")
        if original_url is not None:  # noqa: SIM108
            original_ref = f"\n\n[Ссылка на оригинальное видео]({original_url})"
        else:  # если обрабатывался файл, загруженный пользователем
            original_ref = ""

        time_savings = self.processing_stats.unsilence_stats.action_stats[TIME_SAVINGS_REAL_KEY]

        return f"{yt_dlp_info["title"]}\n" f"\n" f"{silence_remove_done_report(time_savings)}" f"{original_ref}"

    async def send(self, bot: Bot, chat_id: int | str, reply_to_message_id: int | None = None) -> Message:
        async with ChatActionSender(
            bot=bot,
            chat_id=chat_id,
            action=ChatAction.UPLOAD_VIDEO,
        ):
            if self.telegram_file is not None:
                logger.info("Sending cached in telegram video %s", self.id)
                video = self.telegram_file.file_id
            else:
                logger.info("Uploading video %s to telegram", self.id)
                ext = Path(self.file["filename"]).suffix
                video = S3FileInput(
                    obj=self.file.file.object,
                    filename=f"processed{ext}",
                )

            message = await bot.send_video(
                video=video,
                caption=self.get_caption(),
                chat_id=chat_id,
                supports_streaming=True,
                reply_to_message_id=reply_to_message_id,
                parse_mode=ParseMode.MARKDOWN,
            )

            if self.telegram_file is None:
                self.telegram_file = message.video

            return message

    async def broadcast_for_waiters(self, bot: Bot):

        chat_ids = []
        per_chat_kwargs = []

        for waiter in self.waiters:
            chat_ids.append(waiter.telegram_chat_id)
            per_chat_kwargs.append({"reply_to_message_id": waiter.reply_to_message_id})

        async def send_method(chat_id: int | str, reply_to_message_id: int | None = None) -> None:
            await self.send(bot=bot, chat_id=chat_id, reply_to_message_id=reply_to_message_id)

        await broadcast(
            send_method=send_method,
            chat_ids=chat_ids,
            count=len(chat_ids),
            per_chat_kwargs=per_chat_kwargs,
        )
