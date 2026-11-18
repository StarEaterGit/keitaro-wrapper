"""Contract from the supplied 6:13 demonstration video.
Every FakeKeitaro.calls item records an upstream write, so we can prove
stage/restore/cancel/fetch operations do NOT modify the shared tracker.
"""
import pytest
from app.services.campaigns import DomainError, create_campaign
from app.services.drafts import (
    fetch_streams, view_draft, stage_add, stage_remove, stage_restore,
    stage_pin, cancel, push,
)


def setup(fake, settings, db, payload):
    c = create_campaign(db, fake, settings, payload)
    d = fetch_streams(db, fake, settings, c['id'])
    return c['id'], c['offers_stream_id'], d


def shares(view):
    return [(r['offer_id'], r['share']) for r in view['rows'] if not r['removed'] and r['state'] == 'active']


def test_fetch_offers_and_keep_no_offer_geo_stream_untouched(fake, settings, db, payload):
    id_, stream_id, view = setup(fake, settings, db, payload)
    before = len(fake.calls)
    view = fetch_streams(db, fake, settings, id_)
    assert len(fake.calls) == before
    assert shares(view) == [(10, 100)]
    assert view['stream_id'] == stream_id
    assert any(x['schema'] == 'redirect' for x in fake.streams.values())


def test_add_is_only_local_until_push_and_balances_34_33_33(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    before = len(fake.calls)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    d = stage_add(db, fake, settings, id_, d['version'], 30)
    assert d['dirty']
    assert shares(d) == [(10, 34), (20, 33), (30, 33)]
    assert len(fake.calls) == before
    assert len(fake.streams[stream_id]['offers']) == 1
    d = push(db, fake, settings, id_, d['version'])
    assert d['dirty'] is False
    assert [x['share'] for x in fake.streams[stream_id]['offers']] == [34, 33, 33]
    assert fake.calls[-1][1] == f'streams/{stream_id}'
    assert list(fake.calls[-1][2]) == ['offers']


def test_cancel_drops_unpublished_new_offer_but_not_remote(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    before = len(fake.calls)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    d = cancel(db, fake, settings, id_, d['version'])
    assert shares(d) == [(10, 100)]
    assert not d['dirty']
    assert len(fake.calls) == before
    assert [x['offer_id'] for x in fake.streams[stream_id]['offers']] == [10]


def test_remove_archived_then_bring_back_published(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    d = push(db, fake, settings, id_, d['version'])
    before = len(fake.calls)
    d = stage_remove(db, fake, settings, id_, d['version'], 10)
    assert next(x for x in d['rows'] if x['offer_id'] == 10)['share'] == 0
    assert next(x for x in d['rows'] if x['offer_id'] == 10)['removed']
    assert len(fake.calls) == before
    d = push(db, fake, settings, id_, d['version'])
    assert [x['offer_id'] for x in fake.streams[stream_id]['offers']] == [20]
    assert next(x for x in d['rows'] if x['offer_id'] == 10)['removed']
    assert 10 in fake.offers  # global Keitaro offer was NOT deleted
    d = stage_restore(db, fake, settings, id_, d['version'], 10)
    assert shares(d) == [(10, 50), (20, 50)]
    d = push(db, fake, settings, id_, d['version'])
    assert {x['offer_id'] for x in fake.streams[stream_id]['offers']} == {10, 20}


def test_fetch_archives_external_removal_without_put(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    d = push(db, fake, settings, id_, d['version'])
    fake.streams[stream_id]['offers'] = [{'offer_id': 20, 'share': 100, 'state': 'active'}]
    before = len(fake.calls)
    d = fetch_streams(db, fake, settings, id_)
    assert len(fake.calls) == before
    removed = next(x for x in d['rows'] if x['offer_id'] == 10)
    assert removed['removed'] and removed['share'] == 0
    assert d['dirty'] is False
    d = stage_restore(db, fake, settings, id_, d['version'], 10)
    assert shares(d) == [(20, 50), (10, 50)]


def test_pin_25_distributes_75_over_remaining_and_stays_pinned(fake, settings, db, payload):
    id_, _, d = setup(fake, settings, db, payload)
    for offer in (20, 30, 40):
        fake.offers[offer] = {'id': offer, 'name': f'Offer {offer}', 'state': 'active'}
        d = stage_add(db, fake, settings, id_, d['version'], offer)
    assert shares(d) == [(10, 25), (20, 25), (30, 25), (40, 25)]
    d = stage_pin(db, fake, settings, id_, d['version'], 10, True)
    d = stage_remove(db, fake, settings, id_, d['version'], 40)
    assert shares(d) == [(10, 25), (20, 38), (30, 37)]
    assert sum(share for _, share in shares(d)) == 100
    assert next(x for x in d['rows'] if x['offer_id'] == 10)['pinned']


def test_push_rejects_remote_external_edits_without_writes(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    fake.streams[stream_id]['offers'] = [{'offer_id': 10, 'share': 90, 'state': 'active'}]
    before = len(fake.calls)
    with pytest.raises(DomainError, match='изменился') as exc:
        push(db, fake, settings, id_, d['version'])
    assert exc.value.status == 409
    assert len(fake.calls) == before


def test_foreign_campaign_staging_rejected_without_put(fake, settings, db):
    fake.campaigns[77] = {'id':77,'name':'test_ivanov_lookalike','notes':'no','alias':'other','state':'active'}
    fake.streams[77] = {'id':77,'campaign_id':77,'schema':'landings','type':'default','offers':[]}
    with pytest.raises(DomainError) as exc:
        stage_add(db, fake, settings, 77, 1, 10)
    assert exc.value.status == 403
    assert fake.calls == []


def test_fetch_refuses_to_erase_unsaved_draft(fake, settings, db, payload):
    id_, _, d = setup(fake, settings, db, payload)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    with pytest.raises(DomainError) as exc:
        fetch_streams(db, fake, settings, id_)
    assert exc.value.status == 409
    assert view_draft(db, fake, settings, id_)['dirty']


def test_readonly_mode_allows_only_local_drafts_and_cancel(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    before = len(fake.calls)
    settings.keitaro_write_enabled = False

    d = stage_add(db, fake, settings, id_, d['version'], 20)
    assert d['dirty'] and shares(d) == [(10, 50), (20, 50)]
    d = stage_add(db, fake, settings, id_, d['version'], 30)
    d = stage_pin(db, fake, settings, id_, d['version'], 10, True)
    d = stage_remove(db, fake, settings, id_, d['version'], 20)
    assert next(x for x in d['rows'] if x['offer_id'] == 20)['removed']
    d = stage_restore(db, fake, settings, id_, d['version'], 20)
    assert shares(d) == [(10, 34), (20, 33), (30, 33)]
    assert len(fake.calls) == before  # no writes to tracker
    assert len(fake.streams[stream_id]['offers']) == 1

    with pytest.raises(DomainError) as exc:
        push(db, fake, settings, id_, d['version'])
    assert exc.value.status == 403
    assert len(fake.calls) == before
    d = cancel(db, fake, settings, id_, d['version'])
    assert not d['dirty'] and shares(d) == [(10, 100)]
    assert len(fake.calls) == before


def test_zero_active_offers_cannot_be_pushed(fake, settings, db, payload):
    id_, stream_id, d = setup(fake, settings, db, payload)
    d = stage_remove(db, fake, settings, id_, d['version'], 10)
    before = len(fake.calls)
    with pytest.raises(DomainError) as exc:
        push(db, fake, settings, id_, d['version'])
    assert exc.value.status == 422
    assert len(fake.calls) == before


def test_stale_draft_version_rejected(fake, settings, db, payload):
    id_, _, d = setup(fake, settings, db, payload)
    d = stage_add(db, fake, settings, id_, d['version'], 20)
    with pytest.raises(DomainError) as exc:
        stage_remove(db, fake, settings, id_, d['version']-1, 10)
    assert exc.value.status == 409
