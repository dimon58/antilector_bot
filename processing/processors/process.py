import logging

from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from djgram.db.base import get_autocommit_session
from tools.audio_processing.actions.abstract import ProcessingImpossibleError
from tools.video_processing.actions.unsilence_actions import SilenceOnlyError
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link
from utils.get_bot import get_tg_bot
from .error_texts import get_silence_only_error_text, get_generic_error_text, get_unable_to_process_text
from ..models import ProcessedVideo, ProcessedVideoStatus
from ..processing_file import run_video_pipeline

logger = logging.getLogger(__name__)


async def get_video_for_processing(processed_video_id: int) -> ProcessedVideo | None:
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
                return processed_video

            case ProcessedVideoStatus.PROCESSING:
                logger.warning("Video %s processing in other task", processed_video.id)
                return None

            case ProcessedVideoStatus.PROCESSED:
                logger.warning("Video %s already processed", processed_video.id)
                return None

            case ProcessedVideoStatus.IMPOSSIBLE:
                logger.warning(
                    "Process video that %s is impossible (%s)",
                    processed_video.id,
                    processed_video.impossible_reason,
                )

                async with get_tg_bot() as bot:
                    await processed_video.broadcast_text_for_waiters(bot, get_silence_only_error_text(processed_video))
                return None

            case _:
                logger.error("Unknown status %s for processed video %s", processed_video.status, processed_video.id)
                return None


async def run_video_processing(processed_video: ProcessedVideo) -> None:
    async with get_tg_bot() as bot:
        await processed_video.broadcast_text_for_waiters(
            bot=bot,
            text=f"Обрабатываю {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}",
            disable_notification=True,
        )

    processed_video = await run_video_pipeline(processed_video)

    logger.info("Broadcasting processed video")
    async with get_tg_bot() as bot:
        await processed_video.broadcast_for_waiters(bot)

    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        await db_session.execute(
            update(ProcessedVideo)
            .where(ProcessedVideo.id == processed_video.id)
            .values(telegram_file=processed_video.telegram_file)
        )


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


async def cleanup_failed_processing(processed_video: ProcessedVideo) -> None:
    async with get_autocommit_session() as db_session:
        logger.info("Deleting not processed video %s", processed_video.id)
        # noinspection PyTypeChecker
        await db_session.execute(delete(ProcessedVideo).where(ProcessedVideo.id == processed_video.id))

    async with get_tg_bot() as bot:
        await processed_video.broadcast_text_for_waiters(bot, get_generic_error_text(processed_video))


async def process_video(processed_video_id: int) -> None:
    """
    Обрабатывает видео, согласно выбранным профилям

    При вызове этой функции должно гарантироваться гарантируется, что:
    1) Видео скачано
    2) Функция вызывается в первый раз для данного видео и профиля обработки, если статус TASK_CREATED
    """

    processed_video = await get_video_for_processing(processed_video_id)

    try:
        await run_video_processing(processed_video)

    except ProcessingImpossibleError as exc:
        logger.error("Impossible to process video %s", processed_video)
        await mark_processing_impossible(processed_video, exc)

    except Exception as exc:
        logger.exception("Failed to process video %s: %s", processed_video.id, exc, exc_info=exc)
        await cleanup_failed_processing(processed_video)
