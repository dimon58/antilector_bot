import logging
from typing import Any, Literal

from configs import YT_DLP_VIDEO_MAX_HEIGHT, YT_DLP_VIDEO_MAX_WIDTH

logger = logging.getLogger(__name__)


def get_video_format_repr(video_format: dict[str, Any]) -> str:
    return f"{video_format.get('format')} - {video_format.get('vbr', 0) or 0:.0f} kb/s - {video_format['ext']}"


def get_audio_format_repr(audio_format: dict[str, Any]) -> str:
    return f"{audio_format.get('format')} - {audio_format.get('abr', 0) or 0:.0f} kb/s - {audio_format['ext']}"


def has_codec(format_: dict, key: Literal["acodec", "vcodec"]) -> bool:
    value = format_.get(key, "none")
    return value != "none" and value is not None


def has_bitrate(format_: dict, key: Literal["abr", "vbr", "tbe"]) -> bool:
    value = format_.get(key)

    if not isinstance(value, float | int):
        return False

    return value > 0


def fallback_any_audio(formats: list[dict[str, Any]]) -> dict | None:
    """
    Пытается найти любое аудио
    """
    try:
        f = next(f for f in formats if has_codec(f, "acodec"))

    except StopIteration:
        if len(formats) == 0:
            logger.warning("Failed to select audio format")
            return None

        return formats[0]

    else:
        logger.warning("Fallback audio to %s", get_audio_format_repr(f))
        return f


def fallback_any_video(formats: list[dict[str, Any]]) -> dict | None:
    """
    Пытается найти любое видео
    """
    try:
        f = next(f for f in formats if has_codec(f, "vcodec"))

    except StopIteration:
        if len(formats) == 0:
            logger.warning("Failed to select video format")
            return None

        return formats[0]

    else:
        logger.warning("Fallback video to %s", get_video_format_repr(f))
        return f


def merge_formats(*formats_: dict[str, Any]) -> dict[str, Any]:
    # These are the minimum required fields for a merged format
    return {
        "format_id": "+".join(str(f["format_id"]) for f in formats_),
        "ext": formats_[0]["ext"],
        "requested_formats": formats_,
        # Must be + separated list of protocols
        "protocol": "+".join(str(f["protocol"]) for f in formats_),
    }


def select_best_video(formats: list[dict[str, Any]]) -> dict[str, Any]:
    # Сортируем по битрейту
    # В yt-dlp есть эвристики по сортировки по качеству,
    # поэтому ещё применяем stable sort (в питоне по умолчанию)

    video_formats = [
        format_
        for format_ in formats
        if has_codec(format_, "vcodec")
        and has_bitrate(format_, "vbr")  # В файле содержится видео
        # Высота видео не должна быть слишком большой
        # Если она не указана, что считаем, что не подходит
        # Так как в высоте может быть указан 0 или высота вообще может быть не указана,
        # поэтому применяем питонью магию
        and (format_.get("height") or (YT_DLP_VIDEO_MAX_HEIGHT + 1)) <= YT_DLP_VIDEO_MAX_HEIGHT
        and (format_.get("width") or (YT_DLP_VIDEO_MAX_WIDTH + 1)) <= YT_DLP_VIDEO_MAX_WIDTH
    ]

    if len(video_formats) == 0:
        return fallback_any_video(formats)

    return video_formats[0]


def select_best_audio(formats: list[dict[str, Any]]) -> dict[str, Any]:
    audio_formats = [
        format_
        for format_ in formats
        if has_codec(format_, "acodec") and has_bitrate(format_, "abr")  # В файле содержится видео
    ]

    if len(audio_formats) == 0:
        return fallback_any_audio(formats)

    return audio_formats[0]


def select_format(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Выбирает mp4 или mkv с разрешением не более 1080p

    https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#use-a-custom-format-selector
    """

    # formats are already sorted worst to best
    formats = ctx.get("formats")[::-1]

    best_video = select_best_video(formats)
    best_audio = select_best_audio(formats)

    if best_video is not None and best_audio is not None:
        if best_video.get("format_id") == best_audio.get("format_id"):
            logger.info("Selected video+audio in one format %s", get_video_format_repr(best_video))
            yield merge_formats(best_video)

        else:
            logger.info(
                "Selected separated formats %s+%s: video %s, audio %s",
                best_video["format_id"],
                best_audio["format_id"],
                get_video_format_repr(best_video),
                get_audio_format_repr(best_audio),
            )
            yield merge_formats(best_video, best_audio)

    elif best_video is not None:
        logger.info("Selected video only format %s", get_video_format_repr(best_video))
        yield merge_formats(best_video)

    elif best_audio is not None:
        logger.info("Selected audio only format %s", get_audio_format_repr(best_audio))
        yield merge_formats(best_audio)

    else:
        logger.warning("No format selected")
        yield {}
