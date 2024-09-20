from dataclasses import dataclass


@dataclass
class NisqaMetrics:
    """
    https://arxiv.org/abs/2104.09494
    https://www.youtube.com/watch?v=AtGyrKGxC4Y
    https://github.com/gabrielmittag/NISQA
    https://github.com/deepvk/NISQA-s

    Все метрики оцениваются по шкале от 1 до 5

    :argument overall_quality: Mean opinion score: 1 - очень плохое качество. 5 - очень хорошее качество.
    :argument noisiness: Зашумлённость: 1 - очень шумно, не слышно речь. 5 - отличное качество, шумов нет.
    :argument coloration:
        Окраска: 1 - бубнёж не понятный, невнятный звук. 5 - хорошее, практически студийное качество голоса.
    :argument discontinuity:
        Прерываемость: 1 - слишком много провалов в речи, слишком много прерываний. 5 - отличная непрерывная речь.
    :argument loudness:
        Громкость: 1 - некомфортная громкость, как слишком тихо, так и слишком громко. 5 - комфортная громкость.

    :argument length: Длина записи в секундах
    :argument sr: Частота дискретизации
    :argument time: Время измерения
    """

    overall_quality: float
    noisiness: float
    coloration: float
    discontinuity: float
    loudness: float

    length: float
    sr: int
    time: float

    def short_desc(self) -> str:
        return (
            f"MOS {self.overall_quality}"
            f" | NOI {self.noisiness}"
            f" | COL {self.coloration}"
            f" | DISC {self.discontinuity}"
            f" | LOUD {self.loudness}"
        )
