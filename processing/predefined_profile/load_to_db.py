import asyncio
import logging.config
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from configs import LOGGING_CONFIG
from djgram.db import async_session_maker
from processing.models import AudioProcessingProfile
from processing.predefined_profile import predefined_audio_pipelines

excellent = AudioProcessingProfile(
    name="Прекрасный",
    description="Подходит для идеального студийного звука. Только сводит в моно и нормализует звук.",
    audio_pipeline=predefined_audio_pipelines.excellent_audio_pipeline,
)

good = AudioProcessingProfile(
    name="Хороший",
    description="Подходит для качественных записей с непостоянной громкостью речи и без шумов."
    " Старается выровнять громкость речи.",
    audio_pipeline=predefined_audio_pipelines.good_audio_pipeline,
)

normal = AudioProcessingProfile(
    name="Нормальный",
    description="Подходит для относительно хороших записей с непостоянной громкостью речи и с посторонними шумами. "
    "Старается выровнять громкость речи и подавить шумы.",
    audio_pipeline=predefined_audio_pipelines.normal_audio_pipeline,
)
terrible = AudioProcessingProfile(
    name="Ужасный",
    description="Используйте только, если у вас очень плохая запись. "
    "Может помочь в случаях, когда звук очень тихий и шумы, громче, чем речь.",
    audio_pipeline=predefined_audio_pipelines.terrible_audio_pipeline,
)


async def main():
    async with async_session_maker() as db_session:
        await db_session.begin()

        for profile in (excellent, good, normal, terrible):
            if await db_session.scalar(
                select(AudioProcessingProfile).where(AudioProcessingProfile.name == profile.name)
            ):
                logging.info("Skip adding %s", profile.name)
                continue

            db_session.add(profile)
            logging.info("Added %s", profile.name)

        await db_session.commit()


if __name__ == "__main__":
    logging.config.dictConfig(LOGGING_CONFIG)
    asyncio.run(main())
