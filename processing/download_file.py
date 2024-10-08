import logging
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy_file import File
from yt_dlp.utils import DownloadError

from configs import VIDEO_DOWNLOAD_TIMEOUT
from djgram.db.base import get_autocommit_session
from djgram.db.utils import get_or_create
from djgram.utils.download import download_file
from tools.yt_dlp_downloader.misc import convert_entries_generator, yt_dlp_jsonify, yt_dlp_get_html_link
from tools.yt_dlp_downloader.yt_dlp_download_videos import (
    YtDlpInfoDict,
    extract_info,
    download,
    get_url,
    YtDlpContentType,
)
from .misc import execute_file_update_statement
from .models import Playlist, Video, Waiter
from .schema import VideoOrPlaylistForProcessing, FILE_TYPE

DOWNLOAD_ATTEMPTS = 3

logger = logging.getLogger(__name__)


async def _create_video(
    yt_dlp_info: YtDlpInfoDict,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
    playlist: Playlist | None,
) -> Video:
    video_id = yt_dlp_info["id"]

    async with get_autocommit_session() as db_session:
        stmt = select(Video).options(selectinload(Video.playlists)).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            db_video.add_if_not_in_waiters_from_task(video_or_playlist_for_processing)

            if playlist is not None:
                # Неправильный результат
                # playlist not in db_video.playlists:

                for pl in db_video.playlists:
                    if playlist.id == pl.id:
                        break
                else:
                    db_video.playlists.add(playlist)

            return db_video

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

    with tempfile.TemporaryDirectory() as temp_dir:
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            url = get_url(yt_dlp_info)
            try:
                download_data = download(url=url, output_dir=temp_dir)
            except DownloadError as exc:
                logger.error("Download attempt %s failed for %s: %s", attempt, url, exc)
            else:
                break
        else:
            raise DownloadError(f"Failed to download {url} in {DOWNLOAD_ATTEMPTS} attempts: {exc}")

        video_file = Path(download_data.filenames[download_data.info["id"]])

        file = File(content_path=video_file.as_posix())
        logger.info("Uploading file to storage")
        file.save_to_storage(Video.file.type.upload_storage)
        stmt = (
            update(Video)
            .where(Video.id == db_video.id)
            .values(file=file, yt_dlp_info=download_data.info)
            .returning(Video)
        )
        return await execute_file_update_statement(file, stmt)


async def _create_playlist(
    bot: Bot,
    yt_dlp_info: YtDlpInfoDict,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[Video]:
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

        video = extract_info(url=get_url(video), process=False)
        yield await _create_video(video, video_or_playlist_for_processing, playlist)


async def get_from_url(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[Video]:
    logger.info("Downloading video or playlist")
    yt_dlp_info = extract_info(url=video_or_playlist_for_processing.url, process=False)
    if yt_dlp_info["_type"] == YtDlpContentType.URL:
        logger.info('Resolving url with type "url": %s', video_or_playlist_for_processing.url)
        yt_dlp_info = extract_info(url=yt_dlp_info["url"], process=False)

    if yt_dlp_info.get("entries") is not None:
        async for video in _create_playlist(bot, yt_dlp_info, video_or_playlist_for_processing):
            yield video
        return

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
) -> Video:
    # Создаём видео в базе данных, если его нет
    # Иначе присоединяемся к ожидающим скачивание
    async with get_autocommit_session() as db_session:
        video_id = video_or_playlist_for_processing.make_id_from_telegram()
        stmt = select(Video).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            db_video.add_if_not_in_waiters_from_task(video_or_playlist_for_processing)
            return db_video

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
    return await execute_file_update_statement(file, stmt)


async def get_downloaded_videos(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> AsyncGenerator[Video]:
    """
    Возвращает скачанные видео
    """
    if video_or_playlist_for_processing.url is not None:
        async for video in get_from_url(bot, video_or_playlist_for_processing):
            yield video

        return

    yield await get_from_telegram(bot, video_or_playlist_for_processing)
