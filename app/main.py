from collections.abc import Iterator
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import OwnedCampaign
from app.schemas import CampaignCreate, DraftOfferChange, DraftPinChange, DraftVersion
from app.services.campaigns import (DomainError, campaign_detail, create_campaign,
                                    preview, expect_list)
from app.services.keitaro import KeitaroClient, KeitaroError
from app.services import drafts

app = FastAPI(title='Keitaro Wrapper', version='1.1.0')
static = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=static), name='static')


def get_keitaro(settings: Settings = Depends(get_settings)) -> Iterator[KeitaroClient]:
    if not settings.keitaro_api_key or settings.keitaro_api_key == 'REPLACE_WITH_YOUR_ADMIN_API_KEY':
        raise HTTPException(503, 'Установите KEITARO_API_KEY в .env.')
    client = KeitaroClient(settings.keitaro_base_url, settings.keitaro_api_key)
    try:
        yield client
    finally:
        client.close()


@app.exception_handler(DomainError)
def handle_domain_error(request, exc: DomainError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status, content={'detail': exc.message})

@app.exception_handler(KeitaroError)
def handle_keitaro_error(request, exc: KeitaroError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.message})

@app.get('/', include_in_schema=False)
def home():
    return FileResponse(static / 'index.html')

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/api/config')
def config(settings: Settings = Depends(get_settings)):
    return {'write_enabled': settings.keitaro_write_enabled,
            'campaign_prefix': settings.campaign_prefix,
            'campaign_defaults': {
                'domain_id': settings.campaign_domain_id,
                'group_id': settings.campaign_group_id,
                'traffic_source_id': settings.campaign_traffic_source_id,
            },
            'safety_policy': 'Only this installation’s DB-registered campaigns can be edited.'}

@app.get('/api/lookups')
def lookups(client: KeitaroClient = Depends(get_keitaro)):
    def slim(items):
        return [{'id': x['id'], 'name': x.get('name', f'ID {x["id"]}')} for x in items
                if isinstance(x, dict) and isinstance(x.get('id'), int) and x.get('state') != 'deleted']
    offered = expect_list(client.get('offers'), 'офферов')
    return {
        'domains': slim(expect_list(client.get('domains'), 'доменов')),
        'groups': slim(expect_list(client.get('groups', params={'type': 'campaigns'}), 'групп')),
        'traffic_sources': slim(expect_list(client.get('traffic_sources'), 'источников')),
        'offers': slim(offered),
        'offers_returned_by_api': len(offered),
    }

@app.post('/api/preview')
def creation_preview(payload: CampaignCreate,
                     settings: Settings = Depends(get_settings),
                     client: KeitaroClient = Depends(get_keitaro)):
    return preview(client, settings, payload)

@app.post('/api/campaigns', status_code=201)
def create(payload: CampaignCreate, db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return create_campaign(db, client, settings, payload)

@app.get('/api/campaigns')
def campaigns(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    # Only local owned campaigns are included. No remote foreign resources are modified.
    rows = db.scalars(select(OwnedCampaign).where(OwnedCampaign.instance_url == settings.keitaro_base_url)
                     .order_by(OwnedCampaign.id.desc())).all()
    return [{'id': r.id, 'name': r.name, 'status': r.status, 'created_at': r.created_at.isoformat() if r.created_at else None}
            for r in rows]

@app.get('/api/campaigns/{campaign_id}')
def detail(campaign_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
           client: KeitaroClient = Depends(get_keitaro)):
    return campaign_detail(db, client, settings, campaign_id)


@app.get('/api/offers/search')
def search_offers(q: str = '', client: KeitaroClient = Depends(get_keitaro)):
    term = q.strip().lower()
    if not term:
        return []
    items = expect_list(client.get('offers'), 'офферов')
    return [{'id': x['id'], 'name': x.get('name', str(x['id']))}
            for x in items
            if isinstance(x, dict) and isinstance(x.get('id'), int)
            and x.get('state') != 'deleted'
            and (term in str(x['id']) or term in str(x.get('name', '')).lower())][:30]


@app.get('/api/offers/{offer_id}/lookup')
def lookup_offer(offer_id: int, client: KeitaroClient = Depends(get_keitaro)):
    """Look up an exact ID independently of the offers dropdown.

    Read-only. Never creates or updates offers in Keitaro.
    """
    if offer_id <= 0:
        raise HTTPException(422, 'ID оффера должен быть положительным числом.')
    item = client.get_offer(offer_id)
    if not isinstance(item, dict) or item.get('id') != offer_id or item.get('state') == 'deleted':
        raise HTTPException(404, 'Оффер не найден, удалён или недоступен через этот API-ключ.')
    return {
        'id': item['id'],
        'name': str(item.get('name') or f'Offer {offer_id}'),
        'state': str(item.get('state') or 'unknown'),
    }


@app.get('/api/campaigns/{campaign_id}/editor')
def editor(campaign_id: int, db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.view_draft(db, client, settings, campaign_id)


@app.post('/api/campaigns/{campaign_id}/editor/fetch')
def editor_fetch(campaign_id: int, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.fetch_streams(db, client, settings, campaign_id)


@app.post('/api/campaigns/{campaign_id}/editor/add')
def editor_add(campaign_id: int, body: DraftOfferChange, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.stage_add(db, client, settings, campaign_id, body.version, body.offer_id)


@app.post('/api/campaigns/{campaign_id}/editor/remove')
def editor_remove(campaign_id: int, body: DraftOfferChange, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.stage_remove(db, client, settings, campaign_id, body.version, body.offer_id)


@app.post('/api/campaigns/{campaign_id}/editor/restore')
def editor_restore(campaign_id: int, body: DraftOfferChange, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.stage_restore(db, client, settings, campaign_id, body.version, body.offer_id)


@app.post('/api/campaigns/{campaign_id}/editor/pin')
def editor_pin(campaign_id: int, body: DraftPinChange, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.stage_pin(db, client, settings, campaign_id, body.version, body.offer_id, body.pinned)


@app.post('/api/campaigns/{campaign_id}/editor/cancel')
def editor_cancel(campaign_id: int, body: DraftVersion, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.cancel(db, client, settings, campaign_id, body.version)


@app.post('/api/campaigns/{campaign_id}/editor/push')
def editor_push(campaign_id: int, body: DraftVersion, db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings), client: KeitaroClient = Depends(get_keitaro)):
    return drafts.push(db, client, settings, campaign_id, body.version)
