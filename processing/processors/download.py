import logging

from aiogram.enums import ParseMode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from configs import LOG_EACH_VIDEO_DOWNLOAD
from djgram.db.base import get_autocommit_session
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link
from utils.get_bot import get_tg_bot
from .error_texts import get_silence_only_error_text
from ..download_file import get_downloaded_videos
from ..models import (
    ProcessedVideo,
    AudioProcessingProfile,
    UnsilenceProfile,
    Video,
    Waiter,
    ProcessedVideoStatus,
    VideoProcessingResourceUsage,
)
from ..schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


async def process_video_or_playlist(video_or_playlist_for_processing: VideoOrPlaylistForProcessing):
    """
    Обрабатывает видео или плейлист

    Если уже обрабатывает, то отправляет готовое

    Если скачано, то создаёт задачи на обработку

    Если не скачано, то скачивает и создаёт задачи на обработку
    """

    if LOG_EACH_VIDEO_DOWNLOAD:
        async with get_tg_bot() as bot:
            start_text = "Начинаю обработку"

            if video_or_playlist_for_processing.download_data.is_playlist:
                start_text = f"{start_text}. Видео из плейлиста будут отправлены по мере готовности."

            await bot.send_message(
                text=start_text,
                chat_id=video_or_playlist_for_processing.telegram_chat_id,
                reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                disable_notification=True,
                disable_web_page_preview=True,
            )

    async with get_tg_bot() as bot:
        async for db_video_repr in get_downloaded_videos(bot, video_or_playlist_for_processing):

            # Проблемы с загрузкой, логируется в get_downloaded_videos
            if db_video_repr is None:
                continue

            downloaded_here, db_video = db_video_repr

            # Реально скачивается в другой задаче
            if not downloaded_here:
                suffix = "ing" if db_video.file is None else "ed"
                logger.info("Video %s download%s in other task", db_video.id, suffix)
                async with get_autocommit_session() as db_session:
                    processed_video = await create_processed_video_initial_and_add_waiter(
                        db_session,
                        db_video.id,
                        video_or_playlist_for_processing,
                        select_with_original_video=True,
                    )

                    match processed_video.status:
                        case ProcessedVideoStatus.TASK_CREATED:
                            # Создаём таску для работы.
                            # Если она будет дублироваться, то отсеиваем её в process_video_task
                            logger.info("Video %s created, but not processed", processed_video.id)

                        case ProcessedVideoStatus.PROCESSING:
                            # Не обработано, значит пользователь в очереди на рассылку
                            logger.info("Video %s is processing", processed_video.id)
                            async with get_tg_bot() as bot:
                                await bot.send_message(
                                    text=f"Обрабатываю {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}",
                                    chat_id=video_or_playlist_for_processing.telegram_chat_id,
                                    reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                                    disable_notification=True,
                                    parse_mode=ParseMode.HTML,
                                )

                        case ProcessedVideoStatus.PROCESSED:
                            db_session.add(
                                VideoProcessingResourceUsage(
                                    user_id=video_or_playlist_for_processing.user_id,
                                    processed_video_id=processed_video.id,
                                    real_processed=False,
                                )
                            )

                            # Отправляем обработанное видео
                            if processed_video.telegram_file is not None:
                                logger.info("Sending video %s", processed_video.id)
                                await processed_video.send(
                                    bot=bot,
                                    chat_id=video_or_playlist_for_processing.telegram_chat_id,
                                    reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                                )
                            # Если тг файла ещё нет, то отправляем в список ожидающих
                            else:
                                await processed_video.add_if_not_in_waiters_from_task(
                                    db_session=db_session,
                                    video_or_playlist_for_processing=video_or_playlist_for_processing,
                                )
                            continue

                        case ProcessedVideoStatus.IMPOSSIBLE:
                            logger.warning(
                                "User %s tried to process video that %s is impossible (%s)",
                                video_or_playlist_for_processing.user_id,
                                processed_video.id,
                                processed_video.impossible_reason,
                            )

                            await bot.send_message(
                                chat_id=video_or_playlist_for_processing.telegram_chat_id,
                                text=get_silence_only_error_text(processed_video),
                                reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                            )
                            continue

                        case _:
                            logger.error(
                                "Unknown status %s for processed video %s", processed_video.status, processed_video.id
                            )
                            await bot.send_message(
                                chat_id=video_or_playlist_for_processing.telegram_chat_id,
                                text="Ошибка скачивания",
                                reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                            )
                            continue

            from ..tasks import process_video_task

            # Реально скачивается в этой задаче -> создаём задачу для обработки здесь
            logger.info(
                "Send video %s (audio profile %s, unsilence profile %s) to processing",
                db_video,
                video_or_playlist_for_processing.unsilence_data.audio_processing_profile_id,
                video_or_playlist_for_processing.unsilence_data.unsilence_profile_id,
            )
            async with get_autocommit_session() as db_session:
                processed_video = await create_processed_video_initial_and_add_waiter(
                    db_session=db_session,
                    db_video_id=db_video.id,
                    video_or_playlist_for_processing=video_or_playlist_for_processing,
                )
            process_video_task.delay(
                processed_video.id,
                Waiter.from_task(video_or_playlist_for_processing).model_dump(mode="json"),
            )

    # TODO: Добавить retry


