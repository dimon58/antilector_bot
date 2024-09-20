import enum
import re
import subprocess

from pkg_resources import parse_version


class FFMpegStatus(enum.Enum):
    NOT_DETECTED = "not_detected"
    USABLE = "usable"
    REQUIREMENTS_UNSATISFIED = "requirements_unsatisfied"
    UNKNOWN_VERSION = "unknown_version"


def is_ffmpeg_usable() -> FFMpegStatus:
    try:
        console_output = subprocess.run(  # noqa: S603
            ["ffmpeg", "-version"],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        ).stdout
    except FileNotFoundError:
        return FFMpegStatus.NOT_DETECTED

    console_output = str(console_output)

    regex = r"libavutil\s*((?:\d+\.\s*){2}\d+)"
    match = re.search(regex, str(console_output))

    if match:
        groups = match.groups()
        version_string = "".join(groups[0].split())

        # Version 56.31.100 is the libavutil version used in the ffmpeg release 4.2.4 "Ada"
        if parse_version(version_string) >= parse_version("56.31.100"):
            return FFMpegStatus.USABLE

        return FFMpegStatus.REQUIREMENTS_UNSATISFIED

    return FFMpegStatus.UNKNOWN_VERSION
