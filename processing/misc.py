import logging

from sqlalchemy_file import File
from sqlalchemy_file.storage import StorageManager

from djgram.db.base import get_autocommit_session

logger = logging.getLogger(__name__)


async def execute_file_update_statement(file: File, stmt):
    async with get_autocommit_session() as db_session:
        try:
            db_video = await db_session.execute(stmt)
        except Exception as exc:
            logger.error(exc)
            for path in file["files"]:
                StorageManager.delete_file(path)
                logger.info("Deleted %s", path)
            raise

        return db_video
