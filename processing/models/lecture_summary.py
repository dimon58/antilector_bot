import logging
from operator import or_
from typing import Any

import aiogram
import pydantic
from aiogram import Bot
from aiogram.enums import ChatAction, ParseMode
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from openai.types.chat import ChatCompletion
from sqlalchemy import ForeignKey, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_file import File, FileField

from configs import LECTURES_SUMMARY_STORAGE, PDF_UPLOAD_TIMEOUT
from djgram.db.models import TimeTrackableBaseModel
from djgram.db.pydantic_field import ImmutablePydanticField
from djgram.utils.input_file_ext import S3FileInput
from djgram.utils.upload import LoggingInputFile
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link

from .common import HasTelegramFileAndOriginalVideo, Waiter
from .download import Video

logger = logging.getLogger(__name__)


class TranscriptionStats(pydantic.BaseModel):
    processing_time: float

    whisper_model_size: str
    whisper_compute_type: str

    transcription_info: dict[str, Any]  # TranscriptionInfo


class LlmStats(pydantic.BaseModel):
    processing_time: float

    open_ai_response: ChatCompletion


class SummarizationStats(pydantic.BaseModel):
    processing_time: float

    transcription_stats: TranscriptionStats
    llm_stats: LlmStats
    compile_time: float


class LectureSummary(HasTelegramFileAndOriginalVideo, TimeTrackableBaseModel):
    original_video_id: Mapped[str] = mapped_column(ForeignKey(Video.id), index=True)
    original_video: Mapped[Video] = relationship(Video)

    transcription_text: Mapped[str | None]
    stats: Mapped[SummarizationStats] = mapped_column(
        ImmutablePydanticField(SummarizationStats, should_frozen=False),
        doc="Статистика обработки",
    )

    latex: Mapped[str | None]
    pdf: Mapped[File | None] = mapped_column(
        FileField(upload_storage=LECTURES_SUMMARY_STORAGE),
        doc="Скомпилированный конспект в формате latex",
    )
    telegram_file: Mapped[aiogram.types.Document | None] = mapped_column(
        ImmutablePydanticField(aiogram.types.Document),
        doc="Отправленный файл в телеграм",
    )

    @hybrid_property
    def is_corrupted(self) -> bool:
        return self.transcription_text is not None and self.pdf is None

    @is_corrupted.inplace.expression
    @classmethod
    def _is_corrupted_expression(cls):  # noqa: ANN206
        return and_(
            cls.transcription_text.is_not(None),
            or_(
                cls.pdf.is_(None),
                func.json_typeof(cls.pdf) == "null",
            ),
        )

    async def send(self, bot: Bot, chat_id: int | str, reply_to_message_id: int | None = None) -> Message:
        async with ChatActionSender(
            bot=bot,
            chat_id=chat_id,
            action=ChatAction.UPLOAD_DOCUMENT,
        ):
            if self.telegram_file is not None:
                logger.info("Sending cached in telegram pdf %s", self.id)
                document = self.telegram_file.file_id
            else:
                logger.info("Uploading pdf %s to telegram", self.id)
                document = LoggingInputFile(
                    S3FileInput(
                        obj=self.pdf.file.object,
                        filename="summary.pdf",
                    ),
                )

            message = await bot.send_document(
                document=document,
                caption=f"Конспект {yt_dlp_get_html_link(self.original_video.yt_dlp_info)}",
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                parse_mode=ParseMode.HTML,
                request_timeout=PDF_UPLOAD_TIMEOUT,
            )

            if self.telegram_file is None:
                self.telegram_file = message.document

            return message

    async def send_or_add_waiter(self, waiter: Waiter, bot: Bot, db_session: AsyncSession) -> bool:
        if self.telegram_file is not None:
            await self.send(
                bot=bot,
                chat_id=waiter.telegram_chat_id,
                reply_to_message_id=waiter.reply_to_message_id,
            )
            return True

        await self.add_if_not_in_waiters(db_session, waiter)

        return False
