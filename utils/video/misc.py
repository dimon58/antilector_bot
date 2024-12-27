# https://developer.nvidia.com/video-encode-and-decode-gpu-support-matrix-new
NVENC_MAX_CONCURRENT_SESSIONS = 8

NVENC_CODECS = ("hevc_nvenc", "h264_nvenc", "av1_nvenc")  # todo: calculate based on gpu


def ensure_nvenc_correct(use_nvenc: bool, force_video_codec: str | None, threads: int) -> bool | None:  # noqa: FBT001
    """
    Проверяет, можно ли использовать nvenc в такой конфигурации

    :param use_nvenc: Нужно ли включить nvenc
    :param force_video_codec: кодек для видео
    :param threads: число параллельных сессий
    """
    if not use_nvenc:

        if force_video_codec in NVENC_CODECS:
            raise ValueError(f"You must enable nvenc to use {force_video_codec}")

        return

    if force_video_codec is None:
        raise ValueError("You must specify video codec to use nvenc acceleration in ffmpeg")

    if force_video_codec not in NVENC_CODECS:
        raise ValueError(f"Video codec must be in {NVENC_CODECS} if you use nvenc, got {force_video_codec}")

    if threads > NVENC_MAX_CONCURRENT_SESSIONS:
        raise ValueError(f"nvenc supports maximum {NVENC_MAX_CONCURRENT_SESSIONS} cuncurrent sessions")
