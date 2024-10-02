from aiogram import Bot

from configs import TELEGRAM_BOT_TOKEN
from .download_file import get_downloaded_videos
from .schema import VideoOrPlaylistForProcessing


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

    db_videos = await get_downloaded_videos(bot, video_or_playlist_for_processing)

    # TODO: Добавить retry
    # TODO: отправить в очередь на обработку. В идеале сделать в виде генератора.
    # TODO: Добавить обработку аварийно завершившихся скачиваний

    await bot.session.close()
