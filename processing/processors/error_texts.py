from processing.models import ProcessedVideo
from tools.yt_dlp_downloader.misc import yt_dlp_get_html_link


def get_generic_error_text(processed_video: ProcessedVideo):
    return f"Ошибка обработки видео {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}"


def get_unable_to_process_text(processed_video: ProcessedVideo):
    return (
        f"Невозможно обработать видео {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}."
        f" Попробуйте другие профили обработки, если вы уверены, что в видео есть участки без тишины."
    )


def get_silence_only_error_text(processed_video: ProcessedVideo):
    return (
        f"В видео {yt_dlp_get_html_link(processed_video.original_video.yt_dlp_info)}"
        f" найдена только тишина. Обработка прекращена."
        f" Попробуйте другие профили обработки, если вы уверены, что в видео есть участки без тишины."
    )
