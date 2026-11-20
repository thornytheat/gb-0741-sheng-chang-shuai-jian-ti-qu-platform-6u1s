from collections import defaultdict

from app.reasons import reason
from app.records import Band, Segment

# 完整性缺陷：无法确认缺口两侧是否属于同一物理过程，禁止缩短，整带退回补测
FATAL_CODES = frozenset({'CAL_CONFLICT', 'DUPLICATE_CONFLICT', 'EXTRA_POINTS'})
# 可恢复缺陷：坏行本身隔离，剩余连续采样段允许按段缩短估计
RECOVERABLE_CODES = frozenset({'MISSING_POINTS', 'TRUNCATED_BAND', 'ROW_ISOLATED'})


def issue(line, hz, code, raw):
    return {'line': line, 'band_hz': hz, 'raw': raw, **reason(code)}


def build_segments(hz, accepted):
    """按采样序号切成互不拼接的连续采样段，段内序号严格 +1。"""
    segments, current = [], []
    previous = None
    for sample in accepted:
        if previous is not None and sample.index != previous + 1:
            segments.append(current)
            current = []
        current.append(sample)
        previous = sample.index
    if current:
        segments.append(current)
    return tuple(
        Segment(f'{hz}-S{position}', tuple(run), run[0].index, run[-1].index, run[0].line, run[-1].line)
        for position, run in enumerate(segments)
    )


def check_band(hz, rows, invalid_rows):
    if not rows:
        failure = {'band_hz': hz, 'findings': [{**reason('ROW_ISOLATED'), 'lines': invalid_rows}],
                   'fatal_codes': ['ROW_ISOLATED'], 'recoverable_codes': []}
        return None, failure, [], 0, 0
    first, first_sample = rows[0]
    configs = {}
    by_index = defaultdict(list)
    for calibration, sample in rows:
        configs.setdefault(calibration, sample.line)
        by_index[sample.index].append(sample)
    findings = []
    if invalid_rows:
        findings.append({**reason('ROW_ISOLATED'), 'lines': invalid_rows})
    if len(configs) > 1:
        findings.append({**reason('CAL_CONFLICT'), 'lines': sorted(configs.values())})
    duplicates, accepted = [], []
    for index in sorted(by_index):
        samples = by_index[index]
        origin = samples[0]
        if any(sample.amplitude != origin.amplitude for sample in samples[1:]):
            findings.append({**reason('DUPLICATE_CONFLICT'), 'index': index, 'lines': [sample.line for sample in samples],
                             'values': [str(sample.amplitude) for sample in samples[:12]]})
        else:
            duplicates.extend(issue(sample.line, hz, 'DUPLICATE_ROW', sample.raw) for sample in samples[1:])
        accepted.append(origin)
    accepted.sort(key=lambda sample: sample.index)
    indices = sorted(by_index)
    extra = [index for index in indices if index >= first.expected]
    missing = [index for index in range(min(indices[-1] + 1, first.expected)) if index not in by_index]
    if extra:
        findings.append({**reason('EXTRA_POINTS'), 'indices': extra[:20], 'count': len(extra)})
    if missing:
        findings.append({**reason('MISSING_POINTS'), 'indices': missing[:20], 'count': len(missing)})
    if indices[-1] < first.expected - 1:
        findings.append({**reason('TRUNCATED_BAND'), 'from_index': indices[-1] + 1, 'to_index': first.expected - 1})
    duplicate_count = len(duplicates)
    if findings:
        codes = {item['code'] for item in findings}
        fatal = sorted(codes & FATAL_CODES)
        recoverable = sorted(codes & RECOVERABLE_CODES)
        failure = {'band_hz': hz, 'sample_count': len(rows), 'first_line': first_sample.line,
                   'findings': findings, 'fatal_codes': fatal, 'recoverable_codes': recoverable}
        if fatal:
            # 完整性缺陷：不产生任何采信段，所有物理行退回补测
            return None, failure, duplicates, len(rows), duplicate_count
        segments = build_segments(hz, accepted)
        # 可恢复缺陷：整带记录保留，但只允许在连续段上缩短估计
        band = Band(hz, first, accepted, segments, True, tuple(findings))
        return band, failure, duplicates, 0, duplicate_count
    segments = build_segments(hz, accepted)
    return Band(hz, first, accepted, segments, False, ()), None, duplicates, 0, duplicate_count
