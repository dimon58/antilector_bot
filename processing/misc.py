import logging
from pathlib import Path

from sqlalchemy_file import File
from sqlalchemy_file.storage import StorageManager

from djgram.db.base import get_autocommit_session
from utils.logging_tqdm import LoggingTQDM

logger = logging.getLogger(__name__)


async def execute_file_update_statement(file: File, stmt):  # noqa: ANN001, ANN201
    async with get_autocommit_session() as db_session:
        try:
            db_video = await db_session.scalar(stmt)
        except Exception as exc:
            logger.exception(exc)  # noqa: TRY401
            for path in file["files"]:
                StorageManager.delete_file(path)
                logger.info("Deleted %s", path)
            raise

        return db_video


def download_file_from_s3(file: File, path: Path) -> None:
    s3_file = file.file
    pbar = LoggingTQDM(
        desc="Downloading file from S3",
        total=file["size"],
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    )
    with open(path, "wb") as f:  # noqa: PTH123
        for chunk in s3_file.object.as_stream():
            pbar.update(len(chunk))
            f.write(chunk)
