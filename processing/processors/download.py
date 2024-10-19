import logging
from collections.abc import Callable, Awaitable
from dataclasses import dataclass

from configs import LOG_EACH_VIDEO_DOWNLOAD
from processing.models import Video
from processing.schema import VideoOrPlaylistForProcessing
from utils.get_bot import get_tg_bot
from ..download_file import get_downloaded_videos

logger = logging.getLogger(__name__)


@dataclass
class VideoDownloadEvent:
    video_or_playlist_for_processing: VideoOrPlaylistForProcessing
    downloaded_here: bool
    db_video: Video


class DownloadObserver:
    def __init__(self):
        self.subscribers: list[tuple[Callable[[VideoDownloadEvent], Awaitable[None]], int]] = []

    def subscribe(self, *, retries: int):
        def inner_appender(callback: Callable[[VideoDownloadEvent], Awaitable[None]]):
            self.subscribers.append((callback, retries))

        return inner_appender

    async def publish(self, event: VideoDownloadEvent) -> None:
        for callback, retries in self.subscribers:
            for attempt in range(1, retries + 1):
                try:
                    logger.debug("Attempt %s/%s: calling %s", attempt, retries, callback.__name__)
                    await callback(event)
                except Exception as exc:
                    logger.exception(
                        "Attempt %s/%s: failed to call %s",
                        attempt,
                        retries,
                        callback.__name__,
                        exc_info=exc,
                    )
                else:
                    break


download_observer = DownloadObserver()


async def process_video_or_playlist(video_or_playlist_for_processing: VideoOrPlaylistForProcessing):
    """
    Обрабатывает видео или плейлист

    Если уже обрабатывает, то отправляет готовое

    Если скачано, то создаёт задачи на обработку

    Если не скачано, то скачивает и создаёт задачи на обработку
    """

    if LOG_EACH_VIDEO_DOWNLOAD:
        async with get_tg_bot() as bot:
            start_text = "Начинаю обработку"

            if video_or_playlist_for_processing.download_data.is_playlist:
                start_text = f"{start_text}. Видео из плейлиста будут отправлены по мере готовности."

            await bot.send_message(
                text=start_text,
                chat_id=video_or_playlist_for_processing.telegram_chat_id,
                reply_to_message_id=video_or_playlist_for_processing.reply_to_message_id,
                disable_notification=True,
                disable_web_page_preview=True,
            )

    async with get_tg_bot() as bot:
        async for db_video_repr in get_downloaded_videos(bot, video_or_playlist_for_processing):

            # Проблемы с загрузкой, логируется в get_downloaded_videos
            if db_video_repr is None:
                continue

            downloaded_here, db_video = db_video_repr

            await download_observer.publish(
                VideoDownloadEvent(
                    video_or_playlist_for_processing=video_or_playlist_for_processing,
                    downloaded_here=downloaded_here,
                    db_video=db_video,
                )
            )
