import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

from ffmpeg.types import Option

from libs.unsilence import Interval
from libs.unsilence.render_media.options import RenderOptions
from libs.unsilence.render_media.render_filter import (
    get_audio_filter,
    get_fade_filter,
    get_speed_and_volume,
    get_video_filter,
)
from utils.fixed_ffmpeg import FixedFFmpeg

FFmpegOptionsType: TypeAlias = dict[str, Option | None]


logger = logging.getLogger(__name__)


@dataclass
class IntervalRenderTask:
    interval: Interval
    video_filter: str | None = None
    audio_filter: str | None = None

    @classmethod
    def create(cls, interval: Interval, render_options: RenderOptions) -> "IntervalRenderTask":
        task = IntervalRenderTask(interval=interval)

        current_speed, current_volume = get_speed_and_volume(render_options, interval)
        # ----------------- video filter ----------------- #

        if not render_options.audio_only:
            task.video_filter = get_video_filter(current_speed)
            logger.debug("Video filter: %s", task.video_filter)

        # ----------------- audio filter ----------------- #
        fade = get_fade_filter(
            total_duration=interval.duration,
            interval_in_fade_duration=render_options.interval_in_fade_duration,
            interval_out_fade_duration=render_options.interval_out_fade_duration,
            fade_curve=render_options.fade_curve,
        )
        task.audio_filter = get_audio_filter(fade, current_speed, current_volume)
        logger.debug("Audio filter: %s", task.audio_filter)

        return task


