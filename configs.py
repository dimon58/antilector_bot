import os
from pathlib import Path

import silero_vad
import torch
from dotenv import load_dotenv
from libcloud.storage.drivers.minio import MinIOStorageDriver

from utils.minio_utils import get_container_safe
from utils.torch_utils import is_cuda
from utils.video.misc import NVENC_MAX_CONCURRENT_SESSIONS

#: Корень проекта
BASE_DIR = Path(__file__).resolve().parent

# Переменные окружения из файла .env
# Загружаем без перезаписи, чтобы ими можно было управлять из вне
load_dotenv(BASE_DIR / ".env", override=False)

#: Включить режим отладки
DEBUG = bool(int(os.environ.get("DEBUG", "1")))  # pyright: ignore [reportArgumentType]

# --------------------------------- api токены --------------------------------- #

#: Токен телеграм бота
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")  # pyright: ignore [reportAssignmentType]

# ---------- База данных ---------- #

# Данные для подключения к PostgreSQL
POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "localhost")  # pyright: ignore [reportAssignmentType]
POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", "5432"))  # pyright: ignore [reportArgumentType]
POSTGRES_DB: str = os.environ.get("POSTGRES_DB", "postgres")  # pyright: ignore [reportAssignmentType]
POSTGRES_USER: str = os.environ.get("POSTGRES_USER", "admin")  # pyright: ignore [reportAssignmentType]
POSTGRES_PASSWORD: str = os.environ.get("POSTGRES_PASSWORD", "admin")  # pyright: ignore [reportAssignmentType]

# https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls
DB_URL = "postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}".format(  # noqa: UP032
    user=POSTGRES_USER,
    password=POSTGRES_PASSWORD,
    host=POSTGRES_HOST,
    port=POSTGRES_PORT,
    dbname=POSTGRES_DB,
)

DB_ENGINE_SETTINGS = {
    # https://stackoverflow.com/questions/24956894/sql-alchemy-queuepool-limit-overflow
    "pool_size": 25,
}
DB_SUPPORTS_ARRAYS = True

# Данные для подключения к ClickHouse
CLICKHOUSE_HOST: str = os.environ.get("CLICKHOUSE_HOST", "localhost")  # pyright: ignore [reportAssignmentType]
CLICKHOUSE_PORT: int = int(os.environ.get("CLICKHOUSE_PORT", 9000))  # pyright: ignore [reportArgumentType]
CLICKHOUSE_DB: str = os.environ.get("CLICKHOUSE_DB", "default")  # pyright: ignore [reportAssignmentType]
CLICKHOUSE_USER: str = os.environ.get("CLICKHOUSE_USER", "default")  # pyright: ignore [reportAssignmentType]
CLICKHOUSE_PASSWORD: str = os.environ.get("CLICKHOUSE_PASSWORD", "")  # pyright: ignore [reportAssignmentType]

REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")  # pyright: ignore [reportAssignmentType]
REDIS_PORT: int = int(os.environ.get("REDIS_PORT", 6379))  # pyright: ignore [reportArgumentType]
REDIS_USER: str | None = os.environ.get("REDIS_USER")
REDIS_PASSWORD: str | None = os.environ.get("REDIS_PASSWORD")

#: Номер базы данных для хранилища машины конченых состояний
REDIS_STORAGE_DB: int = int(os.environ.get("REDIS_STORAGE_DB", 0))  # pyright: ignore [reportArgumentType]

