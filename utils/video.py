import copy
import enum
import logging
import os
import shlex
import subprocess  # nosec: B404
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import orjson
from ffmpeg import FFmpegError

from configs import TQDM_LOGGING_INTERVAL
from utils.fixed_ffmpeg import FixedFFmpeg
from utils.pathtools import split_filename_ext
from utils.progress_bar import ProgressBar, setup_progress_for_ffmpeg

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


def ensure_nvenc_correct(use_nvenc: bool, force_video_codec: str | None):
    if not use_nvenc:
        return

    if force_video_codec is None:
        raise ValueError("You must specify video codec to use nvenc acceleration in ffmpeg")

    allowed_codecs = ("hevc_nvenc", "h264_nvenc", "av1_nvenc")  # todo: calculate based on gpu
    if force_video_codec not in allowed_codecs:
        raise ValueError(f"Video codec must be in {allowed_codecs} if you use nvenc, got {force_video_codec}")


def resolve_media_codec(
    input_file: Path,
    output_file: Path,
    codec: str | None,
    force_transcode: bool,
    media_stream_type: MediaStreamType,
) -> str | None:
    original_codec = get_media_codecs(input_file, media_stream_type)[0]

    if codec is not None:
        # Handle nvenc
        new_codec_repr = codec[:-6] if codec.endswith("_nvenc") else codec

        if not force_transcode and original_codec == new_codec_repr:
            logger.info("Coping %s stream", media_stream_type.name.lower())
            return "copy"

        logger.info("Transcoding %s stream from %s to %s", media_stream_type.name.lower(), original_codec, codec)
        return codec

    if not force_transcode and can_copy_media_stream(input_file, output_file, media_stream_type):
        logger.info("Coping %s stream", media_stream_type.name.lower())
        return "copy"

    logger.info("Transcoding %s stream from %s to ffmpeg choice", media_stream_type.name.lower(), original_codec)
    return None


def concat_media_files(
    input_files: Sequence[Path],
    output_file: Path,
    concat_file: Path,
) -> subprocess.Popen:
    """
    Объединяет медиафайлы

    :param input_files: список файлов для объединения
    :param output_file: выходной файл
    :param concat_file: файл, в котором можно временно сохранить списки для объединения
    """
    with concat_file.open("w+") as file:
        lines = [f"file {interval_file.name}\n" for interval_file in input_files]
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

    return subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def concat_media_files_with_progress(
    input_files: Sequence[Path],
    output_file: Path,
    concat_file: Path,
):
    """
    Объединяет медиафайлы

    :param input_files: список файлов для объединения
    :param output_file: выходной файл
    :param concat_file: файл, в котором можно временно сохранить списки для объединения
    """
    console_output = concat_media_files(input_files=input_files, output_file=output_file, concat_file=concat_file)

    total_files = len(input_files)
    progress = ProgressBar(
        desc="Concatenating media files",
        mininterval=TQDM_LOGGING_INTERVAL,
        set_total_on_close=True,
    )
    progress.set_total(total_files)

    current_file = 0
    for line in console_output.stdout:
        if "Auto-inserting" in line:
            current_file += 1
            progress.update(current_file)

    progress.close()


def replace_audio_in_video(
    video_file: Path,
    audio_file: Path,
    output_file: Path,
    use_nvenc: bool = False,
    video_codec: str | None = None,
    audio_codec: str | None = None,
    force_transcode_video: bool = False,
    force_transcode_audio: bool = False,
    threads: int = 1,
    temp_dir: Path | None = None,
) -> None:
    """
    Заменяет аудиопоток в video_file на аудиопоток из audio_file и сохраняет в output_file
    """

    if threads > 1 and temp_dir is None:
        raise ValueError("You need to set temp_dir if you want to use multithreading")

    ensure_nvenc_correct(use_nvenc, video_codec)

    if use_nvenc:
        logger.info("Using nvenc")
        video_input_options = {
            "hwaccel": "cuda",
            "hwaccel_output_format": "cuda",
        }
    else:
        video_input_options = {}

    output_options = {"async": 1, "vsync": 1, "map": ["0:v", "1:a"]}

    audio_codec = resolve_media_codec(
        input_file=audio_file,
        output_file=output_file,
        codec=audio_codec,
        force_transcode=force_transcode_audio,
        media_stream_type=MediaStreamType.AUDIO,
    )
    if audio_codec is not None:
        output_options["c:a"] = audio_codec

    video_codec = resolve_media_codec(
        input_file=video_file,
        output_file=output_file,
        codec=video_codec,
        force_transcode=force_transcode_video,
        media_stream_type=MediaStreamType.VIDEO,
    )
    if video_codec is not None:
        output_options["c:v"] = video_codec

    def worker(_idx: int, _start: float, _end: float, single: bool, local_output_file: Path) -> None:
        if single:
            local_audio_input_options = {}
            local_video_input_options = video_input_options
        else:
            local_audio_input_options = {"ss": _start, "to": _end}
            local_video_input_options = copy.deepcopy(video_input_options)
            local_video_input_options |= local_audio_input_options  # Нужно только ss и to

        ffmpeg = (
            FixedFFmpeg()
            .option("y")
            .input(video_file.as_posix(), local_video_input_options)
            .input(audio_file.as_posix(), local_audio_input_options)
            .output(local_output_file.as_posix(), output_options)
        )

        desc = "Replacing audio in video"
        if not single:
            desc = f"[thread {_idx}] {desc}"
        setup_progress_for_ffmpeg(ffmpeg, _end - _start, desc)

        logger.debug("Call: %s", shlex.join(ffmpeg.arguments))

        ffmpeg.execute()

    # Если поток 1, то просто запускаем
    duration = get_video_duration(video_file)
    if threads < 2:  # noqa: PLR2004
        worker(0, 0, duration, single=True, local_output_file=output_file)
        return

    # Во время тестирования нормально работало до 8 потоков.
    # На 10 появлялась ошибка: OpenEncodeSessionEx failed: incompatible client key (21): (no details)
    if threads > 8:  # noqa: PLR2004
        logger.warning("Too many threads for nvenc. Possibly unstable work.")

    media_part_paths: list[Path] = []
    thread_list = []
    for idx in range(threads):
        start = idx * duration / threads
        end = (idx + 1) * duration / threads

        local_output_file = temp_dir / f"part_{idx}{output_file.suffix}"
        media_part_paths.append(local_output_file)

        logger.debug("Spawning thread %s", idx)
        thread = threading.Thread(target=worker, args=(idx, start, end, False, local_output_file))
        thread.start()
        thread_list.append(thread)

    for thread in thread_list:
        thread.join()

    media_part_paths = cast(list[Path], media_part_paths)

    concat_file = temp_dir / "concat_list.txt"
    concat_media_files_with_progress(media_part_paths, output_file, concat_file)
