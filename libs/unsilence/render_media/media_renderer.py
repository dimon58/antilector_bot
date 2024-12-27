import logging
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from utils.video.modify import concat_media_files

from .._typing import UpdateCallbackType  # noqa: TID252
from ..intervals.intervals import Intervals  # noqa: TID252
from ..render_media.render_interval_thread import RenderIntervalThread  # noqa: TID252
from .options import RenderOptions

logger = logging.getLogger(__name__)


class MediaRenderer:
    """
    The Media Renderer handles the rendering of Intervals objects, so it processes the complete video and concatenates
    the different intervals at the end
    """

    def __init__(self, temp_path: Path):
        """
        Initializes a new MediaRenderer Object
        :param temp_path: The temp path where all temporary files should be stored
        """
        self._temp_path = Path(temp_path).absolute()

    def render(  # noqa: PLR0913
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

        # # Копируем видеопоток, если
        # # файлы должны иметь одинаковое расширение, не должно быть ускорения и видео должно быть
        # # Это частый случай, поэтому оптимизация даёт серьезный рост производительности
        # can_copy_video = can_copy_media_stream(input_file, output_file, MediaStreamType.VIDEO)  # noqa: ERA001
        # if can_copy_video:
        #     original_codec = get_media_codecs(input_file, MediaStreamType.VIDEO)[0]  # noqa: ERA001
        # else:  # noqa: ERA001
        #     original_codec = None  # noqa: ERA001
        # original_codec: str | None  # noqa: ERA001

        intervals = intervals.remove_short_intervals_from_start(
            render_options.audible_speed, render_options.silent_speed
        )

        video_temp_path = self._temp_path / str(uuid.uuid4())
        video_temp_path.mkdir(parents=True)

        concat_file = video_temp_path / "concat_list.txt"
        final_output = video_temp_path / f"out_final{output_file.suffix}"

        file_list = []

        thread_lock = threading.Lock()
        task_queue = queue.Queue()
        thread_list = []
        completed_tasks = []
        corrupted_intervals = []

        def handle_thread_completed_task(completed_task: SimpleNamespace, corrupted: bool) -> None:
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
                    on_render_progress_update(len(completed_tasks), len(intervals.intervals))
            else:
                corrupted_intervals.append(completed_task)

            thread_lock.release()

        logger.info("Spawning %s threads for rendering intervals", render_options.threads)
        for i in range(render_options.threads):
            thread = RenderIntervalThread(
                i, input_file, render_options, task_queue, thread_lock, on_task_completed=handle_thread_completed_task
            )
            thread.start()
            thread_list.append(thread)

        if render_options.use_nvenc:
            logger.info("Using nvenc")
        else:
            logger.info("Encoding on cpu")
        for i, interval in enumerate(intervals.intervals):
            current_file_name = f"out_{i}{output_file.suffix}"
            current_path = video_temp_path / current_file_name

            file_list.append(current_path)

            task = SimpleNamespace(
                task_id=i,
                total_tasks=len(intervals.intervals),
                interval_output_file=current_path,
                interval=interval,
            )

            thread_lock.acquire()
            task_queue.put(task)
            thread_lock.release()

        while len(completed_tasks) < (len(intervals.intervals) - len(corrupted_intervals)):
            time.sleep(0.5)

        for thread in thread_list:
            thread.stop()

        completed_file_list = [task.interval_output_file for task in sorted(completed_tasks, key=lambda x: x.task_id)]

        MediaRenderer._concat_intervals(
            file_list=completed_file_list,
            concat_file=concat_file,
            output_file=final_output,
            update_concat_progress=on_concat_progress_update,
        )

        shutil.move(final_output, output_file)

    @staticmethod
    def _concat_intervals(
        file_list: list[Path], concat_file: Path, output_file: Path, update_concat_progress: UpdateCallbackType | None
    ) -> None:
        """
        Concatenates all interval files to create a finished file
        :param file_list: List of interval files
        :param concat_file: Where the ffmpeg concat filter file should be saved
        :param output_file: Where the final output file should be saved
        :param update_concat_progress: A function that is called when a step is finished
            (called like function(current, total))
        :return: None
        """

        console_output = concat_media_files(
            input_files=file_list,
            output_file=output_file,
            concat_file=concat_file,
        )

        total_files = len(file_list)
        current_file = 0
        for line in console_output.stdout:
            if "Auto-inserting" in line and update_concat_progress is not None:
                current_file += 1
                update_concat_progress(current_file, total_files)
