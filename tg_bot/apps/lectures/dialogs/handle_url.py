import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import yt_dlp
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram_dialog import DialogManager
from cashews import Cache
from yt_dlp.utils import YoutubeDLError

from djgram.utils.async_tools import run_async_wrapper
from djgram.utils.formating import seconds_to_human_readable
from tools.yt_dlp_downloader.misc import get_playlist_duration
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpContentType, YtDlpInfoDict, extract_info

from .states import LectureProcessingStates

if TYPE_CHECKING:
    from djgram.contrib.auth.models import User

URL_KEY = "url"

logger = logging.getLogger(__name__)

thread_executor = ThreadPoolExecutor()

cache = Cache()
cache.setup("mem://")
extract_info_async = cache(ttl=timedelta(minutes=5))(run_async_wrapper(extract_info, thread_executor))


def is_possible_thumbnail_url(thumbnail_url: str | None) -> bool:
    if thumbnail_url is None:
        return False

    return urlparse(thumbnail_url).path.endswith(".jpg")


def get_thumbnail_url_for_preview(info: YtDlpInfoDict) -> str | None:
    thumbnail_url = info.get("thumbnail")
    if is_possible_thumbnail_url(thumbnail_url):
        return thumbnail_url

    for thumbnail in reversed(info.get("thumbnails", [])):
        thumbnail_url = thumbnail.get("url")
        if is_possible_thumbnail_url(thumbnail_url):
            return thumbnail_url

    return None


async def send_preview(message: Message, msg: str, thumbnail_url: str, parse_mode: ParseMode | None = None) -> None:
    if thumbnail_url is not None:
        try:
            await message.reply_photo(thumbnail_url, msg, parse_mode=parse_mode)
        except TelegramBadRequest as exc:
            logger.warning("Failed to send thumbnail preview: %s", str(exc))
        else:
            return

    await message.reply(msg, parse_mode=parse_mode, disable_web_page_preview=True)


async def handle_unsupported_url(exc: YoutubeDLError, message: Message) -> None:
    logger.warning(exc.msg)
    await message.reply("Эта ссылка не поддерживается")


async def is_user_error(message: Message, exc: YoutubeDLError) -> bool:
    error_msg = exc.msg.lower()
    if "unsupported url" in error_msg:
        await handle_unsupported_url(exc, message)
        return True

    if "is not a valid url" in error_msg:
        logger.warning(exc.msg)
        await message.reply("Неправильная ссылка")
        return True

    if "[vk] access restricted" in error_msg:
        logger.warning(exc.msg)
        await message.reply(
            "Доступ запрещён. "
            "Возможно вы скопировали ссылку на видео с доступом по ссылке не полностью. "
            "Ссылка должна иметь вид https://vk.com/video123456789_123456789?list=ln-j094ku3j0ku5m034d3"
        )
        return True

    return False


async def try_get_info(url: str, message: Message) -> YtDlpInfoDict | None:
    try:
        # TODO: почему-то это блокирует event loop
        return await extract_info_async(url, process=False, convert_entries_to_list=True)
    except yt_dlp.utils.UnsupportedError as exc:
        await handle_unsupported_url(exc, message)
        return None
    except yt_dlp.utils.YoutubeDLError as exc:
        if await is_user_error(message, exc):
            return None

        logger.exception(exc.msg, exc_info=exc)
        await message.reply("Ошибка")
        return None


async def handle_url(message: Message, manager: DialogManager) -> YtDlpContentType | None:
    user: User = manager.middleware_data["user"]

    async with ChatActionSender(
        bot=message.bot,
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
    ):
        await message.answer("Скачиваю информацию")
        info = await try_get_info(message.text, message)
        if info is None:
            return None

        _type = info["_type"]
        if _type == YtDlpContentType.URL:
            logger.info('Resolving url with type "url": %s', message.text)
            info = await try_get_info(info["url"], message)
            if info is None:
                return None

        _type = info["_type"]
        if _type == YtDlpContentType.URL:
            # Второй раз получили тип url -> что-то не так
            logger.warning('User sent url with type "url": %s', message.text)

        if info.get("is_live") or info.get("live_status") == "is_live":
            await message.reply("Работа с прямыми трансляциями не поддерживается")
            return None

        manager.dialog_data[URL_KEY] = message.text

        match _type:
            case YtDlpContentType.VIDEO:
                thumbnail_url = get_thumbnail_url_for_preview(info)
                await send_preview(
                    message,
                    f"По ссылке находиться видео\n{info['title']} - {seconds_to_human_readable(info["duration"])}",
                    thumbnail_url,
                )

            case YtDlpContentType.PLAYLIST:
                thumbnail_url = get_thumbnail_url_for_preview(info)

                info["entries"] = list(info["entries"])  # Превращает итератор в список
                playlist_desc = (
                    f"По ссылке находиться плейлист\n"
                    f"[{info['title']}]({info["webpage_url"]})\n"
                    f"Общая продолжительность - {seconds_to_human_readable(get_playlist_duration(info))}"
                )
                videos_desc = "\n●".join(
                    f"[{video["title"]}]({video["url"]}) - {seconds_to_human_readable(video["duration"])}"
                    for video in info["entries"]
                )
                msg = f"{playlist_desc}\n\nСписок видео:\n●{videos_desc}"
                await send_preview(message, msg, thumbnail_url, parse_mode=ParseMode.MARKDOWN)

            case _:
                manager.dialog_data.pop(URL_KEY, None)
                logger.error("User %s tried to process unsupported content type %s", user.id, _type)
                await message.reply(f"Работа с типом _{_type}_ не поддерживается", parse_mode=ParseMode.MARKDOWN)
                return None

        await manager.switch_to(LectureProcessingStates.choose_audio_processing_profile)

        return _type
