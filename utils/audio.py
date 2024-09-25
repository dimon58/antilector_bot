import logging
import os
import re
import shlex
import subprocess  # nosec: B404
import tempfile
import time
from pathlib import Path

import soundfile
import torch
import torchaudio
from ffmpeg import FFmpegError

from configs import TORCH_DEVICE, USE_CUDA
from utils.fixed_ffmpeg import FixedFFmpeg
from utils.pathtools import PathType
from utils.progress_bar import setup_progress_for_ffmpeg
from utils.video.measure import get_video_duration

logger = logging.getLogger(__name__)


def _read_audio_tensor(path: Path, sample_rate: int | None = None) -> tuple[torch.Tensor, int]:
    """
    Возвращает аудио тензор для музыки или видео

    :param path: путь до файла
    :return: тензор и частоту дискретизации
    """
    _, ext = os.path.splitext(path)  # noqa: PTH122
    ext = ext[1:]  # удаляем точку спереди

    if soundfile.check_format(ext):
        logger.info("Loading audio")
        return torchaudio.load(path, backend="soundfile")

    s = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = os.path.join(temp_dir, "audio.wav")  # noqa: PTH118
        opts = {"ac": 1}
        if sample_rate is not None:
            opts["ar"] = sample_rate
        ffmpeg = FixedFFmpeg().option("y").input(path).output(output_file, **opts)
        setup_progress_for_ffmpeg(ffmpeg, get_video_duration(path), "Transforming to wav")
        logger.debug("FFmpeg call: %s", ffmpeg.arguments)
        ffmpeg.execute()
        e = time.perf_counter()
        logger.info("Transformation to wav done in %s sec", e - s)

        return torchaudio.load(output_file)


def read_audio(path: PathType, sample_rate: int | None = None) -> tuple[torch.Tensor, int]:
    """
    Читает аудио из файла и преобразует к требуемой частоте дискретизации
    """
    path = Path(path)

    wav, sr = _read_audio_tensor(path, sample_rate)

    if wav.size(0) > 1:
        logger.info("Converting to mono")
        wav = wav.mean(dim=0, keepdim=True)

    if sample_rate is not None and sr != sample_rate:
        logger.info("Resampling on %s from %s to %s", "cuda" if USE_CUDA else "cpu", sr, sample_rate)
        transform = torchaudio.transforms.Resample(orig_freq=sr, new_freq=sample_rate)

        if USE_CUDA:  # noqa: SIM108
            wav = transform.to(TORCH_DEVICE)(wav.to(TORCH_DEVICE)).cpu()
        else:
            wav = transform(wav)
        sr = sample_rate

    return wav.squeeze(0), sr


def measure_volume(filename: PathType) -> float:
    """
    Возвращает среднюю громкость видео в ДБ
    """

    path = Path(filename).as_posix()

    process = subprocess.Popen(  # noqa: S603 # nosec: B603, B607
        [  # noqa: S607
            "ffprobe",
            "-f",
            "lavfi",
            "-i",
            f"amovie={shlex.quote(path)}, volumedetect",
            "-show_entries",
            "frame_tags=lavfi.volumedetect.mean_volume",
            "-of",
            "default=nw=1:nk=1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = process.communicate()
    retcode = process.poll()
    if retcode:
        raise FFmpegError.create(err.decode("utf-8"), [])

    # ffrobe пишет в stderr
    err_str = err.decode("utf-8")

    rms_match = re.search(r"mean_volume:\s*(.+)\s*dB", err_str)
    if rms_match is None:
        raise ValueError(f"Failed to get volume from ffrobe output: {err_str}")

    return float(rms_match.group(1))
