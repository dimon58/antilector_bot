import os
from os import PathLike
from pathlib import Path
from typing import TypeAlias

PathType: TypeAlias = str | bytes | PathLike | Path


def split_filename_ext(filename: PathType) -> tuple[str, str]:
    name, ext = os.path.splitext(filename)  # noqa: PTH122
    if ext.startswith("."):
        ext = ext[1:]

    return name, ext
