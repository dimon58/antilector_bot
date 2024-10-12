import logging

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from configs import TELEGRAM_BOT_TOKEN
from djgram.db.base import get_autocommit_session
from utils.get_bot import get_tg_bot
from .error_texts import get_silence_only_error_text
from ..download_file import get_downloaded_videos
from ..models import ProcessedVideo, AudioProcessingProfile, UnsilenceProfile, Video, Waiter, ProcessedVideoStatus
from ..schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


async def process_video_or_playlist(video_or_playlist_for_processing: VideoOrPlaylistForProcessing):
    """
    Обрабатывает видео или плейлист

    Если уже обрабатывает, то отправляет готовое

    Если скачано, то создаёт задачи на обработку

    Если не скачано, то скачивает и создаёт задачи на обработку
    """
    bot = Bot(TELEGRAM_BOT_TOKEN)

    start_text = "Начинаю обработку"

    if video_or_playlist_for_processing.is_playlist:
        start_text = f"{start_text}. Видео из плейлиста будут отправлены по мере готовности."

    await bot.send_message(
        text=start_text,
        chat_id=video_or_playlist_for_processing.telegram_chat_id,
        reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        disable_notification=True,
        disable_web_page_preview=True,
    )

    from ..tasks import process_video_task

    async for db_video_repr in get_downloaded_videos(bot, video_or_playlist_for_processing):

        # Проблемы с загрузкой, логируется в get_downloaded_videos
        if db_video_repr is None:
            continue

        downloaded_here, db_video = db_video_repr

        # Реально скачивается в другой задаче
        if not downloaded_here:
            suffix = "ing" if db_video.file is None else "ed"
            logger.info("Video %s download%s in other task", db_video.id, suffix)
            processed_video = await create_processed_video_initial(
                db_video.id,
                video_or_playlist_for_processing,
                select_with_original_video=True,
            )

            match processed_video.status:
                case ProcessedVideoStatus.TASK_CREATED:
                    # Создаём таску для работы. Если она будет дублироваться, то отсеиваем её в process_video_task
                    logger.warning("Video %s created, but not processed", processed_video.id)

                case ProcessedVideoStatus.PROCESSING:
                    # Не обработано, значит пользователь в очереди на рассылку
                    if processed_video.status != ProcessedVideoStatus.PROCESSED:
                        continue

                case ProcessedVideoStatus.PROCESSED:
                    # Отправляем обработанное видео
                    async with get_tg_bot() as bot:
                        await processed_video.broadcast_for_waiters(bot)
                    continue

                case ProcessedVideoStatus.IMPOSSIBLE:
                    logger.warning(
                        "User %s tried to process video that %s is impossible (%s)",
                        video_or_playlist_for_processing.user_id,
                        processed_video.id,
                        processed_video.impossible_reason,
                    )

                    async with get_tg_bot() as bot:
                        await processed_video.broadcast_text_for_waiters(
                            bot,
                            get_silence_only_error_text(processed_video),
                        )
                    continue

                case _:
                    logger.error("Unknown status %s for processed video %s", processed_video.status, processed_video.id)
                    continue

        # Реально скачивается в этой задаче -> создаём задачу для обработки здесь
        logger.info(
            "Send video %s (audio profile %s, unsilence profile %s) to processing",
            db_video,
            video_or_playlist_for_processing.audio_processing_profile_id,
            video_or_playlist_for_processing.unsilence_profile_id,
        )
        processed_video = await create_processed_video_initial(db_video.id, video_or_playlist_for_processing)
        process_video_task.delay(processed_video.id)

    # TODO: Добавить retry

    await bot.session.close()


async def ensure_video_and_profiles_exist(
    db_session: AsyncSession,
    db_video_id: str,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
):
    # noinspection PyTypeChecker
    stmt = select(AudioProcessingProfile).where(
        AudioProcessingProfile.id == video_or_playlist_for_processing.audio_processing_profile_id
    )
    audio_processing_profile: AudioProcessingProfile | None = await db_session.scalar(stmt)
    if audio_processing_profile is None:
        msg = "Audio processing profile %s not found" % video_or_playlist_for_processing.audio_processing_profile_id
        logger.error(msg)
        raise ValueError(msg)

    # noinspection PyTypeChecker
    stmt = select(UnsilenceProfile).where(UnsilenceProfile.id == video_or_playlist_for_processing.unsilence_profile_id)
    unsilence_profile: UnsilenceProfile | None = await db_session.scalar(stmt)
    if unsilence_profile is None:
        msg = "Unsilence profile %s not found" % video_or_playlist_for_processing.unsilence_profile_id
        logger.error(msg)
        raise ValueError(msg)

    # noinspection PyTypeChecker
    stmt = select(Video).where(Video.id == db_video_id)
    db_video: Video | None = await db_session.scalar(stmt)
    if db_video is None:
        msg = "Video %s not found in database" % db_video_id
        logger.error(msg)
        raise ValueError(msg)


async def create_processed_video_initial(
    db_video_id: str,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
    *,
    select_with_original_video: bool = False,
) -> ProcessedVideo:
    async with get_autocommit_session() as db_session:
        # Если обработанное видео уже существует, то
        # noinspection PyTypeChecker
        stmt = (
            select(ProcessedVideo)
            .with_for_update()
            .where(
                ProcessedVideo.original_video_id == db_video_id,
                ProcessedVideo.audio_processing_profile_id
                == video_or_playlist_for_processing.audio_processing_profile_id,
                ProcessedVideo.unsilence_profile_id == video_or_playlist_for_processing.unsilence_profile_id,
            )
        )
        if select_with_original_video:
            stmt = stmt.options(selectinload(ProcessedVideo.original_video))
        processed_video: ProcessedVideo | None = await db_session.scalar(stmt)

        if processed_video is not None:
            if processed_video.status != ProcessedVideoStatus.PROCESSED:
                processed_video.add_if_not_in_waiters_from_task(video_or_playlist_for_processing)
            return processed_video

        await ensure_video_and_profiles_exist(
            db_session=db_session,
            db_video_id=db_video_id,
            video_or_playlist_for_processing=video_or_playlist_for_processing,
        )

        processed_video = ProcessedVideo(
            original_video_id=db_video_id,
            audio_processing_profile_id=video_or_playlist_for_processing.audio_processing_profile_id,
            unsilence_profile_id=video_or_playlist_for_processing.unsilence_profile_id,
            waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        )
        db_session.add(processed_video)

    return processed_video
