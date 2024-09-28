from pathlib import Path

from libs.unsilence import Unsilence
from libs.unsilence._typing import UpdateCallbackType
from libs.unsilence.intervals.interval import SerializedInterval
from libs.unsilence.render_media.options import RenderOptions
from libs.unsilence.unsilence import default_render_options

from .fast_media_renderer import FastMediaRenderer


class FastUnsilence(Unsilence):
    def render_media(
        self,
        output_file: Path,
        temp_dir: Path = Path(".tmp"),
        render_options: RenderOptions = default_render_options,
        separated_audio: Path | None = None,
        on_render_progress_update: UpdateCallbackType | None = None,
        on_concat_progress_update: UpdateCallbackType | None = None,
    ) -> list[list[SerializedInterval]]:
        """
        Renders the current intervals with options specified in the kwargs

        output_file: Where the final file should be saved at
        separated_audio: Audio stream from input in separated file (wav is the best).
            Providing can increase performance.
        temp_dir: The temp dir where temporary files can be saved

        Remaining keyword arguments are passed to :func:`~unsilence.lib.render_media.MediaRenderer.MediaRenderer.render`

        :return: None
        """
        if self._intervals is None:
            raise ValueError("Silence detection was not yet run and no intervals where given manually!")

        renderer = FastMediaRenderer(temp_dir)
        return renderer.render(
            input_file=self._input_file,
            output_file=output_file,
            intervals=self._intervals,
            render_options=render_options,
            separated_audio=separated_audio,
            on_render_progress_update=on_render_progress_update,
            on_concat_progress_update=on_concat_progress_update,
        )
