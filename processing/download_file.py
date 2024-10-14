import logging
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TypeVar, ParamSpec

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy_file import File

from configs import VIDEO_DOWNLOAD_TIMEOUT, LOG_EACH_VIDEO_DOWNLOAD
from djgram.db.base import get_autocommit_session
from djgram.db.utils import get_or_create
from djgram.utils.download import download_file
from tools.yt_dlp_downloader.misc import convert_entries_generator, yt_dlp_jsonify, yt_dlp_get_html_link
from tools.yt_dlp_downloader.yt_dlp_download_videos import (
    YtDlpInfoDict,
    download,
    get_url,
    YtDlpContentType,
)
from utils.get_bot import get_tg_bot
from utils.thumbnail import get_best_thumbnail
from utils.video.measure import ffprobe_extract_meta
from utils.yt_dlp_cached import extract_info_async_cached
from .misc import execute_file_update_statement
from .models import Playlist, Video, Waiter
from .schema import VideoOrPlaylistForProcessing, FILE_TYPE

T = TypeVar("T")
P = ParamSpec("P")

DOWNLOAD_ATTEMPTS = 3

logger = logging.getLogger(__name__)


async def delete_downloaded_video(db_video: Video):
    async with get_autocommit_session() as db_session:
        logger.debug("Deleting not downloaded video %s", db_video.id)
        # noinspection PyTypeChecker
        await db_session.execute(delete(Video).where(Video.id == db_video.id))

    async with get_tg_bot() as bot:
        await db_video.broadcast_text_for_waiters(
            bot,
            f"Ошибка скачивания видео {yt_dlp_get_html_link(db_video.yt_dlp_info)}",
        )


async def _download_video(db_video, yt_dlp_info):
    with tempfile.TemporaryDirectory() as temp_dir:
        url = get_url(yt_dlp_info)
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                download_data = download(url=url, output_dir=temp_dir)
            except Exception as exc:  # (DownloadError, FileNotFoundError)
                logger.error("Download attempt %s/%s failed for %s: %s", attempt, DOWNLOAD_ATTEMPTS, url, exc)
            else:
                break

        else:
            logger.error("Failed to download %s in %s attempts", url, DOWNLOAD_ATTEMPTS)
            await delete_downloaded_video(db_video)
            return None

        video_file = Path(download_data.filenames[download_data.info["id"]])

        file = File(content_path=video_file.as_posix())
        logger.info("Uploading file to storage")
        file.save_to_storage(Video.file.type.upload_storage)

        thumbnail = await get_best_thumbnail(yt_dlp_info)
        if thumbnail is not None:
            logger.info("Uploading thumbnail to storage")
            thumbnail_file = File(content=thumbnail, filename="thumbnail.jpg")
            thumbnail_file.save_to_storage(Video.thumbnail.type.upload_storage)
        else:
            thumbnail_file = None

        meta = ffprobe_extract_meta(video_file)
        # noinspection PyTypeChecker
        stmt = (
            update(Video)
            .where(Video.id == db_video.id)
            .values(file=file, yt_dlp_info=download_data.info, meta=meta, thumbnail=thumbnail_file)
            .returning(Video)
        )
        return await execute_file_update_statement(file, stmt)


async def _create_video(
    yt_dlp_info: YtDlpInfoDict,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
    playlist: Playlist | None,
) -> tuple[bool, Video] | None:
    video_id = yt_dlp_info["id"]

    async with get_autocommit_session() as db_session:
        stmt = select(Video).options(selectinload(Video.playlists)).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            await db_video.add_if_not_in_waiters_from_task(db_session, video_or_playlist_for_processing)

            if playlist is not None:
                # Неправильный результат
                # playlist not in db_video.playlists:

                for pl in db_video.playlists:
                    if playlist.id == pl.id:
                        break
                else:
                    db_video.playlists.add(playlist)

            return False, db_video

        logger.info("Creating new video %s", video_id)
        db_video = Video(
            id=video_id,
            source=yt_dlp_info["extractor"],
            yt_dlp_info=yt_dlp_jsonify(yt_dlp_info),
            file=None,
            waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        )
        if playlist is not None:
            db_video.playlists.add(playlist)
        db_session.add(db_video)

    try:
        return True, await _download_video(db_video, yt_dlp_info)
    except Exception as exc:
        logger.exception("Failed to download video %s: %s", db_video.id, exc, exc_info=exc)
        await delete_downloaded_video(db_video)

    return None


