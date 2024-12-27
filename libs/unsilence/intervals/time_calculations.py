from typing import TypeAlias

from ..render_media.render_filter import clamp_speed  # noqa: TID252
from .intervals import Intervals

TimeData: TypeAlias = dict[str, dict[str, tuple[float, float]]]


def calculate_time(
    intervals: Intervals,
    audible_speed: float,
    silent_speed: float,
    minimum_interval_duration: float,
) -> TimeData:
    """
    Generates a time estimate on the time saved if the current speed settings get applied

    :param intervals: Intervals which should be estimated (lib.Intervals.Intervals)
    :param audible_speed: The speed at which audible intervals should be played back at
    :param silent_speed: The speed at which silent intervals should be played back at
    :return: Time calculation dict
    """

    audible_before = 0
    silent_before = 0
    for interval in intervals.intervals:
        if interval.is_silent:
            silent_before += interval.duration
        else:
            audible_before += interval.duration

    time_data = {"before": {}, "after": {}, "delta": {}}

    time_data["before"]["all"] = (audible_before + silent_before, 1)
    time_data["before"]["audible"] = (audible_before, audible_before / time_data["before"]["all"][0])
    time_data["before"]["silent"] = (silent_before, silent_before / time_data["before"]["all"][0])

    new_audible = 0
    new_silent = 0

    for interval in intervals.intervals_without_breaks:
        if interval.is_silent:
            new_silent += interval.duration / clamp_speed(interval.duration, silent_speed, minimum_interval_duration)
        else:
            new_audible += interval.duration / clamp_speed(interval.duration, audible_speed, minimum_interval_duration)

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
