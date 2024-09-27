from collections.abc import Callable
from typing import TypeAlias

UpdateCallbackType: TypeAlias = Callable[[float, float], None]
