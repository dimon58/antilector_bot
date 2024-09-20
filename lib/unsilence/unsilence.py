import logging
import shutil
from pathlib import Path

from ._typing import UpdateCallbackType
from .detect_silence.detect_silence import detect_silence
from .intervals.intervals import Intervals
from .intervals.time_calculations import TimeData, calculate_time
from .render_media.media_renderer import MediaRenderer
from .tools.ffmpeg_version import FFMpegStatus, is_ffmpeg_usable

logger = logging.getLogger(__name__)


class Unsilence:
    """
    Unsilence Class to remove (or isolate or many other use cases) silence from audible video parts
    """

    def __init__(self, input_file: Path):
        """
        :param input_file: The file that should be processed
        """
        self._input_file = Path(input_file)
        self._intervals: Intervals | None = None

        ffmpeg_status = is_ffmpeg_usable()
        if ffmpeg_status == FFMpegStatus.NOT_DETECTED:
            raise OSError("ffmpeg not found!")
        if ffmpeg_status == FFMpegStatus.REQUIREMENTS_UNSATISFIED:
            raise OSError("ffmpeg version not supported, a version >= 4.2.4 is required!")
        if ffmpeg_status == FFMpegStatus.UNKNOWN_VERSION:
            logger.warning("Could not detect ffmpeg version, proceed at your own risk! (version >= 4.2.4 required)")

    def detect_silence(
        self,
        silence_level: float = -35.0,
        silence_time_threshold: float = 0.5,
        short_interval_threshold: float = 0.3,
        stretch_time: float = 0.25,
        on_silence_detect_progress_update: UpdateCallbackType | None = None,
    ) -> Intervals:
        """
        Detects silence of the file (Options can be specified in kwargs)

        short_interval_threshold : The shortest allowed interval length (default: 0.3) (in seconds)
        stretch_time: Time the interval should be enlarged/shrunken (default 0.25) (in seconds)

        Remaining keyword arguments are passed to :func:`~unsilence.lib.detect_silence.DetectSilence.detect_silence`

        :return: A generated Intervals object
        :rtype: ~unsilence.lib.intervals.Intervals.Intervals
        """
        self._intervals = detect_silence(
            self._input_file,
            silence_level=silence_level,
            silence_time_threshold=silence_time_threshold,
            on_silence_detect_progress_update=on_silence_detect_progress_update,
        )

        self._intervals.optimize(short_interval_threshold, stretch_time)

        return self._intervals

    def set_intervals(self, intervals: Intervals) -> None:
        """
        Set the intervals so that they do not need to be re-detected

        :param intervals: Intervals collection
        :type intervals: ~unsilence.lib.intervals.Intervals.Intervals

        :return: None
        """
        self._intervals = intervals

    def get_intervals(self) -> Intervals:
        """
        Get the current Intervals so they can be reused if wanted

        :return: Intervals collection
        :rtype: ~unsilence.lib.intervals.Intervals.Intervals
        """
        return self._intervals

    def estimate_time(self, audible_speed: float = 1, silent_speed: float = 6) -> TimeData:
        """
        Estimates the time (savings) when the current options are applied to the intervals

        :param audible_speed: The speed at which the audible intervals get played back at
        :type audible_speed: float
        :param silent_speed: The speed at which the silent intervals get played back at
        :type silent_speed: float

        :raises: **ValueError** -- If silence detection was never run

        :return: Dictionary of time information
        :rtype: dict
        """
        if self._intervals is None:
            raise ValueError("Silence detection was not yet run and no intervals where given manually!")

        return calculate_time(self._intervals, audible_speed, silent_speed)

    def render_media(
        self,
        output_file: Path,
        temp_dir: Path = Path(".tmp"),
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
        Renders the current intervals with options specified in the kwargs

        output_file: Where the final file should be saved at
        temp_dir: The temp dir where temporary files can be saved

        Remaining keyword arguments are passed to :func:`~unsilence.lib.render_media.MediaRenderer.MediaRenderer.render`

        :return: None
        """
        if self._intervals is None:
            raise ValueError("Silence detection was not yet run and no intervals where given manually!")

        renderer = MediaRenderer(temp_dir)
        renderer.render(
            input_file=self._input_file,
            output_file=output_file,
            intervals=self._intervals,
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
            threads=threads,
            on_render_progress_update=on_render_progress_update,
            on_concat_progress_update=on_concat_progress_update,
        )

        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    def cleanup(self) -> None:
        """
        Cleans up the temporary directories, called automatically when the program ends

        :return: None
        """