async def ensure_video_and_profiles_exist(
    db_session: AsyncSession,
    db_video_id: str,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
):
    # noinspection PyTypeChecker
    stmt = select(AudioProcessingProfile).where(
        AudioProcessingProfile.id == video_or_playlist_for_processing.unsilence_data.audio_processing_profile_id
    )
    audio_processing_profile: AudioProcessingProfile | None = await db_session.scalar(stmt)
    if audio_processing_profile is None:
        msg = (
            "Audio processing profile %s not found"
            % video_or_playlist_for_processing.unsilence_data.audio_processing_profile_id
        )
        logger.error(msg)
        raise ValueError(msg)

    # noinspection PyTypeChecker
    stmt = select(UnsilenceProfile).where(
        UnsilenceProfile.id == video_or_playlist_for_processing.unsilence_data.unsilence_profile_id
    )
    unsilence_profile: UnsilenceProfile | None = await db_session.scalar(stmt)
    if unsilence_profile is None:
        msg = "Unsilence profile %s not found" % video_or_playlist_for_processing.unsilence_data.unsilence_profile_id
        logger.error(msg)
        raise ValueError(msg)

    # noinspection PyTypeChecker
    stmt = select(Video).where(Video.id == db_video_id)
    db_video: Video | None = await db_session.scalar(stmt)
    if db_video is None:
        msg = "Video %s not found in database" % db_video_id
        logger.error(msg)
        raise ValueError(msg)


async def create_processed_video_initial_and_add_waiter(
    db_session: AsyncSession,
    db_video_id: str,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
    *,
    select_with_original_video: bool = False,
) -> ProcessedVideo:
    # noinspection PyTypeChecker
    stmt = (
        select(ProcessedVideo)
        .with_for_update()
        .where(
            ProcessedVideo.original_video_id == db_video_id,
            ProcessedVideo.audio_processing_profile_id
            == video_or_playlist_for_processing.unsilence_data.audio_processing_profile_id,
            ProcessedVideo.unsilence_profile_id == video_or_playlist_for_processing.unsilence_data.unsilence_profile_id,
        )
    )
    if select_with_original_video:
        stmt = stmt.options(selectinload(ProcessedVideo.original_video))
    processed_video: ProcessedVideo | None = await db_session.scalar(stmt)

    if processed_video is not None:
        if processed_video.status != ProcessedVideoStatus.PROCESSED:
            await processed_video.add_if_not_in_waiters_from_task(db_session, video_or_playlist_for_processing)
        return processed_video

    await ensure_video_and_profiles_exist(
        db_session=db_session,
        db_video_id=db_video_id,
        video_or_playlist_for_processing=video_or_playlist_for_processing,
    )

    processed_video = ProcessedVideo(
        original_video_id=db_video_id,
        audio_processing_profile_id=video_or_playlist_for_processing.unsilence_data.audio_processing_profile_id,
        unsilence_profile_id=video_or_playlist_for_processing.unsilence_data.unsilence_profile_id,
        waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        status=ProcessedVideoStatus.TASK_CREATED,
    )
    db_session.add(processed_video)

    return processed_video
