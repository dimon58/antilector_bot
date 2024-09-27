import warnings
from typing import Self

from pydantic import BaseModel, Field, PositiveInt, model_validator

from utils.video.misc import ensure_nvenc_correct


class RenderOptions(BaseModel):
    """
    Options for rendering intervals for unsilence
    """

    audio_only: bool = Field(False, description="Whether the output should be audio only")
    audible_speed: float = Field(1, description="The speed at which the audible intervals get played back at")
    silent_speed: float = Field(6, description="The speed at which the silent intervals get played back at")
    audible_volume: float = Field(1, description="The volume at which the audible intervals get played back at")
    silent_volume: float = Field(0.5, description="The volume at which the silent intervals get played back at")
    drop_corrupted_intervals: bool = Field(
        False,
        description="Whether corrupted video intervals should be discarded or tried to recover",
    )
    check_intervals: bool = Field(False, description="Need to check corrupted intervals")
    minimum_interval_duration: float = Field(0.25, description="Minimum duration of result interval")
    interval_in_fade_duration: float = Field(0.01, description="Fade duration at interval start")
    interval_out_fade_duration: float = Field(0.01, description="Fade duration at interval end")
    fade_curve: str = Field(
        "tri",
        description="Set curve for fade transition. (https://ffmpeg.org/ffmpeg-filters.html#afade-1)",
    )

    threads: PositiveInt = Field(2, description="Number of threads to render simultaneously")
    use_nvenc: bool = Field(False, description="Use nvenc for transcoding")
    force_video_codec: str | None = Field(None, description="Video codec to use for rendering")
    force_audio_codec: str | None = Field(None, description="Audio codec to use for rendering")

    # Можно ли копировать видеопоток при рендеринге.
    # Стоит давать разрешение, только если будут
    # одинаковы все параметры кодирования входного и выходного файлов.
    # ---------
    # Может появиться соблазн добавить копирование видео- и аудио-потоков
    # Я попробовал и выяснилось, что перекодирование обязательно, иначе появляются артефакты в видео
    # Скорее всего образка видео и копирование вместе работать не могут
    # Для видеофайла mp4 с кодеком hevc у меня были проблемы почти со всеми интервалами
    allow_copy_video_stream: bool = Field(
        False,
        description="Allow copy video stream if not filter applied. "
        "If input and output codec have different params output video may have problems. "
        "It should be controlled in calling code.",
        exclude=True,
    )
    allow_copy_audio_stream: bool = Field(
        False,
        description="Allow copy audio stream if not filter applied.",
        exclude=True,
    )

    @model_validator(mode="after")
    def check_nvenc_settings(self) -> Self:
        ensure_nvenc_correct(self.use_nvenc, self.force_video_codec, self.threads)
        return self

    @model_validator(mode="after")
    def check_allow_copy_settings(self) -> Self:
        if self.allow_copy_audio_stream:
            warnings.warn("Using allow_copy_audio_stream=True leads to artifacts in the audio", stacklevel=100)
        if self.allow_copy_video_stream:
            warnings.warn("Using allow_copy_video_stream=True leads to artifacts in the video", stacklevel=100)

        return self
