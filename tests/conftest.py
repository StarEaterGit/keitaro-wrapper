import copy
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.config import Settings


class FakeKeitaro:
    def __init__(self):
        self.campaigns = {}
        self.streams = {}
        self.offers = {10: {'id': 10, 'name': 'Offer 10', 'state': 'active'},
                       20: {'id': 20, 'name': 'Offer 20', 'state': 'active'},
                       30: {'id': 30, 'name': 'Offer 30', 'state': 'active'}}
        self.calls = []
        self.next_campaign_id = 9000
        self.next_stream_id = 5000
        self.fail_stream_number = None

    def get(self, path, params=None):
        if path == 'domains': return [{'id': 1, 'name': 'example.test'}]
        if path == 'groups': return [{'id': 2, 'name': 'My group'}]
        if path == 'traffic_sources': return [{'id': 3, 'name': 'Test source'}]
        if path == 'offers': return list(self.offers.values())
        raise RuntimeError('unexpected GET ' + path)

    def get_offer(self, offer_id):
        return copy.deepcopy(self.offers.get(offer_id, {}))

    def get_campaign(self, campaign_id):
        return copy.deepcopy(self.campaigns.get(campaign_id, {}))

    def get_streams(self, campaign_id):
        return copy.deepcopy([s for s in self.streams.values() if s['campaign_id'] == campaign_id])

    def get_stream(self, stream_id):
        return copy.deepcopy(self.streams.get(stream_id, {}))

    def create_campaign(self, body):
        self.calls.append(('POST', 'campaigns', copy.deepcopy(body)))
        id_ = self.next_campaign_id; self.next_campaign_id += 1
        self.campaigns[id_] = dict(copy.deepcopy(body), id=id_)
        return copy.deepcopy(self.campaigns[id_])

    def create_stream(self, body):
        n = len([c for c in self.calls if c[1] == 'streams']) + 1
        self.calls.append(('POST', 'streams', copy.deepcopy(body)))
        if n == self.fail_stream_number:
            raise RuntimeError('simulated Keitaro failure')
        id_ = self.next_stream_id; self.next_stream_id += 1
        self.streams[id_] = dict(copy.deepcopy(body), id=id_, offers=body.get('offers', []))
        return copy.deepcopy(self.streams[id_])

    def activate_campaign(self, campaign_id):
        self.calls.append(('PUT', f'campaigns/{campaign_id}', {'state': 'active'}))
        self.campaigns[campaign_id]['state'] = 'active'

    def replace_stream_offers(self, stream_id, offers):
        self.calls.append(('PUT', f'streams/{stream_id}', {'offers': copy.deepcopy(offers)}))
        self.streams[stream_id]['offers'] = copy.deepcopy(offers)


@pytest.fixture
def fake():
    return FakeKeitaro()

@pytest.fixture
def settings():
    return Settings(_env_file=None, keitaro_base_url='https://example.invalid',
                    campaign_prefix='test_ivanov_', keitaro_write_enabled=True,
                    keitaro_api_key='test-key', database_url='sqlite://')

@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()

@pytest.fixture
def payload():
    from app.schemas import CampaignCreate
    return CampaignCreate(name='test_ivanov_campaign1', country='DE', offer_id=10,
                          domain_id=1, group_id=2, traffic_source_id=3)
