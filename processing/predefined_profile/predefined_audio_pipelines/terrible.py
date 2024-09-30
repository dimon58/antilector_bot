from tools.audio_processing.actions import audiotools_actions, deepfilternet_actions, ffmpeg_actions
from tools.audio_processing.pipeline import AudioPipeline

# Профиль создан для улучшения звука в записи лекции
# на телефон POCO F2 PRO с расстояния около 10-15 метров.
# Исходный звук был тихий (около 45 дб) и содержал шумы,
# интенсивность которых была выше, чем у речи.
terrible_audio_pipeline = (
    AudioPipeline()
    .add(
        audiotools_actions.AudiotoolsAction()
        .to_mono()
        # Вообще телефон записал так,
        # что в левом канале был только шум,
        # а в правом речь, но в общем случае так не будет
        # .remove_all_channels_except(1)
        .normalize(-0.1, remove_dc=True, stereo_independent=False)
        .remove_clicks(250, 30)
        .normalize(-0.1, remove_dc=True, stereo_independent=False)
        .remove_clicks(100, 20)
        .normalize(-0.1, remove_dc=True, stereo_independent=False)
    )
    .add(
        ffmpeg_actions.SimpleFFMpegAction(
            output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
        )
    )
    .add(deepfilternet_actions.DeepFilterNet3Denoise(cleanup=True))
    .add(audiotools_actions.AudiotoolsAction().normalize(-0.1, remove_dc=True, stereo_independent=False))
    .add(
        ffmpeg_actions.SimpleFFMpegAction(
            # output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
            output_options={"af": "speechnorm", "ar": 48000},
        )
    )
)
