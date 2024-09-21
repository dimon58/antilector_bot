import os
from pathlib import Path

import silero_vad
import torch

TORCH_USE_CUDA = torch.cuda.is_available()
TORCH_DEVICE = torch.device("cuda" if TORCH_USE_CUDA else "cpu")

# Setup device for deepfilternet
os.environ["DEVICE"] = str(TORCH_DEVICE)

VAD_MODEL = silero_vad.load_silero_vad(onnx=True)
SILERO_VAD_SAMPLE_RATE = 16000
UNSILENCE_DEFAULT_CPU_COUNT = max(1, os.cpu_count() - 1)
# Если менять в разумных пределах, то время работы почти не зависит от этого параметра
MAX_DEEPFILTERNET_CHUNK_SIZE_BYTES = 1 * 2**30

TQDM_LOGGING_INTERVAL = 3

DEBUG = False
#: Корень проекта
BASE_DIR = Path(__file__).resolve().parent

# ---------- yt-dlp ---------- #

YT_DLP_LOGGING_DEBOUNCE_TIME = 5
YT_DLP_HTTP_CHUNK_SIZE = 10485760  # 10 MB

# Лекции чётче 1080p не имеют смысла
YT_DLP_VIDEO_MAX_HEIGHT = 1080
YT_DLP_VIDEO_MAX_WIDTH = 1920 * 2  # формат 32x9 подходит

# ---------- Логирование ---------- #

#: Папка для логирования
LOGGING_FOLDER = BASE_DIR / "logs"
LOGGING_FOLDER.mkdir(exist_ok=True)

#: Файл с логами
LOG_FILE = LOGGING_FOLDER / "logs.log"

#: Формат логов
# Красим точку в тот же цвет, что и дату и миллисекунды
LOGGING_FORMAT = (
    "[%(name)s:%(filename)s:%(funcName)s:%(lineno)d:"
    "%(asctime)s\033[32m.\033[0m%(msecs)03d:%(levelname)s] %(message)s"
)

#: Формат даты в логах
LOGGING_DATE_FORMAT = "%d-%m-%Y %H:%M:%S"

#: Настройки логирования
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": LOGGING_FORMAT,
            "datefmt": LOGGING_DATE_FORMAT,
        },
        "colored": {
            "()": "coloredlogs.ColoredFormatter",
            "format": LOGGING_FORMAT,
            "datefmt": LOGGING_DATE_FORMAT,
            "field_styles": {
                "asctime": {"color": "green"},
                "msecs": {"color": "green"},
                "hostname": {"color": "magenta"},
                "name": {"color": "blue"},
                "programname": {"color": "cyan"},
                "username": {"color": "yellow"},
            },
        },
    },
    "handlers": {
        "stream_handler": {
            "class": "logging.StreamHandler",
            "formatter": "colored",
        },
        "file_handler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "default",
            "filename": LOG_FILE,
            "encoding": "utf-8",
            "when": "W0",
        },
    },
    "loggers": {
        "root": {
            "handlers": ["stream_handler", "file_handler"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": True,
            "encoding": "utf-8",
        },
    },
}