async def _create_playlist(
    bot: Bot,
    yt_dlp_info: YtDlpInfoDict,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[tuple[bool, Video] | None]:
    yt_dlp_info = convert_entries_generator(yt_dlp_info)
    async with get_autocommit_session() as db_session:
        playlist, created = await get_or_create(
            session=db_session,
            model=Playlist,
            with_for_update=False,
            defaults={
                "source": yt_dlp_info["extractor"],
                "yt_dlp_info": yt_dlp_jsonify(yt_dlp_info),
            },
            id=yt_dlp_info["id"],
        )

        if created:
            logger.info("Created playlist %s", playlist.id)
        else:
            logger.info("Using existing playlist %s", playlist.id)

    logging_message: Message | None = None
    playlist_count = yt_dlp_info["playlist_count"]
    for idx, video in enumerate(yt_dlp_info["entries"], start=1):
        if LOG_EACH_VIDEO_DOWNLOAD:
            text = f"Скачиваю {idx}/{playlist_count} {yt_dlp_get_html_link(video)}"
            if logging_message is None:
                logging_message = await bot.send_message(
                    text=text,
                    chat_id=video_or_playlist_for_processing.telegram_chat_id,
                    reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    disable_notification=True,
                )
            else:
                await logging_message.edit_text(text=text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)

        video = await extract_info_async_cached(url=get_url(video), process=False)
        yield await _create_video(video, video_or_playlist_for_processing, playlist)


async def get_from_url(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[tuple[bool, Video] | None]:
    logger.info("Downloading video or playlist")
    yt_dlp_info = await extract_info_async_cached(url=video_or_playlist_for_processing.url, process=False)
    if yt_dlp_info["_type"] == YtDlpContentType.URL:
        logger.info('Resolving url with type "url": %s', video_or_playlist_for_processing.url)
        yt_dlp_info = await extract_info_async_cached(url=yt_dlp_info["url"], process=False)

    if yt_dlp_info.get("entries") is not None:
        async for video in _create_playlist(bot, yt_dlp_info, video_or_playlist_for_processing):
            yield video
        return

    if LOG_EACH_VIDEO_DOWNLOAD:
        await bot.send_message(
            text="Скачиваю",
            chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
            disable_web_page_preview=True,
            disable_notification=True,
        )
    yield await _create_video(yt_dlp_info, video_or_playlist_for_processing, None)


async def get_from_telegram(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> tuple[bool, Video]:
    # Создаём видео в базе данных, если его нет
    # Иначе присоединяемся к ожидающим скачивание
    async with get_autocommit_session() as db_session:
        video_id = video_or_playlist_for_processing.make_id_from_telegram()
        # noinspection PyTypeChecker
        stmt = select(Video).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            await db_video.add_if_not_in_waiters_from_task(db_session, video_or_playlist_for_processing)
            return False, db_video

        video = video_or_playlist_for_processing.get_tg_video()
        yt_dlp_info = video.model_dump(mode="json") | {
            "id": video_id,
            "title": video.file_name,
            "extractor": FILE_TYPE,
        }

        logger.info("Creating new video %s", video_id)
        db_video = Video(
            id=video_id,
            source=FILE_TYPE,
            yt_dlp_info=yt_dlp_info,
            file=None,
            waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        )
        db_session.add(db_video)

    logger.info("Downloading video %s from telegram", video.file_id)
    if LOG_EACH_VIDEO_DOWNLOAD:
        await bot.send_message(
            text="Скачиваю",
            chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        )

    # TODO: можно заливать файл напрямую в хранилище через container.upload_object_via_stream
    buffer = await download_file(bot, video.file_id, video.file_size, timeout=VIDEO_DOWNLOAD_TIMEOUT)

    file = File(
        content=buffer,
        content_type=video.mime_type,
    )
    logger.info("Uploading file to storage")
    file.save_to_storage(Video.file.type.upload_storage)
    stmt = update(Video).where(Video.id == db_video.id).values(file=file).returning(Video)
    return True, await execute_file_update_statement(file, stmt)


async def get_downloaded_videos(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[tuple[bool, Video] | None]:
    """
    Возвращает скачанные видео
    """
    if video_or_playlist_for_processing.url is not None:
        async for video in get_from_url(bot, video_or_playlist_for_processing):
            yield video

        return

    try:
        telegram_video = await get_from_telegram(bot, video_or_playlist_for_processing)
    except Exception as exc:
        logger.exception(
            "Failed to download video %s from telegram: %s",
            (video_or_playlist_for_processing.video or video_or_playlist_for_processing.document).file_id,
            exc,
            exc_info=exc,
        )
        yield None
    else:
        yield telegram_video
