from djgram.utils.formating import seconds_to_human_readable
from tools.yt_dlp_downloader.misc import get_playlist_duration, yt_dlp_get_html_link
from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict


def format_as_video_html(info: YtDlpInfoDict) -> str:  # noqa: D103
    return f"{yt_dlp_get_html_link(info)} - {seconds_to_human_readable(info["duration"])}"


def format_as_playlist_html(info: YtDlpInfoDict) -> str:  # noqa: D103
    playlist_desc = (
        f"{yt_dlp_get_html_link(info)}\n"
        f"Общая продолжительность - {seconds_to_human_readable(get_playlist_duration(info))}"
    )
    videos_desc = "\n●".join(
        f"{yt_dlp_get_html_link(video)} - {seconds_to_human_readable(video["duration"])}" for video in info["entries"]
    )

    return f"{playlist_desc}\n\nСписок видео:\n●{videos_desc}"
