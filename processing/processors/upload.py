import logging
from typing import Any

from sqlalchemy import update, select
from sqlalchemy.orm import selectinload

from djgram.db.base import get_autocommit_session
from processing.models import ProcessedVideo, Waiter
from utils.get_bot import get_tg_bot

logger = logging.getLogger(__name__)


async def upload_to_telegram(processed_video_id: int, waiter_dict: dict[str, Any] | None = None) -> None:

    waiter = Waiter.model_validate(waiter_dict) if waiter_dict is not None else None

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

    has_tg_file = processed_video.telegram_file is not None

    logger.info("Broadcasting processed video")
    async with get_tg_bot() as bot:
        if waiter is None:
            await processed_video.broadcast_for_waiters(bot)
        else:
            await processed_video.send(
                bot=bot,
                chat_id=waiter.telegram_chat_id,
                reply_to_message_id=waiter.reply_to_message_id,
            )

    if has_tg_file:
        return

    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        await db_session.execute(
            update(ProcessedVideo)
            .where(ProcessedVideo.id == processed_video.id)
            .values(telegram_file=processed_video.telegram_file)
        )
