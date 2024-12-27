import unittest

from tools.audio_processing.actions import audiotools_actions, deepfilternet_actions, ffmpeg_actions
from tools.audio_processing.pipeline import AudioPipeline


class TestAudioPipelineSerialization(unittest.TestCase):
    def test_correct_serialization(self) -> None:
        pipeline = (
            AudioPipeline()
            .add(
                audiotools_actions.AudiotoolsAction()
                .to_mono()
                .normalize(-0.1, remove_dc=True)
                .remove_clicks(250, 30)
                .normalize(-0.1, remove_dc=True)
                .remove_clicks(100, 20)
                .normalize(-0.1, remove_dc=True),
            )
            .add(
                ffmpeg_actions.SimpleFFMpegAction(
                    output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
                ),
            )
            .add(deepfilternet_actions.DeepFilterNet3Denoise())
            .add(audiotools_actions.AudiotoolsAction().normalize(-0.1, remove_dc=True))
            .add(
                ffmpeg_actions.SimpleFFMpegAction(
                    output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
                ),
            )
        )

        dumped = pipeline.model_dump_json()
        AudioPipeline.model_validate_json(dumped)
