"""
Геттеры для диалогов
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from processing.models import AudioProcessingProfile

AUDIO_PROFILE_KEY = "audio_profile"
AUDIO_PROFILES_KEY = "audio_profiles"
AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY = "audio_processing_profiles_description"


async def get_audio_processing_profiles(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    return {AUDIO_PROFILES_KEY: [(profile.id, profile.name) for profile in profiles]}


async def get_audio_processing_profiles_description(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    text = [
        "Описание профилей:",
        "",
        *(f"*{profile.name}*: {profile.description}" for profile in profiles),
    ]

    return {AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY: "\n".join(text)}
