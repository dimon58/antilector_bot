import logging.config

from configs import LOGGING_CONFIG
from processing.models import setup_storage
from utils.logging_tqdm import patch_tqdm


def system_init() -> None:  # noqa: D103
    logging.config.dictConfig(LOGGING_CONFIG)
    patch_tqdm()

    setup_storage()
