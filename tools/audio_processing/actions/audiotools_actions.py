from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, ParamSpec, Self, TypeAlias, TypeVar

import pydantic
from pyaudiotoolslib.wavfile import WavFile

from .abstract import Action, ActionStatsType

T = TypeVar("T")
R = TypeVar("R")
P = ParamSpec("P")

Method: TypeAlias = Callable[[T, P], R]


def self_caller(func: Method[T, P, R], *args: P.args, **kwargs: P.kwargs) -> Callable[[Method[T, P, R]], R]:
    def inner(self: T) -> R:
        return func(self, *args, **kwargs)

    return inner


class AudiotoolsSubAction(pydantic.BaseModel):
    func: Callable[[WavFile, ...], WavFile]
    args: dict[str, Any] = {}

    @pydantic.field_serializer("func")
    def serialize_func(self, func: Callable[[WavFile, ...], WavFile], _info: pydantic.SerializationInfo) -> str:
        return func.__name__

    @pydantic.field_validator("func", mode="wrap")
    @classmethod
    def validate_func(cls, func: Any, _info: pydantic.SerializationInfo) -> Callable[[WavFile, ...], WavFile]:
        if isinstance(func, Callable):
            return func

        return getattr(WavFile, func)

    def __call__(self, wavfile: WavFile):
        return self.func(wavfile, **self.args)


class AudiotoolsAction(Action):
    name: Literal["AudiotoolsAction"] = "AudiotoolsAction"

    subactions: list[AudiotoolsSubAction] = []

    def normalize(self, peak_level: float = -1.0, remove_dc: bool = True, stereo_independent: bool = False) -> Self:
        self.subactions.append(
            AudiotoolsSubAction(
                func=WavFile.normalize,
                args={"peak_level": peak_level, "remove_dc": remove_dc, "stereo_independent": stereo_independent},
            )
        )
        return self

    def remove_all_channels_except(self, channel: int) -> Self:
        self.subactions.append(AudiotoolsSubAction(func=WavFile.remove_all_channels_except, args={"channel": channel}))
        return self

    def remove_clicks(self, threshold_level: int = 200, click_width: int = 20) -> Self:
        self.subactions.append(
            AudiotoolsSubAction(
                func=WavFile.remove_clicks, args={"threshold_level": threshold_level, "click_width": click_width}
            )
        )
        return self

    def to_mono(self) -> Self:
        self.subactions.append(AudiotoolsSubAction(func=WavFile.to_mono))
        return self

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:
        wavfile = WavFile(input_file)

        for subaction in self.subactions:
            wavfile = subaction(wavfile)

        wavfile.save(output_file)

        return None
