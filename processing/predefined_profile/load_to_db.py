import asyncio
import logging.config
import sys
from pathlib import Path

from sqlalchemy import select, update

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from configs import LOGGING_CONFIG
from djgram.db import async_session_maker
from processing.models import AudioProcessingProfile, UnsilenceProfile
from processing.predefined_profile import predefined_audio_pipelines, predefined_unsilence_profiles


async def load_audio_processing_profiles() -> None:
    excellent = AudioProcessingProfile(
        slug="excellent",
        name="Прекрасный",
        description="Подходит для идеального студийного звука. Только сводит в моно и нормализует звук.",
        audio_pipeline=predefined_audio_pipelines.excellent_audio_pipeline,
    )

    good = AudioProcessingProfile(
        slug="good",
        name="Хороший",
        description="Подходит для качественных записей с непостоянной громкостью речи и без шумов."
        " Старается выровнять громкость речи.",
        audio_pipeline=predefined_audio_pipelines.good_audio_pipeline,
    )

    normal = AudioProcessingProfile(
        slug="normal",
        name="Нормальный",
        description="Подходит для относительно хороших записей с непостоянной громкостью речи и с посторонними шумами. "
        "Старается выровнять громкость речи и подавить шумы.",
        audio_pipeline=predefined_audio_pipelines.normal_audio_pipeline,
    )
    terrible = AudioProcessingProfile(
        slug="terrible",
        name="Ужасный",
        description="Используйте только, если у вас очень плохая запись. "
        "Может помочь в случаях, когда звук очень тихий и шумы, громче, чем речь.",
        audio_pipeline=predefined_audio_pipelines.terrible_audio_pipeline,
    )

    async with async_session_maker() as db_session:
        await db_session.begin()

        for profile in (excellent, good, normal, terrible):
            # noinspection PyTypeChecker
            if await db_session.scalar(
                select(AudioProcessingProfile).with_for_update().where(AudioProcessingProfile.slug == profile.slug),
            ):
                # noinspection PyTypeChecker
                await db_session.execute(
                    update(AudioProcessingProfile)
                    .values(
                        name=profile.name,
                        description=profile.description,
                        audio_pipeline=profile.audio_pipeline,
                    )
                    .where(AudioProcessingProfile.slug == profile.slug),
                )
                logging.info("Updated %s", profile.slug)
                continue

            db_session.add(profile)
            logging.info("Added %s", profile.slug)

        await db_session.commit()


async def load_unsilence_profiles() -> None:
    unsilence_profile = UnsilenceProfile(
        slug="unsilence_profile",
        name="Поиск тишины",
        description="Убирает немного меньше тишины, чем профиль с поиском речи,"
        " зато хорошо работает для видео, содержащих музыку.",
        unsilence_action=predefined_unsilence_profiles.unsilence_only_action,
    )
    # vad_profile = UnsilenceProfile( ERA001
    #     slug="vad_profile",  # noqa: ERA001
    #     name="Детекция речи",  # noqa: ERA001
    #     description="Подходит для лекций. Не стоит использовать для видео содержащих музыку.",  # noqa: ERA001
    #     unsilence_action=predefined_unsilence_profiles.vad_only_action,  # noqa: ERA001
    # ) ERA001
    unsilence_and_vad_profile = UnsilenceProfile(
        slug="unsilence_and_vad_profile",
        name="Поиск речи",
        description="Хорошо подходит для лекций. Не стоит использовать для видео содержащих музыку.",
        unsilence_action=predefined_unsilence_profiles.unsilence_and_vad_action,
    )

    async with async_session_maker() as db_session:
        await db_session.begin()

        for profile in (unsilence_and_vad_profile, unsilence_profile):
            # noinspection PyTypeChecker
            if await db_session.scalar(
                select(UnsilenceProfile).with_for_update().where(UnsilenceProfile.slug == profile.slug),
            ):
                # noinspection PyTypeChecker
                await db_session.execute(
                    update(UnsilenceProfile)
                    .values(
                        name=profile.name,
                        description=profile.description,
                        unsilence_action=profile.unsilence_action,
                    )
                    .where(UnsilenceProfile.slug == profile.slug),
                )
                logging.info("Updated %s", profile.slug)
                continue

            db_session.add(profile)
            logging.info("Added %s", profile.slug)

        await db_session.commit()


async def main() -> None:
    await load_audio_processing_profiles()
    await load_unsilence_profiles()


if __name__ == "__main__":
    logging.config.dictConfig(LOGGING_CONFIG)
    asyncio.run(main())
