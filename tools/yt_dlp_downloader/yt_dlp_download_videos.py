import enum
import logging.config
import os.path
import re
import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeAlias

import yt_dlp
from yt_dlp.downloader import FileDownloader
from yt_dlp.extractor.common import InfoExtractor

from configs import YT_DLP_HTTP_CHUNK_SIZE, YT_DLP_LOGGING_DEBOUNCE_TIME

from .yt_dlp_extractors import CUSTOM_EXTRACTORS
from .yt_dlp_format_select import select_format

YtDlpInfoDict: TypeAlias = dict[str, Any]

logger = logging.getLogger(__name__)


class YtDlpContentType(enum.StrEnum):
    PLAYLIST = "playlist"
    VIDEO = "video"
    MULTI_VIDEO = "multi_video"

    # custom types
    CHANNEL = "channel"


class YoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, params: dict[str, Any] | None = None):  # noqa: D107
        super().__init__(params=params, auto_init=True)
        self.insert_first_info_extractor(*(ie() for ie in CUSTOM_EXTRACTORS))

    def insert_first_info_extractor(self, *ies: InfoExtractor) -> None:
        """Add an InfoExtractor object to the start of the list."""

        if len(ies) == 0:
            return

        _tmp = {}
        _tmp_instances = {}
        for ie in ies:
            ie_key = ie.ie_key()
            _tmp[ie_key] = ie
            if not isinstance(ie, type):
                _tmp_instances[ie_key] = ie
                ie.set_downloader(self)

        self._ies = _tmp | self._ies
        if len(_tmp_instances) > 0:
            self._ies_instances = _tmp_instances | self._ies_instances


class DebouncedLogger:
    debug_prefix = "[debug] "
    download_state_regex = re.compile(r"^\[download]\s+\d+\.\d+%", flags=re.UNICODE)  # keep logs for 100%
    logging_debounce_time = (
        YT_DLP_LOGGING_DEBOUNCE_TIME  # sec - костыльный способ ограничить поток логов при скачивании видео
    )

    def __init__(self):  # noqa: D107
        self._last_download_log = -self.logging_debounce_time

    def download_debounce(self, msg: str) -> None:
        now = time.monotonic()

        # Сильно сокращает спам в логи
        if (now - self._last_download_log) > self.logging_debounce_time:
            logger.info(msg)
            self._last_download_log = now

    def debug(self, msg: str) -> None:
        # For compatibility with youtube-dl, both debug and info are passed into debug
        # You can distinguish them by the prefix '[debug] '
        if msg.startswith(self.debug_prefix):
            logger.debug(msg[len(self.debug_prefix) :])
        elif re.match(self.download_state_regex, msg):
            self.download_debounce(msg)
        else:
            self.info(msg)

    def info(self, msg: str) -> None:
        logger.info(msg)

    def warning(self, msg: str) -> None:
        logger.warning(msg)

    def error(self, msg: str) -> None:
        logger.error(msg)


@dataclass
class DownloadData:
    info: YtDlpInfoDict = field(default_factory=dict)
    filenames: dict[str, str] = field(default_factory=dict)


