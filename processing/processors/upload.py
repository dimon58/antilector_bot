import logging

from sqlalchemy import update, select
from sqlalchemy.orm import selectinload

from djgram.db.base import get_autocommit_session
from processing.models import ProcessedVideo
from utils.get_bot import get_tg_bot

logger = logging.getLogger(__name__)


async def upload_to_telegram(processed_video_id: int) -> None:
    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        processed_video: ProcessedVideo | None = await db_session.scalar(
            select(ProcessedVideo)
            .options(selectinload(ProcessedVideo.original_video))
            .where(ProcessedVideo.id == processed_video_id)
        )
        if processed_video is None:
            logger.error("Processed video %s not found", processed_video_id)
            return

    logger.info("Broadcasting processed video")
    async with get_tg_bot() as bot:
        await processed_video.broadcast_for_waiters(bot)

    old_waiters = set(processed_video.waiters)
    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        processed_video = await db_session.scalar(
            update(ProcessedVideo)
            .where(ProcessedVideo.id == processed_video.id)
            .values(telegram_file=processed_video.telegram_file)
            .returning(ProcessedVideo)
            .options(selectinload(ProcessedVideo.original_video))
        )
        waiters = processed_video.waiters
        await db_session.execute(
            update(ProcessedVideo).where(ProcessedVideo.id == processed_video.id).values(waiters=[])
        )

    waiters = [waiter for waiter in waiters if waiter not in old_waiters]

    if len(waiters) == 0:
        return

    logger.info("Broadcasting processed video for rest waiters")
    processed_video.waiters = waiters
    async with get_tg_bot() as bot:
        await processed_video.broadcast_for_waiters(bot)
