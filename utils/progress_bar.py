import logging
import shlex
from typing import TYPE_CHECKING

from ffmpeg import FFmpeg, Progress

from configs import TQDM_LOGGING_INTERVAL
from utils.logging_tqdm import DEFAULT_TQDM_LOGGING_INTERVAL, LoggingTQDM

if TYPE_CHECKING:
    from tqdm import tqdm
logger = logging.getLogger("progress_bar")


class ProgressBar:
    def __init__(
        self,
        desc: str,
        mininterval: float = DEFAULT_TQDM_LOGGING_INTERVAL,
        *,
        set_total_on_close: bool = False,
    ):
        """
        :param desc: аргумент desc для tqdm
        """
        self._desc = desc
        self._mininterval = mininterval

        self._tqdm: tqdm | None = None

        self._closed = False

        self._set_total_on_close = set_total_on_close

    def _setup_tqdm(self, total: float) -> None:
        self._tqdm = LoggingTQDM(
            total=total,
            desc=self._desc,
            # ncols=len(self.__desc) + 80,
            mininterval=self._mininterval,
            position=0,
            leave=False,
        )

    def set_total(self, total: float) -> None:
        if self._tqdm is None:
            logger.debug("Set total %s for progress bar %s", total, self._desc)
            self._setup_tqdm(total)
        elif self._tqdm.total != total:
            self._tqdm.total = total
            self._tqdm.refresh()

        if self._closed and total > self._tqdm.n:
            self._closed = False

    def update(self, current: float) -> None:
        self._tqdm.update(current - self._tqdm.n)

        if self._tqdm.n == self._tqdm.total:
            self.close()

        # logger.info("%s %s/%s", self.__desc, current, self.__total)

    def update_unsilence(self, current: float, total: float) -> None:
        if self._tqdm is None:
            logger.info("Started %s", self._desc)
            self._setup_tqdm(total)

        self.update(current)

    def update_ffmpeg(self, progress: Progress) -> None:
        new_value = progress.time.total_seconds()

        # В некоторых случаях возвращается нулевое время в конце
        # Например, команда
        # ffmpeg -y -i video.mp4 -i tmp/audio.wav -async 1 -vsync 1 -c:v copy -map 0:v -map 1:a res.mp4
        if new_value < self._tqdm.n:
            return

        # logger.info("%s %s %s %s",self.__desc, self.__total, progress.time, progress.time.total_seconds())
        self.update(new_value)

    def close(self) -> None:

        if self._closed:
            return

        if self._set_total_on_close:
            self._tqdm.n = self._tqdm.total

        if self._tqdm is not None:
            self._tqdm.refresh()
            self._tqdm.close()

        self._closed = True
        logger.info("Finished %s", self._desc)


def setup_progress_for_ffmpeg(ffmpeg: FFmpeg, duration: float, title: str) -> ProgressBar:
    progress_bar = ProgressBar(title, set_total_on_close=True, mininterval=TQDM_LOGGING_INTERVAL)
    progress_bar.set_total(duration)

    @ffmpeg.on("start")
    def on_start(arguments: list[str]) -> None:
        logger.debug("Call ffmpeg: %s", shlex.join(arguments))

    @ffmpeg.on("completed")
    def on_complete() -> None:
        logger.debug("%s done", title)
        progress_bar.close()

    ffmpeg.on("progress", progress_bar.update_ffmpeg)
    ffmpeg.on("terminated", progress_bar.close)

    return progress_bar
