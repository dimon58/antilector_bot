import logging
import tempfile
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlalchemy_file import File

from configs import USE_NVENC, FORCE_VIDEO_CODEC, FORCE_AUDIO_CODEC, PROCESSED_EXT, USE_NISQA, TORCH_DEVICE
from libs.nisqa.model import NisqaModel
from tools.video_processing.pipeline import VideoPipeline
from utils.get_bot import get_tg_bot
from utils.video.measure import ffprobe_extract_meta
from .misc import execute_file_update_statement
from .models import ProcessedVideo, ProcessedVideoStatus
from .schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


async def handle_processed_video(
    db_video_id: str,
    processed_video: ProcessedVideo,
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing,
) -> bool:
    if processed_video.file is None:
        logger.info(
            "Video %s (audio profile %s, unsilence profile %s) processing in other task. Appending waiter id.",
            db_video_id,
            video_or_playlist_for_processing.audio_processing_profile_id,
            video_or_playlist_for_processing.unsilence_profile_id,
        )
        processed_video.add_if_not_in_waiters_from_task(video_or_playlist_for_processing)
        return False

    # Уже обработано
    async with get_tg_bot() as bot:
        logger.info(
            "Sending processing video %s (audio profile %s, unsilence profile %s)",
            db_video_id,
            video_or_playlist_for_processing.audio_processing_profile_id,
            video_or_playlist_for_processing.unsilence_profile_id,
        )
        await processed_video.send(
            bot=bot,
            chat_id=video_or_playlist_for_processing.telegram_chat_id,
            reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
        )

    return True


async def run_video_pipeline(processed_video: ProcessedVideo) -> ProcessedVideo:
    logger.info(
        "Start processing video %s (audio profile %s, unsilence profile %s). Result will be in processed video %s",
        processed_video.original_video_id,
        processed_video.audio_processing_profile_id,
        processed_video.unsilence_profile_id,
        processed_video.id,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        logger.info("Downloading video %s from storage to temporary directory", processed_video.original_video_id)
        file = processed_video.original_video.file.file
        input_file = temp_dir / file.filename
        with open(input_file, "wb") as f:
            for chunk in file.object.as_stream():
                f.write(chunk)

        logger.info("Start processing")
        video_pipeline = VideoPipeline(
            audio_pipeline=processed_video.audio_processing_profile.audio_pipeline,
            unsilence_action=processed_video.unsilence_profile.unsilence_action,
            use_nvenc=USE_NVENC,
            force_video_codec=FORCE_VIDEO_CODEC,
            force_audio_codec=FORCE_AUDIO_CODEC,
        )
        if USE_NISQA:
            logger.info("Initializing nisqa model")
            nisqa_model = NisqaModel(TORCH_DEVICE, warmup=True)
        else:
            nisqa_model = None
        output_file = temp_dir / f"processed{PROCESSED_EXT}"
        processing_temp_dir = temp_dir / "processing"
        processing_temp_dir.mkdir(exist_ok=True)

        processing_stats = video_pipeline.run(
            input_file=input_file,
            output_file=output_file,
            tempdir=processing_temp_dir,
            nisqa_model=nisqa_model,
        )
        meta = ffprobe_extract_meta(output_file)

        logger.info("Uploading processed video to storage")
        file = File(content_path=output_file.as_posix())
        file.save_to_storage(ProcessedVideo.file.type.upload_storage)

    # noinspection PyTypeChecker
    stmt = (
        update(ProcessedVideo)
        .where(ProcessedVideo.id == processed_video.id)
        .values(
            file=file,
            processing_stats=processing_stats,
            meta=meta,
            status=ProcessedVideoStatus.PROCESSED,
            audio_pipeline_json=processed_video.audio_processing_profile.audio_pipeline,
            unsilence_action_json=processed_video.unsilence_profile.unsilence_action,
        )
        .returning(ProcessedVideo)
        .options(selectinload(ProcessedVideo.original_video))
    )

    return await execute_file_update_statement(file, stmt)
