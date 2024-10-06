from contextlib import AbstractAsyncContextManager, asynccontextmanager

from aiogram import Bot

from configs import TELEGRAM_BOT_TOKEN


@asynccontextmanager
async def get_tg_bot() -> AbstractAsyncContextManager[Bot]:
    bot = Bot(TELEGRAM_BOT_TOKEN)
    yield bot
    await bot.session.close()
