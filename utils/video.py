import enum
import logging
import os
import subprocess  # nosec: B404
from pathlib import Path

import orjson
from ffmpeg import FFmpegError

from utils.fixed_ffmpeg import FixedFFmpeg
from utils.pathtools import split_filename_ext
from utils.progress_bar import setup_progress_for_ffmpeg

logger = logging.getLogger(__name__)

# https://ru.wikipedia.org/wiki/MPEG-4_Part_14
mp4_aliases = (
    # Оригинально расширение
    "mp4",
    # Компания Apple активно использует контейнер MP4,
    # но использует собственные, не предусмотренные стандартом, расширения файла:
    # Аудиофайл, содержащий поток в формате AAC или ALAC. Может быть переименован в .mp4
    "m4a",
    # Файл содержащий аудио- и видеопотоки. Может быть переименован в .mp4
    "m4v",
    # Файл AAC, поддерживающий закладки. Используется для аудиокниг и подкастов,
    # используется в онлайн-магазинах, подобных Apple iTunes Store
    "m4b",
    # Защищённый файл AAC.
    # Используется для защиты файла от копирования при легальной загрузке
    # собственнической музыки в онлайн-магазинах, подобных Apple iTunes Store;
    "m4p",
    # Файл рингтона используемый в Apple iOS.
    "m4r",
)

# Список кодеков, которые FFMpeg 6.1.1 позволяет упаковывать в mp4
mp4_possible_video_codecs = {
    "h264",
    "hevc",
    "vp9",
    "av1",
    # Старые кодеки
    "mpeg1video",
    "mpeg2video",
    "mpeg4",
    # Далее идут совсем странные кодеки
    "dirac",
    "jpeg2000",
    "mjpeg",
    "png",
}

# Только это нормально нагуглил
mp4_possible_audio_codecs = {"acc"}


class MediaStreamType(enum.StrEnum):
    AUDIO = "a"
    VIDEO = "v"


def get_media_codecs(input_file: Path, media_stream_type: MediaStreamType) -> list[str]:
    if media_stream_type not in MediaStreamType:
        raise ValueError(f"media_stream_type must be {MediaStreamType.__name__}, not {media_stream_type}")

    # ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0
    process = subprocess.Popen(  # noqa: S603 # nosec: B603, B607
        [  # noqa: S607
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            str(media_stream_type),
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            os.fspath(input_file),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = process.communicate()
    retcode = process.poll()
    if retcode:
        raise FFmpegError.create(f"ffmpeg return code {retcode}: {err}", [])

    return [codec for codec in out.strip().decode("utf-8").split(",") if codec]


def can_copy_media_stream(input_file: Path, output_file: Path, media_stream_type: MediaStreamType) -> bool:
    """
    Возвращает можно ли копировать видеопоток из input_file в output_file без перекодирования
    """

    if media_stream_type not in MediaStreamType:
        raise ValueError(f"media_stream_type must be {MediaStreamType.__name__}, not {media_stream_type}")

    _, ext_in = split_filename_ext(input_file)
    _, ext_out = split_filename_ext(output_file)

    if ext_in == ext_out:
        return True

    # В основном выходным файлом будет mp4, поэтому больше специализируемся на его него
    # Остальные форматы можно рассмотреть отдельно, но пока нет смысла
    if ext_out not in mp4_aliases:
        return False

    # Вход и выход mp4
    if ext_in in mp4_aliases:
        return True

    if media_stream_type == MediaStreamType.VIDEO:
        mp4_possible_codecs = mp4_possible_video_codecs
    elif media_stream_type == MediaStreamType.AUDIO:
        mp4_possible_codecs = mp4_possible_audio_codecs

    # Если все кодеки из входного файла можно поместить в mp4, то разрешаем копирование
    input_codecs = get_media_codecs(input_file, media_stream_type)
    return len(set(input_codecs) - mp4_possible_codecs) == 0


def get_video_duration(filename: str | Path) -> float:
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


def replace_audio_in_video(video_file: Path, audio_file: Path, output_file: Path) -> None:
    """
    Заменяет аудиопоток в video_file на аудиопоток из audio_file и сохраняет в output_file
    """
    output_options = {"async": 1, "vsync": 1, "map": ["0:v", "1:a"]}

    if can_copy_media_stream(video_file, output_file, MediaStreamType.VIDEO):
        output_options["c:v"] = "copy"
        logger.info("Coping video stream")
    else:
        logger.info("Transcoding video stream")

    if can_copy_media_stream(video_file, output_file, MediaStreamType.AUDIO):
        output_options["a:v"] = "copy"
        logger.info("Coping audio stream")
    else:
        logger.info("Transcoding audio stream")

    ffmpeg = (
        FixedFFmpeg()
        .option("y")
        .input(video_file.as_posix())
        .input(audio_file.as_posix())
        .output(output_file.as_posix(), output_options)
    )

    setup_progress_for_ffmpeg(ffmpeg, get_video_duration(video_file), "Replacing audio in video")

    ffmpeg.execute()
