from configs import (
    CPU_ADDITIONAL_OPTIONS,
    FORCE_VIDEO_CODEC,
    NVENC_ADDITIONAL_OPTIONS,
    SILERO_VAD_SAMPLE_RATE,
    UNSILENCE_DEFAULT_CPU_COUNT,
    USE_NVENC,
)
from libs.unsilence.render_media.options import RenderOptions

common = {
    "silence_upper_threshold": 60,  # Слишком длинные интервалы с тишиной считаем перерывами и вырезаем полностью
    "short_interval_threshold": 0.3,
    "stretch_time": 0.25,
}

unsilence_specific = {
    "silence_level": -35.0,
    "silence_time_threshold": 0.5,
}

vad_specific = {
    "threshold": 0.5,
    "sampling_rate": SILERO_VAD_SAMPLE_RATE,
    "min_speech_duration_ms": 250,
    "max_speech_duration_s": None,
    "min_silence_duration_ms": 100,
    "speech_pad_ms": 30,
    "return_seconds": False,  # Обязательно False, так как библиотека округляет секунды до 1 знака после запятой
    "visualize_probs": False,  # Никакого рисования не нужно
    "window_size_samples": 512,
}

default_render_options = RenderOptions(
    audio_only=False,
    audible_speed=1,
    silent_speed=6,
    audible_volume=1,
    silent_volume=0.5,
    drop_corrupted_intervals=False,
    check_intervals=False,
    minimum_interval_duration=0.5,
    interval_in_fade_duration=0.01,
    interval_out_fade_duration=0.01,
    fade_curve="tri",
    threads=UNSILENCE_DEFAULT_CPU_COUNT,
    use_nvenc=USE_NVENC,
    force_video_codec=FORCE_VIDEO_CODEC,
    additional_output_options=NVENC_ADDITIONAL_OPTIONS if USE_NVENC else CPU_ADDITIONAL_OPTIONS,
)
