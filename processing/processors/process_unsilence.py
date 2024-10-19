import logging
from typing import Any

from aiogram.enums import ParseMode
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from djgram.db.base import get_autocommit_session
from tools.audio_processing.actions.abstract import ProcessingImpossibleError
from tools.video_processing.actions.unsilence_actions import SilenceOnlyError
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link
from utils.get_bot import get_tg_bot
from .download import VideoDownloadEvent, download_observer
from .error_texts import get_silence_only_error_text, get_generic_error_text, get_unable_to_process_text
from ..models import (
    ProcessedVideo,
    ProcessedVideoStatus,
    VideoProcessingResourceUsage,
    Waiter,
    AudioProcessingProfile,
    UnsilenceProfile,
    Video,
)
from ..processing_file import run_video_pipeline
from ..schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


@download_observer.subscribe(retries=3)
async def process_unsilence(video_download_event: VideoDownloadEvent) -> None:
    video_or_playlist_for_processing = video_download_event.video_or_playlist_for_processing

    if video_or_playlist_for_processing.unsilence_data is None:
        logger.debug("Task not for this processor")
        return

    downloaded_here = video_download_event.downloaded_here
    db_video = video_download_event.db_video

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
                        async with get_tg_bot() as bot:
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
                    return

                case ProcessedVideoStatus.IMPOSSIBLE:
                    logger.warning(
                        "User %s tried to process video that %s is impossible (%s)",
                        video_or_playlist_for_processing.user_id,
                        processed_video.id,
                        processed_video.impossible_reason,
                    )

                    async with get_tg_bot() as bot:
                        await bot.send_message(
                            chat_id=video_or_playlist_for_processing.telegram_chat_id,
                            text=get_silence_only_error_text(processed_video),
                            reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                        )
                    return

                case _:
                    logger.error("Unknown status %s for processed video %s", processed_video.status, processed_video.id)
                    async with get_tg_bot() as bot:
                        await bot.send_message(
                            chat_id=video_or_playlist_for_processing.telegram_chat_id,
                            text="Ошибка скачивания",
                            reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                        )
                    return

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


async def get_video_for_processing(processed_video_id: int, waiter: Waiter) -> ProcessedVideo | None:
    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        processed_video: ProcessedVideo | None = await db_session.scalar(
            select(ProcessedVideo)
            .options(selectinload(ProcessedVideo.original_video))
            .options(selectinload(ProcessedVideo.audio_processing_profile))
            .options(selectinload(ProcessedVideo.unsilence_profile))
            .where(ProcessedVideo.id == processed_video_id)
        )
        if processed_video is None:
            logger.error("Processed video %s not found", processed_video_id)
            return None

        match processed_video.status:
            case ProcessedVideoStatus.TASK_CREATED:
                logger.info("Start processing %s", processed_video.id)
                processed_video.status = ProcessedVideoStatus.PROCESSING
                await processed_video.add_if_not_in_waiters(db_session, waiter)
                return processed_video

            case ProcessedVideoStatus.PROCESSING:
                logger.warning("Video %s processing in other task", processed_video.id)
                await processed_video.add_if_not_in_waiters(db_session, waiter)
                return None

            case ProcessedVideoStatus.PROCESSED:
                logger.warning("Video %s already processed", processed_video.id)
                await processed_video.add_if_not_in_waiters(db_session, waiter)
                if processed_video.telegram_file is not None:
                    async with get_tg_bot() as bot:
                        await processed_video.send(
                            bot=bot,
                            chat_id=waiter.telegram_chat_id,
                            reply_to_message_id=waiter.reply_to_message_id,
                        )
                else:
                    await processed_video.add_if_not_in_waiters(db_session, waiter)
                return None

            case ProcessedVideoStatus.IMPOSSIBLE:
                logger.warning(
                    "Process video that %s is impossible (%s)",
                    processed_video.id,
                    processed_video.impossible_reason,
                )
                await processed_video.add_if_not_in_waiters(db_session, waiter)

                async with get_tg_bot() as bot:
                    await processed_video.broadcast_text_for_waiters(bot, get_silence_only_error_text(processed_video))

                processed_video.waiters = []
                return None

            case _:
                logger.error("Unknown status %s for processed video %s", processed_video.status, processed_video.id)
                async with get_tg_bot() as bot:
                    await bot.send_message(
                        chat_id=waiter.telegram_chat_id,
                        text="Ошибка обработки",
                        reply_to_message_id=waiter.reply_to_message_id,
                    )
                return None


