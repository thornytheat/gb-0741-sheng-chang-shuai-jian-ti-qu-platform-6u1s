import pytest

from app.config import SAMPLES
from app.errors import Problem
from app.modules.m1_intake.reader import read


def test_sample_counts_are_exclusive_and_remove_repeated_header():
    fresh = read(SAMPLES['hall'].read_bytes())  # 独立读取，避免评估阶段对采信/排除行的重分类
    # 缩短规则下：可恢复带（63/250）保留在 bands，致命带（2000）整带隔离；排除段在评估阶段才从 accepted 划至 excluded
    assert fresh.counts == {'input': 8466, 'accepted': 7398, 'isolated': 1065, 'duplicate': 1, 'blank': 1,
                            'repeated_headers': 1, 'excluded': 0}  # TRAP-04
    assert sum(value for key, value in fresh.counts.items() if key != 'input') == fresh.counts['input']


def test_bom_and_multiline_keep_physical_sample_lines(data):
    assert data.encoding == 'utf-8-sig'  # TRAP-02
    band = next(band for band in data.bands if band.hz == 500)
    assert (band.samples[6].line, band.samples[6].raw['note'], band.samples[7].line) == (2207, '直达声\n舞台柜位', 2209)  # TRAP-03


def test_reference_reads_gb18030():
    source = read(SAMPLES['reference'].read_bytes())
    assert source.encoding == 'gb18030'  # TRAP-01
    assert source.bands[0].samples[6].raw['note'].startswith('直达声')


def test_short_width_and_missing_amplitude_have_distinct_codes(data):
    bad = {row['code']: row for row in data.row_issues}
    assert (bad['ROW_WIDTH']['line'], bad['ROW_WIDTH']['raw']) == (8468, ['NOT-A-BAND', '4'])  # TRAP-05
    assert (bad['AMPLITUDE_MISSING']['band_hz'], bad['AMPLITUDE_MISSING']['raw']['amplitude']) == (63, 'N/A')  # TRAP-07
    band63 = next(band for band in data.bands if band.hz == 63)
    # 坏行隔离但频带保留：63 Hz 切成两段连续采样，交由缩短评估决定采信或退回补测
    assert band63.recoverable and [segment.label for segment in band63.segments] == ['63-S0', '63-S1']
    assert all(sample.index != 44 for segment in band63.segments for sample in segment.samples)


def test_missing_points_and_truncated_tail_are_different(data):
    band250 = next(band for band in data.bands if band.hz == 250)
    missing = next(item for item in band250.defects if item['code'] == 'MISSING_POINTS')
    assert missing['indices'] == [100]
    # 缺点在序号 100 断开：两段连续采样，绝不跨缺口拼接
    assert [(segment.start_index, segment.end_index) for segment in band250.segments] == [(0, 99), (101, 1099)]
    rejected = {row['band_hz']: row for row in data.rejected_bands}
    tail = next(item for item in rejected[2000]['findings'] if item['code'] == 'TRUNCATED_BAND')  # TRAP-16
    assert (tail['from_index'], tail['to_index']) == (1062, 1099)
    # 矛盾重复属致命完整性缺陷，2000 Hz 不允许缩短、整带退回补测
    assert rejected[2000]['fatal_codes'] == ['DUPLICATE_CONFLICT']


def test_contradictory_duplicate_band_never_reaches_fit(data):
    conflict = next(item for row in data.rejected_bands if row['band_hz'] == 2000 for item in row['findings'] if item['code'] == 'DUPLICATE_CONFLICT')  # TRAP-14
    assert conflict['index'] == 14 and len(conflict['lines']) == 2 and conflict['values'][1] == '99'
    assert [row['band_hz'] for row in data.row_issues if row['code'] == 'DUPLICATE_ROW'] == [500]


def test_arrival_order_reconstructed_by_sample_index(data):
    band = next(row for row in data.bands if row.hz == 1000)
    assert (band.samples[21].index, band.samples[22].index) == (21, 22)  # TRAP-13
    assert band.samples[21].line > band.samples[22].line


def test_empty_cases_raise_distinct_codes(encode):
    for content, expected in [(b'', 'EMPTY_FILE'), (b'\n\n', 'BLANK_FILE'), (encode(), 'HEADER_ONLY')]:
        with pytest.raises(Problem) as failure:
            read(content)
        assert failure.value.code == expected  # TRAP-18


def test_incomplete_csv_is_rejected_before_storage(client, encode):
    reply = client.post('/api/intake', files={'file': ('broken.csv', encode() + b'"broken')})
    assert (reply.status_code, reply.json()['code']) == (422, 'BROKEN_CSV')
    with client.app.state.store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM source').fetchone()[0] == 2


def test_config_conflict_keeps_both_citation_lines(encode):
    content = encode((500,0,1000,64,'Pa',0,'',1,''), (500,1,1000,64,'Pa',3,'',1,''))
    row = read(content).rejected_bands[0]
    assert row['findings'][0]['code'] == 'CAL_CONFLICT'
    assert row['findings'][0]['lines'] == [2, 3]
