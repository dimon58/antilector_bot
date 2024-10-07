"""
Геттеры для диалогов
"""

from typing import Any

from aiogram_dialog import DialogManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from processing.models import AudioProcessingProfile, UnsilenceProfile

from .callbacks import AUDIO_PROCESSING_PROFILE_ID_KEY, UNSILENCE_PROFILE_ID_KEY

AUDIO_PROCESSING_PROFILE_KEY = "audio_processing_profile"
AUDIO_PROCESSING_PROFILES_KEY = "audio_processing_profiles"
AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY = "audio_processing_profiles_description"

UNSILENCE_PROFILE_KEY = "unsilence_profile"
UNSILENCE_PROFILES_KEY = "unsilence_profiles"
UNSILENCE_PROFILES_DESCRIPTION_KEY = "unsilence_profiles_description"

CONFIRM_TEXT = "confirm_text"


async def get_audio_processing_profiles(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    return {AUDIO_PROCESSING_PROFILES_KEY: [(profile.id, profile.name) for profile in profiles]}


async def get_audio_processing_profiles_description(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    text = [
        "Описание профилей:",
        "",
        *(f"*{profile.name}*: {profile.description}" for profile in profiles),
    ]

    return {AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY: "\n".join(text)}


async def get_unsilence_profiles(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(UnsilenceProfile))

    return {UNSILENCE_PROFILES_KEY: [(profile.id, profile.name) for profile in profiles]}


async def get_unsilence_profiles_description(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(UnsilenceProfile))

    text = [
        "Описание профилей:",
        "",
        *(f"*{profile.name}*: {profile.description}" for profile in profiles),
    ]

    return {UNSILENCE_PROFILES_DESCRIPTION_KEY: "\n".join(text)}


async def get_confirm_text(db_session: AsyncSession, dialog_manager: DialogManager, **kwargs) -> dict[str, Any]:
    audio_processing_profile = await db_session.scalar(
        select(AudioProcessingProfile).where(
            AudioProcessingProfile.id == dialog_manager.dialog_data[AUDIO_PROCESSING_PROFILE_ID_KEY]
        )
    )
    unsilence_profile = await db_session.scalar(
        select(UnsilenceProfile).where(UnsilenceProfile.id == dialog_manager.dialog_data[UNSILENCE_PROFILE_ID_KEY])
    )

    text = (
        f"Настройки обработки\n"
        f"\n"
        f"*Профиль аудио:* {audio_processing_profile.name}\n"
        f"*Профиль поиска тишины:* {unsilence_profile.name}\n"
    )

    return {CONFIRM_TEXT: text}
