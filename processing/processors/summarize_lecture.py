import logging
import tempfile
import time
from pathlib import Path

from aiogram.types import BufferedInputFile
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy_file import File

from djgram.contrib.communication.broadcast import broadcast
from djgram.db.base import get_autocommit_session
from processing.models import LectureSummary, Video, Waiter
from processing.schema import VideoOrPlaylistForProcessing
from tools.audio_processing.actions.ffmpeg_actions import ExtractAudioFromVideo
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link
from utils.get_bot import get_tg_bot

from ..misc import download_file_from_s3  # noqa: TID252
from ..models.lecture_summary import LlmStats, SummarizationStats  # noqa: TID252
from ..summary import transcribe, transcription_to_summary  # noqa: TID252
from ..summary.lecture_to_summary import extract_latex_from_llm_answer, markdown_parser, render_latex  # noqa: TID252
from .download import VideoDownloadEvent, download_observer

logger = logging.getLogger(__name__)


@download_observer.subscribe(retries=1)  # больше 1 раза дорого
async def summarize_lecture_subscriber(video_download_event: VideoDownloadEvent) -> None:
    from ..tasks import summarize_lecture_task  # noqa: TID252

    if not video_download_event.video_or_playlist_for_processing.for_summary:
        logger.debug("Task not for this processor")
        return

    summarize_lecture_task.delay(
        video_download_event.db_video.id,
        video_download_event.video_or_playlist_for_processing.model_dump(mode="json"),
    )


async def summarize_lecture(
    downloaded_video_id: str,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> None:
    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        lecture_summary: LectureSummary | None = await db_session.scalar(
            select(LectureSummary)
            .options(selectinload(LectureSummary.original_video))
            .with_for_update()
            .where(LectureSummary.original_video_id == downloaded_video_id)
            .where(~LectureSummary.is_corrupted),
        )

        if lecture_summary is not None:
            logger.info("Lecture summary for video %s already exists", downloaded_video_id)
            async with get_tg_bot() as bot:
                await lecture_summary.send_or_add_waiter(
                    waiter=Waiter.from_task(video_or_playlist_for_processing),
                    bot=bot,
                    db_session=db_session,
                )
                return

        logger.info("Creating new lecture summary for video %s", downloaded_video_id)
        lecture_summary = LectureSummary(
            original_video_id=downloaded_video_id,
            waiters=[Waiter.from_task(video_or_playlist_for_processing)],
        )
        db_session.add(lecture_summary)

        # noinspection PyTypeChecker
        video: Video | None = await db_session.scalar(select(Video).where(Video.id == downloaded_video_id))
        if video is None:
            raise ValueError(f"Video {downloaded_video_id} does not exist")

    try:
        await process_summarization(downloaded_video_id, lecture_summary, video)
    except Exception as exc:
        logger.exception("Failed to process summarize %s: %s", downloaded_video_id, exc, exc_info=exc)  # noqa: TRY401

        async with get_autocommit_session() as db_session:
            waiters = await lecture_summary.pop_waiters(db_session)

        if len(waiters) == 0:
            return

        async with get_tg_bot() as bot:
            lecture_summary.waiters = waiters
            await lecture_summary.broadcast_text_for_waiters(
                bot=bot,
                text=f"Ошибка обработки {yt_dlp_get_html_link(video.yt_dlp_info)}",
            )


async def process_summarization(  # noqa: PLR0915
    downloaded_video_id: str,
    lecture_summary: LectureSummary,
    video: Video,
) -> None:
    global_start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_dir = Path(tmp_dir)
        logger.info("Downloading video %s to temporary folder fot summarization", downloaded_video_id)
        s3_file = video.file.file
        video_file = temp_dir / s3_file.filename
        download_file_from_s3(video.file, video_file)
        wav_file = temp_dir / f"{s3_file.filename}.wav"

        ExtractAudioFromVideo(to_mono=True, output_config={"ar": 16000}).run(video_file, wav_file)

        logger.info("Transcribing")
        transcription, transcription_stats = transcribe(wav_file)

    logger.info("Asking llm to generate summary")
    title = video.yt_dlp_info.get("title", "")
    description = video.yt_dlp_info.get("description", "")
    llm_start = time.perf_counter()
    llm_summary = transcription_to_summary(
        title=title,
        description=description,
        transcription=transcription,
    )
    llm_end = time.perf_counter()
    llm_stats = LlmStats(
        processing_time=llm_end - llm_start,
        open_ai_response=llm_summary,
    )
    llm_answer_with_latex = llm_summary.choices[0].message.content

    compile_start = time.perf_counter()
    logger.info("Compiling latex to pdf")
    latex = extract_latex_from_llm_answer(markdown_parser, llm_answer_with_latex)
    try:
        pdf = render_latex(latex)
    except Exception as exc:
        compile_end = time.perf_counter()
        logger.exception("Failed render pdf: %s", exc, exc_info=exc)  # noqa: TRY401
        pdf_file = None
    else:
        compile_end = time.perf_counter()
        pdf_file = File(content=pdf, filename="summary.pdf")
        logger.info("Uploading file to storage")
        pdf_file.save_to_storage(LectureSummary.pdf.type.upload_storage)
    global_end = time.perf_counter()

    async with get_autocommit_session() as db_session:
        # noinspection PyTypeChecker
        stmt = (
            update(LectureSummary)
            .where(LectureSummary.id == lecture_summary.id)
            .values(
                transcription_text=transcription,
                latex=latex,
                pdf=pdf_file,
                stats=SummarizationStats(
                    processing_time=global_end - global_start,
                    transcription_stats=transcription_stats,
                    llm_stats=llm_stats,
                    compile_time=compile_end - compile_start,
                ),
            )
            .returning(LectureSummary)
            .options(selectinload(LectureSummary.original_video))
        )
        lecture_summary: LectureSummary = await db_session.scalar(stmt)
        waiters = await lecture_summary.pop_waiters(db_session)

    lecture_summary.waiters = waiters
    async with get_tg_bot() as bot:
        if not lecture_summary.is_corrupted:
            await lecture_summary.broadcast_two_step(bot)
            async with get_autocommit_session() as db_session:
                # noinspection PyTypeChecker
                await db_session.execute(
                    update(LectureSummary)
                    .where(LectureSummary.id == lecture_summary.id)
                    .values(telegram_file=lecture_summary.telegram_file),
                )
        elif lecture_summary.latex is not None:
            chat_ids = []
            per_chat_kwargs = []

            for waiter in lecture_summary.waiters:
                chat_ids.append(waiter.telegram_chat_id)
                per_chat_kwargs.append({"reply_to_message_id": waiter.reply_to_message_id})

            async def send_method(chat_id: int | str, reply_to_message_id: int | None = None) -> None:
                await bot.send_document(
                    document=BufferedInputFile(
                        file=latex.encode("utf-8"),
                        filename="source.tex",
                    ),
                    caption="Не удалось сгенерировать pdf, поэтому отправил вам исходный код latex",
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                )

            await broadcast(
                send_method=send_method,
                chat_ids=chat_ids,
                count=len(chat_ids),
                per_chat_kwargs=per_chat_kwargs,
            )
        else:
            await lecture_summary.broadcast_text_for_waiters(
                bot=bot,
                text=f"Ошибка обработки {yt_dlp_get_html_link(video.yt_dlp_info)}",
            )
