import logging
import shlex
from pathlib import Path
from typing import Literal

from ffmpeg_normalize import FFmpegNormalize
from pydantic import model_validator

from utils.fixed_ffmpeg import FixedFFmpeg
from utils.progress_bar import setup_progress_for_ffmpeg
from utils.video import get_video_duration

from .abstract import Action, ActionStatsType

logger = logging.getLogger(__name__)


class ExtractAudioFromVideo(Action):
    name: Literal["ExtractAudioFromVideo"] = "ExtractAudioFromVideo"

    to_mono: bool = False
    output_config: dict[str, str | int] = {}

    @model_validator(mode="after")
    def resolve_configs(self):
        if self.to_mono:
            self.output_config["ac"] = 1

        return self

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:
        input_file = input_file.absolute().as_posix()
        output_file = output_file.absolute().as_posix()

        ffmpeg = FixedFFmpeg().option("y").input(input_file).output(output_file, **self.output_config)
        setup_progress_for_ffmpeg(ffmpeg, get_video_duration(input_file), "Extracting audio from video")
        logger.debug("Executing %s", shlex.join(ffmpeg.arguments))

        ffmpeg.execute()

        return None


class SimpleFFMpegAction(Action):
    name: Literal["SimpleFFMpegAction"] = "SimpleFFMpegAction"

    input_options: dict[str, int | float | str | list[int | float | str] | None] = {}
    output_options: dict[str, int | float | str | list[int | float | str] | None] = {}

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:
        input_file = input_file.absolute().as_posix()
        output_file = output_file.absolute().as_posix()

        ffmpeg = (
            FixedFFmpeg().option("y").input(input_file, self.input_options).output(output_file, self.output_options)
        )
        setup_progress_for_ffmpeg(ffmpeg, get_video_duration(input_file), "Executing simple ffmpeg action")

        logger.debug("Executing %s", shlex.join(ffmpeg.arguments))

        ffmpeg.execute()

        return None


class FFMpegNormalizeAction(Action):
    name: Literal["FFMpegNormalizeAction"] = "FFMpegNormalizeAction"

    normalization_type: Literal["ebu", "rms", "peak"] = "ebu"
    target_level: float = -23.0
    print_stats: bool = False
    # threshold=0.5
    loudness_range_target: float = 7.0
    keep_loudness_range_target: bool = False
    keep_lra_above_loudness_range_target: bool = False
    true_peak: float = -2.0
    offset: float = 0.0
    dual_mono: bool = False
    dynamic: bool = False
    audio_codec: str = "pcm_s16le"
    audio_bitrate: float | None = None
    sample_rate: float | int | None = None
    keep_original_audio: bool = False
    pre_filter: str | None = None
    post_filter: str | None = None
    video_codec: str = "copy"
    video_disable: bool = False
    subtitle_disable: bool = False
    metadata_disable: bool = False
    chapters_disable: bool = False
    extra_input_options: list[str] | None = None
    extra_output_options: list[str] | None = None
    output_format: str | None = None
    dry_run: bool = False
    debug: bool = False
    progress: bool = False

    def run(self, input_file: Path, output_file: Path) -> ActionStatsType | None:
        ffmpeg_normalize = FFmpegNormalize(
            normalization_type=self.normalization_type,
            target_level=self.target_level,
            print_stats=self.print_stats,
            # threshold=self.threshold,
            loudness_range_target=self.loudness_range_target,
            keep_loudness_range_target=self.keep_loudness_range_target,
            keep_lra_above_loudness_range_target=self.keep_lra_above_loudness_range_target,
            true_peak=self.true_peak,
            offset=self.offset,
            dual_mono=self.dual_mono,
            dynamic=self.dynamic,
            audio_codec=self.audio_codec,
            audio_bitrate=self.audio_bitrate,
            sample_rate=self.sample_rate,
            keep_original_audio=self.keep_original_audio,
            pre_filter=self.pre_filter,
            post_filter=self.post_filter,
            video_codec=self.video_codec,
            video_disable=self.video_disable,
            subtitle_disable=self.subtitle_disable,
            metadata_disable=self.metadata_disable,
            chapters_disable=self.chapters_disable,
            extra_input_options=self.extra_input_options,
            extra_output_options=self.extra_output_options,
            output_format=self.output_format,
            dry_run=self.dry_run,
            debug=self.debug,
            progress=self.progress,
        )
        ffmpeg_normalize.add_media_file(input_file.as_posix(), output_file.as_posix())
        ffmpeg_normalize.run_normalization()

        return None
