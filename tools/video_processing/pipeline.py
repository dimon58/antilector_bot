import logging
import time
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Self

import pydantic

from lib.nisqa.model import NisqaModel
from tools.audio_processing.actions.ffmpeg_actions import ExtractAudioFromVideo
from tools.audio_processing.pipeline import AudioPipeline, AudioPipelineStatistics, StepStatistics
from utils.audio import measure_volume, read_audio
from utils.pathtools import split_filename_ext
from utils.video import replace_audio_in_video

from .actions.unsilence_actions import UnsilenceAction

logger = logging.getLogger(__name__)


class VideoPipelineStatistics(pydantic.BaseModel):
    total_time: float

    extract_audio_stats: StepStatistics
    audio_pipeline_stats: AudioPipelineStatistics
    replacing_audio_time: float
    unsilence_stats: StepStatistics


class VideoPipeline(pydantic.BaseModel):
    audio_pipeline: AudioPipeline
    unsilence_action: UnsilenceAction

    use_nvenc: bool | None = None
    force_video_codec: str | None = None
    force_audio_codec: str | None = None
    force_transcode_video: bool = False
    force_transcode_audio: bool = False

    @pydantic.model_validator(mode="after")
    def resolve_settings(self) -> Self:

        if self.use_nvenc is not None:
            logger.info("Using nvenc for unsilence")
            self.unsilence_action.use_nvenc = self.use_nvenc

        if self.force_video_codec is not None:
            logger.info("Encoding video using %s for unsilence", self.force_video_codec)
            self.unsilence_action.force_video_codec = self.force_video_codec

            if self.force_transcode_video:
                logger.info("Allowing copy video stream for unsilence")
                self.unsilence_action.allow_copy_video_stream = True

        if self.force_audio_codec is not None and self.force_transcode_audio:
            logger.info("Allowing copy audio stream for unsilence")
            self.unsilence_action.allow_copy_audio_stream = True

        return self

    def run(
        self,
        input_file: Path,
        output_file: Path,
        tempdir_factory: AbstractContextManager[str],
        nisqa_model: NisqaModel | None = None,
    ) -> VideoPipelineStatistics:

        pipeline_start = time.perf_counter()

        with tempdir_factory as _tempdir:
            tempdir = Path(_tempdir)

            ###############################
            logger.info("Extracting audio")
            extract_audio_start = time.perf_counter()
            extracted_audio_file = tempdir / "step_0_extract_audio.wav"
            extract_audio_stats = ExtractAudioFromVideo().run(input_file, extracted_audio_file)
            extract_audio_end = time.perf_counter()

            ###############################
            logger.info("Running audio pipeline")
            processed_audio_file = tempdir / "processed_audio.wav"
            audio_pipeline_stats = self.audio_pipeline.run(
                extracted_audio_file, processed_audio_file, tempdir, nisqa_model
            )

            ###############################
            logger.info("Replacing audio in video")
            replacing_audio_start = time.perf_counter()
            _, ext = split_filename_ext(output_file)
            processed_video_file = tempdir / f"processed_audio.{ext}"
            replace_audio_in_video(
                video_file=input_file,
                audio_file=processed_audio_file,
                output_file=processed_video_file,
                use_nvenc=self.use_nvenc,
                video_codec=self.force_video_codec,
                audio_codec=self.force_audio_codec,
                force_transcode_video=self.force_transcode_video,
                force_transcode_audio=self.force_transcode_audio,
            )
            replacing_audio_end = time.perf_counter()

            ###############################
            logger.info("Unsilencing")
            unsilence_start = time.perf_counter()
            self.unsilence_action.temp_dir = tempdir / "unsilence"
            unsilence_stats = self.unsilence_action.run(
                input_file=processed_video_file,
                output_file=output_file,
            )
            unsilence_end = time.perf_counter()

            if nisqa_model is not None:
                unsilence_nisqa = nisqa_model.measure_from_tensor(*read_audio(output_file))
            else:
                unsilence_nisqa = None

            unsilence_rms_db = measure_volume(output_file)

        pipeline_end = unsilence_end
        ###############################
        return VideoPipelineStatistics(
            total_time=pipeline_end - pipeline_start,
            extract_audio_stats=StepStatistics(
                step=0,
                time=extract_audio_end - extract_audio_start,
                action_stats=extract_audio_stats,
                nisqa=None,
                rms_db=0,
            ),
            audio_pipeline_stats=audio_pipeline_stats,
            replacing_audio_time=replacing_audio_end - replacing_audio_start,
            unsilence_stats=StepStatistics(
                step=self.audio_pipeline.get_steps_count(),
                time=unsilence_end - unsilence_start,
                action_stats=unsilence_stats,
                nisqa=unsilence_nisqa,
                rms_db=unsilence_rms_db,
            ),
        )
