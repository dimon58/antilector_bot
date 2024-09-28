import logging
import time
from pathlib import Path
from typing import Self

import pydantic

from libs.nisqa.model import NisqaModel
from tools.audio_processing.actions.ffmpeg_actions import ExtractAudioFromVideo
from tools.audio_processing.pipeline import AudioPipeline, AudioPipelineStatistics, StepStatistics
from utils.audio import measure_volume, read_audio

from .actions.unsilence_actions import UnsilenceAction

logger = logging.getLogger(__name__)


class VideoPipelineStatistics(pydantic.BaseModel):
    total_time: float

    extract_audio_stats: StepStatistics
    audio_pipeline_stats: AudioPipelineStatistics
    unsilence_stats: StepStatistics

    def get_nisqa_time(self) -> float:
        """
        Возвращает полной время, потраченное на nisqa
        """
        res = 0

        if self.extract_audio_stats.nisqa is not None:
            res += self.extract_audio_stats.nisqa.time

        res += self.audio_pipeline_stats.get_nisqa_time()

        if self.unsilence_stats.nisqa is not None:
            res += self.unsilence_stats.nisqa.time

        return res


class VideoPipeline(pydantic.BaseModel):
    audio_pipeline: AudioPipeline
    unsilence_action: UnsilenceAction

    use_nvenc: bool | None = None
    force_video_codec: str | None = None
    force_audio_codec: str | None = None

    @pydantic.model_validator(mode="after")
    def resolve_settings(self) -> Self:

        if self.use_nvenc is not None:
            logger.info("Using nvenc for unsilence")
            self.unsilence_action.render_options.use_nvenc = self.use_nvenc

        if self.force_audio_codec is not None:
            logger.info("Encoding audio using %s for unsilence", self.force_audio_codec)
            self.unsilence_action.render_options.force_audio_codec = self.force_audio_codec

        if self.force_video_codec is not None:
            logger.info("Encoding video using %s for unsilence", self.force_video_codec)
            self.unsilence_action.render_options.force_video_codec = self.force_video_codec

            # Копирование приводит к артефактам при обрезке и склейке
            # if self.force_transcode_video:
            #     logger.info("Allowing copy video stream for unsilence")
            #     self.unsilence_action.render_options.allow_copy_video_stream = True

        # Копирование приводит к артефактам при обрезке и склейке
        # if self.force_audio_codec is not None and self.force_transcode_audio:
        #     logger.info("Allowing copy audio stream for unsilence")
        #     self.unsilence_action.render_options.allow_copy_audio_stream = True

        return self

    def run(
        self,
        input_file: Path,
        output_file: Path,
        tempdir: Path,
        nisqa_model: NisqaModel | None = None,
    ) -> VideoPipelineStatistics:

        pipeline_start = time.perf_counter()

        ###############################
        logger.info("Extracting audio")
        extract_audio_start = time.perf_counter()
        extracted_audio_file = tempdir / "step_0_extract_audio.wav"
        extract_audio_stats = ExtractAudioFromVideo().run(input_file, extracted_audio_file)
        extract_audio_end = time.perf_counter()

        ###############################
        logger.info("Running audio pipeline")
        processed_audio_file = tempdir / "processed_audio.wav"
        audio_pipeline_stats = self.audio_pipeline.run(extracted_audio_file, processed_audio_file, tempdir, nisqa_model)

        ###############################
        logger.info("Unsilencing")
        unsilence_start = time.perf_counter()
        self.unsilence_action.temp_dir = tempdir / "unsilence"
        self.unsilence_action.separated_audio = processed_audio_file
        unsilence_stats = self.unsilence_action.run(
            input_file=input_file,
            output_file=output_file,
        )
        if nisqa_model is not None:
            with nisqa_model.cleanup_cuda():
                unsilence_nisqa = nisqa_model.measure_from_tensor(*read_audio(output_file))
        else:
            unsilence_nisqa = None
        unsilence_rms_db = measure_volume(output_file)
        unsilence_end = time.perf_counter()
        unsilence_stats = StepStatistics(
            step=self.audio_pipeline.get_steps_count(),
            step_name="unsilence",
            time=unsilence_end - unsilence_start,
            action_stats=unsilence_stats,
            nisqa=unsilence_nisqa,
            rms_db=unsilence_rms_db,
        )
        logger.info("Unsilence: %s done in %s", unsilence_stats.repr_for_logging, unsilence_stats.time)

        pipeline_end = unsilence_end
        ###############################
        return VideoPipelineStatistics(
            total_time=pipeline_end - pipeline_start,
            extract_audio_stats=StepStatistics(
                step=0,
                step_name="extract audio",
                time=extract_audio_end - extract_audio_start,
                action_stats=extract_audio_stats,
                nisqa=None,
                rms_db=0,
            ),
            audio_pipeline_stats=audio_pipeline_stats,
            unsilence_stats=unsilence_stats,
        )
