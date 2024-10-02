from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict


def get_playlist_duration(info: YtDlpInfoDict) -> float:
    return sum([x["duration"] for x in info["entries"]])


def convert_entries_generator(info: YtDlpInfoDict):
    info["entries"] = list(info["entries"])
    return info