async def run_video_processing(processed_video: ProcessedVideo, waiter: Waiter) -> None:
    async with get_tg_bot() as bot:
        await processed_video.broadcast_text_for_waiters(
            bot=bot,
            text=f"Обрабатываю {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}",
            disable_notification=True,
            disable_web_page_preview=True,
        )

    processed_video = await run_video_pipeline(processed_video)
    async with get_autocommit_session() as db_session:
        db_session.add(
            VideoProcessingResourceUsage(
                user_id=waiter.user_id,
                processed_video_id=processed_video.id,
                real_processed=True,
            )
        )


async def two_step_broadcast_text(processed_video: ProcessedVideo, text: str) -> None:
    async with get_tg_bot() as bot:
        await processed_video.broadcast_text_for_waiters(bot, text)
        async with get_autocommit_session() as db_session:
            # noinspection PyTypeChecker
            actual_processed_video: ProcessedVideo = await db_session.scalar(
                select(ProcessedVideo).where(ProcessedVideo.id == processed_video.id)
            )
            if actual_processed_video is None:
                return
            waiters = [waiter for waiter in actual_processed_video.waiters if waiter not in processed_video.waiters]
            actual_processed_video.waiters = []

        if len(waiters) == 0:
            return

        processed_video.waiters = waiters
        await processed_video.broadcast_text_for_waiters(bot, text)


async def mark_processing_impossible(processed_video: ProcessedVideo, exc: ProcessingImpossibleError) -> None:
    text_gen = get_silence_only_error_text if isinstance(exc, SilenceOnlyError) else get_unable_to_process_text
    async with get_tg_bot() as bot:
        await processed_video.broadcast_text_for_waiters(bot, text_gen(processed_video))

    async with get_autocommit_session() as db_session:
        logger.info("Marking processed video %s as impossible, because of %s", processed_video.id, exc.text)
        # noinspection PyTypeChecker
        await db_session.execute(
            update(ProcessedVideo)
            .where(ProcessedVideo.id == processed_video.id)
            .values(status=ProcessedVideoStatus.IMPOSSIBLE, impossible_reason=exc.text)
        )

    await two_step_broadcast_text(processed_video, get_generic_error_text(processed_video))


async def cleanup_failed_processing(processed_video: ProcessedVideo) -> None:
    async with get_autocommit_session() as db_session:
        logger.info("Deleting not processed video %s", processed_video.id)
        # noinspection PyTypeChecker
        await db_session.execute(delete(ProcessedVideo).where(ProcessedVideo.id == processed_video.id))

    await two_step_broadcast_text(processed_video, get_generic_error_text(processed_video))


async def process_video(processed_video_id: int, waiter_dict: dict[str, Any]) -> None:
    """
    Обрабатывает видео, согласно выбранным профилям

    При вызове этой функции должно гарантироваться гарантируется, что:
    1) Видео скачано
    2) Функция вызывается в первый раз для данного видео и профиля обработки, если статус TASK_CREATED
    """

    waiter = Waiter.model_validate(waiter_dict)

    processed_video = await get_video_for_processing(processed_video_id, waiter)

    if processed_video is None:
        return

    try:
        await run_video_processing(processed_video, waiter)

    except ProcessingImpossibleError as exc:
        logger.error("Impossible to process video %s", processed_video)
        await mark_processing_impossible(processed_video, exc)

    except Exception as exc:
        logger.exception("Failed to process video %s: %s", processed_video.id, exc, exc_info=exc)
        await cleanup_failed_processing(processed_video)

    from ..tasks import upload_video_task

    upload_video_task.delay(processed_video.id)
