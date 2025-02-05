"""
Точка входа для запуска бота
"""

import logging.config

from aiogram import Dispatcher, Router
from aiogram.enums import UpdateType
from aiogram.filters import Command, CommandStart, ExceptionTypeFilter
from aiogram.fsm.storage.redis import (
    DefaultKeyBuilder,  # pyright: ignore [reportPrivateImportUsage]
    RedisStorage,
)
from aiogram.types import ErrorEvent, Message
from aiogram_dialog import DialogManager, StartMode, ShowMode
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
from redis.asyncio.client import Redis

from configs import (
    LOGGING_CONFIG,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_STORAGE_DB,
    REDIS_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_LOCAL,
    TELEGRAM_LOCAL_SERVER_FILES_URL,
    TELEGRAM_LOCAL_SERVER_URL,
)
from djgram.contrib.analytics.local_server import run_telegram_local_server_stats_collection_in_background
from djgram.contrib.local_server.local_bot import get_local_bot

# noinspection PyUnresolvedReferences
from djgram.db.models import BaseModel  # noqa: F401 нужно для корректной работы alembic
from djgram.setup_djgram import setup_djgram
from system_init import system_init
from tg_bot.apps.lectures import router as lectures_router
from tg_bot.apps.menu import router as menu_router
from tg_bot.apps.menu.dialogs import MenuStates
from tg_bot.apps.summary import router as summary_router

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)
main_router = Router()


@main_router.message(CommandStart())
async def start_handler(message: Message, dialog_manager: DialogManager) -> None:  # noqa: ARG001
    """
    Обработчик команды /start
    """

    await dialog_manager.start(MenuStates.main_menu, mode=StartMode.RESET_STACK)


@main_router.message(Command("help"))
async def help_handler(message: Message) -> None:
    """
    Обработчик команды /help
    """

    await message.answer("/menu - открыть меню")


@main_router.message()
async def no_state_handler(message: Message, dialog_manager: DialogManager) -> None:  # noqa: ARG001
    """
    Запуск главного меню
    """

    await dialog_manager.start(MenuStates.main_menu, mode=StartMode.RESET_STACK)


def setup_routers(dp: Dispatcher) -> None:
    """
    Установка роутеров
    """
    dp.include_router(lectures_router)
    dp.include_router(summary_router)
    dp.include_router(menu_router)
    dp.include_router(main_router)

    logger.info("Routers setup")


async def on_unknown_intent(event: ErrorEvent, dialog_manager: DialogManager) -> None:  # noqa: D103
    logging.error("Error in dialog: %s", event.exception)
    await dialog_manager.start(MenuStates.main_menu, mode=StartMode.RESET_STACK)


async def on_unknown_state(event: ErrorEvent, dialog_manager: DialogManager) -> None:  # noqa: D103
    # Example of handling UnknownState Error and starting new dialog.
    logging.error("Error in dialog: %s", event.exception)
    await dialog_manager.start(MenuStates.main_menu, mode=StartMode.RESET_STACK)


async def main() -> None:
    """
    Точка входа в бота
    """

    system_init()

    redis_for_storage = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        username=REDIS_USER,
        password=REDIS_PASSWORD,
        db=REDIS_STORAGE_DB,
    )

    storage = RedisStorage(redis_for_storage, key_builder=DefaultKeyBuilder(with_destiny=True))

    dp = Dispatcher(storage=storage)
    dp.errors.register(on_unknown_intent, ExceptionTypeFilter(UnknownIntent))
    dp.errors.register(on_unknown_state, ExceptionTypeFilter(UnknownState))
    bot = get_local_bot(
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_local=TELEGRAM_LOCAL,
        telegram_local_server_url=TELEGRAM_LOCAL_SERVER_URL,
        telegram_local_server_files_url=TELEGRAM_LOCAL_SERVER_FILES_URL,
    )

    setup_djgram(dp, analytics=True)
    setup_routers(dp)

    await run_telegram_local_server_stats_collection_in_background()
    await dp.start_polling(bot, skip_updates=False, allowed_updates=list(UpdateType))