RABBITMQ_HOST: str = os.environ.get("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT: int = int(os.environ.get("RABBITMQ_PORT", 5672))
RABBITMQ_DEFAULT_USER: str | None = os.environ.get("RABBITMQ_DEFAULT_USER")
RABBITMQ_DEFAULT_PASS: str | None = os.environ.get("RABBITMQ_DEFAULT_PASS")

MINIO_HOST: str = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT: int = int(os.environ.get("MINIO_PORT", 19000))
MINIO_USER: str | None = os.environ.get("MINIO_USER")
MINIO_PASSWORD: str | None = os.environ.get("MINIO_PASSWORD")

S3_DRIVER = MinIOStorageDriver(
    key=MINIO_USER,
    secret=MINIO_PASSWORD,
    secure=False,
    host=MINIO_HOST,
    port=MINIO_PORT,
)

ORIGINAL_VIDEO_STORAGE = "original-video"
PROCESSED_VIDEO_STORAGE = "processed-video"

ORIGINAL_VIDEO_CONTAINER = get_container_safe(S3_DRIVER, ORIGINAL_VIDEO_STORAGE)
PROCESSED_VIDEO_CONTAINER = get_container_safe(S3_DRIVER, PROCESSED_VIDEO_STORAGE)

# ---------- Настройка логики обработки ---------- #

# Настройка устройств для
USE_CUDA = torch.cuda.is_available()
TORCH_DEVICE = torch.device("cuda:0" if USE_CUDA else "cpu")
os.environ["DEVICE"] = str(TORCH_DEVICE)  # Setup device for deepfilternet

# Лимиты на использование памяти
TOTAL_VRAM = torch.cuda.mem_get_info(TORCH_DEVICE)[1] if is_cuda(TORCH_DEVICE) else 0
MAX_VRAM_FOR_UNSILENCE_RENDERING = 0.8 * TOTAL_VRAM
MAX_RAM_FOR_UNSILENCE_RENDERING = 8 * 2**30

# Настройки обработки видео
USE_NVENC = USE_CUDA
FORCE_VIDEO_CODEC = "hevc_nvenc" if USE_NVENC else "hevc"
FORCE_AUDIO_CODEC = "aac"

VAD_MODEL = silero_vad.load_silero_vad(onnx=True)
SILERO_VAD_SAMPLE_RATE = 16000
# Больше 8 потоков будут проблемы с nvenc
# Кодеки на cpu сами по себе поточны, так что это имеет смысл только с nvenc
UNSILENCE_DEFAULT_CPU_COUNT = min(max(1, os.cpu_count() - 1), NVENC_MAX_CONCURRENT_SESSIONS)
# Если менять в разумных пределах, то время работы почти не зависит от этого параметра
MAX_DEEPFILTERNET_CHUNK_SIZE_BYTES = 1 * 2**30

# ---------- yt-dlp ---------- #

# YT_DLP_HTTP_CHUNK_SIZE = 10485760  # 10 MB
YT_DLP_HTTP_CHUNK_SIZE = None
# Потенциальный способ ускорения загрузки
# https://github.com/yt-dlp/yt-dlp/issues/7987
# https://github.com/yt-dlp/yt-dlp/issues/985
# Хотя скорость в основном зависит от кэширования на стороне провайдера
YT_DLP_YOUTUBE_FORMATS_DASHY = False

# Лекции чётче 1080p не имеют смысла
YT_DLP_VIDEO_MAX_HEIGHT = 1080
YT_DLP_VIDEO_MAX_WIDTH = 1920 * 2  # формат 32x9 подходит

# ---------- Логирование ---------- #

UNSILENCE_MIN_INTERVAL_LENGTH_FOR_LOGGING = 300
TQDM_LOGGING_INTERVAL = 5
YT_DLP_LOGGING_DEBOUNCE_TIME = 5

#: Папка для логирования
LOGGING_FOLDER = BASE_DIR / "logs"
LOGGING_FOLDER.mkdir(exist_ok=True)

#: Файл с логами
LOG_FILE = LOGGING_FOLDER / "logs.log"

#: Формат логов
# Красим точку в тот же цвет, что и дату и миллисекунды
LOGGING_FORMAT = (
    "[%(name)s:%(filename)s:%(funcName)s:%(lineno)d:"
    "%(asctime)s\033[32m.\033[0m%(msecs)03d:%(levelname)s:%(update_id)s] %(message)s"
)

#: Формат даты в логах
LOGGING_DATE_FORMAT = "%d-%m-%Y %H:%M:%S"

#: Настройки логирования
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "update_filter": {
            "()": "djgram.contrib.logs.context.UpdateIdContextFilter",
        },
    },
    "formatters": {
        "default": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": LOGGING_FORMAT,
            "datefmt": LOGGING_DATE_FORMAT,
        },
        "colored": {
            "()": "djgram.contrib.logs.extended_colored_formatter.ExtendedColoredFormatter",
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
            "filters": ["update_filter"],
        },
        "file_handler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "default",
            "filters": ["update_filter"],
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
        "sqlalchemy.engine": {
            "level": "DEBUG" if DEBUG else "WARNING",
        },
    },
}
