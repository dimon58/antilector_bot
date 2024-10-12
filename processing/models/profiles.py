from sqlalchemy.orm import Mapped, mapped_column

from djgram.db.models import TimeTrackableBaseModel
from djgram.db.pydantic_field import ImmutablePydanticField
from tools.audio_processing.pipeline import AudioPipeline
from tools.video_processing.actions.unsilence_actions import UnsilenceAction


class ProfileBase(TimeTrackableBaseModel):
    __abstract__ = True

    slug: Mapped[str] = mapped_column(doc="Название профиля для технических нужд", unique=True, index=True)
    name: Mapped[str] = mapped_column(doc="Название профиля")
    description: Mapped[str] = mapped_column(doc="Описание профиля")


class AudioProcessingProfile(ProfileBase):
    audio_pipeline: Mapped[AudioPipeline] = mapped_column(
        ImmutablePydanticField(AudioPipeline, should_frozen=False),
        nullable=False,
        doc="Audio processing pipeline",
    )


class UnsilenceProfile(ProfileBase):
    name: Mapped[str]
    description: Mapped[str]

    unsilence_action: Mapped[UnsilenceAction] = mapped_column(
        ImmutablePydanticField(UnsilenceAction, should_frozen=False),
        doc="Unsilence action",
    )
