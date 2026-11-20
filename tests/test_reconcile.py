from copy import deepcopy

import pytest

from app.config import SAMPLES
from app.modules.m1_intake.reader import read
from app.modules.m6_reconcile.comparison import compare
from app.modules.m6_reconcile.service import evaluate, reconcile


def test_dirty_sample_conserves_both_counts(data, report):
    result = report['reconcile']
    assert result['status'] == 'MATCHED'
    assert result['totals'] == {'bands': 8, 'fitted': 5, 'insufficient': 1, 'isolated': 0, 'remeasure': 2,
                                'shortened': 1, 'excluded_rows': 399, 'band_difference': 0, 'row_difference': 0,
                                'flagged': 1}
    assert result['unassigned_rows'] == 1
    # 行勾稽互斥且守恒：采信 + 隔离 + 重复 + 空白 + 重复表头 + 排除段 = 输入
    assert sum(value for key, value in data.counts.items() if key != 'input') == data.counts['input']


def test_recoverable_band_keeps_traceable_shortened_conclusion(report):
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 250)
    assert row['status'] == 'FIT' and row['mode'] == 'SHORTENED'
    assert (row['t20_s'], row['t30_s']) == pytest.approx((.66, .66), abs=.001)
    evidence = row['shortening']
    assert evidence['adopted_label'] == '250-S1'
    assert evidence['adopted_lines'] == {'first': 1202, 'last': 2200, 'start_index': 101, 'end_index': 1099}
    blocked = next(segment for segment in evidence['segments'] if segment['label'] == '250-S0')
    assert blocked['admissible'] is False and blocked['adopted'] is False
    assert blocked['block_reason']['code'] == 'DYNAMIC_RANGE'
    # 曲线、拟合、噪声全部对账到同一采信行段
    curve = next(item for item in report['decay']['bands'] if item['band_hz'] == 250)
    assert curve['points'][0]['source_line'] == 1202 and curve['points'][-1]['source_line'] == 2200
    fit = next(item for item in report['fit']['bands'] if item['band_hz'] == 250)
    assert fit['t20']['window']['start_line'] >= 1202 and fit['t30']['window']['end_line'] <= 2200


def test_unestimable_segments_and_fatal_band_return_for_remeasure(report):
    by_hz = {row['band_hz']: row for row in report['reconcile']['bands']}
    blocked = by_hz[63]
    assert blocked['status'] == 'REMEASURE' and blocked['mode'] == 'BLOCKED'
    reasons = {segment['block_reason']['code'] for segment in blocked['shortening']['segments']}
    assert reasons == {'TAIL_TOO_SHORT', 'DYNAMIC_RANGE'}
    fatal = by_hz[2000]
    assert fatal['status'] == 'REMEASURE' and fatal['mode'] == 'FATAL'
    assert any(item['code'] == 'INTEGRITY_FATAL' for item in fatal['findings'])
    assert report['reconcile']['acceptance'] == {
        'full_fit_bands': 4, 'shortened_fit_bands': 1, 'remeasure_bands': 2,
        'insufficient_bands': 1, 'acceptable': False}


def test_shortening_does_not_splice_across_gap(data, report):
    # 63 Hz 两段都不采信时，其全部物理行计入排除，绝不进入任何曲线
    evidence = next(item for item in report['shortening']['bands'] if item['band_hz'] == 63)
    assert evidence['adopted_label'] is None
    curve_hz = {band['band_hz'] for band in report['decay']['bands']}
    assert 63 not in curve_hz and 2000 not in curve_hz
    excluded = report['reconcile']['totals']['excluded_rows']
    assert excluded == 399  # 63 Hz 两段 299 行 + 250 Hz 前段 100 行


def test_post_adoption_partition_conserves_input_rows(data, report):
    # 评估在工作副本上重分类：采信行 + 排除段 = 收件阶段进入频带的有效物理行，行勾稽差额为零
    totals = report['reconcile']['totals']
    assert totals['row_difference'] == 0 and totals['band_difference'] == 0
    # 收件态计数不被评估改写：重新读取仍是收件分区
    fresh = read(SAMPLES['hall'].read_bytes())
    assert fresh.counts['excluded'] == 0 and fresh.counts['accepted'] == 7398
    # 评估采信行（各带校准采样数，含峰值前后）+ 排除段 = 收件有效行
    adopted = sum(band['sample_count'] for band in report['calibration']['bands'])
    assert adopted + totals['excluded_rows'] == fresh.counts['accepted']


def test_two_slope_band_gets_disagreement_flag(report):
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 8000)
    assert (row['t20_s'], row['t30_s']) == pytest.approx((.79543, 1.02319), abs=.0001)
    assert row['gap_flag']['code'] == 'T_DISAGREEMENT' and row['relative_gap'] == pytest.approx(.2226, abs=.0001)


def test_one_fit_preserves_valid_band_but_has_no_two_fit_comparison(report):
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 4000)
    assert row['status'] == 'FIT' and row['t30_s'] is None
    assert row['gap_flag'] is None and row['relative_gap'] is None


def test_independent_frequency_identity_detects_duplicate_even_with_equal_count(data, report):
    wrong = deepcopy(report['fit'])
    wrong['bands'][0]['band_hz'] = wrong['bands'][1]['band_hz']
    result = reconcile(data, wrong)
    # 身份集合出现重复频带，频带数量与声明不符即判差额；状态仍为 DIFFERENCE
    assert result['totals']['band_difference'] != 0 and result['status'] == 'DIFFERENCE'


def test_reference_clean_recording_has_two_valid_bands():
    output = evaluate(read(SAMPLES['reference'].read_bytes()))['reconcile']
    assert [row['t30_s'] for row in output['bands']] == pytest.approx([.60, .90], abs=.001)
    assert (output['totals']['fitted'], output['totals']['isolated'], output['totals']['flagged']) == (2, 0, 0)


def test_high_threshold_equal_case_and_invalid_fits_partition():
    def values(a, b):
        return {'band_hz': 63, 't20': {'rt60_s': a, 'error': None}, 't30': {'rt60_s': b, 'error': None}}
    assert compare(values(.85, 1))['relative_gap'] == pytest.approx(.15)
    assert compare(values(.85, 1))['gap_flag'] is None
    assert compare(values(.86, 1))['gap_flag'] is None
    assert compare(values(.84, 1))['gap_flag']['code'] == 'T_DISAGREEMENT'
