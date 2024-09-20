def __bytes_format(size: float, digits: int = 0) -> float | int:
    if digits == 0:
        return round(size)

    return round(size, digits)


def get_bytes_size_format(size: float, digits: int = 2, stop_at: str | None = None) -> str:
    """
    Форматирует число байт в человекочитаемые единицы измерения
    """
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if size < 1024 or unit == stop_at:  # noqa: PLR2004
            return f"{__bytes_format(size, digits)} {unit}B"
        size /= 1024
    return f"{__bytes_format(size, digits)} YB"
