import copy
import logging
import shlex
import subprocess  # nosec: B404
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from configs import TQDM_LOGGING_INTERVAL
from utils.fixed_ffmpeg import FixedFFmpeg
from utils.progress_bar import ProgressBar, setup_progress_for_ffmpeg

from .measure import MediaStreamType, can_copy_media_stream, get_media_codecs, get_video_duration
from .misc import ensure_nvenc_correct

logger = logging.getLogger(__name__)


def resolve_media_codec(
    input_file: Path,
    output_file: Path,
    codec: str | None,
    media_stream_type: MediaStreamType,
    *,
    force_transcode: bool,
) -> str | None:
    original_codec = get_media_codecs(input_file, media_stream_type)[0]

    if codec is not None:
        # Handle nvenc
        new_codec_repr = codec.removesuffix("_nvenc")

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
        "-movflags",
        "+faststart",
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
) -> None:
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


def replace_audio_in_video(  # noqa: C901, PLR0913
    video_file: Path,
    audio_file: Path,
    output_file: Path,
    *,
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

    ensure_nvenc_correct(use_nvenc, video_codec, threads)

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

    def worker(_idx: int, _start: float, _end: float, single: bool, local_output_file: Path) -> None:  # noqa: FBT001
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
