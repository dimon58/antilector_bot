import asyncio
import logging.config

from configs import LOGGING_CONFIG, USE_CUDA, USE_NVENC
from processing.predefined_profile.load_to_db import main as load_to_db_main


async def main() -> None:  # noqa: D103
    logging.info("USE_CUDA: %s", USE_CUDA)
    logging.info("USE_NVENC: %s", USE_NVENC)
    await load_to_db_main()


if __name__ == "__main__":
    logging.config.dictConfig(LOGGING_CONFIG)
    asyncio.run(main())
