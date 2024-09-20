import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from .._typing import UpdateCallbackType
from ..intervals.intervals import Intervals
from ..render_media.render_interval_thread import RenderIntervalThread


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
        self.__temp_path = Path(temp_path).absolute()

    def render(
        self,
        input_file: Path,
        output_file: Path,
        intervals: Intervals,
        audio_only: bool = False,
        audible_speed: float = 1,
        silent_speed: float = 6,
        audible_volume: float = 1,
        silent_volume: float = 0.5,
        drop_corrupted_intervals: bool = False,
        check_intervals: bool = False,
        minimum_interval_duration: float = 0.25,
        interval_in_fade_duration: float = 0.01,
        interval_out_fade_duration: float = 0.01,
        fade_curve: str = "tri",
        threads: int = 2,
        on_render_progress_update: UpdateCallbackType | None = None,
        on_concat_progress_update: UpdateCallbackType | None = None,
    ) -> None:
        """
        Renders an input_file and writes the final output to output_file

        :param input_file: The file that should be processed
        :param output_file: Where the processed file should be saved
        :param intervals: The Intervals that should be processed
        :param audio_only: Whether the output should be audio only
        :param audible_speed: The speed at which the audible intervals get played back at
        :param silent_speed: The speed at which the silent intervals get played back at
        :param audible_volume: The volume at which the audible intervals get played back at
        :param silent_volume: The volume at which the silent intervals get played back at
        :param drop_corrupted_intervals: Whether corrupted video intervals should be discarded or tried to recover
        :param check_intervals: Need to check corrupted intervals
        :param minimum_interval_duration: Minimum duration of result interval
        :param interval_in_fade_duration: Fade duration at interval start
        :param interval_out_fade_duration: Fade duration at interval end
        :param fade_curve: Set curve for fade transition. (https://ffmpeg.org/ffmpeg-filters.html#afade-1)
        :param threads: Number of threads to render simultaneously (int > 0)
        :param on_render_progress_update: Function that should be called on render progress update
            (called like: func(current, total))
        :param on_concat_progress_update: Function that should be called on concat progress update
            (called like: func(current, total))
        """
        input_file = Path(input_file).absolute()
        output_file = Path(output_file).absolute()

        if not input_file.exists():
            raise FileNotFoundError(f"Input file {input_file} does not exist!")

        render_options = SimpleNamespace(
            audio_only=audio_only,
            audible_speed=audible_speed,
            silent_speed=silent_speed,
            audible_volume=audible_volume,
            silent_volume=silent_volume,
            drop_corrupted_intervals=drop_corrupted_intervals,
            check_intervals=check_intervals,
            minimum_interval_duration=minimum_interval_duration,
            interval_in_fade_duration=interval_in_fade_duration,
            interval_out_fade_duration=interval_out_fade_duration,
            fade_curve=fade_curve,
        )

        intervals = intervals.remove_short_intervals_from_start(
            render_options.audible_speed, render_options.silent_speed
        )

        video_temp_path = self.__temp_path / str(uuid.uuid4())
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

        for i in range(threads):
            thread = RenderIntervalThread(
                i, input_file, render_options, task_queue, thread_lock, on_task_completed=handle_thread_completed_task
            )
            thread.start()
            thread_list.append(thread)

        for i, interval in enumerate(intervals.intervals):
            current_file_name = f"out_{i}{output_file.suffix}"
            current_path = video_temp_path / current_file_name

            file_list.append(current_path)

            task = SimpleNamespace(task_id=i, interval_output_file=current_path, interval=interval)

            thread_lock.acquire()
            task_queue.put(task)
            thread_lock.release()

        while len(completed_tasks) < (len(intervals.intervals) - len(corrupted_intervals)):
            time.sleep(0.5)

        for thread in thread_list:
            thread.stop()

        completed_file_list = [task.interval_output_file for task in sorted(completed_tasks, key=lambda x: x.task_id)]

        MediaRenderer.__concat_intervals(
            file_list=completed_file_list,
            concat_file=concat_file,
            output_file=final_output,
            update_concat_progress=on_concat_progress_update,
        )

        shutil.move(final_output, output_file)
        shutil.rmtree(video_temp_path)

    @staticmethod
    def __concat_intervals(
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
        total_files = len(file_list)

        with concat_file.open("w+") as file:
            lines = [f"file {interval_file.name}\n" for interval_file in file_list]
            file.writelines(lines)

        command = [
            "ffmpeg",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            f"{concat_file.as_posix()}",
            "-c",
            "copy",
            "-y",
            "-loglevel",
            "verbose",
            f"{output_file.as_posix()}",
        ]

        console_output = subprocess.Popen(  # noqa: S603
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
        )

        current_file = 0
        for line in console_output.stdout:
            if "Auto-inserting" in line and update_concat_progress is not None:
                current_file += 1
                update_concat_progress(current_file, total_files)
