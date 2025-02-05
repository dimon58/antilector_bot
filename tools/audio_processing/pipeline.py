import logging
import time
from pathlib import Path
from typing import Self, Union

import pydantic
from pydantic import ConfigDict, Field

from configs import NISQA_MAX_MEMORY
from libs.nisqa.metrics import NisqaMetrics
from libs.nisqa.model import NisqaModel
from utils.audio import measure_volume_if_enabled
from utils.misc import get_all_subclasses

from .actions.abstract import Action, ActionStatsType

logger = logging.getLogger(__name__)


class StepStatistics(pydantic.BaseModel):
    step: int
    step_name: str
    time: float
    action_stats: ActionStatsType | None = None
    nisqa: NisqaMetrics | None = None
    rms_db: float | None

    @property
    def repr_for_logging(self) -> str:
        info = []

        if self.nisqa is not None:
            info.append(self.nisqa.short_desc())

        if self.rms_db is not None:
            info.append(f"RMS {self.rms_db:.2f} dB")

        if len(info) == 0:
            return ""

        return " | ".join(info)


class AudioPipelineStatistics(pydantic.BaseModel):
    step_statistics: list[StepStatistics]
    total_time: float

    def get_nisqa_time(self) -> float:
        """
        Возвращает полной время, потраченное на nisqa
        """
        return sum(step_stat.nisqa.time for step_stat in self.step_statistics if step_stat.nisqa is not None)


class AudioPipeline(pydantic.BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pipeline: list[Union[*get_all_subclasses(Action)]] = Field(default_factory=list)

    _in_working_ext: str = "wav"

    def get_steps_count(self) -> int:
        return len(self.pipeline)

    def add(self, action: Action) -> Self:
        self.pipeline.append(action)
        return self

    def _generate_temp_file_name(self, step: int, action: Action, ext: str) -> str:
        return f"step_{step}_{action.__class__.__name__.lower()}.{ext}"

    def _run(
        self,
        input_file: Path,
        output_file: Path,
        tempdir: Path,
        nisqa_model: NisqaModel | None,
    ) -> list[StepStatistics]:
        if len(self.pipeline) == 0:
            raise ValueError("No actions defined")

        input_stats = StepStatistics(step=0, step_name="input", time=0, rms_db=measure_volume_if_enabled(input_file))
        pipeline_stats = [input_stats]

        if nisqa_model is not None:
            with nisqa_model.cleanup_cuda():
                input_stats.nisqa = nisqa_model.measure_from_path_chunked(input_file, NISQA_MAX_MEMORY)
        logger.info("Input: %s", input_stats.repr_for_logging)

        for step, action in enumerate(self.pipeline[:-1], start=1):
            logger.info("Running step %s/%s - %s", step, len(self.pipeline), action.__class__.__name__)
            temp_file_name = tempdir / self._generate_temp_file_name(step, action, self._in_working_ext)
            start = time.perf_counter()
            action_stats = action.run(input_file, temp_file_name)
            end = time.perf_counter()

            input_file = temp_file_name

            step_stats = StepStatistics(
                step=step,
                step_name=action.__class__.__name__,
                time=end - start,
                action_stats=action_stats,
                rms_db=measure_volume_if_enabled(input_file),
            )
            pipeline_stats.append(step_stats)

            if nisqa_model is not None:
                with nisqa_model.cleanup_cuda():
                    step_stats.nisqa = nisqa_model.measure_from_path_chunked(input_file, NISQA_MAX_MEMORY)
            logger.info("Step %s: %s done in %s", step, step_stats.repr_for_logging, end - start)

        logger.info(
            "Running step %s/%s - %s",
            len(self.pipeline),
            len(self.pipeline),
            self.pipeline[-1].__class__.__name__,
        )
        start = time.perf_counter()
        action_stats = self.pipeline[-1].run(input_file, output_file)
        end = time.perf_counter()

        final_stats = StepStatistics(
            step=len(self.pipeline),
            step_name=self.pipeline[-1].__class__.__name__,
            time=end - start,
            action_stats=action_stats,
            rms_db=measure_volume_if_enabled(output_file),
        )
        pipeline_stats.append(final_stats)

        if nisqa_model is not None:
            with nisqa_model.cleanup_cuda():
                final_stats.nisqa = nisqa_model.measure_from_path_chunked(output_file, NISQA_MAX_MEMORY)
        logger.info("Final step %s: %s done in %s sec", len(self.pipeline), final_stats.repr_for_logging, end - start)

        return pipeline_stats

    def run(
        self,
        input_file: Path,
        output_file: Path,
        tempdir: Path,
        nisqa_model: NisqaModel | None,
    ) -> AudioPipelineStatistics:
        start = time.perf_counter()
        step_statistics = self._run(input_file, output_file, tempdir, nisqa_model)
        end = time.perf_counter()

        return AudioPipelineStatistics(
            step_statistics=step_statistics,
            total_time=end - start,
        )
