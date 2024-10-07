from tools.video_processing.actions.unsilence_actions import UnsilenceAction
from tools.video_processing.vad.vad_unsilence import UnsilenceAndVad
from .common import default_render_options, common, unsilence_specific, vad_specific

unsilence_and_vad_action = UnsilenceAction(
    unsilence_class=UnsilenceAndVad,
    detect_silence_options=vad_specific | unsilence_specific | common,
    render_options=default_render_options,
)
