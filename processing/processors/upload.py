import logging

from sqlalchemy import select
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
            .where(ProcessedVideo.id == processed_video_id),
        )
        if processed_video is None:
            logger.error("Processed video %s not found", processed_video_id)
            return

    async with get_tg_bot() as bot:
        await processed_video.broadcast_for_waiters(bot)
