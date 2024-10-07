"""
Геттеры для диалогов
"""

from typing import Any

from aiogram_dialog import DialogManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from processing.models import AudioProcessingProfile, ProfileBase, UnsilenceProfile

from .callbacks import AUDIO_PROCESSING_PROFILE_ID_KEY, UNSILENCE_PROFILE_ID_KEY

AUDIO_PROCESSING_PROFILE_KEY = "audio_processing_profile"
AUDIO_PROCESSING_PROFILES_KEY = "audio_processing_profiles"
AUDIO_PROCESSING_PROFILES_DESCRIPTION_KEY = "audio_processing_profiles_description"

UNSILENCE_PROFILE_KEY = "unsilence_profile"
UNSILENCE_PROFILES_KEY = "unsilence_profiles"
UNSILENCE_PROFILES_DESCRIPTION_KEY = "unsilence_profiles_description"

CONFIRM_TEXT = "confirm_text"

DEFAULT_AUDIO_PROCESSING_PROFILE_SLUG = "normal"
DEFAULT_UNSILENCE_PROFILE_SLUG = "unsilence_and_vad_profile"


async def get_audio_processing_profiles(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    return {AUDIO_PROCESSING_PROFILES_KEY: [(profile.id, profile.name) for profile in profiles]}


async def get_audio_processing_profiles_description(db_session: AsyncSession, **kwargs) -> dict[str, Any]:
    profiles = await db_session.scalars(select(AudioProcessingProfile))

    text = [
        "Описание профилей:",
        "",
        *(f"*{profile.name}*: {profile.description}" for profile in profiles),
        "",
        "По умолчанию стоит использовать нормальный профиль",
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
        "",
        "По умолчанию стоит использовать поиск речи",
    ]

    return {UNSILENCE_PROFILES_DESCRIPTION_KEY: "\n".join(text)}


async def get_profile(
    db_session: AsyncSession,
    dialog_manager: DialogManager,
    model: type[ProfileBase],
    profile_id_key: str,
    default_profile_slug: str,
):
    if profile_id_key in dialog_manager.dialog_data:
        return await db_session.scalar(select(model).where(model.id == dialog_manager.dialog_data[profile_id_key]))

    # noinspection PyTypeChecker
    profile = await db_session.scalar(select(model).where(model.slug == default_profile_slug))
    dialog_manager.dialog_data[profile_id_key] = profile.id

    return profile


async def get_confirm_text(db_session: AsyncSession, dialog_manager: DialogManager, **kwargs) -> dict[str, Any]:
    audio_processing_profile = await get_profile(
        db_session=db_session,
        dialog_manager=dialog_manager,
        model=AudioProcessingProfile,
        profile_id_key=AUDIO_PROCESSING_PROFILE_ID_KEY,
        default_profile_slug=DEFAULT_AUDIO_PROCESSING_PROFILE_SLUG,
    )
    unsilence_profile = await get_profile(
        db_session=db_session,
        dialog_manager=dialog_manager,
        model=UnsilenceProfile,
        profile_id_key=UNSILENCE_PROFILE_ID_KEY,
        default_profile_slug=DEFAULT_UNSILENCE_PROFILE_SLUG,
    )

    text = (
        f"Настройки обработки\n"
        f"\n"
        f"*Профиль аудио:* {audio_processing_profile.name}\n"
        f"*Профиль поиска тишины:* {unsilence_profile.name}\n"
    )

    return {CONFIRM_TEXT: text}
