import time
from functools import partial
from pathlib import Path

import lazy_object_proxy
import torch
from faster_whisper import WhisperModel
from tqdm import tqdm

from configs import (
    TORCH_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DOWNLOAD_ROOT,
    WHISPER_MIN_SILENCE_DURATION_MS,
    WHISPER_MODEL_SIZE,
)
from processing.models.lecture_summary import TranscriptionStats
from utils.torch_utils import is_cuda

whisper_model = lazy_object_proxy.Proxy(
    partial(
        WhisperModel,
        WHISPER_MODEL_SIZE,
        device=TORCH_DEVICE.type,
        device_index=TORCH_DEVICE.index,
        compute_type=WHISPER_COMPUTE_TYPE,
        download_root=WHISPER_DOWNLOAD_ROOT,
    )
)


def transcribe(audio_file: Path) -> tuple[str, TranscriptionStats]:
    try:
        start = time.perf_counter()
        segments, info = whisper_model.transcribe(
            audio_file.absolute().as_posix(),
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": WHISPER_MIN_SILENCE_DURATION_MS,
            },
        )

        pbar = tqdm(total=info.duration, desc="Transcribing")

        texts = []
        for segment in segments:
            pbar.update(segment.end - pbar.n)
            texts.append(segment.text)

        if pbar.n < info.duration:
            pbar.update(info.duration - pbar.n)

        joined_texts = "\n".join(texts)
        end = time.perf_counter()

        # noinspection PyProtectedMember
        return joined_texts, TranscriptionStats(
            processing_time=end - start,
            whisper_model_size=WHISPER_MODEL_SIZE,
            whisper_compute_type=WHISPER_COMPUTE_TYPE,
            # Convert NamedTuple to dict
            # https://stackoverflow.com/questions/26180528/convert-a-namedtuple-into-a-dictionary
            # https://stackforgeeks.com/blog/convert-a-namedtuple-into-a-dictionary
            transcription_info=info._asdict(),
        )
    finally:
        if is_cuda(TORCH_DEVICE):
            torch.cuda.empty_cache()
