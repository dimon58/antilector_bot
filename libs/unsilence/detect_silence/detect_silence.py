import logging
import re
import shlex
import subprocess
from pathlib import Path

from .._typing import UpdateCallbackType  # noqa: TID252
from ..intervals.intervals import Interval, Intervals  # noqa: TID252

logger = logging.getLogger(__name__)


def detect_silence(  # noqa: C901
    input_file: Path,
    silence_level: float = -35.0,
    silence_time_threshold: float = 0.5,
    on_silence_detect_progress_update: UpdateCallbackType | None = None,
) -> Intervals:
    """
    Detects silence in a file and outputs the intervals (silent/not silent) as a lib.Intervals.Intervals object

    :param input_file: File where silence should be detected
    :param silence_level: Threshold of what should be classified as silent/audible (default -35) (in dB)
    :param silence_time_threshold: Resolution of the ffmpeg detection algorithm (default 0.5) (in seconds)
    :param on_silence_detect_progress_update: Function that should be called on progress update
            (called like: func(current, total))
    """
    input_file = Path(input_file).absolute()

    if not input_file.exists():
        raise FileNotFoundError(f"Input file {input_file} does not exist!")

    command = [
        "ffmpeg",
        "-i",
        str(input_file),
        "-vn",
        "-af",
        f"silencedetect=noise={silence_level}dB:d={silence_time_threshold}",
        "-f",
        "null",
        "-",
    ]

    logger.debug("Executing ffmpeg command: %s", shlex.join(command))

    console_output = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    ).stdout

    intervals = Intervals()
    current_interval = Interval(start=0, end=0, is_silent=False)
    media_duration = None

    for line in console_output:
        if "[silencedetect" in line:
            capture = re.search("\\[silencedetect @ [0-9xa-f]+] silence_([a-z]+): (-?[0-9]+.?[0-9]*[e-]*[0-9]*)", line)
            if capture is None:
                continue

            event = capture[1]
            time = float(capture[2])

            if on_silence_detect_progress_update is not None:
                on_silence_detect_progress_update(time, media_duration)

            if event == "start":
                if current_interval.start != time:
                    current_interval.end = time
                    intervals.add_interval(current_interval)
                current_interval = Interval(start=time, is_silent=True)

            if event == "end":
                current_interval.end = time
                intervals.add_interval(current_interval)
                current_interval = Interval(start=time, is_silent=False)

        elif "Duration" in line:
            capture = re.search("Duration: ([0-9:]+.?[0-9]*)", line)
            if capture is None:
                continue
            hour, minute, second_millisecond = capture[1].split(":")
            second, millisecond = second_millisecond.split(".")
            media_duration = float(str(int(second) + 60 * (int(minute) + 60 * int(hour))) + "." + millisecond)

    current_interval.end = media_duration
    intervals.add_interval(current_interval)

    if on_silence_detect_progress_update is not None:
        on_silence_detect_progress_update(media_duration, media_duration)

    return intervals
