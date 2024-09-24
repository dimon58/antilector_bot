import logging
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

from ffmpeg import FFmpegError
from ffmpeg.types import Option

from configs import (
    MAX_RAM_FOR_UNSILENCE_RENDERING,
    MAX_VRAM_FOR_UNSILENCE_RENDERING,
    UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING,
)
from lib.unsilence import Interval, Intervals
from lib.unsilence._typing import UpdateCallbackType
from lib.unsilence.render_media.media_renderer import MediaRenderer
from lib.unsilence.render_media.options import RenderOptions
from lib.unsilence.render_media.render_filter import (
    get_audio_filter,
    get_fade_filter,
    get_speed_and_volume,
    get_video_filter,
)
from utils.fixed_ffmpeg import FixedFFmpeg
from utils.progress_bar import setup_progress_for_ffmpeg
from utils.video.measure import get_video_bits_per_raw_sample, get_video_framerate, get_video_resolution

FFmpegOptionsType: TypeAlias = dict[str, Option | None]

MAX_FILTERS_WITHOUT_DEGRADATION = 25

logger = logging.getLogger(__name__)


@dataclass
class IntervalRenderTask:
    interval: Interval
    video_filter: str | None = None
    audio_filter: str | None = None

    @classmethod
    def create(cls, interval: Interval, render_options: RenderOptions) -> "IntervalRenderTask":
        task = IntervalRenderTask(interval=interval)

        current_speed, current_volume = get_speed_and_volume(render_options, interval)
        # ----------------- video filter ----------------- #

        if not render_options.audio_only:
            task.video_filter = get_video_filter(current_speed)
            logger.debug("Video filter: %s", task.video_filter)

        # ----------------- audio filter ----------------- #
        fade = get_fade_filter(
            total_duration=interval.duration,
            interval_in_fade_duration=render_options.interval_in_fade_duration,
            interval_out_fade_duration=render_options.interval_out_fade_duration,
            fade_curve=render_options.fade_curve,
        )
        task.audio_filter = get_audio_filter(fade, current_speed, current_volume)
        logger.debug("Audio filter: %s", task.audio_filter)

        return task


