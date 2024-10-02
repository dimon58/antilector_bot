from typing import TypeAlias

from yt_dlp.utils import LazyList

from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict

Json: TypeAlias = dict | list | str | float | int | bool | None


def get_playlist_duration(info: YtDlpInfoDict) -> float:
    return sum([x["duration"] for x in info["entries"]])


def convert_entries_generator(info: YtDlpInfoDict):
    info["entries"] = list(info["entries"])
    return info


def json_defaults(obj: Json) -> Json:
    if isinstance(obj, LazyList):
        return list(obj)

    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def yt_dlp_jsonify(obj: Json) -> Json:
    if isinstance(obj, dict):
        return {k: yt_dlp_jsonify(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [yt_dlp_jsonify(elem) for elem in obj]

    if isinstance(obj, LazyList):
        return list(obj)

    return obj
