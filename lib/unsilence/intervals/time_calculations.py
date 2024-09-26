from typing import TypeAlias

from .. import Interval
from .intervals import Intervals

TimeData: TypeAlias = dict[str, dict[str, tuple[float, float]]]


def get_silent_and_audible(intervals: list[Interval]) -> tuple[float, float]:
    audible = 0
    silent = 0
    for interval in intervals:
        if interval.is_silent:
            silent += interval.duration
        else:
            audible += interval.duration

    return audible, silent


def calculate_time(intervals: Intervals, audible_speed: float, silent_speed: float) -> TimeData:
    """
    Generates a time estimate on the time saved if the current speed settings get applied

    :param intervals: Intervals which should be estimated (lib.Intervals.Intervals)
    :param audible_speed: The speed at which audible intervals should be played back at
    :param silent_speed: The speed at which silent intervals should be played back at
    :return: Time calculation dict
    """

    audible_before, silent_before = get_silent_and_audible(intervals.intervals)

    time_data = {"before": {}, "after": {}, "delta": {}}

    time_data["before"]["all"] = (audible_before + silent_before, 1)
    time_data["before"]["audible"] = (audible_before, audible_before / time_data["before"]["all"][0])
    time_data["before"]["silent"] = (silent_before, silent_before / time_data["before"]["all"][0])

    audible_after, silent_after = get_silent_and_audible(intervals.intervals_without_breaks)
    new_audible = audible_after / audible_speed
    new_silent = silent_after / silent_speed

    time_data["after"]["all"] = (new_audible + new_silent, (new_audible + new_silent) / time_data["before"]["all"][0])
    time_data["after"]["audible"] = (new_audible, new_audible / time_data["before"]["all"][0])
    time_data["after"]["silent"] = (new_silent, new_silent / time_data["before"]["all"][0])

    time_data["delta"]["all"] = (
        time_data["after"]["all"][0] - time_data["before"]["all"][0],
        time_data["after"]["all"][1] - time_data["before"]["all"][1],
    )

    time_data["delta"]["audible"] = (
        time_data["after"]["audible"][0] - time_data["before"]["audible"][0],
        time_data["after"]["audible"][1] - time_data["before"]["audible"][1],
    )

    time_data["delta"]["silent"] = (
        time_data["after"]["silent"][0] - time_data["before"]["silent"][0],
        time_data["after"]["silent"][1] - time_data["before"]["silent"][1],
    )

    # Timedelta not working like i want

    return time_data