@dataclass
class IntervalGroupRenderTask:
    interval_render_tasks: list[IntervalRenderTask] = field(default_factory=list)
    _total_interval_duration: float = 0

    @property
    def total_interval_duration(self):
        return self._total_interval_duration

    @property
    def start_timestamp(self):
        return self.interval_render_tasks[0].interval.start

    @property
    def end_timestamp(self):
        return self.interval_render_tasks[-1].interval.end

    def has_tasks(self) -> bool:
        return len(self.interval_render_tasks) > 0

    def add(self, interval_render_task: IntervalRenderTask):
        self.interval_render_tasks.append(interval_render_task)
        self._total_interval_duration += interval_render_task.interval.duration

    def _generate_command_for_single_interval(  # noqa: PLR0912
        self,
        render_options: RenderOptions,
    ) -> tuple[FFmpegOptionsType, FFmpegOptionsType]:

        # ----------------------- single task specific ----------------------- #
        task = self.interval_render_tasks[0]
        input_options = {"ss": task.interval.start, "to": task.interval.end}

        output_options = {}

        complex_filter_components = []

        # ----------------- video filter ----------------- #
        if task.video_filter is not None:
            complex_filter_components.append(f"[0:v]{task.video_filter}[v]")

        # ----------------- audio filter ----------------- #
        if task.audio_filter:
            complex_filter_components.append(f"[0:a]{task.audio_filter}[a]")

        # ----------------- complex filter ----------------- #

        if len(complex_filter_components) > 0:
            complex_filter = ";".join(complex_filter_components)
            output_options["filter_complex"] = complex_filter
            logger.debug("Using complex filter %s", complex_filter)
        else:
            logger.debug("Not using complex filter")

        output_map = []
        if not render_options.audio_only:
            if task.video_filter is not None:
                output_map.append("[v]")
            else:
                output_map.append("0:v")
                if render_options.allow_copy_video_stream:
                    output_options["c:v"] = "copy"

        if task.audio_filter is not None:
            output_map.append("[a]")
        else:
            output_map.append("0:a")
            if render_options.allow_copy_audio_stream:
                output_options["c:a"] = "copy"

        output_options["map"] = output_map

        if render_options.audio_only:
            output_options["vn"] = None

        if render_options.force_video_codec is not None and output_options.get("c:v") != "copy":
            output_options["c:v"] = render_options.force_video_codec

        return input_options, output_options

    def _generate_command_for_multiple_interval(
        self, render_options: RenderOptions
    ) -> tuple[FFmpegOptionsType, FFmpegOptionsType]:

        # todo: allow copy

        trim_filters = []

        start_timestamp = self.start_timestamp
        for idx, task in enumerate(self.interval_render_tasks):
            if not render_options.audio_only:
                video_filter = f",{task.video_filter}" if task.video_filter is not None else ""

                trim_filters.append(
                    f"[0:v]"
                    f"trim=start={task.interval.start - start_timestamp}:end={task.interval.end - start_timestamp}"
                    f",setpts=PTS-STARTPTS{video_filter}"
                    f"[vf{idx}]"
                )

            audio_filter = f",{task.audio_filter}" if task.audio_filter is not None else ""
            trim_filters.append(
                f"[0:a]"
                f"atrim=start={task.interval.start - start_timestamp}:end={task.interval.end - start_timestamp}"
                f",asetpts=PTS-STARTPTS{audio_filter}"
                f"[af{idx}]"
            )

        concat_input = "".join(f"[vf{idx}][af{idx}]" for idx in range(len(self.interval_render_tasks)))
        concat_filter = f"{concat_input}concat=n={len(self.interval_render_tasks)}:v=1:a=1[v][a]"

        complex_filter_components = [
            *trim_filters,
            concat_filter,
        ]
        complex_filter = ";".join(complex_filter_components)

        # Можно использовать параметр filter_complex_script, если фильтр будет слишком большим
        # Но пока это не имеет смысла, так большие (>50 интервалов) фильтры работают очень медленно
        output_options = {"filter_complex": complex_filter, "map": ["[v]", "[a]"]}

        if render_options.audio_only:
            output_options["vn"] = None

        return {"ss": self.start_timestamp, "to": self.end_timestamp}, output_options

    def generate_command(self, input_file: Path, output_file: Path, render_options: RenderOptions) -> FixedFFmpeg:
        if len(self.interval_render_tasks) == 0:
            raise ValueError("No tasks in group")

        ffmpeg = FixedFFmpeg().option("ignore_unknown").option("y")

        if render_options.use_nvenc:
            logger.debug("Rendering using nvenc")
            ffmpeg = ffmpeg.option("hwaccel", "cuda").option("hwaccel_output_format", "cuda")

        logger.debug("Rendering on cpu")

        if len(self.interval_render_tasks) == 1:
            input_options, output_options = self._generate_command_for_single_interval(render_options)
        else:
            input_options, output_options = self._generate_command_for_multiple_interval(render_options)

        output_options |= {
            "vsync": 1,
            "async": 1,
            "safe": 0,
        }

        if render_options.force_video_codec is not None:
            output_options["c:v"] = render_options.force_video_codec

        return ffmpeg.input(input_file, input_options).output(output_file, output_options)

    def generate_command_notrim(
        self, input_file: Path, output_file: Path, render_options: RenderOptions
    ) -> FixedFFmpeg:
        """
        НЕ ИСПОЛЬЗОВАТЬ!

        Попытка полностью избавить от trim и atrim

        Получилось гораздо медленнее, чем версия с trim и atrim
        """

        if len(self.interval_render_tasks) == 0:
            raise ValueError("No tasks in group")

        ffmpeg = FixedFFmpeg().option("ignore_unknown").option("y")

        if render_options.use_nvenc:
            logger.debug("Rendering using nvenc")
            base_input_options = {
                "hwaccel": "cuda",
                "hwaccel_output_format": "cuda",
            }
        else:
            base_input_options = {}
            logger.debug("Rendering on cpu")

        filters = []
        for idx, task in enumerate(self.interval_render_tasks):
            ffmpeg = ffmpeg.input(input_file, base_input_options | {"ss": task.interval.start, "to": task.interval.end})

            if not render_options.audio_only:
                if task.video_filter is not None:
                    filters.append(f"[{idx}:v]{task.video_filter}[vf{idx}]")
                else:
                    filters.append(f"[{idx}:v]setpts=PTS[vf{idx}]")

            if task.audio_filter is not None:
                filters.append(f"[{idx}:a]{task.audio_filter}[af{idx}]")
            else:
                filters.append(f"[{idx}:a]atempo=1[af{idx}]")

        concat_input = "".join(f"[vf{idx}][af{idx}]" for idx in range(len(self.interval_render_tasks)))
        concat_filter = f"{concat_input}concat=n={len(self.interval_render_tasks)}:v=1:a=1[v][a]"

        complex_filter_components = [
            *filters,
            concat_filter,
        ]
        complex_filter = ";".join(complex_filter_components)

        output_options = {
            "vsync": 1,
            "async": 1,
            "safe": 0,
            "filter_complex": complex_filter,
            "map": ["[v]", "[a]"],
        }

        if render_options.force_video_codec is not None:
            output_options["c:v"] = render_options.force_video_codec

        return ffmpeg.output(output_file, output_options)


