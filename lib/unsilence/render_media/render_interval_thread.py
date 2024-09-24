import logging
import queue
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from ffmpeg import FFmpegError

from configs import UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING
from utils.fixed_ffmpeg import FixedFFmpeg
from utils.progress_bar import setup_progress_for_ffmpeg

from ..intervals.interval import Interval
from .options import RenderOptions
from .render_filter import get_audio_filter, get_fade_filter, get_speed_and_volume, get_video_filter

logger = logging.getLogger(__name__)


class RenderIntervalThread(threading.Thread):
    """
    Worker thread that can render/process intervals based on defined options
    """

    def __init__(
        self,
        thread_id: int,
        input_file: Path,
        render_options: RenderOptions,
        task_queue: queue.Queue,
        thread_lock: threading.Lock,
        on_task_completed: Callable[[SimpleNamespace, bool], None],
    ):
        """
        Initializes a new Worker (is run in daemon mode)
        :param thread_id: ID of this thread
        :param input_file: The file the worker should work on
        :param render_options: The parameters on how the video should be processed, more details below
        :param task_queue: A queue object where the worker can get more tasks
        :param thread_lock: A thread lock object to acquire and release thread locks
        """
        super().__init__()
        self.daemon = True
        self.thread_id = thread_id
        self.task_queue = task_queue
        self.thread_lock = thread_lock
        self._should_exit = False
        self._input_file = input_file
        self._on_task_completed = on_task_completed
        self._render_options = render_options

    def run(self) -> None:
        """
        Start the worker. Worker runs until stop() is called. It runs in a loop, takes a new task if available, and
        processes it
        :return: None
        """
        while not self._should_exit:
            self.thread_lock.acquire()

            if not self.task_queue.empty():
                task: SimpleNamespace = self.task_queue.get()
                self.thread_lock.release()

                completed = self.__render_interval(
                    task_id=task.task_id,
                    total_tasks=task.total_tasks,
                    interval_output_file=task.interval_output_file,
                    interval=task.interval,
                )

                if completed and self._render_options.check_intervals:
                    probe_output = subprocess.run(  # noqa: S603
                        ["ffprobe", "-loglevel", "quiet", f"{task.interval_output_file}"],  # noqa: S607
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    completed = probe_output.returncode == 0

                if self._on_task_completed is not None:
                    self._on_task_completed(task, not completed)
            else:
                self.thread_lock.release()

    def stop(self) -> None:
        """
        Stops the worker after its current task is finished
        :return:
        """
        self._should_exit = True

    def __render_interval(
        self,
        task_id: int,
        total_tasks: int,
        interval_output_file: Path,
        interval: Interval,
        apply_filter: bool = True,
    ) -> bool:
        """
        Renders an interval with the given render options
        :param interval_output_file: Where the current output file should be saved
        :param interval: The current Interval that should be processed
        :param apply_filter: Whether the AV-Filter should be applied or if the media interval should be left untouched
        :return: Whether it is corrupted or not
        """

        ffmpeg = self.__generate_command(interval_output_file, interval, apply_filter)

        # Очень часто длина интервалов меньше нескольких секунд
        # Их логирование только засоряет поток
        # Поэтому логируем только достаточно длинные
        if interval.duration >= UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING:
            setup_progress_for_ffmpeg(
                ffmpeg,
                interval.duration,
                f"[task {self.thread_id}] Rendering interval"
                f" {task_id + 1}/{total_tasks} {{{interval.start}, {interval.end}}}",
            )

        try:
            ffmpeg.execute()
        except FFmpegError as exc:
            if "Conversion failed!" in exc.message.splitlines()[-1]:
                if self._render_options.drop_corrupted_intervals:
                    return False
                if apply_filter:
                    self.__render_interval(
                        task_id=task_id,
                        total_tasks=total_tasks,
                        interval_output_file=interval_output_file,
                        interval=interval,
                        apply_filter=False,
                    )
                else:
                    raise OSError(
                        f"Input file is corrupted between {interval.start} and {interval.end} (in seconds)"
                    ) from exc

            if "Error initializing complex filter" in exc.message:
                raise ValueError("Invalid render options") from exc

            raise ValueError(f"{exc.message}: {exc.arguments}") from exc

        return True

    def _resolve_filter(self, fade: str, interval: Interval) -> dict[str, str]:  # noqa: PLR0912

        additional_output_options = {}

        current_speed, current_volume = get_speed_and_volume(self._render_options, interval)

        complex_filter_components: list[str] = []

        # ----------------- video filter ----------------- #
        if not self._render_options.audio_only:
            video_filter = get_video_filter(current_speed)
            if video_filter is not None:
                video_filter = f"[0:v]{video_filter}[v]"
                complex_filter_components.append(video_filter)
        else:
            video_filter = None
        logger.debug("Video filter: %s", video_filter)

        # ----------------- audio filter ----------------- #
        audio_filter = get_audio_filter(fade, current_speed, current_volume)
        if audio_filter is not None:
            audio_filter = f"[0:a]{audio_filter}[a]"
            complex_filter_components.append(audio_filter)
        logger.debug("Audio filter: %s", audio_filter)

        # ----------------- complex filter ----------------- #

        if len(complex_filter_components) > 0:
            complex_filter = ";".join(complex_filter_components)
            additional_output_options["filter_complex"] = complex_filter
            logger.debug("Using complex filter %s", complex_filter)
        else:
            logger.debug("Not using complex filter")

        output_map = []
        if not self._render_options.audio_only:
            if video_filter is not None:
                output_map.append("[v]")
            else:
                output_map.append("0:v")
                if self._render_options.allow_copy_video_stream:
                    additional_output_options["c:v"] = "copy"

        if audio_filter is not None:
            output_map.append("[a]")
        else:
            output_map.append("0:a")
            if self._render_options.allow_copy_audio_stream:
                additional_output_options["c:a"] = "copy"

        additional_output_options["map"] = output_map

        return additional_output_options

    def __generate_command(self, interval_output_file: Path, interval: Interval, apply_filter: bool) -> FixedFFmpeg:
        """
        Generates the ffmpeg command to process the video
        :param interval_output_file: Where the media interval should be saved
        :param interval: The current interval
        :param apply_filter: Whether a filter should be applied or not
        :return: ffmpeg console command
        """

        input_options = {"ss": interval.start, "to": interval.end}

        if self._render_options.use_nvenc:
            logger.debug("Using nvenc")
            input_options |= {
                "hwaccel": "cuda",
                "hwaccel_output_format": "cuda",
            }
        else:
            logger.debug("Encoding on cpu")

        ffmpeg = FixedFFmpeg().input(self._input_file, input_options).option("ignore_unknown").option("y")

        output_options = {
            "vsync": 1,
            "async": 1,
            "safe": 0,
        }

        fade = get_fade_filter(
            total_duration=interval.duration,
            interval_in_fade_duration=self._render_options.interval_in_fade_duration,
            interval_out_fade_duration=self._render_options.interval_out_fade_duration,
            fade_curve=self._render_options.fade_curve,
        )

        if apply_filter:
            output_options |= self._resolve_filter(
                fade=fade,
                interval=interval,
            )

        else:
            if fade != "":
                output_options["af"] = fade

            elif self._render_options.allow_copy_audio_stream:
                output_options["c:a"] = "copy"

            if self._render_options.allow_copy_video_stream:
                output_options["c:v"] = "copy"

        if self._render_options.audio_only:
            ffmpeg = ffmpeg.option("-vn")

        if self._render_options.force_video_codec is not None and output_options.get("c:v") != "copy":
            output_options["c:v"] = self._render_options.force_video_codec

        logger.debug(
            "Rendering interval {%s, %s} using codec %s", interval.start, interval.end, output_options.get("c:v")
        )

        return ffmpeg.output(interval_output_file, output_options)
