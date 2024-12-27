"""
Администрирование
"""

from djgram.contrib.admin import AppAdmin, ModelAdmin
from djgram.contrib.admin.action_buttons import (
    DownloadFileActionButton,
    DownloadJsonActionButton,
    DownloadStringAsFileActionButton,
)
from djgram.contrib.admin.rendering import OneLineTextRenderer
from processing.models import LectureSummary

app = AppAdmin(verbose_name="Коспектирование")


@app.register
class LectureSummaryAdmin(ModelAdmin):
    model = LectureSummary
    name = "Конспекты"
    list_display = ["id", "original_video_id"]
    exclude_fields = (
        "transcription_text",
        "stats",
        "latex",
    )
    widgets_override = {
        "original_video_id": OneLineTextRenderer,
    }
    object_action_buttons = (
        DownloadStringAsFileActionButton(
            "download_latex_source",
            "📥 Скачать latex",
            field_name="latex",
            filename="source.tex",
        ),
        DownloadFileActionButton("download_pdf", "📥 Скачать pdf", field_name="pdf"),
        DownloadJsonActionButton(
            "download_stats",
            "📊 Скачать статистику обработки",
            field_name="stats",
            filename="stats.json",
        ),
    )
