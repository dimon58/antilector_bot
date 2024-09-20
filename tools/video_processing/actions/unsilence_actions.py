from pathlib import Path
from typing import Any, Literal, Self

import pydantic
from pydantic import ConfigDict, Field, model_validator

from configs import UNSILENCE_DEFAULT_CPU_COUNT, VAD_MODEL
from lib import unsilence
from tools.audio_processing.actions.abstract import Action, ActionStatsType
from tools.video_processing.vad.calculate_time_savings import calculate_time_savings
from tools.video_processing.vad.vad_unsilence import Vad
from utils.misc import find_subclass
from utils.progress_bar import ProgressBar

TIME_SAVINGS_ESTIMATION_KEY = "time_savings_estimation"
TIME_SAVINGS_REAL_KEY = "time_savings_real"


class UnsilenceAction(Action):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: Literal["UnsilenceAction"] = "UnsilenceAction"

    unsilence_class: type[unsilence.Unsilence]
    detect_silence_options: dict[str, Any]
    render_options: dict[str, Any]

    threads: int = Field(UNSILENCE_DEFAULT_CPU_COUNT)

    temp_dir: Path = Field(Path(".tmp"), exclude=True)

    @pydantic.field_serializer("unsilence_class")
    def serialize_unsilence_class(
        self, unsilence_class: type[unsilence.Unsilence], _info: pydantic.SerializationInfo
    ) -> str:
        return unsilence_class.__name__

    @pydantic.field_validator("unsilence_class", mode="wrap")
    @classmethod
    def validate_unsilence_class(
        cls, unsilence_class: unsilence.Unsilence | str, _info: pydantic.SerializationInfo
    ) -> type[unsilence.Unsilence]:

        if isinstance(unsilence_class, type):
            if issubclass(unsilence_class, unsilence.Unsilence):
                return unsilence_class

            raise ValueError(f"{unsilence_class} is not unsilence class")

        found = find_subclass(unsilence.Unsilence, unsilence_class, strict_subclass=False)

        if found is None:
            raise ValueError(f"Can not found unsilence class for {unsilence_class}")

        return found

    # todo валидация параметров для detect_silence_options и render_options

    @model_validator(mode="after")
    def check_render_options(self) -> Self:
        if "threads" in self.render_options:
            raise ValueError("Can not setup threads from render_options")

        return self

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:

        init_additional_options = {}
        detect_additional_options = {}

        silence_detect_progress = ProgressBar("Detecting silence")
        detect_additional_options["on_silence_detect_progress_update"] = silence_detect_progress.update_unsilence

        # Так делать плохо, но можно
        # SOLID вышел из чата
        if issubclass(self.unsilence_class, Vad):
            init_additional_options["model"] = VAD_MODEL

            vad_progress = ProgressBar("Detecting voice activity")
            detect_additional_options["on_vad_progress_update"] = vad_progress.update_unsilence

        # ----------------- Detecting ----------------- #
        u = self.unsilence_class(input_file, **init_additional_options)

        u.detect_silence(**self.detect_silence_options, **detect_additional_options)

        time_savings_estimation = u.estimate_time(
            audible_speed=self.render_options.get("audible_speed", 1),
            silent_speed=self.render_options.get("silent_speed", 6),
        )

        # ----------------- Rendering ----------------- #
        render_progress = ProgressBar("Rendering intervals")
        concat_progress = ProgressBar("Concatenating intervals")
        render_additional_options = {
            "on_render_progress_update": render_progress.update_unsilence,
            "on_concat_progress_update": concat_progress.update_unsilence,
        }

        u.render_media(
            output_file,
            temp_dir=self.temp_dir,
            threads=self.threads,
            **self.render_options,
            **render_additional_options,
        )

        time_savings_real = calculate_time_savings(input_file, output_file)

        return {
            TIME_SAVINGS_ESTIMATION_KEY: time_savings_estimation,
            TIME_SAVINGS_REAL_KEY: time_savings_real,
        }
