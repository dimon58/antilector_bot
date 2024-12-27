from tools.video_processing.actions.unsilence_actions import UnsilenceAction
from tools.video_processing.vad.vad_unsilence import Vad

from .common import common, default_render_options, vad_specific

vad_only_action = UnsilenceAction(
    unsilence_class=Vad,
    detect_silence_options=vad_specific | common,
    render_options=default_render_options,
)
