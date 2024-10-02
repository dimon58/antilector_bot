import json
import logging
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy_file import File
from sqlalchemy_file.storage import StorageManager

from djgram.db.base import get_autocommit_session
from djgram.db.utils import get_or_create
from djgram.utils.download import download_file
from tools.yt_dlp_downloader.misc import convert_entries_generator, yt_dlp_jsonify
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict, extract_info, download, get_url
from .models import Playlist, Video
from .schema import VideoOrPlaylistForProcessing, FILE_TYPE

logger = logging.getLogger(__name__)


async def execute_file_update_statement(file, stmt):
    async with get_autocommit_session() as db_session:
        try:
            db_video = await db_session.execute(stmt)
        except Exception as exc:
            logger.error(exc)
            for path in file["files"]:
                StorageManager.delete_file(path)
                logger.info("Deleted %s", path)
            raise

        return True, db_video


async def _create_video(
    yt_dlp_info: YtDlpInfoDict,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
    playlist: Playlist | None,
) -> tuple[bool, Video]:
    video_id = yt_dlp_info["id"]

    async with get_autocommit_session() as db_session:
        stmt = select(Video).options(selectinload(Video.playlists)).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            db_video.add_if_not_in_waiters(video_or_playlist_for_processing.user_id)

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
            source=FILE_TYPE,
            yt_dlp_info=yt_dlp_jsonify(yt_dlp_info),
            file=None,
            waiters_ids=[video_or_playlist_for_processing.user_id],
        )
        if playlist is not None:
            db_video.playlists.add(playlist)
        db_session.add(db_video)

    with tempfile.TemporaryDirectory() as temp_dir:
        download_data = download(url=get_url(yt_dlp_info), output_dir=temp_dir)
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
) -> list[tuple[bool, Video]]:
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
    videos = []
    playlist_count = yt_dlp_info["playlist_count"]
    for idx, video in enumerate(yt_dlp_info["entries"], start=1):
        text = f"Скачиваю {idx}/{playlist_count} [{video["title"]}]({get_url(video)})"
        if logging_message is None:
            logging_message = await bot.send_message(
                text=text,
                chat_id=video_or_playlist_for_processing.telegram_chat_id,
                reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                disable_notification=True,
            )
        else:
            await logging_message.edit_text(text=text, disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)

        video = extract_info(url=get_url(video), process=False)
        videos.append(await _create_video(video, video_or_playlist_for_processing, playlist))

    return videos


async def get_from_url(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> list[tuple[bool, Video]]:
    logger.info("Downloading video or playlist")
    yt_dlp_info = extract_info(url=video_or_playlist_for_processing.url, process=False)

    if yt_dlp_info.get("entries") is not None:
        return await _create_playlist(bot, yt_dlp_info, video_or_playlist_for_processing)

    await bot.send_message(
        text="Скачиваю",
        chat_id=video_or_playlist_for_processing.telegram_chat_id,
        reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        disable_web_page_preview=True,
        disable_notification=True,
    )
    return [await _create_video(yt_dlp_info, video_or_playlist_for_processing, None)]


async def get_from_telegram(
    bot: Bot,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> tuple[bool, Video]:
    # Создаём видео в базе данных, если его нет
    # Иначе присоединяемся к ожидающим скачивание
    async with get_autocommit_session() as db_session:
        video_id = video_or_playlist_for_processing.make_id_from_telegram()
        stmt = select(Video).with_for_update().where(Video.id == video_id)
        db_video: Video | None = await db_session.scalar(stmt)

        if db_video is not None:
            logger.info("Using existing original video %s", video_id)
            db_video.add_if_not_in_waiters(video_or_playlist_for_processing.user_id)
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
            waiters_ids=[video_or_playlist_for_processing.user_id],
        )
        db_session.add(db_video)

    logger.info("Downloading video %s from telegram", video.file_id)
    await bot.send_message(
        text="Скачиваю",
        chat_id=video_or_playlist_for_processing.telegram_chat_id,
        reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
    )

    # TODO: можно заливать файл напрямую в хранилище через container.upload_object_via_stream
    buffer = await download_file(bot, video.file_id, video.file_size)

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
) -> list[tuple[bool, Video]]:
    """
    Возвращает скачанные видео в формате (скачано текущим заданием или нет, само видео)
    """
    if video_or_playlist_for_processing.url is not None:
        return await get_from_url(bot, video_or_playlist_for_processing)

    return [await get_from_telegram(bot, video_or_playlist_for_processing)]
