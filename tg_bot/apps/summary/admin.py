"""
Администрирование
"""

from djgram.contrib.admin import AppAdmin, ModelAdmin
from processing.models import LectureSummary

app = AppAdmin(verbose_name="Коспектирование")


@app.register
class LectureSummaryAdmin(ModelAdmin):
    model = LectureSummary
    name = "Конспекты"
    list_display = ["id"]
