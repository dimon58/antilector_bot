import sys
from pathlib import Path
from typing import Any

from djgram.utils.async_tools import run_async_in_sync
from run_celery import app
from .schema import VideoOrPlaylistForProcessing

sys.path.append(str(Path(__file__).resolve().parent.parent))
processors = None


@app.task
def process_video_or_playlist(video_or_playlist_for_processing: dict[str, Any]):
    # TODO: начало обработки здесь

    if processors is None:
        # lazy import
        from . import processors as _processors

        globals()["processors"] = _processors

    run_async_in_sync(
        processors.process_video_or_playlist(
            VideoOrPlaylistForProcessing.model_validate(video_or_playlist_for_processing)
        )
    )
