import logging

from lib.unsilence import Interval
from lib.unsilence.render_media.options import RenderOptions

# FFMpeg не позволяет делать скорость аудио меньше 0.5 или больше 100
# https://ffmpeg.org/ffmpeg-filters.html#atempo
FFMPEG_MIN_TEMPO = 0.5
FFMPEG_MAX_TEMPO = 100

logger = logging.getLogger(__name__)


def clamp_speed(duration: float, speed: float, minimum_interval_duration: float = 0.25) -> float:
    if duration / speed < minimum_interval_duration:
        speed = duration / minimum_interval_duration

    if speed < FFMPEG_MIN_TEMPO:
        logger.warning("Too low speed %g, minimum possible %s", speed, FFMPEG_MIN_TEMPO)
        return FFMPEG_MIN_TEMPO

    if speed > FFMPEG_MAX_TEMPO:
        logger.warning("Too high speed %g, maximum possible %s", speed, FFMPEG_MAX_TEMPO)
        return FFMPEG_MAX_TEMPO

    return speed


def get_fade_filter(
    total_duration: float,
    interval_in_fade_duration: float,
    interval_out_fade_duration: float,
    fade_curve: str,
) -> str:
    interval_in_fade_duration = min(interval_in_fade_duration, total_duration / 2)
    interval_out_fade_duration = min(interval_out_fade_duration, total_duration / 2)

    res = []

    if interval_in_fade_duration != 0.0:
        res.append(f"afade=t=in:st=0:d={interval_in_fade_duration:.4f}:curve={fade_curve}")

    if interval_out_fade_duration != 0.0:
        res.append(
            f"afade=t=out"
            f":st={total_duration - interval_out_fade_duration:.4f}"
            f":d={interval_out_fade_duration:.4f}"
            f":curve={fade_curve}"
        )

    return ",".join(res)


def get_speed_and_volume(render_options: RenderOptions, interval: Interval) -> tuple[float, float]:
    if interval.is_silent:
        current_speed = render_options.silent_speed
        current_volume = render_options.silent_volume
    else:
        current_speed = render_options.audible_speed
        current_volume = render_options.audible_volume

    current_speed = clamp_speed(interval.duration, current_speed, render_options.minimum_interval_duration)

    return current_speed, current_volume


def get_video_filter(current_speed: float) -> str | None:
    if current_speed != 1.0:
        return f"setpts=PTS/{current_speed:.4f}"

    return None


def get_audio_filter(fade: str, current_speed: float, current_volume: float) -> str | None:
    audio_filter_components: list[str] = []
    if fade != "":
        audio_filter_components.append(fade)

    if current_speed != 1.0:
        audio_filter_components.append(f"atempo={current_speed:.4f}")

    if current_volume != 1.0:
        audio_filter_components.append(f"volume={current_volume}")

    if len(audio_filter_components) > 0:
        return f"{",".join(audio_filter_components)}"

    return None
