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
    image = Image.open(input_image_buffer)
    background = Image.new("RGB", image.size, "white")
    background.paste(image, image)

    output_image_buffer = BytesIO()
    background.save(output_image_buffer, format="JPEG")
    output_image_buffer.seek(0)

    return output_image_buffer.getvalue()


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
    logger.info("Downloading thumbnail %s", thumbnail_url)
    async with (
        aiohttp.ClientSession() as session,
        session.get(thumbnail_url) as resp,
    ):
        image_bytes = await resp.read()

    if urlparse(thumbnail_url).path.endswith(".jpg"):
        return image_bytes

    # TODO: запихать в process executor
    return jpg2webp(image_bytes)
