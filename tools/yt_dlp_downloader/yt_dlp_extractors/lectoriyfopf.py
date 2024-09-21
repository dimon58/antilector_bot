import re
from typing import Any

from yt_dlp.downloader import FileDownloader
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.youtube import YoutubeIE
from yt_dlp.utils import ExtractorError


class LectoriyFopfIE(InfoExtractor):
    """
    Extractor from https://lectoriyfopf.ru/
    """

    _VALID_URL = (
        r"https?://(?:www\.)?lectoriyfopf\.ru/(?P<playlist_id>[\w\d]+)"
        r"(#tlection=(?P<lectoriyfopf_id>\d+)_(?P<video_id>\d+))?"
    )

    IE_NAME = "lectoriyfopf"

    URLS_REGEX = re.compile(r"<div[^>]+class=\"t\d+__data\"[^>]*>([^<]*)</div>", flags=re.DOTALL)
    TITLE_REGEX = re.compile(r"<div[^>]+class=\"[^>]*t-title[^>]*\"[^>]*>(.+?)</div>")

    def __init__(self, downloader: FileDownloader | None = None):  # noqa: D107
        self._youtube_extractor = YoutubeIE(downloader)
        super().__init__(downloader)

    def set_downloader(self, downloader: FileDownloader) -> None:
        super().set_downloader(downloader)
        self._youtube_extractor.set_downloader(downloader)

    def _extract_video_urls(self, webpage: str) -> list[tuple[str, str]]:
        split = self._html_search_regex(self.URLS_REGEX, webpage, "urls").strip().split(";")

        if len(split) < 2:  # noqa: PLR2004
            raise ValueError("Wrong format at page")

        url_1, *data, name_n = map(str.strip, split)

        urls = [url_1]
        names = []

        for datum in data:
            idx = datum.rfind("https://")

            names.append(datum[:idx].strip())
            urls.append(datum[idx:].strip())

        names.append(name_n)

        return list(zip(urls, names, strict=True))

    def _extract_video(
        self,
        video_url: str,
        name: str,
        _id: str,
        playlist_title: str,
        webpage_url: str,
    ) -> dict[str, Any]:
        youtube_info = self._youtube_extractor.extract(video_url)

        youtube_info["title"] = f"{playlist_title}. {name}"
        youtube_info["id"] = _id
        youtube_info["webpage_url"] = webpage_url

        return youtube_info

    def _real_extract(self, url: str) -> dict[str, Any]:
        mobj = re.match(self._VALID_URL, url)
        playlist_id = mobj.group("playlist_id")

        webpage = self._download_webpage(url, playlist_id)

        if "<title>Members area: authentication required</title>" in webpage:
            raise ExtractorError("Content only for students", expected=True)

        playlist_title = self._html_search_regex(self.TITLE_REGEX, webpage, "title")
        if playlist_title.endswith("."):  # noqa: SIM108
            playlist_title_no_dot = playlist_title[:-1]
        else:
            playlist_title_no_dot = playlist_title

        urls = self._extract_video_urls(webpage)
        video_id = mobj.group("video_id")

        if video_id is not None:
            video_idx = int(video_id) - 1
            if len(urls) < video_idx + 1:
                raise ExtractorError(
                    f"Wrong video number in playlist: {video_id} - more than total video number ({len(urls)})",
                    expected=True,
                    video_id=video_id,
                )
            video_url, name = urls[video_idx]
            video_info = self._extract_video(
                video_url=video_url,
                name=name,
                playlist_title=playlist_title_no_dot,
                webpage_url=url,
                _id=f"{playlist_id}_1",
            )
            video_info["lectoriyfopf_id"] = mobj.group("lectoriyfopf_id")
            return video_info

        entries = []

        for idx, (video_url, name) in enumerate(urls, start=1):
            _id = f"{playlist_id}_{idx}"
            entry = self._extract_video(
                video_url=video_url,
                name=name,
                playlist_title=playlist_title_no_dot,
                webpage_url=url,
                _id=_id,
            )
            self.to_screen(f"Downloaded {idx}/{len(urls)}: {_id}")
            entries.append(entry)

        playlist_info = self.playlist_result(
            entries=entries,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            playlist_count=len(urls),
        )
        playlist_info["webpage_url"] = f"https://lectoriyfopf.ru/{playlist_id}"

        return playlist_info
