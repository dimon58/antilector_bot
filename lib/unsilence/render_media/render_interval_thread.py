import logging
import queue
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from utils.video import MediaStreamType, can_copy_media_stream

from ..intervals.interval import Interval

# FFMpeg не позволяет делать скорость аудио меньше 0.5 или больше 100
# https://ffmpeg.org/ffmpeg-filters.html#atempo
FFMPEG_MIN_TEMPO = 0.5
FFMPEG_MAX_TEMPO = 100

logger = logging.getLogger(__name__)


class RenderIntervalThread(threading.Thread):
    """
    Worker thread that can render/process intervals based on defined options
    """

    def __init__(
        self,
        thread_id: int,
        input_file: Path,
        render_options: SimpleNamespace,
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
                    task.interval_output_file,
                    task.interval,
                    drop_corrupted_intervals=self._render_options.drop_corrupted_intervals,
                    minimum_interval_duration=self._render_options.minimum_interval_duration,
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
        interval_output_file: Path,
        interval: Interval,
        apply_filter: bool = True,
        drop_corrupted_intervals: bool = False,
        minimum_interval_duration: float = 0.25,
    ) -> bool:
        """
        Renders an interval with the given render options
        :param interval_output_file: Where the current output file should be saved
        :param interval: The current Interval that should be processed
        :param apply_filter: Whether the AV-Filter should be applied or if the media interval should be left untouched
        :param drop_corrupted_intervals: Whether to remove corrupted frames from the video or keep them in unedited
        :return: Whether it is corrupted or not
        """

        command = self.__generate_command(interval_output_file, interval, apply_filter, minimum_interval_duration)

        console_output = subprocess.run(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        if "Conversion failed!" in str(console_output.stdout).splitlines()[-1]:
            if drop_corrupted_intervals:
                return False
            if apply_filter:
                self.__render_interval(
                    interval_output_file,
                    interval,
                    apply_filter=False,
                    drop_corrupted_intervals=drop_corrupted_intervals,
                    minimum_interval_duration=minimum_interval_duration,
                )
            else:
                raise OSError(f"Input file is corrupted between {interval.start} and {interval.end} (in seconds)")

        if "Error initializing complex filter" in str(console_output.stdout):
            raise ValueError("Invalid render options")

        return True

    @staticmethod
    def _get_fade_filter(
        total_duration: float,
        interval_in_fade_duration: float,
        interval_out_fade_duration: float,
        fade_curve: str,
    ) -> str:

        res = []

        if interval_in_fade_duration != 0.0:
            res.append(f"afade=t=in:st=0:d={interval_in_fade_duration:.4f}:curve={fade_curve}")

        if interval_out_fade_duration != 0.0:
            res.append(
                f"afade=t=out"
                f":st={total_duration - interval_out_fade_duration:.4f}"
                f":d={interval_out_fade_duration:.4f}"
                f":curve={fade_curve}"
            )

        return ",".join(res)

    def __get_speed_and_volume(self, interval: Interval, minimum_interval_duration: float) -> tuple[float, float]:
        if interval.is_silent:
            current_speed = self._render_options.silent_speed
            current_volume = self._render_options.silent_volume
        else:
            current_speed = self._render_options.audible_speed
            current_volume = self._render_options.audible_volume
        current_speed = RenderIntervalThread.clamp_speed(interval.duration, current_speed, minimum_interval_duration)
        return current_speed, current_volume

    def __get_video_filter(self, current_speed: float) -> str | None:
        if not self._render_options.audio_only and current_speed != 1.0:
            video_filter = f"[0:v]setpts={round(1 / current_speed, 4)}*PTS[v]"
        else:
            video_filter = None

        logger.debug("Video filter: %s", video_filter)

        return video_filter

    @staticmethod
    def __get_audio_filter(fade: str, current_speed: float, current_volume: float) -> str | None:
        audio_filter_components: list[str] = []
        if fade != "":
            audio_filter_components.append(fade)

        if current_volume != 1.0:
            audio_filter_components.append(f"atempo={round(current_speed, 4)}")

        if current_volume != 1.0:
            audio_filter_components.append(f"volume={current_volume}")

        audio_filter: str | None
        if len(audio_filter_components) > 0:  # noqa: SIM108
            audio_filter = f"[0:a]{",".join(audio_filter_components)}[a]"
        else:
            audio_filter = None

        logger.debug("Audio filter: %s", audio_filter)

        return audio_filter

    def __generate_command(  # noqa: PLR0912
        self, interval_output_file: Path, interval: Interval, apply_filter: bool, minimum_interval_duration: float
    ) -> list[str]:
        """
        Generates the ffmpeg command to process the video
        :param interval_output_file: Where the media interval should be saved
        :param interval: The current interval
        :param apply_filter: Whether a filter should be applied or not
        :return: ffmpeg console command
        """
        fade = self._get_fade_filter(
            total_duration=interval.duration,
            interval_in_fade_duration=self._render_options.interval_in_fade_duration,
            interval_out_fade_duration=self._render_options.interval_out_fade_duration,
            fade_curve=self._render_options.fade_curve,
        )
        command = [
            "ffmpeg",
            "-ss",
            f"{interval.start}",
            "-to",
            f"{interval.end}",
            "-i",
            f"{self._input_file}",
            "-vsync",
            "1",
            "-async",
            "1",
            "-safe",
            "0",
            "-ignore_unknown",
            "-y",
        ]

        if apply_filter:

            current_speed, current_volume = self.__get_speed_and_volume(interval, minimum_interval_duration)

            complex_filter_components: list[str] = []

            # ----------------- video filter ----------------- #
            video_filter = self.__get_video_filter(current_speed)
            if video_filter is not None:
                complex_filter_components.append(video_filter)

            # ----------------- audio filter ----------------- #
            audio_filter = self.__get_audio_filter(fade, current_speed, current_volume)
            if audio_filter is not None:
                complex_filter_components.append(audio_filter)

            # ----------------- complex filter ----------------- #

            if len(complex_filter_components) > 0:
                complex_filter = ";".join(complex_filter_components)
                command.extend(["-filter_complex", complex_filter])
                logger.info("Using complex filter %s", complex_filter)
            else:
                logger.info("Not using complex filter")

            if not self._render_options.audio_only:
                if video_filter is not None:
                    command.extend(["-map", "[v]"])
                else:
                    command.extend(["-map", "0:v"])

            if audio_filter is not None:
                command.extend(["-map", "[a]"])
            else:
                command.extend(["-map", "0:a"])

        elif fade != "":
            command.extend(["-af", fade])
        elif can_copy_media_stream(self._input_file, interval_output_file, MediaStreamType.AUDIO):
            command.extend(["-c:a", "copy"])

        if self._render_options.audio_only:
            command.append("-vn")

        # if self._render_options.can_copy_video:
        #     logger.debug("Coping video stream for interval %s", interval)
        #     command.extend(["-c:v", "copy"])
        # else:
        #     logger.info("Transcoding video stream to FFmpeg choice for interval %s", interval)

        command.append(str(interval_output_file))

        return command

    @staticmethod
    def clamp_speed(duration: float, speed: float, minimum_interval_duration: float = 0.25) -> float:
        if duration / speed < minimum_interval_duration:
            speed = duration / minimum_interval_duration

        if speed < FFMPEG_MIN_TEMPO:
            logger.warning("Too low speed %g, minimum possible %s", speed, FFMPEG_MIN_TEMPO)
            return FFMPEG_MIN_TEMPO

        if speed > FFMPEG_MAX_TEMPO:
            logger.warning("Too high speed %g, maximum possible %s", speed, FFMPEG_MAX_TEMPO)
            return FFMPEG_MAX_TEMPO

        return speed
