import logging

from sqlalchemy import ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import sqltypes
from sqlalchemy_file import FileField, File
from sqlalchemy_file.storage import StorageManager

from configs import ORIGINAL_VIDEO_STORAGE, PROCESSED_VIDEO_STORAGE, PROCESSED_VIDEO_CONTAINER, ORIGINAL_VIDEO_CONTAINER
from djgram.db.models import BaseModel, TimeTrackableBaseModel
from djgram.db.pydantic_field import PydanticField
from tools.audio_processing.pipeline import AudioPipeline
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict

logger = logging.getLogger(__name__)


def setup_storage():
    logger.info("Setting up storages")

    StorageManager.add_storage(ORIGINAL_VIDEO_STORAGE, ORIGINAL_VIDEO_CONTAINER)
    StorageManager.add_storage(PROCESSED_VIDEO_STORAGE, PROCESSED_VIDEO_CONTAINER)


class AudioProcessingProfile(BaseModel):
    name: Mapped[str] = mapped_column(sqltypes.String, nullable=False)
    description: Mapped[str] = mapped_column(sqltypes.String, nullable=False)

    audio_pipeline: Mapped[PydanticField] = mapped_column(
        PydanticField(AudioPipeline),
        nullable=False,
        doc="Audio processing pipeline",
    )


class Waitable:
    waiters_ids: Mapped[list[int]] = mapped_column(
        sqltypes.ARRAY(sqltypes.Integer),
        default=[],
        server_default="{}",
        nullable=False,
        doc="Список людей, ожидающих обработки. По сути это список внешних ключей на модель пользователя.",
    )

    def add_if_not_in_waiters(self, user_id: int) -> bool:
        """
        Добавляет в список ожидающих

        Возвращает True, если реально добавлен, False, если пользователь уже был в списке
        """
        if user_id in self.waiters_ids:
            return False

        logger.info("New waiter %s for %s", user_id, self)
        self.waiters_ids.append(user_id)
        return True


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
    id: Mapped[str] = mapped_column(
        sqltypes.String,
        nullable=False,
        primary_key=True,
        doc="Video id",
    )

    original_video_id: Mapped[int] = mapped_column(ForeignKey(Video.id))
    original_video: Mapped[Video] = relationship(Video)
