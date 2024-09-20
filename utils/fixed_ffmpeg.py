from dataclasses import asdict, dataclass
from typing import Self

from ffmpeg import FFmpeg
from ffmpeg.progress import Progress, Tracker
from ffmpeg.statistics import Statistics, _field_factory, _pattern


@dataclass(frozen=True)
class FixedStatistics(Statistics):
    @classmethod
    def from_line(cls, line: str) -> Self:
        """
        Оригинальная реализация не работает при вызове ffmpeg с флагом -c:v copy,
        так как в таком случае не отображается fps
        """
        fields = {key: _field_factory[key](value) for key, value in _pattern.findall(line) if value != "N/A"}
        return Statistics(**fields)


class FixedTracker(Tracker):
    def _on_stderr(self, line: str) -> None:
        statistics = FixedStatistics.from_line(line)
        if statistics is not None:
            self._ffmpeg.emit("progress", Progress(**asdict(statistics)))


class FixedFFmpeg(FFmpeg):
    def __init__(self, executable: str = "ffmpeg"):  # noqa: D107
        super().__init__(executable)

        # noinspection PyTypeChecker
        self._tracker = FixedTracker(self)