@dataclass
class ThreadTask:
    task_id: int
    total_tasks: int
    output_file: Path

    interval_group_render_task: IntervalGroupRenderTask


class FastMediaRenderer(MediaRenderer):
    """
    Faster version of Media Renderer from unsilence

    Этот рендерер примерно в 5-7 раз быстрее, чем прошлая реализация на nvenc.

    Но есть куда расти, так как видно, что nvenc загружен далеко не полностью.
    Возможно из-за слабого процессора (он был 100% во время рендеринга)
    """

    def __init__(
        self,
        temp_path: Path,
        max_group_size: int = MAX_FILTERS_WITHOUT_DEGRADATION,
        max_memory_usage_bytes: float | None = None,
        min_interval_length_for_logging: float = UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING,
    ):
        """

        :param temp_path: Путь до папки, куда можно писать временные файлы.
        :param max_group_size: Максимальный размер группы интервалов.
        :param max_memory_usage_bytes: Максимальный размер памяти, который может использовать рендерер.
        :param min_interval_length_for_logging: Минимальная длина интервала, который можно логировать отдельно.
        """
        super().__init__(temp_path)
        self.max_group_size = max_group_size
        self.max_memory_usage_bytes = max_memory_usage_bytes
        self.min_interval_length_for_logging = min_interval_length_for_logging

    def get_max_ram_size_from_config(self, render_options: RenderOptions) -> float:

        if self.max_memory_usage_bytes is not None:
            return self.max_memory_usage_bytes / render_options.threads

        if render_options.use_nvenc:
            return MAX_VRAM_FOR_UNSILENCE_RENDERING / render_options.threads

        return MAX_RAM_FOR_UNSILENCE_RENDERING / render_options.threads

    @staticmethod
    def get_max_seconds_buffer(input_file: Path, ram_bytes: float) -> float:

        fps = get_video_framerate(input_file)
        width, height = get_video_resolution(input_file)
        try:
            bits_per_raw_sample = get_video_bits_per_raw_sample(input_file)
        except (FFmpegError, ValueError) as exc:
            logger.error("Failed to get bits_per_raw_sample: %s. Falling back to 8.", exc, exc_info=exc)  # noqa: TRY400
            bits_per_raw_sample = 8

        # Реально потребление памяти меньше расчётного, почти всё время в несколько раз
        # Но иногда сильно прыгает
        # 3 канала * бит на канал * width * height // 8 <- перевод в байты
        raw_byte_rate = 3 * bits_per_raw_sample * fps * width * height // 8

        return ram_bytes / raw_byte_rate

    def _create_tasks(
        self, input_file: Path, intervals: Intervals, render_options: RenderOptions
    ) -> list[IntervalGroupRenderTask]:
        intervals = intervals.remove_short_intervals_from_start(
            audible_speed=render_options.audible_speed,
            silent_speed=render_options.silent_speed,
        )

        max_seconds_buffer = self.get_max_seconds_buffer(
            input_file=input_file,
            ram_bytes=self.get_max_ram_size_from_config(render_options),
        )

        tasks: list[IntervalGroupRenderTask] = []

        current_render_group = IntervalGroupRenderTask()

        for interval in intervals.intervals:

            if (
                current_render_group.total_interval_duration + interval.duration > max_seconds_buffer
                or len(current_render_group.interval_render_tasks) >= self.max_group_size
            ):
                tasks.append(current_render_group)
                current_render_group = IntervalGroupRenderTask()

            current_render_group.add(IntervalRenderTask.create(interval, render_options))

        if current_render_group.has_tasks():
            tasks.append(current_render_group)

        return tasks

    def _run_tasks(
        self,
        tasks: list[IntervalGroupRenderTask],
        input_file: Path,
        output_file: Path,
        render_options: RenderOptions,
        on_render_progress_update: UpdateCallbackType | None = None,
    ) -> list[Path]:

        thread_lock = threading.Lock()
        task_queue = queue.Queue[ThreadTask]()
        thread_list: list[RenderIntervalThread] = []
        completed_tasks: list[ThreadTask] = []
        corrupted_intervals: list[ThreadTask] = []

        def handle_thread_completed_task(completed_task: ThreadTask, corrupted: bool) -> None:
            """
            Nested function that is called when a thread completes it current task
            :param completed_task: The completed task
            :param corrupted: If the task contained a corrupted media part
            :return: None
            """

            thread_lock.acquire()

            if not corrupted:
                completed_tasks.append(completed_task)
                if on_render_progress_update is not None:
                    on_render_progress_update(len(completed_tasks), len(tasks))
            else:
                corrupted_intervals.append(completed_task)

            thread_lock.release()

        logger.info("Spawning %s threads for rendering intervals", render_options.threads)
        if render_options.use_nvenc:
            logger.info("Rendering using nvenc")
        else:
            logger.info("Rendering on cpu")

        for i in range(render_options.threads):
            thread = RenderIntervalThread(
                thread_id=i,
                input_file=input_file,
                render_options=render_options,
                task_queue=task_queue,
                thread_lock=thread_lock,
                on_task_completed=handle_thread_completed_task,
                min_interval_length_for_logging=self.min_interval_length_for_logging,
            )
            thread.start()
            thread_list.append(thread)

        self._temp_path.mkdir(parents=True, exist_ok=True)
        file_list = []
        for i, task in enumerate(tasks):
            current_file_name = f"out_{i}{output_file.suffix}"
            current_path = self._temp_path / current_file_name

            thread_task = ThreadTask(
                task_id=i,
                total_tasks=len(tasks),
                output_file=current_path,
                interval_group_render_task=task,
            )
            file_list.append(current_path)

            thread_lock.acquire()
            task_queue.put(thread_task)
            thread_lock.release()

        while len(completed_tasks) < (len(tasks) - len(corrupted_intervals)):
            time.sleep(0.5)

        for thread in thread_list:
            thread.stop()

        return [task.output_file for task in sorted(completed_tasks, key=lambda x: x.task_id)]

    def _concat_rendered_files(
        self, completed_file_list: list[Path], on_concat_progress_update: UpdateCallbackType | None, output_file: Path
    ) -> Path:

        concat_file = self._temp_path / "concat_list.txt"
        final_output = self._temp_path / f"out_final{output_file.suffix}"

        self._concat_intervals(
            file_list=completed_file_list,
            concat_file=concat_file,
            output_file=final_output,
            update_concat_progress=on_concat_progress_update,
        )

        return final_output

    def render(
        self,
        input_file: Path,
        output_file: Path,
        intervals: Intervals,
        render_options: RenderOptions,
        on_render_progress_update: UpdateCallbackType | None = None,
        on_concat_progress_update: UpdateCallbackType | None = None,
    ) -> None:
        """
        Renders an input_file and writes the final output to output_file

        :param input_file: The file that should be processed
        :param output_file: Where the processed file should be saved
        :param intervals: The Intervals that should be processed
        :param render_options: Render options
        :param on_render_progress_update: Function that should be called on render progress update
            (called like: func(current, total))
        :param on_concat_progress_update: Function that should be called on concat progress update
            (called like: func(current, total))
        """

        input_file = Path(input_file).absolute()
        output_file = Path(output_file).absolute()

        if not input_file.exists():
            raise FileNotFoundError(f"Input file {input_file} does not exist!")

        tasks = self._create_tasks(input_file, intervals, render_options)
        logger.info("Rendering %s interval groups", len(tasks))

        completed_file_list = self._run_tasks(
            tasks=tasks,
            input_file=input_file,
            output_file=output_file,
            render_options=render_options,
            on_render_progress_update=on_render_progress_update,
        )

        final_output = self._concat_rendered_files(
            completed_file_list=completed_file_list,
            on_concat_progress_update=on_concat_progress_update,
            output_file=output_file,
        )

        shutil.move(final_output, output_file)


