from concurrent.futures import ThreadPoolExecutor

from app.evidence import canonical, sha256


def test_archive_rerun_has_same_key_manifest_and_bytes(client):
    one = client.post('/api/runs', json={'sample':'hall'}).json()
    saved = client.get(f"/api/runs/{one['id']}/export")
    retry = client.post(f"/api/runs/{one['id']}/rerun").json()
    assert not one['reused'] and retry['reused'] and one['manifest'] == retry['manifest']
    assert client.get(f"/api/runs/{one['id']}/export").content == saved.content
    assert client.get('/api/runs').json()['runs'] == [one['manifest']]


def test_same_source_via_alias_has_one_archive(client):
    one = client.post('/api/runs', json={'sample':'reference'}).json()
    other = client.post('/api/runs', json={'source_id': one['manifest']['source_id']}).json()
    assert one['id'] == other['id'] and other['reused']


def test_rollback_after_insert_exception_and_repeat(client):
    with client.app.state.store.connect() as connection:
        connection.execute("CREATE TRIGGER fail_run AFTER INSERT ON runs BEGIN SELECT RAISE(ABORT, 'test'); END")
    response = client.post('/api/runs', json={'sample':'reference'})
    assert (response.status_code, response.json()['code']) == (503, 'ARCHIVE_FAILED')
    assert client.get('/api/runs').json()['runs'] == []
    with client.app.state.store.connect() as connection:
        connection.execute('DROP TRIGGER fail_run')
    assert client.post('/api/runs', json={'sample':'reference'}).json()['reused'] is False


def test_concurrent_runs_commit_once(client):
    with ThreadPoolExecutor(max_workers=3) as pool:
        values = list(pool.map(lambda _: client.post('/api/runs', json={'sample':'reference'}), range(3)))
    assert all(item.status_code == 200 for item in values)
    assert sum(not item.json()['reused'] for item in values) == 1
    assert len(client.get('/api/runs').json()['runs']) == 1


def test_export_is_attachment_and_digest_verified(client, raw):
    info = client.post('/api/runs', json={'sample':'hall'}).json()
    reply = client.get(f"/api/runs/{info['id']}/export")
    assert reply.headers['content-disposition'].startswith('attachment;')
    result = reply.json()
    assert result['manifest']['source_id'] == sha256(raw)
    assert result['manifest']['digest'] == sha256(canonical(result['result']))
    assert result['result']['reconcile']['totals']['flagged'] == 1


def test_corrupt_digest_blocks_export_and_rerun(client):
    run = client.post('/api/runs', json={'sample':'reference'}).json()['id']
    with client.app.state.store.connect() as connection:
        connection.execute('UPDATE runs SET digest=? WHERE id=?', ('bad', run))
    export = client.get(f'/api/runs/{run}/export')
    retry = client.post(f'/api/runs/{run}/rerun')
    assert [(reply.status_code, reply.json()['code']) for reply in (export, retry)] == [(409, 'EVIDENCE_CHANGED')] * 2


def test_shortened_result_is_deterministic_across_reruns(client):
    first = client.post('/api/runs', json={'sample': 'hall'}).json()
    second = client.post(f"/api/runs/{first['id']}/rerun").json()
    # 同源重跑：同一批次编号、同一摘要、同一采信行，绝不新增采信结果
    assert second['id'] == first['id'] and second['reused']
    assert second['manifest']['digest'] == first['manifest']['digest']
    adopted_one = [b for b in first['result']['reconcile']['bands'] if b.get('mode') == 'SHORTENED']
    adopted_two = [b for b in second['result']['reconcile']['bands'] if b.get('mode') == 'SHORTENED']
    assert adopted_one == adopted_two and len(adopted_one) == 1
    assert adopted_one[0]['shortening']['adopted_lines'] == {
        'first': 1202, 'last': 2200, 'start_index': 101, 'end_index': 1099}


def test_rule_version_change_invalidates_prior_archive(client, monkeypatch):
    from app.modules.m7_archive import service
    first = client.post('/api/runs', json={'sample': 'reference'}).json()
    # 模拟采信规则更新：版本号变化后旧批次重跑被拒绝，需按新规则重算
    monkeypatch.setattr(service, 'RULE_VERSION', 'rt-schroeder-9')
    refused = client.post(f"/api/runs/{first['id']}/rerun")
    assert (refused.status_code, refused.json()['code']) == (409, 'VERSION_CHANGED')
    monkeypatch.setattr(service, 'key', lambda source_id: service.sha256(
        service.canonical({'source_id': source_id, 'version': 'rt-schroeder-9'})))
    new_run = client.post('/api/runs', json={'sample': 'reference'}).json()
    assert new_run['id'] != first['id'] and new_run['manifest']['version'] == 'rt-schroeder-9'


def test_missing_or_ambiguous_source_has_clear_errors(client):
    missing = client.post('/api/runs', json={'sample':'bad'})
    ambiguous = client.post('/api/runs', json={'sample':'reference','source_id':'bad'})
    run = client.get('/api/runs/bad/export')
    assert [(reply.status_code, reply.json()['code']) for reply in (missing, ambiguous, run)] == [(404,'SAMPLE_UNKNOWN'),(422,'CHOOSE_SOURCE'),(404,'RUN_MISSING')]
