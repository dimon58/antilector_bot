import logging
from io import BytesIO
from urllib.parse import urlparse

import aiohttp
from PIL import Image

from tools.yt_dlp_downloader.yt_dlp_download_videos import YtDlpInfoDict

logger = logging.getLogger(__name__)


def jpg2webp(input_image: bytes) -> bytes:
    logger.info("Converting jpg to webp")

    # https://stackoverflow.com/questions/71904568/converting-webp-to-jpg-with-a-white-background-using-pillow
    input_image_buffer = BytesIO(input_image)
    image = Image.open(input_image_buffer).convert("RGBA")
    background = Image.new("RGBA", image.size, "white")
    background.paste(image, image)

    output_image_buffer = BytesIO()
    background.convert("RGB").save(output_image_buffer, format="JPEG")
    output_image_buffer.seek(0)

    return output_image_buffer.getvalue()


async def download_thumbnail(thumbnail_url: str) -> bytes:
    logger.info("Downloading thumbnail %s", thumbnail_url)
    async with (
        aiohttp.ClientSession() as session,
        session.get(thumbnail_url) as resp,
    ):
        return await resp.read()


def is_jpeg(url: str) -> bool:
    return urlparse(url).path.endswith(".jpg")


async def get_best_thumbnail(info: YtDlpInfoDict) -> bytes | None:
    thumbnails = [
        thumbnail
        for thumbnail in info.get("thumbnails", [])
        if thumbnail.get("url") is not None and thumbnail.get("height") is not None
    ]

    max_height = -1
    thumbnail_with_max_height = None
    for thumbnail in thumbnails:
        height = thumbnail["height"]
        if height > max_height:
            max_height = height
            thumbnail_with_max_height = thumbnail

    thumbnail_url = thumbnail_with_max_height["url"]
    image_bytes = await download_thumbnail(thumbnail_url)

    if is_jpeg(thumbnail_url):
        return image_bytes

    # TODO: запихать в process executor
    try:
        return jpg2webp(image_bytes)

    except Exception as exc:
        logger.exception("Failed to convert image to webp: %s", exc, exc_info=exc)  # noqa: TRY401

    for thumbnail in thumbnails:
        thumbnail_url = thumbnail["url"]
        if is_jpeg(thumbnail_url):
            return await download_thumbnail(thumbnail_url)

    return None
