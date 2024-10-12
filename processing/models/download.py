from typing import Any

from sqlalchemy import ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import sqltypes
from sqlalchemy_file import FileField, File

from configs import ORIGINAL_VIDEO_STORAGE, THUMBNAILS_STORAGE
from djgram.db.models import BaseModel, TimeTrackableBaseModel
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict
from .common import Waitable


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
    thumbnail: Mapped[File | None] = mapped_column(
        FileField(upload_storage=THUMBNAILS_STORAGE),
        doc="Лучшая миниатюра для видео в формате jpg",
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
