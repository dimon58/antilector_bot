import unittest

from tools.audio_processing.actions import audiotools_actions, deepfilternet_actions, ffmpeg_actions
from tools.audio_processing.pipeline import AudioPipeline
from tools.video_processing.actions.unsilence_actions import UnsilenceAction
from tools.video_processing.pipeline import VideoPipeline
from tools.video_processing.vad.vad_unsilence import UnsilenceAndVad


class TestVideoPipelineSerialization(unittest.TestCase):
    def test_correct_serialization(self):
        audio_pipeline = (
            AudioPipeline()
            .add(
                audiotools_actions.AudiotoolsAction()
                .to_mono()
                .normalize(-0.1, remove_dc=True)
                .remove_clicks(250, 30)
                .normalize(-0.1, remove_dc=True)
                .remove_clicks(100, 20)
                .normalize(-0.1, remove_dc=True)
            )
            .add(
                ffmpeg_actions.SimpleFFMpegAction(
                    output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
                )
            )
            .add(deepfilternet_actions.DeepFilterNet3Denoise())
            .add(audiotools_actions.AudiotoolsAction().normalize(-0.1, remove_dc=True))
            .add(
                ffmpeg_actions.SimpleFFMpegAction(
                    output_options={"af": "speechnorm=p=0.99:e=3:c=3", "ar": 48000},
                )
            )
        )

        unsilence_profile = UnsilenceAction(
            unsilence_class=UnsilenceAndVad,
            detect_silence_options={
                "silence_level": -35.0,
                "silence_time_threshold": 0.5,
                "short_interval_threshold": 0.3,
                "stretch_time": 0.25,
                "threshold": 0.5,
                "sampling_rate": 16000,
                "min_speech_duration_ms": 250,
                "max_speech_duration_s": float("inf"),
                "min_silence_duration_ms": 100,
                "speech_pad_ms": 30,
                "return_seconds": False,
                # Обязательно False, так как библиотека округляет секунды до 1 знака после запятой
                "visualize_probs": False,  # Никакого рисования не нужно
                "window_size_samples": 512,
            },
            render_options={
                "audio_only": False,
                "audible_speed": 1,
                "silent_speed": 6,
                "audible_volume": 1,
                "silent_volume": 0.5,
                "drop_corrupted_intervals": False,
                "check_intervals": False,
                "minimum_interval_duration": 0.25,
                "interval_in_fade_duration": 0.01,
                "interval_out_fade_duration": 0.01,
                "fade_curve": "tri",
            },
            threads=2,
        )

        video_pipeline = VideoPipeline(
            audio_pipeline=audio_pipeline,
            unsilence_action=unsilence_profile,
        )

        dumped = video_pipeline.model_dump_json()
        VideoPipeline.model_validate_json(dumped)
