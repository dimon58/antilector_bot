import logging
import queue
import shutil
import threading
import time
from pathlib import Path

from ffmpeg import FFmpegError

from configs import (
    MAX_RAM_FOR_UNSILENCE_RENDERING,
    MAX_VRAM_FOR_UNSILENCE_RENDERING,
    UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING,
)
from libs.unsilence import Intervals
from libs.unsilence._typing import UpdateCallbackType
from libs.unsilence.intervals.interval import SerializedInterval
from libs.unsilence.render_media.media_renderer import MediaRenderer
from libs.unsilence.render_media.options import RenderOptions
from utils.video.measure import (
    MediaStreamType,
    get_media_bit_rate_safe,
    get_video_bits_per_raw_sample,
    get_video_framerate,
    get_video_resolution,
)

from .fast_render_interval_thread import RenderIntervalThread, ThreadTask
from .fast_render_task import InputFileInfo, IntervalGroupRenderTask, IntervalRenderTask

MAX_FILTERS_WITHOUT_DEGRADATION = 25

logger = logging.getLogger(__name__)


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

        max_seconds_buffer = self.get_max_seconds_buffer(
            input_file=input_file,
            ram_bytes=self.get_max_ram_size_from_config(render_options),
        )

        tasks: list[IntervalGroupRenderTask] = []

        logger.debug("Grouping intervals")
        current_render_group = IntervalGroupRenderTask()

        for interval in intervals.intervals_without_breaks:

            if current_render_group.has_tasks() and (
                # Нельзя складывать длительности, так как интервалы идут не непрерывно
                # current_render_group.total_interval_duration + interval.duration > max_seconds_buffer
                interval.end - current_render_group.start_timestamp > max_seconds_buffer
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
        separated_audio: Path | None,
        on_render_progress_update: UpdateCallbackType | None = None,
    ) -> list[Path]:

        logger.debug("Starting tasks")

        thread_exceptions = queue.Queue()
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

        if render_options.use_nvenc:
            logger.info("Rendering using nvenc")
        else:
            logger.info("Rendering on cpu")

        render_threads = min(render_options.threads, len(tasks))
        logger.info("Spawning %s threads for rendering intervals", render_threads)
        for i in range(render_threads):
            thread = RenderIntervalThread(
                thread_id=i,
                input_file=input_file,
                render_options=render_options,
                task_queue=task_queue,
                thread_exceptions=thread_exceptions,
                thread_lock=thread_lock,
                on_task_completed=handle_thread_completed_task,
                min_interval_length_for_logging=self.min_interval_length_for_logging,
                separated_audio=separated_audio,
            )
            thread.start()
            thread_list.append(thread)

        logger.debug("Sending tasks to queue")
        self._temp_path.mkdir(parents=True, exist_ok=True)
        file_list = []
        video_bit_rate = get_media_bit_rate_safe(input_file, MediaStreamType.VIDEO)
        input_file_info = InputFileInfo(
            video_bit_rate=video_bit_rate,
            max_video_bit_rate=2 * video_bit_rate,
            audio_bit_rate=get_media_bit_rate_safe(input_file, MediaStreamType.AUDIO),
        )
        for i, task in enumerate(tasks):
            current_file_name = f"out_{i}{output_file.suffix}"
            current_path = self._temp_path / current_file_name

            thread_task = ThreadTask(
                task_id=i,
                total_tasks=len(tasks),
                output_file=current_path,
                interval_group_render_task=task,
                input_file_info=input_file_info,
            )
            file_list.append(current_path)

            thread_lock.acquire()
            task_queue.put(thread_task)
            thread_lock.release()

        logger.debug("Waiting for tasks complete")
        while len(completed_tasks) < (len(tasks) - len(corrupted_intervals)):
            if thread_exceptions.empty():
                time.sleep(0.5)
            else:
                exc_type, exc_obj, exc_trace = thread_exceptions.get(block=False)
                raise exc_obj

        logger.debug("Stopping threads")
        for thread in thread_list:
            thread.stop()

        logger.debug("Joining threads")
        for thread in thread_list:
            thread.join()

        return [task.output_file for task in sorted(completed_tasks, key=lambda x: x.task_id)]

    def _concat_rendered_files(
        self, completed_file_list: list[Path], on_concat_progress_update: UpdateCallbackType | None, output_file: Path
    ) -> Path:

        logger.info("Concatenating files")

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
        separated_audio: Path | None = None,
        on_render_progress_update: UpdateCallbackType | None = None,
        on_concat_progress_update: UpdateCallbackType | None = None,
    ) -> list[list[SerializedInterval]]:
        """
        Renders an input_file and writes the final output to output_file

        :param input_file: The file that should be processed
        :param output_file: Where the processed file should be saved
        :param intervals: The Intervals that should be processed
        :param render_options: Render options
        :param separated_audio: Audio stream from input in separated file (wav is the best).
            Providing can increase performance.
        :param on_render_progress_update: Function that should be called on render progress update
            (called like: func(current, total))
        :param on_concat_progress_update: Function that should be called on concat progress update
            (called like: func(current, total))
        """

        input_file = Path(input_file).absolute()
        output_file = Path(output_file).absolute()
        if separated_audio is not None:
            separated_audio = Path(separated_audio).absolute()

        if not input_file.exists():
            raise FileNotFoundError(f"Input file {input_file} does not exist!")

        tasks = self._create_tasks(input_file, intervals, render_options)
        logger.info("Rendering %s interval groups", len(tasks))

        completed_file_list = self._run_tasks(
            tasks=tasks,
            input_file=input_file,
            output_file=output_file,
            render_options=render_options,
            separated_audio=separated_audio,
            on_render_progress_update=on_render_progress_update,
        )

        final_output = self._concat_rendered_files(
            completed_file_list=completed_file_list,
            on_concat_progress_update=on_concat_progress_update,
            output_file=output_file,
        )

        shutil.move(final_output, output_file)

        return [task.serialize() for task in tasks]
