from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Sample:
    line: int
    index: int
    amplitude: Decimal
    raw: dict


@dataclass(frozen=True)
class Calibration:
    rate: int
    expected: int
    unit: str
    gain_db: Decimal
    pa_per_v: Decimal | None

    def public(self):
        return {'sample_rate_hz': self.rate, 'expected_samples': self.expected, 'unit': self.unit,
                'gain_db': str(self.gain_db), 'pa_per_v': str(self.pa_per_v) if self.pa_per_v is not None else None}


@dataclass
class Band:
    hz: int
    calibration: Calibration
    samples: list[Sample]
    segments: tuple['Segment', ...] = ()
    recoverable: bool = True
    defects: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Segment:
    label: str
    samples: tuple[Sample, ...]
    start_index: int
    end_index: int
    first_line: int
    last_line: int

    @property
    def length(self):
        return len(self.samples)


@dataclass
class Intake:
    bands: list[Band]
    rejected_bands: list[dict]
    row_issues: list[dict]
    counts: dict
    encoding: str


@dataclass(frozen=True)
class Signal:
    hz: int
    rate: int
    peak_index: int
    pa: tuple[float, ...]
    line_numbers: tuple[int, ...]