@dataclass
class IntervalGroupRenderTask:
    interval_render_tasks: list[IntervalRenderTask] = field(default_factory=list)
    _total_interval_duration: float = 0

    @property
    def total_interval_duration(self) -> float:
        return self._total_interval_duration

    @property
    def start_timestamp(self) -> float:
        return self.interval_render_tasks[0].interval.start

    @property
    def end_timestamp(self) -> float:
        return self.interval_render_tasks[-1].interval.end

    def has_tasks(self) -> bool:
        return len(self.interval_render_tasks) > 0

    def add(self, interval_render_task: IntervalRenderTask) -> None:
        self.interval_render_tasks.append(interval_render_task)
        self._total_interval_duration += interval_render_task.interval.duration

    def _generate_command_for_single_interval(  # noqa: PLR0912
        self,
        render_options: RenderOptions,
        separated_audio: Path | None,
    ) -> tuple[FFmpegOptionsType, FFmpegOptionsType]:

        # ----------------------- single task specific ----------------------- #
        task = self.interval_render_tasks[0]
        input_options = {"ss": task.interval.start, "to": task.interval.end}

        output_options = {}

        complex_filter_components = []

        # ----------------- video filter ----------------- #
        if task.video_filter is not None:
            complex_filter_components.append(f"[0:v]{task.video_filter}[v]")

        # ----------------- audio filter ----------------- #
        if task.audio_filter:
            audio_idx = 1 if separated_audio else 0
            complex_filter_components.append(f"[{audio_idx}:a]{task.audio_filter}[a]")

        # ----------------- complex filter ----------------- #

        if len(complex_filter_components) > 0:
            complex_filter = ";".join(complex_filter_components)
            output_options["filter_complex"] = complex_filter
            logger.debug("Using complex filter %s", complex_filter)
        else:
            logger.debug("Not using complex filter")

        output_map = []
        if not render_options.audio_only:
            if task.video_filter is not None:
                output_map.append("[v]")
            else:
                output_map.append("0:v")
                if render_options.allow_copy_video_stream:
                    output_options["c:v"] = "copy"

        if task.audio_filter is not None:
            output_map.append("[a]")
        else:
            audio_idx = 1 if separated_audio else 0
            output_map.append(f"{audio_idx}:a")
            if render_options.allow_copy_audio_stream:
                output_options["c:a"] = "copy"

        output_options["map"] = output_map

        if render_options.audio_only:
            output_options["vn"] = None

        if render_options.force_video_codec is not None and output_options.get("c:v") != "copy":
            output_options["c:v"] = render_options.force_video_codec

        if render_options.force_audio_codec is not None and output_options.get("c:a") != "copy":
            output_options["c:a"] = render_options.force_audio_codec

        return input_options, output_options

    def _generate_command_for_multiple_interval(
        self,
        render_options: RenderOptions,
        separated_audio: Path | None,
    ) -> tuple[FFmpegOptionsType, FFmpegOptionsType]:

        # todo: allow copy

        trim_filters = []

        start_timestamp = self.start_timestamp
        audio_idx = 1 if separated_audio else 0
        for idx, task in enumerate(self.interval_render_tasks):
            if not render_options.audio_only:
                video_filter = f",{task.video_filter}" if task.video_filter is not None else ""

                trim_filters.append(
                    f"[0:v]"
                    f"trim=start={task.interval.start - start_timestamp}:end={task.interval.end - start_timestamp}"
                    f",setpts=PTS-STARTPTS{video_filter}"
                    f"[vf{idx}]"
                )

            audio_filter = f",{task.audio_filter}" if task.audio_filter is not None else ""
            trim_filters.append(
                f"[{audio_idx}:a]"
                f"atrim=start={task.interval.start - start_timestamp}:end={task.interval.end - start_timestamp}"
                f",asetpts=PTS-STARTPTS{audio_filter}"
                f"[af{idx}]"
            )

        concat_input = "".join(f"[vf{idx}][af{idx}]" for idx in range(len(self.interval_render_tasks)))
        concat_filter = f"{concat_input}concat=n={len(self.interval_render_tasks)}:v=1:a=1[v][a]"

        complex_filter_components = [
            *trim_filters,
            concat_filter,
        ]
        complex_filter = ";".join(complex_filter_components)

        # Можно использовать параметр filter_complex_script, если фильтр будет слишком большим
        # Но пока это не имеет смысла, так большие (>50 интервалов) фильтры работают очень медленно
        output_options = {"filter_complex": complex_filter, "map": ["[v]", "[a]"]}

        if render_options.audio_only:
            output_options["vn"] = None

        return {"ss": self.start_timestamp, "to": self.end_timestamp}, output_options

    def generate_command(
        self,
        input_file: Path,
        output_file: Path,
        render_options: RenderOptions,
        separated_audio: Path | None,
    ) -> FixedFFmpeg:
        if len(self.interval_render_tasks) == 0:
            raise ValueError("No tasks in group")

        ffmpeg = FixedFFmpeg().option("ignore_unknown").option("y")

        if render_options.use_nvenc:
            logger.debug("Rendering using nvenc")
            ffmpeg = ffmpeg.option("hwaccel", "cuda").option("hwaccel_output_format", "cuda")

        logger.debug("Rendering on cpu")

        if len(self.interval_render_tasks) == 1:
            input_options, output_options = self._generate_command_for_single_interval(render_options, separated_audio)
        else:
            input_options, output_options = self._generate_command_for_multiple_interval(
                render_options, separated_audio
            )

        output_options |= {
            "vsync": 1,
            "async": 1,
            "safe": 0,
        }

        if render_options.force_video_codec is not None:
            output_options["c:v"] = render_options.force_video_codec

        if render_options.force_audio_codec is not None:
            output_options["c:a"] = render_options.force_audio_codec

        ffmpeg = ffmpeg.input(input_file, input_options)

        if separated_audio:
            ffmpeg = ffmpeg.input(separated_audio, input_options)

        return ffmpeg.output(output_file, output_options)

    def generate_command_notrim(
        self, input_file: Path, output_file: Path, render_options: RenderOptions
    ) -> FixedFFmpeg:
        """
        НЕ ИСПОЛЬЗОВАТЬ!

        Попытка полностью избавить от trim и atrim

        Получилось гораздо медленнее, чем версия с trim и atrim
        """

        if len(self.interval_render_tasks) == 0:
            raise ValueError("No tasks in group")

        ffmpeg = FixedFFmpeg().option("ignore_unknown").option("y")

        if render_options.use_nvenc:
            logger.debug("Rendering using nvenc")
            base_input_options = {
                "hwaccel": "cuda",
                "hwaccel_output_format": "cuda",
            }
        else:
            base_input_options = {}
            logger.debug("Rendering on cpu")

        filters = []
        for idx, task in enumerate(self.interval_render_tasks):
            ffmpeg = ffmpeg.input(input_file, base_input_options | {"ss": task.interval.start, "to": task.interval.end})

            if not render_options.audio_only:
                if task.video_filter is not None:
                    filters.append(f"[{idx}:v]{task.video_filter}[vf{idx}]")
                else:
                    filters.append(f"[{idx}:v]setpts=PTS[vf{idx}]")

            if task.audio_filter is not None:
                filters.append(f"[{idx}:a]{task.audio_filter}[af{idx}]")
            else:
                filters.append(f"[{idx}:a]atempo=1[af{idx}]")

        concat_input = "".join(f"[vf{idx}][af{idx}]" for idx in range(len(self.interval_render_tasks)))
        concat_filter = f"{concat_input}concat=n={len(self.interval_render_tasks)}:v=1:a=1[v][a]"

        complex_filter_components = [
            *filters,
            concat_filter,
        ]
        complex_filter = ";".join(complex_filter_components)

        output_options = {
            "vsync": 1,
            "async": 1,
            "safe": 0,
            "filter_complex": complex_filter,
            "map": ["[v]", "[a]"],
        }

        if render_options.force_video_codec is not None:
            output_options["c:v"] = render_options.force_video_codec

        if render_options.force_audio_codec is not None:
            output_options["c:a"] = render_options.force_audio_codec

        return ffmpeg.output(output_file, output_options)
