from tools.audio_processing.actions import ffmpeg_actions, audiotools_actions, deepfilternet_actions
from tools.audio_processing.pipeline import AudioPipeline

normal_audio_pipeline = (
    AudioPipeline()
    .add(
        ffmpeg_actions.SimpleFFMpegAction(
            output_options={"ac": 1, "ar": 48000},
        )
    )
    .add(audiotools_actions.AudiotoolsAction().normalize(peak_level=-0.1, remove_dc=True, stereo_independent=False))
    .add(ffmpeg_actions.SimpleFFMpegAction(output_options={"af": "speechnorm"}))
    .add(deepfilternet_actions.DeepFilterNet3Denoise(cleanup=True))
    .add(audiotools_actions.AudiotoolsAction().normalize(peak_level=-0.1, remove_dc=True, stereo_independent=False))
)
