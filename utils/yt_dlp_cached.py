from concurrent.futures import ThreadPoolExecutor

from cashews import Cache

from configs import (
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_USER,
    REDIS_YT_DLP_CACHE_DB,
    YT_DLP_EXTRACT_INFO_CACHE_TTL,
)
from djgram.utils.async_tools import run_async_wrapper
from tools.yt_dlp_downloader.yt_dlp_download_videos import extract_info

thread_executor = ThreadPoolExecutor()

yt_dlp_cache = Cache()
yt_dlp_cache.setup(f"redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_YT_DLP_CACHE_DB}")

extract_info_async_cached = yt_dlp_cache(ttl=YT_DLP_EXTRACT_INFO_CACHE_TTL)(
    run_async_wrapper(extract_info, thread_executor),
)
