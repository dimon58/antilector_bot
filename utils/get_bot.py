from contextlib import AbstractAsyncContextManager, asynccontextmanager

from aiogram import Bot

from configs import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_LOCAL,
    TELEGRAM_LOCAL_SERVER_FILES_URL,
    TELEGRAM_LOCAL_SERVER_URL,
)
from djgram.contrib.local_server.local_bot import get_local_bot


@asynccontextmanager
async def get_tg_bot() -> AbstractAsyncContextManager[Bot]:
    bot = get_local_bot(
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_local=TELEGRAM_LOCAL,
        telegram_local_server_url=TELEGRAM_LOCAL_SERVER_URL,
        telegram_local_server_files_url=TELEGRAM_LOCAL_SERVER_FILES_URL,
    )
    try:
        yield bot
    finally:
        await bot.session.close()
