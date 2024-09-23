from pathlib import Path

import silero_vad
from torch.jit import ScriptModule

from lib.unsilence import Interval, Intervals, Unsilence
from lib.unsilence.detect_silence.detect_silence import detect_silence
from lib.unsilence.unsilence import UpdateCallbackType
from utils.audio import read_audio


def silent_detect_progress_update_proxy(callback: UpdateCallbackType, duration: float):
    def inner(current: float) -> None:
        callback(current * duration / 100, duration)

    return inner


def detect_speech(
    input_file: Path,
    model: silero_vad.utils_vad.OnnxWrapper | ScriptModule,
    *,
    threshold: float = 0.5,
    sampling_rate: int = 16000,
    min_speech_duration_ms: int = 250,
    max_speech_duration_s: float = float("inf"),
    min_silence_duration_ms: int = 100,
    speech_pad_ms: int = 30,
    return_seconds: bool = False,
    visualize_probs: bool = False,
    window_size_samples: int = 512,
    on_silence_detect_progress_update: UpdateCallbackType | None = None,
) -> Intervals:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file {input_file} does not exist!")

    wav, _ = read_audio(input_file, sample_rate=sampling_rate)
    media_duration = len(wav) / sampling_rate

    if on_silence_detect_progress_update is not None:
        on_silence_detect_progress_update = silent_detect_progress_update_proxy(
            callback=on_silence_detect_progress_update,
            duration=media_duration,
        )

    # ---------------------- Detection ---------------------- #
    model.reset_states()
    speech_timestamps = silero_vad.get_speech_timestamps(
        audio=wav,
        model=model,
        threshold=threshold,
        sampling_rate=sampling_rate,
        min_speech_duration_ms=min_speech_duration_ms,
        max_speech_duration_s=max_speech_duration_s,
        min_silence_duration_ms=min_silence_duration_ms,
        speech_pad_ms=speech_pad_ms,
        return_seconds=return_seconds,
        visualize_probs=visualize_probs,
        progress_tracking_callback=on_silence_detect_progress_update,
        window_size_samples=window_size_samples,
    )
    # ---------------------- Detection ---------------------- #

    # ---------------------- Converting ---------------------- #
    for speech_timestamp in speech_timestamps:
        speech_timestamp["start"] /= sampling_rate
        speech_timestamp["end"] /= sampling_rate

    intervals = Intervals()

    no_speech_interval = Interval(start=0, is_silent=True)

    for interval in speech_timestamps:
        no_speech_interval.end = interval["start"]

        intervals.add_interval(no_speech_interval)

        intervals.add_interval(
            Interval(
                start=interval["start"],
                end=interval["end"],
                is_silent=False,
            )
        )

        no_speech_interval = Interval(start=interval["end"], is_silent=True)

    if no_speech_interval.start < media_duration:
        no_speech_interval.end = media_duration
        intervals.add_interval(no_speech_interval)

    # ---------------------- Converting ---------------------- #

    if on_silence_detect_progress_update is not None:
        on_silence_detect_progress_update(100)

    return intervals


class Vad(Unsilence):

    def __init__(self, input_file: Path, model: silero_vad.utils_vad.OnnxWrapper | ScriptModule):
        """
        model: silero vad
        """
        super().__init__(input_file)
        self._model = model

    def detect_silence(
        self,
        *,
        short_interval_threshold: float = 0.3,
        stretch_time: float = 0.25,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        max_speech_duration_s: float = float("inf"),
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
        return_seconds: bool = False,
        visualize_probs: bool = False,
        window_size_samples: int = 512,
        on_silence_detect_progress_update: UpdateCallbackType | None = None,
        separated_audio: Path | None = None,
    ) -> Intervals:
        """
        Все аргументы, кроме silent_detect_progress_update игнорируются
        """
        self._intervals = detect_speech(
            separated_audio or self._input_file,
            model=self._model,
            threshold=threshold,
            sampling_rate=sampling_rate,
            min_speech_duration_ms=min_speech_duration_ms,
            max_speech_duration_s=max_speech_duration_s,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=speech_pad_ms,
            return_seconds=return_seconds,
            visualize_probs=visualize_probs,
            window_size_samples=window_size_samples,
            on_silence_detect_progress_update=on_silence_detect_progress_update,
        )

        self._intervals.optimize(short_interval_threshold, stretch_time)

        return self._intervals


def intervals_or(intervals1: Intervals, intervals2: Intervals) -> Intervals:
    """
    Применяет логическое или к 2 последовательностям интервалов
    """
    intervals1: list[Interval] = intervals1.intervals
    intervals2: list[Interval] = intervals2.intervals

    result = Intervals()
    idx2 = 0
    for interval1 in intervals1:
        while True:
            if idx2 >= len(intervals2):
                return result

            interval2 = intervals2[idx2]

            if interval2.start > interval1.end:
                break

            result.add_interval(
                Interval(
                    start=max(interval1.start, interval2.start),
                    end=min(interval1.end, interval2.end),
                    is_silent=interval1.is_silent or interval2.is_silent,
                )
            )

            if interval2.end > interval1.end:
                break

            idx2 += 1

    return result


def intervals_collapse(intervals: Intervals) -> Intervals:
    """
    Объединяет последовательные интервалы одного типа в один
    """

    # Если интервалов 1 или 0, то нет смысла их обрабатывать
    if len(intervals.intervals) < 2:  # noqa: PLR2004
        return intervals

    result = Intervals()
    current_interval: Interval = intervals.intervals[0]

    for interval in intervals.intervals[1:]:
        interval: Interval
        if interval.is_silent == current_interval.is_silent:
            current_interval.end = interval.end
        else:
            result.add_interval(current_interval)
            current_interval = interval

    if len(result.intervals) == 0:
        result.add_interval(current_interval)

    if result.intervals[-1].end < intervals.intervals[-1].end:
        current_interval.end = intervals.intervals[-1].end
        result.add_interval(current_interval)

    return result


class UnsilenceAndVad(Vad):
    def detect_silence(
        self,
        *,
        silence_level: float = -35.0,
        silence_time_threshold: float = 0.5,
        short_interval_threshold: float = 0.3,
        stretch_time: float = 0.25,
        on_silence_detect_progress_update: UpdateCallbackType | None = None,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        max_speech_duration_s: float = float("inf"),
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
        return_seconds: bool = False,
        visualize_probs: bool = False,
        window_size_samples: int = 512,
        on_vad_progress_update: UpdateCallbackType | None = None,
        separated_audio: Path | None = None,
    ) -> Intervals:
        silence = detect_silence(
            separated_audio or self._input_file,
            silence_level=silence_level,
            silence_time_threshold=silence_time_threshold,
            on_silence_detect_progress_update=on_silence_detect_progress_update,
        )

        no_speech = detect_speech(
            separated_audio or self._input_file,
            model=self._model,
            threshold=threshold,
            sampling_rate=sampling_rate,
            min_speech_duration_ms=min_speech_duration_ms,
            max_speech_duration_s=max_speech_duration_s,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=speech_pad_ms,
            return_seconds=return_seconds,
            visualize_probs=visualize_probs,
            window_size_samples=window_size_samples,
            on_silence_detect_progress_update=on_vad_progress_update,
        )

        intervals = intervals_or(silence, no_speech)
        intervals = intervals_collapse(intervals)
        intervals.optimize(short_interval_threshold, stretch_time)

        self._intervals = intervals

        return self._intervals
