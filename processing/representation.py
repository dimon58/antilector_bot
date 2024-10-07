from typing import TypeAlias

TimeCalculationsDict: TypeAlias = dict[str, dict[str, tuple[float, float]]]

future = (
    "Исходная продолжительность",
    "Будет убрано около",
    "В итоге останется примерно",
    "Ускорение составит примерно",
)

past = (
    "Исходная продолжительность",
    "Было убрано",
    "В итоге осталось",
    "Ускорение составило",
)


def to_hhmmss(duration: float) -> str:
    if duration < 1.0:
        return "менее 1 сек"

    duration = round(duration)

    ss = duration % 60
    duration //= 60
    mm = duration % 60
    hh = duration // 60

    res = []
    if hh > 0:
        res.append(f"{hh} ч")
    if mm > 0:
        res.append(f"{mm} мин")
    if ss > 0:
        res.append(f"{ss} сек")

    return " ".join(res)


def _silence_remove_report(intervals: TimeCalculationsDict, translation: tuple[str, str, str, str]) -> str:
    """
    :param intervals: выход функции estimate_time
    """

    before = intervals["before"]["all"][0]
    delta_silence_duration, delta_silence_percent = intervals["delta"]["all"]
    after_duration, after_percent = intervals["after"]["all"]

    speedup = before / after_duration

    return (
        f"{translation[0]} {to_hhmmss(before)}\n"
        f"{translation[1]} {to_hhmmss(abs(delta_silence_duration))} тишины ({delta_silence_percent:.1%})\n"
        f"{translation[2]} {to_hhmmss(after_duration)} ({after_percent:.1%})\n"
        f"{translation[3]} {speedup:.2f}"
    )


def silence_remove_report(intervals: TimeCalculationsDict) -> str:
    """
    :param intervals: выход функции estimate_time
    """

    return _silence_remove_report(intervals, future)


def silence_remove_done_report(intervals: TimeCalculationsDict) -> str:
    """
    :param intervals: выход функции estimate_time
    """

    return _silence_remove_report(intervals, past)
