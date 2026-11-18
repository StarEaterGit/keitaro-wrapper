"""Safety contract: optional in UI does NOT mean silently omitted remotely."""
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import app, get_db, get_keitaro, get_settings
from app.schemas import CampaignCreate
from app.services.campaigns import DomainError, create_campaign, preview


def input_3():
    return CampaignCreate(name='test_ivanov_campaign2', country='MX', offer_id=20)


def configure(settings):
    settings.campaign_domain_id = 1
    settings.campaign_group_id = 2
    settings.campaign_traffic_source_id = 3


def test_missing_ids_block_readonly_preview_before_remote_checks(fake, settings):
    payload = input_3()
    with pytest.raises(DomainError, match='Не настроены: домен, группа, источник трафика') as exc:
        preview(fake, settings, payload)
    assert exc.value.status == 422
    assert not fake.calls


def test_missing_ids_block_creation_before_any_http_writes(fake, settings, db):
    with pytest.raises(DomainError) as exc:
        create_campaign(db, fake, settings, input_3())
    assert exc.value.status == 422
    assert not fake.calls and not fake.campaigns


def test_configured_defaults_allow_three_input_preview(fake, settings):
    configure(settings)
    result = preview(fake, settings, input_3())
    assert result['selected_configuration'] == {'domain_id': 1, 'group_id': 2, 'traffic_source_id': 3}
    assert result['campaign']['domain_id'] == 1
    assert result['campaign']['group_id'] == '2'
    assert result['campaign']['traffic_source_id'] == 3
    assert result['streams'][0]['filters'][0]['payload'] == ['MX']
    assert not fake.calls


def test_manual_values_can_override_defaults(fake, settings):
    configure(settings)
    old_get = fake.get
    def get(path, params=None):
        if path == 'domains':
            return [{'id': 1, 'name':'default'}, {'id': 5, 'name':'explicit'}]
        return old_get(path, params)
    fake.get = get
    payload = input_3().model_copy(update={'domain_id': 5})
    plan = preview(fake, settings, payload)
    assert plan['selected_configuration']['domain_id'] == 5
    assert plan['selected_configuration']['group_id'] == 2
    assert not fake.calls


def test_unknown_default_id_cannot_be_written(fake, settings, db):
    configure(settings)
    settings.campaign_domain_id = 123456
    with pytest.raises(DomainError, match='Не найден домен'):
        create_campaign(db, fake, settings, input_3())
    assert not fake.calls


def test_three_input_creation_writes_only_own_new_campaign(fake, settings, db):
    configure(settings)
    result = create_campaign(db, fake, settings, input_3())
    assert result['status'] == 'ready'
    assert len(fake.campaigns) == 1
    assert fake.calls[0][2]['group_id'] == '2'
    assert [call[1] for call in fake.calls] == ['campaigns','streams','streams',f"campaigns/{result['id']}"]


def test_configuration_endpoint_does_not_expose_api_key(fake, settings, db):
    configure(settings)
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            public = http.get('/api/config')
            assert public.status_code == 200
            assert public.json()['campaign_defaults'] == {
                'domain_id': 1, 'group_id': 2, 'traffic_source_id': 3,
            }
            assert 'keitaro_api_key' not in public.text and 'test-key' not in public.text
            result = http.post('/api/preview', json=input_3().model_dump(exclude_none=True))
            assert result.status_code == 200
            assert not fake.calls
    finally:
        app.dependency_overrides.clear()


def test_env_optional_ids_validate_positive_numbers():
    with pytest.raises(ValueError):
        Settings(_env_file=None, campaign_domain_id=-1)
    s = Settings(_env_file=None, campaign_domain_id=1, campaign_group_id=2,
                 campaign_traffic_source_id=3)
    assert (s.campaign_domain_id,s.campaign_group_id,s.campaign_traffic_source_id)==(1,2,3)


def test_http_missing_defaults_returns_422_without_writes(fake, settings, db):
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            result = http.post('/api/preview',json=input_3().model_dump(exclude_none=True))
            assert result.status_code == 422
            assert 'домен' in result.json()['detail']
            assert fake.calls == []
    finally:
        app.dependency_overrides.clear()


def test_http_optional_fields_are_merged_by_backend(fake, settings, db):
    configure(settings)
    app.dependency_overrides[get_keitaro] = lambda: fake
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as http:
            result = http.post('/api/campaigns',json=input_3().model_dump(exclude_none=True))
            assert result.status_code == 201
            remote = fake.campaigns[result.json()['id']]
            assert remote['domain_id'] == 1
            assert remote['group_id'] == '2'
            assert remote['traffic_source_id'] == 3
    finally:
        app.dependency_overrides.clear()
