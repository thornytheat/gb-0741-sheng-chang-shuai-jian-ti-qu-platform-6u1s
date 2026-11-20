from collections import Counter
from dataclasses import replace

from app.modules.m3_decay.segments import recover_band
from app.modules.m3_decay.service import decay
from app.modules.m4_fit.service import fits
from app.modules.m6_reconcile.comparison import DISAGREEMENT_LIMIT, compare
from app.reasons import reason


def clean_pipeline(data):
    curves, calibrated, decay_report = decay(data)
    fitted, noise = fits(curves)
    return curves, calibrated, decay_report, fitted, noise


def shortening_evidence(band, adopted, verdicts):
    runs = [{
        'label': verdict.label, 'start_index': verdict.start_index, 'end_index': verdict.end_index,
        'first_line': verdict.first_line, 'last_line': verdict.last_line, 'sample_count': verdict.sample_count,
        'peak_index': verdict.peak_index, 'peak_line': verdict.peak_line, 'admissible': verdict.admissible,
        'adopted': verdict.adopted, 'usable_depth_db': verdict.depth_db,
        't20_rt60_s': verdict.t20['rt60_s'], 't30_rt60_s': verdict.t30['rt60_s'],
        'block_reason': verdict.block_reason,
    } for verdict in verdicts]
    return {
        'band_hz': band.hz, 'mode': 'SHORTENED', 'defects': list(band.defects),
        'adopted_label': adopted.label if adopted else None,
        'adopted_lines': {'first': adopted.first_line, 'last': adopted.last_line,
                          'start_index': adopted.start_index, 'end_index': adopted.end_index} if adopted else None,
        'segments': runs,
        'reason': reason('SEGMENT_SHORTENED') if adopted else reason('SEGMENT_BLOCKED'),
    }


def evaluate(data):
    # 评估在工作副本上重分类采信/排除行，不改动收件原始计数（/api/intake 仍返回收件态）
    work = replace(data, counts=dict(data.counts))
    shortenings = {}
    excluded_lines = []
    adopted_lines = set()
    clean_bands, recovered_bands = [], []
    for band in work.bands:
        if not band.recoverable:
            clean_bands.append(band)
            continue
        adopted, verdicts = recover_band(band)
        shortenings[band.hz] = shortening_evidence(band, adopted, verdicts)
        segment_by_label = {segment.label: segment for segment in band.segments}
        for verdict in verdicts:
            lines = [sample.line for sample in segment_by_label[verdict.label].samples]
            if verdict.adopted:
                adopted_lines.update(lines)
            else:
                excluded_lines.extend(lines)
        if adopted is None:
            # 所有连续段均不支撑估计：整带退回补测，不进入曲线与拟合
            continue
        recovered_bands.append(replace(band, samples=list(segment_by_label[adopted.label].samples)))

    # 采信行只含缩短段实际采用的样本；其余连续段计入排除，保证行勾稽互斥且守恒
    work.counts['accepted'] = sum(len(band.samples) for band in clean_bands) + len(adopted_lines)
    clean_data = replace(work, bands=clean_bands + recovered_bands, rejected_bands=[])
    _, calibrated, decay_report, fitted, noise = clean_pipeline(clean_data)
    reconcile = reconcile_bands(work, fitted, shortenings, excluded_lines, recovered_bands)
    return {'calibration': calibrated, 'decay': decay_report, 'fit': fitted, 'noise': noise,
            'reconcile': reconcile, 'shortening': {'bands': [shortenings[hz] for hz in sorted(shortenings)]}}


def reconcile_bands(data, fitted, shortenings, excluded_lines, recovered_bands):
    rows = [compare(row) for row in fitted['bands']]
    recovered_hz = {band.hz for band in recovered_bands}
    for row in rows:
        if row['band_hz'] in recovered_hz:
            row['mode'] = 'SHORTENED'
            row['shortening'] = shortenings[row['band_hz']]
        else:
            row['mode'] = 'FULL'
    # 可恢复但无段可采信：退回补测
    for hz, evidence in shortenings.items():
        if evidence['adopted_label'] is None:
            rows.append({'band_hz': hz, 'status': 'REMEASURE', 'mode': 'BLOCKED', 't20_s': None, 't30_s': None,
                         'relative_gap': None, 'gap_flag': None,
                         'findings': [*evidence['defects'], reason('SEGMENT_BLOCKED')],
                         'shortening': evidence})
    # 完整性致命缺陷：整带退回补测
    for failure in data.rejected_bands:
        rows.append({'band_hz': failure['band_hz'], 'status': 'REMEASURE', 'mode': 'FATAL',
                     't20_s': None, 't30_s': None, 'relative_gap': None, 'gap_flag': None,
                     'findings': [*failure['findings'], reason('INTEGRITY_FATAL')], 'shortening': None})
    rows.sort(key=lambda row: row['band_hz'])
    return build_totals(data, rows, excluded_lines)


def reconcile(data, fitted):
    """旧勾稽入口：无缩短上下文时，拒收频带按致命缺陷退回补测处理。"""
    rows = [compare(row) for row in fitted['bands']]
    for row in rows:
        row['mode'] = 'FULL'
    for failure in data.rejected_bands:
        rows.append({'band_hz': failure['band_hz'], 'status': 'REMEASURE', 'mode': 'FATAL',
                     't20_s': None, 't30_s': None, 'relative_gap': None, 'gap_flag': None,
                     'findings': [*failure['findings'], reason('INTEGRITY_FATAL')], 'shortening': None})
    rows.sort(key=lambda row: row['band_hz'])
    return build_totals(data, rows, [])


def build_totals(data, rows, excluded_lines):
    totals = Counter(row['status'] for row in rows)
    data.counts['excluded'] = len(excluded_lines)
    declared = len(data.bands) + len(data.rejected_bands)
    row_gap = data.counts['input'] - sum(value for key, value in data.counts.items() if key != 'input')
    band_gap = declared - sum(totals.values())
    expected_bands = {band.hz for band in data.bands} | {row['band_hz'] for row in data.rejected_bands}
    identities_match = expected_bands == {row['band_hz'] for row in rows} and len(rows) == len(expected_bands)
    shortened = sum(row.get('mode') == 'SHORTENED' for row in rows)
    remeasure = sum(row['status'] == 'REMEASURE' for row in rows)
    acceptance = {
        'full_fit_bands': sum(row['status'] == 'FIT' and row.get('mode') == 'FULL' for row in rows),
        'shortened_fit_bands': shortened,
        'remeasure_bands': remeasure,
        'insufficient_bands': totals['INSUFFICIENT'],
        'acceptable': all(row['status'] in {'FIT', 'INSUFFICIENT'} for row in rows),
    }
    return {'status': 'MATCHED' if identities_match and band_gap == row_gap == 0 else 'DIFFERENCE',
            'totals': {'bands': declared, 'fitted': totals['FIT'], 'insufficient': totals['INSUFFICIENT'],
                       'isolated': totals['ISOLATED'], 'remeasure': remeasure, 'shortened': shortened,
                       'excluded_rows': len(excluded_lines), 'band_difference': band_gap, 'row_difference': row_gap,
                       'flagged': sum(row['gap_flag'] is not None for row in rows)},
            'acceptance': acceptance,
            'disagreement_limit': DISAGREEMENT_LIMIT, 'bands': rows,
            'unassigned_rows': sum(item['band_hz'] is None for item in data.row_issues)}
