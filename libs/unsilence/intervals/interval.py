from typing import TypeAlias

SerializedInterval: TypeAlias = dict[str, float | bool]


class Interval:
    """
    Represents a section in time where the media file is either silent or audible
    """

    def __init__(self, start: float = 0, end: float = 0, *, is_silent: bool = False):
        """
        Initializes an Interval object

        :param start: Start time of the interval in seconds
        :param end: End time of the interval in seconds
        :param is_silent: Whether the interval is silent or not
        """
        self._start = start
        self._end = end
        self._duration = self._end - self._start
        self.is_silent = is_silent

    @property
    def start(self) -> float:
        """
        Get the start time
        :return: start time in seconds
        """
        return self._start

    @start.setter
    def start(self, new_start: float) -> None:
        """
        Sets the new start time and updates the duration
        :param new_start: start time in seconds
        :return: None
        """
        self._start = new_start
        self._duration = self._end - self._start

    @property
    def end(self) -> float:
        """
        Get the end time
        :return: end time in seconds
        """
        return self._end

    @end.setter
    def end(self, new_end: float) -> None:
        """
        Sets the new end time and updates the duration
        :param new_end: start time in seconds
        :return: None
        """
        self._end = new_end
        self._duration = self._end - self._start

    @property
    def duration(self) -> float:
        """
        Returns the duration of the interval
        :return: Duration of the interval
        """
        return self._duration

    def enlarge_audible_interval(
        self,
        stretch_time: float,
        *,
        is_start_interval: bool = False,
        is_end_interval: bool = False,
    ) -> None:
        """
        Enlarges/Shrinks the audio interval, based on if it is silent or not
        :param stretch_time: Time the interval should be enlarged/shrunken
        :param is_start_interval: Whether the current interval is at the start (should not enlarge/shrink)
        :param is_end_interval: Whether the current interval is at the end (should not enlarge/shrink)
        :return: None
        """
        if stretch_time >= self.duration:
            raise ValueError("Stretch time to large, please choose smaller size")

        stretch_time_part = (-1 if self.is_silent else 1) * stretch_time / 2

        if not is_start_interval:
            self.start -= stretch_time_part

        if not is_end_interval:
            self.end += stretch_time_part

    def copy(self) -> "Interval":
        """
        Creates a deep copy of this Interval
        :return: Interval deepcopy
        """
        return Interval(self.start, self.end, is_silent=self.is_silent)

    def serialize(self) -> SerializedInterval:
        """
        Serializes the current interval into a dict format
        :return: serialized dict
        """
        return {"start": self.start, "end": self.end, "is_silent": self.is_silent}

    @staticmethod
    def deserialize(serialized_obj: SerializedInterval) -> "Interval":
        """
        Deserializes a previously serializes Interval and generates a new Interval with this data
        :param serialized_obj: previously serializes Interval (type dict)
        :return: Interval
        """
        return Interval(serialized_obj["start"], serialized_obj["end"], is_silent=serialized_obj["is_silent"])

    def __repr__(self):
        """
        String representation
        :return: String representation
        """
        return f"<Interval start={self.start} end={self.end} duration={self.duration} is_silent={self.is_silent}>"
