# ruff: noqa: ERA001
from .excellent import excellent_audio_pipeline
from .good import good_audio_pipeline
from .normal import normal_audio_pipeline
from .terrible import terrible_audio_pipeline


# Идеальный: нормализация
# Хороший: нормализация + speechnorm
# Средний: Хороший + удаление шумов
# Плохой: Все средства хороши
