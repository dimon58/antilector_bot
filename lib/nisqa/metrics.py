from dataclasses import dataclass


@dataclass
class NisqaMetrics:
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
