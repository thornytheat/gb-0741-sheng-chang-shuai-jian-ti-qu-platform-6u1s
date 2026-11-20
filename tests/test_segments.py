"""连续采样缩短：坏行断开后的采信、挡下与整带退回补测规则。"""
from decimal import Decimal

from app.modules.m1_intake.continuity import build_segments
from app.modules.m1_intake.reader import read
from app.modules.m6_reconcile.service import evaluate
from app.records import Sample


def sample(index, amplitude, line=None):
    return Sample(line if line is not None else index + 2, index, Decimal(str(amplitude)), {})


def decaying(n, rt60=0.6, noise=2e-5, rate_hz=1000.0):
    # 指数衰减（RT60 定斜率）叠加恒定低噪声底，与真实脉冲响应尾段模型一致
    return [10 ** (-60.0 / rt60 * (i / rate_hz) / 20.0)
            + (noise if i % 2 == 0 else -noise) for i in range(n)]


def test_build_segments_never_joins_across_index_gap():
    samples = [sample(0, 1), sample(1, 1), sample(3, 1), sample(4, 1), sample(7, 1)]
    segments = build_segments(500, samples)
    assert [(seg.start_index, seg.end_index, seg.length) for seg in segments] == [(0, 1, 2), (3, 4, 2), (7, 7, 1)]


def test_pure_truncation_recovers_shortened_band_without_remeasure(encode):
    # 尾部截断（可恢复），保留段自身有足够衰减深度：应缩短采信而非整带退回
    n = 600
    values = decaying(n)
    records = [(500, i, 1000, n + 40, 'Pa', 0, '', v, '') for i, v in enumerate(values)]
    data = read(encode(*records))
    band = next(item for item in data.bands if item.hz == 500)
    assert band.recoverable
    assert [(seg.start_index, seg.end_index) for seg in band.segments] == [(0, n - 1)]
    report = evaluate(data)
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 500)
    assert row['status'] == 'FIT' and row['mode'] == 'SHORTENED'
    assert row['t20_s'] is not None and row['t30_s'] is not None
    assert report['reconcile']['totals']['remeasure'] == 0
    assert report['reconcile']['status'] == 'MATCHED'


def test_middle_gap_with_estimable_post_gap_run_is_shortened(encode):
    # 中间缺一行，峰值在前段，但后段连续且有足够深度：采信后段，前段留档挡下
    head = decaying(40)
    tail = decaying(600)
    records = [(500, i, 1000, 642, 'Pa', 0, '', v, '') for i, v in enumerate(head)]
    records += [(500, i + 41, 1000, 642, 'Pa', 0, '', v, '') for i, v in enumerate(tail)]
    data = read(encode(*records))
    report = evaluate(data)
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 500)
    assert row['mode'] == 'SHORTENED' and row['status'] == 'FIT'
    evidence = row['shortening']
    assert evidence['adopted_label'] == '500-S1'
    assert evidence['segments'][0]['adopted'] is False
    # 采信行不跨缺口：起点序号正是缺口之后
    assert evidence['adopted_lines']['start_index'] == 41


def test_all_runs_unestimable_returns_band_for_remeasure(encode):
    # 前段过短、后段动态范围不足：两段都挡下，整带退回补测且不产生曲线
    records = [(500, i, 1000, 120, 'Pa', 0, '', 1.0, '') for i in range(10)]
    records += [(500, i + 11, 1000, 120, 'Pa', 0, '', 0.9, '') for i in range(60)]
    data = read(encode(*records))
    report = evaluate(data)
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 500)
    assert row['status'] == 'REMEASURE' and row['mode'] == 'BLOCKED'
    assert 500 not in {item['band_hz'] for item in report['decay']['bands']}
    assert {seg['block_reason']['code'] for seg in row['shortening']['segments']}


def test_contradictory_duplicate_is_fatal_and_never_shortened(encode):
    records = [(500, i, 1000, 120, 'Pa', 0, '', v, '') for i, v in enumerate(decaying(120))]
    records.append((500, 14, 1000, 120, 'Pa', 0, '', 99, ''))  # 同序号矛盾值
    data = read(encode(*records))
    assert data.bands == [] and data.rejected_bands[0]['fatal_codes'] == ['DUPLICATE_CONFLICT']
    report = evaluate(data)
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 500)
    assert row['status'] == 'REMEASURE' and row['mode'] == 'FATAL'
    assert report['shortening']['bands'] == []


def test_adopted_segment_window_citations_stay_inside_adopted_lines(encode):
    n = 600
    values = decaying(n)
    records = [(500, i + 30, 1000, n + 70, 'Pa', 0, '', v, '') for i, v in enumerate(values)]
    data = read(encode(*records))
    report = evaluate(data)
    fit = next(item for item in report['fit']['bands'] if item['band_hz'] == 500)
    evidence = next(item for item in report['shortening']['bands'] if item['band_hz'] == 500)
    bounds = evidence['adopted_lines']
    for name in ('t20', 't30'):
        window = fit[name].get('window')
        if window and fit[name]['rt60_s'] is not None:
            assert bounds['first'] <= window['start_line'] and window['end_line'] <= bounds['last']


def test_extra_points_and_all_invalid_band_are_fatal_remeasure(encode):
    extra = [(500, i, 1000, 64, 'Pa', 0, '', 1.0, '') for i in range(70)]  # 超出声明长度
    data = read(encode(*extra))
    assert data.rejected_bands[0]['fatal_codes'] == ['EXTRA_POINTS']
    report = evaluate(data)
    row = report['reconcile']['bands'][0]
    assert row['status'] == 'REMEASURE' and row['mode'] == 'FATAL'

    invalid = [(500, i, 1000, 70, 'Pa', 0, '', 'N/A', '') for i in range(70)]  # 无任何有效行
    empty = evaluate(read(encode(*invalid)))
    only = empty['reconcile']['bands'][0]
    assert only['status'] == 'REMEASURE' and only['mode'] == 'FATAL'
    assert empty['reconcile']['status'] == 'MATCHED'
    assert empty['reconcile']['totals']['excluded_rows'] == 0


def test_multiple_gaps_adopt_single_best_run_and_exclude_others(encode):
    values = decaying(600)
    records = [(500, i, 1000, 650, 'Pa', 0, '', v, '') for i, v in enumerate(values[:50])]
    records += [(500, i + 51, 1000, 650, 'Pa', 0, '', v, '') for i, v in enumerate(values[50:500])]
    records += [(500, i + 502, 1000, 650, 'Pa', 0, '', v, '') for i, v in enumerate(values[500:])]
    data = read(encode(*records))
    band = next(item for item in data.bands if item.hz == 500)
    assert [(seg.start_index, seg.end_index) for seg in band.segments] == [(0, 49), (51, 500), (502, 601)]
    report = evaluate(data)
    row = next(item for item in report['reconcile']['bands'] if item['band_hz'] == 500)
    assert row['shortening']['adopted_label'] == '500-S1'
    assert sum(seg['adopted'] for seg in row['shortening']['segments']) == 1  # 同带唯一采信
    # 其余两段 50 + 100 行全部排除，绝不参与回归
    assert report['reconcile']['totals']['excluded_rows'] == 150
