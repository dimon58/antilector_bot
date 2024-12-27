from libs.unsilence_fast.unsilence import FastUnsilence
from tools.video_processing.actions.unsilence_actions import UnsilenceAction

from .common import common, default_render_options, unsilence_specific

unsilence_only_action = UnsilenceAction(
    unsilence_class=FastUnsilence,
    detect_silence_options=unsilence_specific | common,
    render_options=default_render_options,
)
