from lib.unsilence.intervals.time_calculations import TimeData
from utils.pathtools import PathType
from utils.video import get_video_duration


def calculate_time_savings(original_file: PathType, processed_path: PathType) -> TimeData:
    original_duration = get_video_duration(original_file)
    processed_duration = get_video_duration(processed_path)

    delta = processed_duration - original_duration
    ratio = processed_duration / original_duration

    # Считаем, что в итоге нет тишины, хотя это не так
    # Алгоритм оставляет маленькую тишину между речью для нормального восприятия звука

    return {
        "before": {
            "all": (original_duration, 1),
            "audible": (processed_duration, ratio),
            "silent": (-delta, 1 - ratio),
        },
        "after": {
            "all": (processed_duration, ratio),
            "audible": (processed_duration, ratio),
            "silent": (0, 0),
        },
        "delta": {
            "all": (delta, ratio - 1),
            "audible": (0, 0),
            "silent": (delta, ratio - 1),
        },
    }