class RenderIntervalThread(threading.Thread):
    def __init__(
        self,
        thread_id: int,
        input_file: Path,
        render_options: RenderOptions,
        task_queue: queue.Queue,
        thread_lock: threading.Lock,
        on_task_completed: Callable[[ThreadTask, bool], None],
        min_interval_length_for_logging: float,
    ):
        """
        Initializes a new Worker (is run in daemon mode)
        :param thread_id: ID of this thread
        :param input_file: The file the worker should work on
        :param render_options: The parameters on how the video should be processed, more details below
        :param task_queue: A queue object where the worker can get more tasks
        :param thread_lock: A thread lock object to acquire and release thread locks
        """
        super().__init__(daemon=True)
        self.thread_id = thread_id
        self.task_queue = task_queue
        self.thread_lock = thread_lock
        self._should_exit = False
        self._input_file = input_file
        self._on_task_completed = on_task_completed
        self._render_options = render_options
        self._min_interval_length_for_logging = min_interval_length_for_logging

    def run(self) -> None:
        """
        Start the worker. Worker runs until stop() is called. It runs in a loop, takes a new task if available, and
        processes it
        :return: None
        """
        while not self._should_exit:
            self.thread_lock.acquire()

            if not self.task_queue.empty():
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
            else:
                self.thread_lock.release()

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

            raise ValueError(f"{exc.message}: {exc.arguments}") from exc

        return True
