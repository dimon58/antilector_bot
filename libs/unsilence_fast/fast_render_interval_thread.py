import logging
import queue
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ffmpeg import FFmpegError

from libs.unsilence.render_media.options import RenderOptions
from utils.progress_bar import setup_progress_for_ffmpeg

from .fast_render_task import IntervalGroupRenderTask

logger = logging.getLogger(__name__)


@dataclass
class ThreadTask:
    task_id: int
    total_tasks: int
    output_file: Path

    interval_group_render_task: IntervalGroupRenderTask


class RenderIntervalThread(threading.Thread):
    def __init__(
        self,
        thread_id: int,
        input_file: Path,
        render_options: RenderOptions,
        task_queue: queue.Queue,
        thread_exceptions: queue.Queue,
        thread_lock: threading.Lock,
        on_task_completed: Callable[[ThreadTask, bool], None],
        min_interval_length_for_logging: float,
        separated_audio: Path | None = None,
    ):
        """
        Initializes a new Worker (is run in daemon mode)
        :param thread_id: ID of this thread
        :param input_file: The file the worker should work on
        :param render_options: The parameters on how the video should be processed, more details below
        :param task_queue: A queue object where the worker can get more tasks
        :param thread_lock: A thread lock object to acquire and release thread locks
        :param separated_audio: Audio stream from input in separated file (wav is the best).
            Providing can increase performance.
        """
        super().__init__(daemon=True)
        self.thread_id = thread_id
        self.task_queue = task_queue
        self.thread_exceptions = thread_exceptions
        self.thread_lock = thread_lock
        self._should_exit = False
        self._input_file = input_file
        self._on_task_completed = on_task_completed
        self._render_options = render_options
        self._min_interval_length_for_logging = min_interval_length_for_logging
        self._separated_audio = separated_audio

    def _run(self) -> None:
        self.thread_lock.acquire()

        if self.task_queue.empty():
            self.thread_lock.release()
            return

        task: ThreadTask = self.task_queue.get()
        self.thread_lock.release()

        completed = self._render_interval(task)

        if completed and self._render_options.check_intervals:
            probe_output = subprocess.run(  # noqa: S603
                ["ffprobe", "-loglevel", "quiet", f"{task.output_file}"],  # noqa: S607
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                check=False,
            )
            completed = probe_output.returncode == 0

        if self._on_task_completed is not None:
            self._on_task_completed(task, not completed)

    def run(self) -> None:
        """
        Start the worker. Worker runs until stop() is called. It runs in a loop, takes a new task if available, and
        processes it
        :return: None
        """
        while not self._should_exit:
            # noinspection PyBroadException
            try:
                self._run()
            except Exception:  # noqa: BLE001
                self.thread_exceptions.put(sys.exc_info())
                return

    def stop(self) -> None:
        """
        Stops the worker after its current task is finished
        :return:
        """
        self._should_exit = True

    def _render_interval(self, task: ThreadTask) -> bool:
        """
        Renders an interval with the given task
        """
        ffmpeg = task.interval_group_render_task.generate_command(
            input_file=self._input_file,
            output_file=task.output_file,
            render_options=self._render_options,
            separated_audio=self._separated_audio,
        )

        # Нет смысла логировать вообще все куски, поэтому оставляем только самые длинные
        if task.interval_group_render_task.total_interval_duration >= self._min_interval_length_for_logging:
            setup_progress_for_ffmpeg(
                ffmpeg,
                task.interval_group_render_task.total_interval_duration,
                f"[task {self.thread_id}] Rendering interval group"
                f" №{task.task_id + 1}/{task.total_tasks} "
                f"{{{task.interval_group_render_task.start_timestamp}, "
                f"{task.interval_group_render_task.end_timestamp}}}",
            )

        logger.debug("Executing ffmpeg command on thread %s: %s", self.thread_id, shlex.join(ffmpeg.arguments))

        try:
            ffmpeg.execute()
        except FFmpegError as exc:
            if "Conversion failed!" in exc.message.splitlines()[-1]:
                if self._render_options.drop_corrupted_intervals:
                    return False

                raise OSError(
                    f"Input file is corrupted between "
                    f"{task.interval_group_render_task.start_timestamp} and "
                    f"{task.interval_group_render_task.end_timestamp} (in seconds)"
                ) from exc

            if "Error initializing complex filter" in exc.message:
                raise ValueError("Invalid render options") from exc

            raise ValueError(f"{exc.message}: {shlex.join(exc.arguments)}") from exc

        return True
