from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import sqltypes

from djgram.db.models import BaseModel
from djgram.db.pydantic_field import PydanticField
from tools.audio_processing.pipeline import AudioPipeline


class AudioProcessingProfile(BaseModel):
    name: Mapped[str] = mapped_column(sqltypes.String, nullable=False)
    description: Mapped[str] = mapped_column(sqltypes.String, nullable=False)

    audio_pipeline: Mapped[PydanticField] = mapped_column(
        PydanticField(AudioPipeline),
        nullable=False,
        doc="Audio processing pipeline",
    )
