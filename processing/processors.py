import logging

from aiogram import Bot

from configs import TELEGRAM_BOT_TOKEN
from .download_file import get_downloaded_videos
from .schema import VideoOrPlaylistForProcessing

logger = logging.getLogger(__name__)


async def process_video_or_playlist(video_or_playlist_for_processing: VideoOrPlaylistForProcessing):
    bot = Bot(TELEGRAM_BOT_TOKEN)

    start_text = "Начинаю обработку"

    if video_or_playlist_for_processing.is_playlist:
        start_text = f"{start_text}. Видео из плейлиста будут отправлены по мере готовности."

    await bot.send_message(
        text=start_text,
        chat_id=video_or_playlist_for_processing.telegram_chat_id,
        reply_to_message_id=video_or_playlist_for_processing.telegram_message_id,
    )

    async for db_video in get_downloaded_videos(bot, video_or_playlist_for_processing):
        logger.info(
            "Send video %s (audio profile %s) to processing",
            db_video,
            video_or_playlist_for_processing.audio_processing_profile_id,
        )

    # TODO: Добавить retry
    # TODO: отправить в очередь на обработку. В идеале сделать в виде генератора.
    # TODO: Добавить обработку аварийно завершившихся скачиваний

    await bot.session.close()
