from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeAlias

import pydantic

ActionStatsType: TypeAlias = dict[str, Any]


class Action(ABC, pydantic.BaseModel):
    name: str = __name__

    @abstractmethod
    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:
        raise NotImplementedError
