import logging

from .interval import Interval, SerializedInterval

logger = logging.getLogger(__name__)


class Intervals:
    """
    Collection of lib.Intervals.Interval
    """

    def __init__(
        self,
        interval_list: list[Interval] | None = None,
        interval_list_without_breaks: list[Interval] | None = None,
    ):
        """
        Initializes a new Interval Collection

        :param interval_list: list of intervals, optional
        """
        if interval_list is None:
            interval_list = []

        if interval_list_without_breaks is None:
            interval_list_without_breaks = interval_list

        self._interval_list: list[Interval] = interval_list
        self._interval_list_without_breaks = interval_list_without_breaks

    def add_interval(self, interval: Interval) -> None:
        """
        Adds an interval to the collection
        :param interval: interval to be added
        :return: None
        """
        self._interval_list.append(interval)

    @property
    def intervals(self) -> list[Interval]:
        """
        Returns the list of intervals
        :return:
        """
        return self._interval_list

    @property
    def intervals_without_breaks(self) -> list[Interval]:
        """
        Returns the list of intervals without breaks
        :return:
        """
        return self._interval_list_without_breaks

    def optimize(
        self,
        short_interval_threshold: float = 0.3,
        stretch_time: float = 0.25,
        silence_upper_threshold: float | None = None,
    ) -> None:
        """
        Optimizes the Intervals to be a better fit for media cutting

        :param silence_upper_threshold: Time intervals longer than which are considered a break,
            so they are cut out completely. None приравнивается  к float("inf").
        :param short_interval_threshold: The shortest allowed interval length (in seconds)
        :param stretch_time: The time that should be added/removed from a audible/silent interval
        :return: None
        """
        logger.debug("Optimazing intervals")
        self.__combine_intervals(short_interval_threshold)
        self.__enlarge_audible_intervals(stretch_time)
        self.__remove_breaks(silence_upper_threshold)

    def __combine_intervals(self, short_interval_threshold: float) -> None:
        """
        Combines multiple intervals in order to remove intervals smaller than a threshold
        :param short_interval_threshold: Threshold for the shortest allowed interval
        :return: None
        """
        intervals = []
        current_interval = Interval(is_silent=None)

        for interval in self._interval_list:
            if interval.duration <= short_interval_threshold or current_interval.is_silent == interval.is_silent:
                current_interval.end = interval.end

            elif current_interval.is_silent is None:
                current_interval.is_silent = interval.is_silent
                current_interval.end = interval.end
            else:
                intervals.append(current_interval)
                current_interval = interval.copy()

        if current_interval.is_silent is None:
            current_interval.is_silent = False

        intervals.append(current_interval)

        logger.debug("%s intervals combined in %s", len(self._interval_list), len(intervals))
        self._interval_list = intervals

    def __enlarge_audible_intervals(self, stretch_time: float) -> None:
        """
        Enlarges/Shrinks intervals based on if they are silent or audible
        :param stretch_time: Time the intervals should be enlarged/shrunken
        :return: None
        """
        logger.debug("Enlarging intervals")
        for i, interval in enumerate(self._interval_list):
            interval.enlarge_audible_interval(
                stretch_time, is_start_interval=(i == 0), is_end_interval=(i == len(self._interval_list) - 1)
            )

    def __remove_breaks(self, silence_upper_threshold: float | None) -> None:
        if silence_upper_threshold is None or silence_upper_threshold == float("inf"):
            logger.debug("Skip removing breaks")
            self._interval_list_without_breaks = self._interval_list
            return

        intervals = []
        for interval in self._interval_list:
            if interval.is_silent and interval.duration >= silence_upper_threshold:
                continue
            intervals.append(interval)

        logger.debug("Removed %s intervals with breaks", len(self._interval_list) - len(intervals))

        self._interval_list_without_breaks = intervals

    def remove_short_intervals_from_start(self, audible_speed: float = 1, silent_speed: float = 2) -> "Intervals":
        """
        Removes Intervals from start that are shorter than 0.5 seconds after
        speedup to avoid having a final output without an audio track
        :param audible_speed: The speed at which the audible intervals get played back at
        :param silent_speed: The speed at which the silent intervals get played back at
        :return: The new, possibly shorter, Intervals object
        """

        # Зачем это вообще нужно???
        raise UserWarning("Do not use it")
        for i, interval in enumerate(self._interval_list_without_breaks):
            speed = silent_speed if interval.is_silent else audible_speed

            if interval.duration / speed > 0.5:  # noqa: PLR2004
                return Intervals(self._interval_list_without_breaks[i:])

        raise ValueError("No interval has a length over 0.5 seconds after speed changes! This is required.")

    def copy(self) -> "Intervals":
        """
        Creates a deep copy
        :return: Deep copy of Intervals
        """
        new_interval_list = [interval.copy() for interval in self._interval_list]
        new_interval_list_without_breaks = [interval.copy() for interval in self._interval_list_without_breaks]

        return Intervals(new_interval_list, new_interval_list_without_breaks)

    def serialize(self) -> tuple[list[SerializedInterval], list[SerializedInterval]]:
        """
        Serializes this collection
        :return: Serialized list
        """
        return (
            [interval.serialize() for interval in self._interval_list],
            [interval.serialize() for interval in self._interval_list_without_breaks],
        )

    @staticmethod
    def deserialize(serialized_obj: tuple[list[SerializedInterval], list[SerializedInterval]]) -> "Intervals":
        """
        Deserializes a previously serialized object and creates a new Instance from it
        :param serialized_obj: Serialized list
        :return: New instance of Intervals
        """
        serialized_interval_list, serialized_interval_list_without_breaks = serialized_obj
        interval_list = [Interval.deserialize(serialized_interval) for serialized_interval in serialized_interval_list]
        interval_list_without_breaks = [
            Interval.deserialize(serialized_interval) for serialized_interval in serialized_interval_list_without_breaks
        ]
        return Intervals(interval_list, interval_list_without_breaks)

    def __repr__(self):
        """
        String representation
        :return: String representation
        """
        return str(self._interval_list)
