import logging

from aiogram import Bot
from sqlalchemy import select

from configs import TELEGRAM_BOT_TOKEN
from djgram.db.base import get_autocommit_session
from utils.get_bot import get_tg_bot
from .download_file import get_downloaded_videos
from .models import ProcessedVideo, AudioProcessingProfile, Video, Waiter
from .processing_file import run_video_pipeline, handle_processed_video
from .schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


async def process_video_or_playlist(video_or_playlist_for_processing: VideoOrPlaylistForProcessing):
    bot = Bot(TELEGRAM_BOT_TOKEN)

    start_text = "Начинаю обработку"

    if video_or_playlist_for_processing.is_playlist:
        start_text = f"{start_text}. Видео из плейлиста будут отправлены по мере готовности."

    await bot.send_message(
        text=start_text,
        chat_id=video_or_playlist_for_processing.telegram_chat_id,
        reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
    )

    from .tasks import process_video_task

    async for db_video in get_downloaded_videos(bot, video_or_playlist_for_processing):
        logger.info(
            "Send video %s (audio profile %s) to processing",
            db_video,
            video_or_playlist_for_processing.audio_processing_profile_id,
        )
        process_video_task.delay(db_video.id, video_or_playlist_for_processing.model_dump(mode="json"))

    # TODO: Добавить retry
    # TODO: Добавить обработку аварийно завершившихся скачиваний

    await bot.session.close()


async def process_video(db_video_id: str, video_or_playlist_for_processing: VideoOrPlaylistForProcessing) -> None:
    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        stmt = (
            select(ProcessedVideo)
            .with_for_update()
            .where(
                ProcessedVideo.original_video_id == db_video_id,
                ProcessedVideo.audio_processing_profile_id
                == video_or_playlist_for_processing.audio_processing_profile_id,
            )
        )
        processed_video: ProcessedVideo | None = await db_session.scalar(stmt)
        if processed_video is not None:
            # Обрабатывается в другой задаче
            await handle_processed_video(db_video_id, processed_video, video_or_playlist_for_processing)
            return

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
        db_video: Video | None = await db_session.scalar(select(Video).where(Video.id == db_video_id))
        if db_video is None:
            msg = "Video %s not found in database" % db_video_id
            logger.error(msg)
            raise ValueError(msg)

        processed_video = ProcessedVideo(
            original_video_id=db_video_id,
            audio_processing_profile=audio_processing_profile,
            waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        )
        db_session.add(processed_video)

    async with get_tg_bot() as bot:
        await bot.send_message(
            text="Скачиваю",
            chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
            disable_web_page_preview=True,
            disable_notification=True,
        )
    processed_video = await run_video_pipeline(audio_processing_profile, db_video, processed_video)

    logger.info("Broadcasting video")
    async with get_tg_bot() as bot:
        await processed_video.broadcast_for_waiters(bot)
