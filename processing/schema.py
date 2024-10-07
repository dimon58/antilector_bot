import aiogram
import pydantic
from pydantic import model_validator

FILE_TYPE = "file"


class VideoOrPlaylistForProcessing(pydantic.BaseModel):
    url: str | None = None
    video: aiogram.types.Video | None = None
    document: aiogram.types.Document | None = None
    is_playlist: bool = False

    user_id: int
    telegram_chat_id: int | str
    telegram_message_id: int

    audio_processing_profile_id: int
    unsilence_profile_id: int

    @model_validator(mode="after")
    def validate_content(self, _info):
        has_url = self.url is not None
        has_video = self.video is not None
        has_document = self.document is not None

        err_msg = "You must specify either url or video or document"
        if has_url and (has_video or has_document):
            raise ValueError(err_msg)

        if has_video and has_document:
            raise ValueError(err_msg)

        return self

    def get_tg_video(self) -> aiogram.types.Video | aiogram.types.Document | None:
        return self.video or self.document

    def make_id_from_telegram(self) -> str:

        video = self.get_tg_video()
        if video is None:
            raise ValueError("There is not telegram video")

        return f"{FILE_TYPE}_{video.file_id}"
