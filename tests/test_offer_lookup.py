"""API contract: ID can be resolved even when list view is partial."""
from fastapi.testclient import TestClient
from app.main import app, get_keitaro, get_db, get_settings
from app.config import Settings
from app.schemas import CampaignCreate
from app.services.campaigns import preview


def test_custom_uppercase_prefix_is_accepted(fake):
    settings = Settings(_env_file=None, keitaro_base_url='https://example.invalid',
        keitaro_api_key='test-key', campaign_prefix='test_yakimenkoVS_',
        keitaro_write_enabled=False, database_url='sqlite://')
    payload = CampaignCreate(name='test_yakimenkoVS_campaign1', country='DE',
        offer_id=20, domain_id=1, group_id=2, traffic_source_id=3)
    result = preview(fake, settings, payload)
    assert result['campaign']['name'] == payload.name
    assert result['streams'][1]['offers'][0]['offer_id'] == 20
    assert fake.calls == []


def test_offer_direct_lookup_works_if_list_has_one_item(fake, settings, db, payload):
    original_get=fake.get
    def one_visible_offer_in_list(path, params=None):
        if path == 'offers':
            return [{'id': 10, 'name': 'Offer 10', 'state': 'active'}]
        return original_get(path, params=params)
    fake.get=one_visible_offer_in_list
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            listing = http.get('/api/lookups')
            assert listing.status_code == 200
            assert listing.json()['offers_returned_by_api'] == 1
            assert [x['id'] for x in listing.json()['offers']] == [10]
            direct = http.get('/api/offers/20/lookup')
            assert direct.status_code == 200
            assert direct.json()['id'] == 20
            body = payload.model_dump() | {'offer_id': 20}
            planned = http.post('/api/preview', json=body)
            assert planned.status_code == 200
            assert planned.json()['streams'][1]['offers'][0]['offer_id'] == 20
            assert fake.calls == []
    finally:
        app.dependency_overrides.clear()


def test_invalid_id_lookup_is_read_only(fake, settings, db):
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            assert http.get('/api/offers/0/lookup').status_code == 422
            assert http.get('/api/offers/9999/lookup').status_code == 404
            assert fake.calls == []
    finally:
        app.dependency_overrides.clear()
