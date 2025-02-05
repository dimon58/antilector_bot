import unittest

from libs.unsilence import Unsilence
from libs.unsilence.render_media.options import RenderOptions
from tools.video_processing.actions.unsilence_actions import UnsilenceAction
from tools.video_processing.vad.vad_unsilence import UnsilenceAndVad, Vad


class TestSerializationUnsilenceAction(unittest.TestCase):
    def test_serialization_deserialization_unsilence(self) -> None:
        action = UnsilenceAction(
            unsilence_class=Unsilence,
            detect_silence_options={
                "silence_level": -35.0,
                "silence_time_threshold": 0.5,
                "short_interval_threshold": 0.3,
                "stretch_time": 0.25,
            },
            render_options=RenderOptions(
                audio_only=False,
                audible_speed=1,
                silent_speed=6,
                audible_volume=1,
                silent_volume=0.5,
                drop_corrupted_intervals=False,
                check_intervals=False,
                minimum_interval_duration=0.25,
                interval_in_fade_duration=0.01,
                interval_out_fade_duration=0.01,
                fade_curve="tri",
            ),
        )
        dumped = action.model_dump_json()
        action.model_validate_json(dumped)

    def test_serialization_deserialization_vad(self) -> None:
        action = UnsilenceAction(
            unsilence_class=Vad,
            detect_silence_options={
                "short_interval_threshold": 0.3,
                "stretch_time": 0.25,
                "threshold": 0.5,
                "sampling_rate": 16000,
                "min_speech_duration_ms": 250,
                "max_speech_duration_s": float("inf"),
                "min_silence_duration_ms": 100,
                "speech_pad_ms": 30,
                "return_seconds": False,
                "visualize_probs": False,
                "window_size_samples": 512,
            },
            render_options=RenderOptions(
                audio_only=False,
                audible_speed=1,
                silent_speed=6,
                audible_volume=1,
                silent_volume=0.5,
                drop_corrupted_intervals=False,
                check_intervals=False,
                minimum_interval_duration=0.25,
                interval_in_fade_duration=0.01,
                interval_out_fade_duration=0.01,
                fade_curve="tri",
            ),
        )
        dumped = action.model_dump_json()
        action.model_validate_json(dumped)

    def test_serialization_deserialization_unsilence_and_vad(self) -> None:
        action = UnsilenceAction(
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
                "visualize_probs": False,
                "window_size_samples": 512,
            },
            render_options=RenderOptions(
                audio_only=False,
                audible_speed=1,
                silent_speed=6,
                audible_volume=1,
                silent_volume=0.5,
                drop_corrupted_intervals=False,
                check_intervals=False,
                minimum_interval_duration=0.25,
                interval_in_fade_duration=0.01,
                interval_out_fade_duration=0.01,
                fade_curve="tri",
            ),
        )
        dumped = action.model_dump_json()
        action.model_validate_json(dumped)
