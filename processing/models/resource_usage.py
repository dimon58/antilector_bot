from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column, relationship, Mapped

from djgram.contrib.auth.models import User
from djgram.db.models import TimeTrackableBaseModel
from processing.models import ProcessedVideo


class VideoProcessingResourceUsage(TimeTrackableBaseModel):
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"))
    user: Mapped[User] = relationship()

    processed_video_id: Mapped[int] = mapped_column(ForeignKey(ProcessedVideo.id, ondelete="CASCADE"))
    processed_video: Mapped[ProcessedVideo] = relationship()

    # TODO: Научиться нормально считать это
    total_cpu_time: Mapped[float] = mapped_column(default=0, doc="Процессорное время, потраченное на обработку")
    real_processed: Mapped[bool] = mapped_column(
        doc="Если True, то этот пользователь был инициатором обработки. Иначе видео было взято из уже обработанных."
    )
