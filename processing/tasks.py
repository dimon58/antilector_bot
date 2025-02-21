import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from configs import VIDEO_DOWNLOAD_QUEUE, VIDEO_PROCESS_QUEUE, VIDEO_UPLOAD_QUEUE
from djgram.utils.async_tools import run_async_in_sync
from processing.celery_app import app

from .schema import VideoOrPlaylistForProcessing

sys.path.append(str(Path(__file__).resolve().parent.parent))

if TYPE_CHECKING:
    from . import processors
else:
    processors = None


def ensure_processors() -> None:
    if processors is None:
        # lazy import
        from . import processors as _processors

        globals()["processors"] = _processors


@app.task(queue=VIDEO_DOWNLOAD_QUEUE)
def process_video_or_playlist(video_or_playlist_for_processing: dict[str, Any]) -> None:
    # TODO: начало обработки здесь

    ensure_processors()

    run_async_in_sync(
        processors.process_video_or_playlist(
            VideoOrPlaylistForProcessing.model_validate(video_or_playlist_for_processing),
        ),
    )


@app.task(queue=VIDEO_PROCESS_QUEUE)
def process_video_task(process_video_id: int, waiter_dict: dict[str, Any]) -> None:
    ensure_processors()

    run_async_in_sync(processors.process_video(process_video_id, waiter_dict))


@app.task(queue=VIDEO_UPLOAD_QUEUE)
def upload_video_task(processed_video_id: int) -> None:
    ensure_processors()

    run_async_in_sync(processors.upload_to_telegram(processed_video_id))


# @app.task(queue=LECTURES_SUMMARIZE_QUEUE)
@app.task(queue=VIDEO_PROCESS_QUEUE)
def summarize_lecture_task(downloaded_video_id: str, video_or_playlist_for_processing: dict[str, Any]) -> None:
    ensure_processors()

    run_async_in_sync(
        processors.summarize_lecture(
            downloaded_video_id,
            VideoOrPlaylistForProcessing.model_validate(video_or_playlist_for_processing),
        ),
    )
