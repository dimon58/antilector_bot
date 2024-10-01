from typing import Any

from run_celery import app


@app.task
def process_video_or_playlist(video_or_playlist_for_processing: dict[str, Any]):
    # TODO: начало обработки здесь
    ...
