"""连续采样段恢复：坏行断开后只在完整连续段上估计，绝不跨缺口拼接。

每个段独立走校准→能量积分→噪声门→T20/T30 拟合的同一套质量门槛；
只有段内自身支撑估计时才允许采信，并保留段边界与来源行用于对账。
"""
from dataclasses import dataclass, replace

from app.modules.m2_calibration.units import calibrate
from app.modules.m3_decay.integral import integrate
from app.modules.m4_fit.windows import fit_window
from app.modules.m5_noise.gate import noise_gate
from app.reasons import reason


@dataclass
class SegmentVerdict:
    label: str
    band_hz: int
    start_index: int
    end_index: int
    first_line: int
    last_line: int
    sample_count: int
    peak_index: int
    peak_line: int
    adopted: bool
    admissible: bool
    depth_db: float
    t20: dict
    t30: dict
    gate: dict
    curve_error: dict | None
    block_reason: dict | None


def evaluate_segment(band, segment):
    sub = replace(band, samples=list(segment.samples))
    signal = calibrate(sub)
    curve = integrate(signal)
    gate = noise_gate(curve)
    t20 = fit_window(curve, gate, 25)
    t30 = fit_window(curve, gate, 35)
    admissible = t20['rt60_s'] is not None or t30['rt60_s'] is not None
    block_reason = None
    if not admissible:
        block_reason = curve.error or gate.get('error') or t20['error'] or t30['error'] or reason('SEGMENT_BLOCKED')
    return SegmentVerdict(
        label=segment.label, band_hz=band.hz, start_index=segment.start_index, end_index=segment.end_index,
        first_line=segment.first_line, last_line=segment.last_line, sample_count=segment.length,
        peak_index=signal.peak_index, peak_line=signal.line_numbers[signal.peak_index],
        adopted=False, admissible=admissible, depth_db=gate['usable_depth_db'],
        t20=t20, t30=t30, gate=gate, curve_error=curve.error, block_reason=block_reason,
    )


def choose_adoption(verdicts):
    """采信规则（同带唯一）：优先含整带直达声峰值的可估计段；否则取可用深度最大的段。"""
    eligible = [verdict for verdict in verdicts if verdict.admissible]
    if not eligible:
        return None
    peak_holders = [verdict for verdict in eligible if verdict.peak_index == 0]
    pool = peak_holders or eligible
    chosen = max(pool, key=lambda verdict: (verdict.depth_db, -verdict.start_index))
    chosen.adopted = True
    return chosen


def recover_band(band):
    """返回 (采信段或 None, 全部段判定)。无缺陷带不经过恢复流程。"""
    verdicts = [evaluate_segment(band, segment) for segment in band.segments]
    adopted = choose_adoption(verdicts)
    return adopted, verdicts
