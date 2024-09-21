import os
import subprocess  # nosec: B404
from pathlib import Path

import orjson
from ffmpeg import FFmpegError

from utils.fixed_ffmpeg import FixedFFmpeg
from utils.pathtools import split_filename_ext
from utils.progress_bar import setup_progress_for_ffmpeg


def can_copy_video_stream(input_file: Path, output_file: Path):
    """
    Возвращает можно ли копировать видеопоток из input_file в output_file без перекодирования
    """
    _, ext_in = split_filename_ext(input_file)
    _, ext_out = split_filename_ext(output_file)

    if ext_in == ext_out:
        return True

    # TODO

    return False


def can_copy_audio_stream(input_file: Path, output_file: Path):
    """
    Возвращает можно ли копировать аудиопоток из input_file в output_file без перекодирования
    """
    _, ext_in = split_filename_ext(input_file)
    _, ext_out = split_filename_ext(output_file)

    if ext_in == ext_out:
        return True

    # TODO

    return False


def get_video_duration(filename: str | Path):
    """
    Возвращает длительность видео
    """

    process = subprocess.Popen(  # noqa: S603 # nosec: B603, B607
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            os.fspath(filename),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = process.communicate()
    retcode = process.poll()
    if retcode:
        raise FFmpegError.create(f"ffmpeg return code {retcode}: {err}", [])

    return float(out)


def get_video_resolution(filename: str | Path) -> tuple[int, int]:
    """
    Возвращает разрешение первой видеодорожки в видео в кортеже (ширина, высота)
    """

    # ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 input.mp4
    process = subprocess.Popen(  # noqa: S603 # nosec: B603, B607
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json=compact=1",
            os.fspath(filename),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = process.communicate()
    retcode = process.poll()
    if retcode:
        raise FFmpegError.create(f"ffmpeg return code {retcode}: {err}", [])

    try:
        data = orjson.loads(out)
    except orjson.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode json: {out}") from exc
    stream = data["streams"][0]

    return stream["width"], stream["height"]


def replace_audio_in_video(video_file: Path, audio_file: Path, output_file: Path):
    options = {"async": 1, "vsync": 1, "map": ["0:v", "1:a"]}
    if can_copy_video_stream(video_file, output_file):
        options["c:v"] = "copy"

    if can_copy_audio_stream(audio_file, output_file):
        options["a:v"] = "copy"

    ffmpeg = (
        FixedFFmpeg()
        .option("y")
        .input(video_file.as_posix())
        .input(audio_file.as_posix())
        .output(output_file.as_posix(), options)
    )

    setup_progress_for_ffmpeg(ffmpeg, get_video_duration(video_file), "Replacing audio in video")

    ffmpeg.execute()
