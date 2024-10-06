import asyncio
import logging.config

from configs import LOGGING_CONFIG
from processing.predefined_profile.load_to_db import main as load_to_db_main


async def main():
    await load_to_db_main()


if __name__ == "__main__":
    logging.config.dictConfig(LOGGING_CONFIG)
    asyncio.run(main())
