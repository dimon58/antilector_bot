import logging
import math
import time
from pathlib import Path
from typing import Any, Literal, Self

import pydantic
import torch
from df import init_df
from df.enhance import DEFAULT_MODEL, enhance
from df.io import load_audio, save_audio
from df.utils import get_device
from libdf import DF
from pydantic import ConfigDict, Field
from torch import nn
from torchaudio import AudioMetaData

from configs import MAX_DEEPFILTERNET_CHUNK_SIZE_BYTES
from utils.formating import get_bytes_size_format
from utils.logging_tqdm import LoggingTQDM
from utils.torch_utils import get_byte_size_of_tensor, is_cuda

from .abstract import Action, ActionStatsType

logger = logging.getLogger(__name__)


class CudaMemoryUsageAtStep(pydantic.BaseModel):
    measure_time: float

    reserved: int

    max_allocated: int
    max_reserved: int

    memory_stats: dict[str, Any]

    @classmethod
    def measure(cls, device: torch.device) -> "CudaMemoryUsageAtStep":
        start = time.perf_counter()
        memory_stats = torch.cuda.memory_stats(device)
        end = time.perf_counter()

        return cls(
            measure_time=end - start,
            max_allocated=memory_stats.get("allocated_bytes.all.peak", 0),
            reserved=memory_stats.get("reserved_bytes.all.current", 0),
            max_reserved=memory_stats.get("reserved_bytes.all.peak", 0),
            memory_stats=memory_stats,
        )


class CudaMemoryUsageStats(pydantic.BaseModel):
    _audio_offset_bytes: float
    _target_allocation_size: float
    _target_allocation_size_threshold: float

    _device: torch.device

    device_type: str
    device_index: int | None

    trace: list[CudaMemoryUsageAtStep] = []

    @classmethod
    def init(
        cls, device: torch.device, target_allocation_size: float, target_allocation_size_threshold: float
    ) -> "CudaMemoryUsageStats":
        usage = CudaMemoryUsageAtStep.measure(device)

        logger.debug(
            "Cuda memory initial max allocated %s (reserved %s)",
            get_bytes_size_format(usage.max_allocated, stop_at="M"),
            get_bytes_size_format(usage.reserved, stop_at="M"),
        )

        instance = cls(
            device_type=device.type,
            device_index=device.index,
            trace=[usage],
        )

        instance._device = device  # noqa: SLF001
        instance._audio_offset_bytes = 0  # noqa: SLF001
        instance._target_allocation_size = target_allocation_size  # noqa: SLF001
        instance._target_allocation_size_threshold = target_allocation_size_threshold  # noqa: SLF001

        return instance

    def log_memory_usage(self, audio_chunk: torch.Tensor) -> None:
        usage = CudaMemoryUsageAtStep.measure(self._device)
        self.trace.append(usage)

        initial_usage = self.trace[0]

        audio_chunk_size_bytes = get_byte_size_of_tensor(audio_chunk)
        additionally_allocated = usage.max_allocated - initial_usage.max_allocated
        logger.debug(
            "Cuda max memory allocated %s (reserved %s) for %s of audio data at offset %s",
            get_bytes_size_format(additionally_allocated, stop_at="M"),
            get_bytes_size_format(usage.reserved - initial_usage.reserved, stop_at="M"),
            get_bytes_size_format(audio_chunk_size_bytes, stop_at="M"),
            get_bytes_size_format(self._audio_offset_bytes),
        )
        self._audio_offset_bytes += audio_chunk_size_bytes

        # Если аллацировано меньше, то, скорее всего, обрабатывался не полный чанк данных
        # Если больше, то тут проблемы с настройкой размера чанка
        if (
            additionally_allocated - self._target_allocation_size
        ) / self._target_allocation_size > self._target_allocation_size_threshold:
            logger.warning(
                "Too much memory allocated - %s (expected %s)",
                get_bytes_size_format(additionally_allocated),
                get_bytes_size_format(self._target_allocation_size),
            )


class DeepFilterNet3Denoise(Action):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: Literal["DeepFilterNet3Denoise"] = "DeepFilterNet3Denoise"

    model: nn.Module | None = Field(None, exclude=True)
    df_state: DF | None = Field(None, exclude=True)
    df_model_name: str = DEFAULT_MODEL
    device: torch.device | None = Field(None, exclude=True)
    cleanup: bool = Field(True, exclude=True)

    # 4 GiB
    chunk_max_size_bytes: float = Field(MAX_DEEPFILTERNET_CHUNK_SIZE_BYTES, exclude=True)
    _cuda_memory_warning_threshold = 0.01
    _CUDA_MEMORY_KEY = "cuda_memory"

    @pydantic.model_validator(mode="after")
    def load_model(self) -> Self:
        self.model, self.df_state, self.df_model_name = init_df(default_model=self.df_model_name)
        self.device = get_device()

        return self

    def get_chunk_size(self, audio: torch.Tensor, meta: AudioMetaData) -> int:
        # DeepFilterNet3 потребляет около 238.5 байт на 1 семпл
        # memory_per_sample = 238.5
        # Так как нет способа (или он очень сложен) предварительно узнать
        # сколько нейросеть потребляет памяти, поэтому я просто померил
        memory_per_sample = 239

        # Размер окна для STFT
        fft_window_size = self.df_state.fft_size()

        # Считаем размер одного элемента
        # Вообще зависит от модели, но пусть будет
        dtype_size = audio.itemsize

        # Округляем с точностью до fft_window_size, чтобы избежать лишних падингов
        return (
            math.floor(
                self.chunk_max_size_bytes / memory_per_sample * 4 / dtype_size / fft_window_size / meta.num_channels
            )
            * fft_window_size
        )

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:

        self.device = get_device()
        stats = {
            "model": self.df_model_name,
            "device": {
                "type": self.device.type,
                "index": self.device.index,
            },
        }

        audio, meta = load_audio(input_file.as_posix(), sr=self.df_state.sr())

        chunk_size = self.get_chunk_size(audio, meta)

        if is_cuda(self.device):
            torch.cuda.reset_peak_memory_stats()
            cuda_memory_usage_stats = CudaMemoryUsageStats.init(
                self.device, self.chunk_max_size_bytes, self._cuda_memory_warning_threshold
            )

        enhanced_audio = []
        for offset in LoggingTQDM(range(0, meta.num_frames, chunk_size), f"Denoising using {self.df_model_name}"):
            torch.cuda.reset_peak_memory_stats()

            audio_chunk = audio[:, offset : offset + chunk_size]
            enhanced_audio_chunk = enhance(self.model.cuda(), self.df_state, audio_chunk)
            enhanced_audio.append(enhanced_audio_chunk)

            if is_cuda(self.device):
                cuda_memory_usage_stats.log_memory_usage(audio_chunk)

        if is_cuda(self.device):
            stats[self._CUDA_MEMORY_KEY] = cuda_memory_usage_stats.model_dump()

        save_audio(output_file.as_posix(), torch.concat(enhanced_audio, dim=1), self.df_state.sr())

        if self.cleanup and is_cuda(self.device):
            torch.cuda.empty_cache()

        return stats
