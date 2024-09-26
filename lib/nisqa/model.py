import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import soundfile as sf
import torch
import yaml
from torch._prims_common import DeviceLikeType
from tqdm import tqdm

from .core.model_torch import model_init
from .metrics import NisqaMetrics
from .utils.process_utils import process

BASE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


class NisqaModel:
    def __init__(
        self,
        device: Optional[DeviceLikeType] = None,
        config_path: Path = BASE_DIR / "config" / "nisqa_s.yaml",
        ckp_path: Path = BASE_DIR / "weights" / "nisqa_s.tar",
        warmup: bool = False,
        frame: int = 2,
        updates: int | None = None,
    ):
        """

        :param config_path: Path to config file
        :param ckp_path: Path to checkpoint that will be used for inference
        :param warmup: warmup run before inference; usually is not needed on CPU runs
        :param frame: framesize for file/mic capture in seconds
        :param updates: if null, metrics will be calculated over whole available frame (every [frame] seconds);
            if int - metrics will be calculated every n bins
            (which equivalent to sr / ms_n_fft * n seconds, for updates=1 it will be 48000/960*1 = 20ms)
        :param device: Device to run model
        """
        self.config_path = config_path
        self.ckp_path = ckp_path
        self.frame = frame
        self.updates = updates
        if device is not None:
            device = torch.device(device)
        self.device = device

        with open(self.config_path) as ymlfile:
            args_yaml = yaml.load(ymlfile, Loader=yaml.FullLoader)

        self.args = {**args_yaml, "ckp": self.ckp_path, "updates": self.updates}

        self.model, self.h0, self.c0 = model_init(self.args, self.device)

        if warmup:
            self.warmup()

    def warmup(self):
        _sr = 48000
        _, _, _ = process(
            torch.zeros(self.frame * _sr, device=self.device), _sr, self.model, self.h0, self.c0, self.args
        )

    def measure_from_tensor(self, audio: torch.Tensor, sample_rate: int) -> NisqaMetrics:

        audio = audio.to(self.device)

        if len(audio.size()) > 1:
            # raise ValueError ???
            logger.warning("Nisqa can be calculated only for single channel audio. Converting to mono")
            audio = audio.mean(1)

        start = time.perf_counter()
        audio_length = len(audio) / sample_rate
        framesize = sample_rate * self.frame

        # if length of audio is not divisible by framesize, then pad
        if audio.shape[0] % framesize != 0:
            audio = torch.cat((audio, torch.zeros(framesize - audio.shape[0] % framesize, device=self.device)))

        audio_spl = torch.split(audio, framesize, dim=0)

        out_all = []
        for audio_chunk in tqdm(audio_spl, desc="Measuring nisqa"):
            out, self.h0, self.c0 = process(audio_chunk, sample_rate, self.model, self.h0, self.c0, self.args)
            out_all.append(out)

        metrics = torch.concat(out_all, dim=0).mean(dim=0).cpu()

        end = time.perf_counter()

        return NisqaMetrics(
            noisiness=float(metrics[0]),
            coloration=float(metrics[1]),
            discontinuity=float(metrics[2]),
            loudness=float(metrics[3]),
            overall_quality=float(metrics[4]),
            length=audio_length,
            sr=sample_rate,
            time=end - start,
        )

    def measure_from_path(self, audio_file: Path) -> NisqaMetrics:
        audio, sample_rate = sf.read(audio_file)
        audio = torch.as_tensor(audio, device=self.device)

        return self.measure_from_tensor(audio, sample_rate)

    def _need_cleanup_cuda(self):
        return self.device is not None and self.device.type == "cuda"

    @contextmanager
    def cleanup_cuda(self, warmup: bool = True, empty_cache: bool = True):
        need_cleanup_cuda = self._need_cleanup_cuda()
        if warmup and need_cleanup_cuda:
            self.warmup()
        yield
        if empty_cache and need_cleanup_cuda:
            torch.cuda.empty_cache()
