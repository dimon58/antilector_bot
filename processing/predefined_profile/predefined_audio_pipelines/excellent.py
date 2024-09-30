from tools.audio_processing.actions import ffmpeg_actions, audiotools_actions
from tools.audio_processing.pipeline import AudioPipeline

# Этот профиль только сводит звук в моно и пересемлирует в 48 кГц
# Подходит для качественных студийных записей
excellent_audio_pipeline = (
    AudioPipeline()
    .add(
        ffmpeg_actions.SimpleFFMpegAction(
            output_options={"ac": 1, "ar": 48000},
        )
    )
    .add(audiotools_actions.AudiotoolsAction().normalize(peak_level=-0.1, remove_dc=True, stereo_independent=False))
)