class RecalcIds(yt_dlp.postprocessor.PostProcessor):
    """
    Пересчитывает id в формат (extractor)_(old id)_(url hash)
    """

    def __init__(  # noqa: D107
        self,
        sanitizer: Callable[[dict, bool], dict] | None = None,
        remove_private_keys: bool = False,
        downloader: FileDownloader | None = None,
        nested: bool = False,
    ):
        super().__init__(downloader)
        self.__sanitizer = sanitizer
        self.__sanitizer__remove_private_keys = remove_private_keys
        self.__nested = nested

    @staticmethod
    def recalc_id(info: YtDlpInfoDict, extractor: str) -> str:
        """
        Пересчитывает id видео в строку вида (extractor)_(old id)_(url hash)
        """
        if "id" not in info:
            info["id"] = "no_id"

        # Возможно в id есть пробелы, поэтому их выкидываем
        _id = re.sub(r"\s+", "", info["id"], flags=re.UNICODE)

        return f"{extractor}_{_id}"

    def recalc_ids_generator(self, entries: Generator, extractor: str) -> Iterator[dict[str, Any]]:
        """
        Пересчитывает id у генератора entries при итерациях
        """
        for entry in entries:
            entry["id"] = self.recalc_id(entry, extractor)
            yield entry

    def recalc_all_ids(self, info: YtDlpInfoDict) -> YtDlpInfoDict:
        """
        Пересчитывает id у элемента и его entries, если они есть
        """
        extractor = info["extractor"]
        info["id"] = self.recalc_id(info, extractor)

        if not self.__nested:
            return info

        entries = info.get("entries")
        if isinstance(entries, Generator):
            entries = self.recalc_ids_generator(entries, extractor)
        elif isinstance(entries, list):
            for entry in entries:
                entry["id"] = self.recalc_id(entry, extractor)

        info["entries"] = entries

        if self.__sanitizer is None:
            return info
        info = self.__sanitizer(info, self.__sanitizer__remove_private_keys)

        if isinstance(entries, Generator):
            info["entries"] = entries

        return info

    def run(self, info: YtDlpInfoDict) -> tuple[list, YtDlpInfoDict]:
        return [], self.recalc_all_ids(info)


class SaveInfo(yt_dlp.postprocessor.PostProcessor):
    """
    Сохраняет информацию о видео в data
    """

    def __init__(self, data: DownloadData, downloader: FileDownloader | None = None):  # noqa: D107
        super().__init__(downloader)
        self.__data = data

    def run(self, info: YtDlpInfoDict) -> tuple[list, YtDlpInfoDict]:
        self.__data.info = info
        return [], info


def resolve_type(info: YtDlpInfoDict) -> str:
    """
    Определяет тип канала на youtube
    """
    _type = info["_type"]

    if (
        _type == YtDlpContentType.PLAYLIST
        and info["extractor"].startswith("youtube")
        and not info["webpage_url"].startswith("https://www.youtube.com/playlist?list=")
    ):
        return "channel"

    return _type


def get_url(info: YtDlpInfoDict) -> str:
    for key in "webpage_url", "url":
        if key in info:
            return info[key]

    raise ValueError(f"No url in info: {info}")


COMMON_YT_DLP_OPTIONS = {
    "logger": DebouncedLogger(),
    "http_chunk_size": YT_DLP_HTTP_CHUNK_SIZE,
    "format": select_format,
    "noplaylist": True,
}


def download(url: str, output_dir: str, **additional_ydl_opts) -> DownloadData:
    """
    Скачивает видео или плейлист с youtube

    Args:
        url: Ссылка на видео или плейлист на youtube
        output_dir: Папка для скачивания файлов
        additional_ydl_opts: дополнительные настройки yt_dlp
            https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#usage-and-options
    Returns:
        dict[str, str]: Словарь вида {"id видео": "абсолютный путь до скачанного файла"}
    """
    data = DownloadData()

    def get_file_name(filename: str) -> None:
        rel_filename = os.path.relpath(filename, output_dir)
        _id = rel_filename.split(".", 1)[0]
        data.filenames[_id] = filename

    ydl_opts = (
        COMMON_YT_DLP_OPTIONS
        | {
            "post_hooks": [get_file_name],
            "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),  # noqa: PTH118
        }
        | additional_ydl_opts
    )

    with YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(RecalcIds(), when="pre_process")
        ydl.add_post_processor(RecalcIds(), when="playlist")
        ydl.add_post_processor(SaveInfo(data), when="pre_process")
        ydl.add_post_processor(SaveInfo(data), when="playlist")
        ydl.download([url])

    return data


def extract_info(
    url: str, process: bool = True, remove_private_keys: bool = False, **additional_ydl_opts
) -> YtDlpInfoDict:
    """
    Извлекает информацию про видео
    """

    ydl_opts = (
        COMMON_YT_DLP_OPTIONS
        | {
            "verbose": True,
        }
        | additional_ydl_opts
    )
    with YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(RecalcIds(ydl.sanitize_info, remove_private_keys), when="pre_process")
        info = ydl.extract_info(url, download=False, process=process)
        info["_type"] = resolve_type(info)
        return info
