import pytest
from app.services.campaigns import (DomainError, build_plan, create_campaign, preview,
                                    campaign_detail, revision)


def test_preview_does_not_write(fake, settings, payload):
    result = preview(fake, settings, payload)
    assert result['streams'][0]['filters'][0]['payload'] == ['DE']
    assert result['streams'][1]['offers'][0]['offer_id'] == 10
    assert not fake.calls


def test_disabled_writes_do_not_post(fake, settings, db, payload):
    settings.keitaro_write_enabled = False
    with pytest.raises(DomainError) as exc:
        create_campaign(db, fake, settings, payload)
    assert exc.value.status == 403
    assert fake.calls == []


def test_wrong_name_does_not_post(fake, settings, db, payload):
    payload.name = 'test_other_campaign'
    with pytest.raises(DomainError) as exc:
        create_campaign(db, fake, settings, payload)
    assert exc.value.status == 422
    assert not fake.calls


def test_create_only_new_objects_and_verify_then_activate(fake, settings, db, payload):
    result = create_campaign(db, fake, settings, payload)
    assert result['status'] == 'ready'
    assert fake.campaigns[result['id']]['state'] == 'active'
    writes = [(method, path) for method, path, _ in fake.calls]
    assert writes == [
        ('POST', 'campaigns'), ('POST', 'streams'), ('POST', 'streams'),
        ('PUT', f"campaigns/{result['id']}"),
    ]
    assert fake.calls[0][2]['state'] == 'disabled'
    assert fake.calls[0][2]['group_id'] == '2'
    assert fake.calls[1][2]['type'] == 'forced'
    assert fake.calls[2][2]['type'] == 'default'
    assert all(method != 'DELETE' for method, _, _ in fake.calls)


def test_unfinished_creation_stays_disabled_and_is_audited(fake, settings, db, payload):
    fake.fail_stream_number = 2
    with pytest.raises(DomainError) as exc:
        create_campaign(db, fake, settings, payload)
    assert 'отключённом состоянии' in exc.value.message
    assert fake.campaigns[9000]['state'] == 'disabled'
    from app.models import OwnedCampaign
    row = db.get(OwnedCampaign, 9000)
    assert row.status == 'failed'
    assert row.geo_stream_id is not None
    assert row.offers_stream_id is None
    assert not [call for call in fake.calls if call[0] == 'DELETE']



def test_foreign_campaign_read_only_and_cannot_change(fake, settings, db, payload):
    from app.services.drafts import fetch_streams
    fake.campaigns[777] = {'id': 777, 'name': 'test_ivanov_looks_like_mine',
                           'alias': 'test', 'notes': 'not-the-marker', 'state': 'active'}
    fake.streams[888] = {'id': 888, 'campaign_id': 777, 'type': 'default',
                         'schema': 'landings', 'offers': [{'offer_id': 10, 'share': 100}]}
    info = campaign_detail(db, fake, settings, 777)
    assert info['can_edit'] is False
    with pytest.raises(DomainError) as exc:
        fetch_streams(db, fake, settings, 777)
    assert exc.value.status == 403
    assert not fake.calls


def test_manual_owner_marker_change_blocks_all_editor_operations(fake, settings, db, payload):
    from app.services.drafts import fetch_streams, stage_add
    id_ = create_campaign(db, fake, settings, payload)['id']
    before = fetch_streams(db, fake, settings, id_)
    fake.campaigns[id_]['notes'] = 'someone changed this'
    assert not campaign_detail(db, fake, settings, id_)['can_edit']
    with pytest.raises(DomainError) as exc:
        stage_add(db, fake, settings, id_, before['version'], 20)
    assert exc.value.status == 409


def test_foreign_extra_stream_blocks_editor_write(fake, settings, db, payload):
    from app.services.drafts import fetch_streams, stage_add
    result = create_campaign(db, fake, settings, payload)
    id_ = result['id']
    before = fetch_streams(db, fake, settings, id_)
    fake.streams[999999] = {'id': 999999, 'campaign_id': id_, 'type': 'regular',
                            'schema': 'redirect', 'offers': []}
    with pytest.raises(DomainError) as exc:
        stage_add(db, fake, settings, id_, before['version'], 20)
    assert exc.value.status == 409
