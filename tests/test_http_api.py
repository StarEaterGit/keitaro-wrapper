from fastapi.testclient import TestClient
from app.main import app, get_keitaro, get_db, get_settings


def test_http_unknown_campaign_cannot_be_edited(fake, settings, db, payload):
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            assert http.get('/health').status_code == 200
            assert http.get('/api/config').json()['write_enabled'] is True
            preview = http.post('/api/preview', json=payload.model_dump())
            assert preview.status_code == 200
            assert fake.calls == []
            forbidden = http.post('/api/campaigns/777/editor/add',json={
                'offer_id': 20, 'version': 1,
            })
            assert forbidden.status_code == 403
            assert fake.calls == []
            # Deliberate absence of any Keitaro resource DELETE API.
            assert http.delete('/api/campaigns/777').status_code == 405
    finally:
        app.dependency_overrides.clear()


def test_http_campaign_write_requires_explicit_flag(fake, settings, db, payload):
    settings.keitaro_write_enabled = False
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            response = http.post('/api/campaigns', json=payload.model_dump())
            assert response.status_code == 403
            assert fake.calls == []
    finally:
        app.dependency_overrides.clear()


def test_http_draft_roundtrip_and_explicit_push(fake, settings, db, payload):
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            created = http.post('/api/campaigns', json=payload.model_dump())
            assert created.status_code == 201
            id_ = created.json()['id']
            initial = http.get(f'/api/campaigns/{id_}/editor')
            assert initial.status_code == 200
            version = initial.json()['version']
            writes = len(fake.calls)
            staged = http.post(f'/api/campaigns/{id_}/editor/add', json={'version': version, 'offer_id': 20})
            assert staged.status_code == 200
            assert staged.json()['dirty']
            assert len(fake.calls) == writes  # No writes to Keitaro on Add.
            published = http.post(f'/api/campaigns/{id_}/editor/push', json={'version': staged.json()['version']})
            assert published.status_code == 200
            assert not published.json()['dirty']
            assert fake.calls[-1][0:2] == ('PUT', f'streams/{created.json()["offers_stream_id"]}')
            assert http.post(f'/api/campaigns/{id_}/offers', json={}).status_code == 404  # old unsafe endpoint is gone
    finally:
        app.dependency_overrides.clear()


def test_http_readonly_allows_draft_but_blocks_push(fake, settings, db, payload):
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            created = http.post('/api/campaigns', json=payload.model_dump())
            assert created.status_code == 201
            campaign_id = created.json()['id']
            offer_stream = created.json()['offers_stream_id']
            initial = http.get(f'/api/campaigns/{campaign_id}/editor')
            settings.keitaro_write_enabled = False
            before = len(fake.calls)
            staged = http.post(f'/api/campaigns/{campaign_id}/editor/add', json={
                'version': initial.json()['version'], 'offer_id': 20,
            })
            assert staged.status_code == 200
            assert staged.json()['dirty']
            assert len(fake.calls) == before
            assert [x['offer_id'] for x in fake.streams[offer_stream]['offers']] == [10]
            push = http.post(f'/api/campaigns/{campaign_id}/editor/push', json={
                'version': staged.json()['version'],
            })
            assert push.status_code == 403
            assert len(fake.calls) == before
            canceled = http.post(f'/api/campaigns/{campaign_id}/editor/cancel', json={
                'version': staged.json()['version'],
            })
            assert canceled.status_code == 200
            assert not canceled.json()['dirty']
            assert len(fake.calls) == before
    finally:
        app.dependency_overrides.clear()


def test_http_readonly_foreign_campaign_cannot_stage(fake, settings, db):
    settings.keitaro_write_enabled = False
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            forbidden = http.post('/api/campaigns/8181/editor/add', json={
                'version': 1, 'offer_id': 20,
            })
            assert forbidden.status_code == 403
            assert fake.calls == []
    finally:
        app.dependency_overrides.clear()
