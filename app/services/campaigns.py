"""Domain logic. Safety guards are applied server-side, never only in the UI."""
from pydantic.dataclasses import dataclass
from hashlib import sha256
import json
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, OwnedCampaign
from app.schemas import CampaignCreate
from app.services.keitaro import KeitaroClient, KeitaroError

GOOGLE_URL = 'https://www.google.com/'

class DomainError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def require_writes(settings: Settings) -> None:
    if not settings.keitaro_write_enabled:
        raise DomainError(403, 'Запись отключена. Проверьте конфигурацию и включите KEITARO_WRITE_ENABLED=true.')
    if settings.campaign_prefix == 'test_yoursurname_':
        raise DomainError(403, 'Установите собственную фамилию в CAMPAIGN_PREFIX перед записью.')


def require_owned_name(settings: Settings, name: str) -> None:
    if not name.startswith(settings.campaign_prefix) or len(name) <= len(settings.campaign_prefix):
        raise DomainError(422, f'Имя должно начинаться с {settings.campaign_prefix}, далее — название кампании.')


def extract_id(data) -> int:
    if not isinstance(data, dict) or not isinstance(data.get('id'), int) or data['id'] <= 0:
        raise DomainError(502, 'Keitaro вернул неожиданный формат объекта (нет ID).')
    return data['id']


def expect_list(data, name: str) -> list:
    if not isinstance(data, list):
        raise DomainError(502, f'Keitaro вернул неверный формат списка {name}.')
    return data


@dataclass(frozen=True)
class CampaignPlan:
    """Immutable plan; no HTTP side effects at construction time."""
    campaign: dict
    google_stream: dict
    offers_stream: dict


def build_plan(data: CampaignCreate, alias: str, marker: str, campaign_id: int = 0) -> CampaignPlan:
    return CampaignPlan(
        campaign={
            'name': data.name,
            'alias': alias,
            'state': 'disabled',  # Never expose a half-configured campaign.
            'type': 'position',
            'domain_id': data.domain_id,
            'group_id': str(data.group_id),
            'traffic_source_id': data.traffic_source_id,
            'notes': marker,
        },
        google_stream={
            'campaign_id': campaign_id,
            'name': f'GEO {data.country} -> Google',
            'type': 'forced',
            'position': 1,
            'schema': 'redirect',
            'action_type': 'http',
            'action_payload': GOOGLE_URL,
            'collect_clicks': True,
            'state': 'active',
            'filters': [{'name': 'country', 'mode': 'accept', 'payload': [data.country]}],
        },
        offers_stream={
            'campaign_id': campaign_id,
            'name': 'Offers (wrapper managed)',
            'type': 'default',
            'position': 2,
            'schema': 'landings',
            'action_type': 'http',
            'collect_clicks': True,
            'state': 'active',
            'offers': [{'offer_id': data.offer_id, 'share': 100, 'state': 'active'}],
        },
    )


def _check_exists(client: KeitaroClient, data: CampaignCreate) -> None:
    offer = client.get_offer(data.offer_id)
    if not isinstance(offer, dict) or offer.get('id') != data.offer_id or offer.get('state') == 'deleted':
        raise DomainError(422, 'Оффер не найден или архивирован.')
    for endpoint, id_, label in [
        ('domains', data.domain_id, 'домен'),
        ('groups', data.group_id, 'группа'),
        ('traffic_sources', data.traffic_source_id, 'источник'),
    ]:
        options = expect_list(client.get(endpoint, params={'type': 'campaigns'} if endpoint == 'groups' else None), label)
        if not any(isinstance(item, dict) and item.get('id') == id_ and item.get('state') != 'deleted' for item in options):
            raise DomainError(422, f'Не найден {label} с ID {id_} или объект недоступен.')


def resolve_campaign_settings(settings: Settings, data: CampaignCreate) -> CampaignCreate:
    """Merge optional form overrides with explicit server defaults (never API guesses).

    Missing IDs block preview and creation before any remote write. Values supplied
    by the user cannot silently override the requirement that an object exists.
    """
    resolved = {
        'domain_id': data.domain_id if data.domain_id is not None else settings.campaign_domain_id,
        'group_id': data.group_id if data.group_id is not None else settings.campaign_group_id,
        'traffic_source_id': (data.traffic_source_id if data.traffic_source_id is not None
                              else settings.campaign_traffic_source_id),
    }
    labels = {'domain_id': 'домен', 'group_id': 'группа', 'traffic_source_id': 'источник трафика'}
    missing = [labels[k] for k, value in resolved.items() if value is None]
    if missing:
        raise DomainError(422, 'Не настроены: ' + ', '.join(missing) +
                          '. Укажите их в дополнительных параметрах или в .env. '
                          'Автоматически выбирать чужие объекты нельзя.')
    return CampaignCreate.model_validate({**data.model_dump(), **resolved})


def preview(client: KeitaroClient, settings: Settings, data: CampaignCreate) -> dict:
    require_owned_name(settings, data.name)
    data = resolve_campaign_settings(settings, data)
    _check_exists(client, data)
    plan = build_plan(data, 'alias-will-be-generated', 'marker-will-be-generated')
    return {
        'write_enabled': settings.keitaro_write_enabled,
        'campaign': plan.campaign,
        'selected_configuration': {
            'domain_id': data.domain_id, 'group_id': data.group_id,
            'traffic_source_id': data.traffic_source_id,
        },
        'streams': [plan.google_stream, plan.offers_stream],
        'notice': 'Предпросмотр безопасен: только GET-запросы. POST/PUT не выполнялись.',
    }


def create_campaign(db: Session, client: KeitaroClient, settings: Settings, data: CampaignCreate) -> dict:
    require_writes(settings)
    require_owned_name(settings, data.name)
    data = resolve_campaign_settings(settings, data)
    _check_exists(client, data)  # All preflight checks happen before first POST.
    marker = 'keitaro-wrapper-owner:' + uuid.uuid4().hex
    alias = data.name[:65] + '_' + uuid.uuid4().hex[:8]
    plan = build_plan(data, alias, marker)
    # IMPORTANT: From this point there can be partial writes to *new* Keitaro objects.
    response = client.create_campaign(plan.campaign)
    campaign_id = extract_id(response)
    owned = OwnedCampaign(
        id=campaign_id, instance_url=settings.keitaro_base_url,
        name=data.name, alias=alias, owner_marker=marker, status='creating',
    )
    db.add(owned)
    db.add(AuditLog(campaign_id=campaign_id, action='created_disabled', details='Campaign ID recorded before any stream changes'))
    db.commit()

    activated = False
    try:
        google_body = dict(plan.google_stream, campaign_id=campaign_id)
        google_id = extract_id(client.create_stream(google_body))
        owned.geo_stream_id = google_id
        db.add(AuditLog(campaign_id=campaign_id, action='google_stream_created', details=str(google_id)))
        db.commit()

        offers_body = dict(plan.offers_stream, campaign_id=campaign_id)
        offers_id = extract_id(client.create_stream(offers_body))
        owned.offers_stream_id = offers_id
        db.add(AuditLog(campaign_id=campaign_id, action='offers_stream_created', details=str(offers_id)))
        db.commit()

        remote = client.get_campaign(campaign_id)
        streams = expect_list(client.get_streams(campaign_id), 'потоков')
        if not _matches_identity(remote, owned):
            raise DomainError(409, 'Настройки кампании изменились: автоактивация остановлена.')
        if len(streams) != 2 or {x.get('id') for x in streams} != {google_id, offers_id}:
            raise DomainError(409, 'Набор потоков не совпадает: автоактивация остановлена.')
        by_id = {x['id']: x for x in streams}
        if by_id[google_id].get('type') != 'forced' or by_id[google_id].get('schema') != 'redirect':
            raise DomainError(409, 'GEO-поток имеет неожиданную схему.')
        off = by_id[offers_id]
        if off.get('type') != 'default' or off.get('schema') != 'landings' or not any(
            x.get('offer_id') == data.offer_id for x in (off.get('offers') or [])
        ):
            raise DomainError(409, 'Поток офферов не прошёл проверку.')
        # Read back the configured filter and URL. Fail closed if unexpected.
        geo = by_id[google_id]
        def contains_country(f):
            payload = f.get('payload')
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = [payload]
            return f.get('name') == 'country' and f.get('mode') == 'accept' and data.country in (payload or [])
        if not any(contains_country(f) for f in (geo.get('filters') or [])) or geo.get('action_payload') != GOOGLE_URL:
            raise DomainError(409, 'GEO-фильтр/Google URL не совпадают: автоактивация остановлена.')
        client.activate_campaign(campaign_id)
        activated = True
        owned.status = 'ready'
        db.add(AuditLog(campaign_id=campaign_id, action='activated', details='Both streams verified before activation'))
        db.commit()
        return {'id': campaign_id, 'name': data.name, 'status': 'ready', 'geo_stream_id': google_id, 'offers_stream_id': offers_id}
    except Exception as exc:
        # NEVER DELETE, ARCHIVE, or TOUCH other campaigns to compensate for a failure.
        owned.status = 'failed'
        owned.error = ('Активация могла завершиться, но локальная фиксация дала сбой.' if activated else
                       'Создание не завершено. Проверьте отключённую кампанию; автоматической очистки нет.')
        db.add(AuditLog(campaign_id=campaign_id, action='creation_failed', details=type(exc).__name__))
        db.commit()
        status_note = 'Возможна активация; проверьте статус вручную' if activated else 'Кампания создана в отключённом состоянии'
        raise DomainError(502, f'Кампания ID {campaign_id}: {status_note}. Настройка не завершена. Удаление не выполнялось.') from exc


def _matches_identity(remote: dict, owned: OwnedCampaign) -> bool:
    return (
        isinstance(remote, dict)
        and remote.get('id') == owned.id
        and remote.get('name') == owned.name
        and remote.get('alias') == owned.alias
        and remote.get('notes') == owned.owner_marker
        and remote.get('state') != 'deleted'
    )


def revision(offers: list) -> str:
    canonical = sorted(({
        'offer_id': x.get('offer_id'), 'share': x.get('share'), 'state': x.get('state') or 'active',
    } for x in offers), key=lambda x: x['offer_id'])
    return sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _owned_row(db: Session, settings: Settings, campaign_id: int, lock: bool = False) -> OwnedCampaign:
    statement = select(OwnedCampaign).where(OwnedCampaign.id == campaign_id)
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None or row.instance_url != settings.keitaro_base_url or not row.name.startswith(settings.campaign_prefix):
        raise DomainError(403, 'Чужая или незарегистрированная кампания: редактирование запрещено.')
    if row.status != 'ready':
        raise DomainError(409, 'Эта кампания не готова к редактированию (статус не ready).')
    return row


def _verified_stream(client: KeitaroClient, owned: OwnedCampaign) -> dict:
    if not owned.geo_stream_id or not owned.offers_stream_id:
        raise DomainError(409, 'В БД отсутствуют ID собственных потоков.')
    remote = client.get_campaign(owned.id)
    if not _matches_identity(remote, owned):
        raise DomainError(409, 'Кампания изменена или не принадлежит этому приложению. Запись заблокирована.')
    streams = expect_list(client.get_streams(owned.id), 'потоков')
    if len(streams) != 2 or {x.get('id') for x in streams} != {owned.geo_stream_id, owned.offers_stream_id}:
        raise DomainError(409, 'Состав потоков изменён извне; автоматическое редактирование запрещено.')
    stream = client.get_stream(owned.offers_stream_id)
    if (
        not isinstance(stream, dict)
        or stream.get('id') != owned.offers_stream_id
        or stream.get('campaign_id') != owned.id
        or stream.get('type') != 'default'
        or stream.get('schema') != 'landings'
        or not isinstance(stream.get('offers'), list)
    ):
        raise DomainError(409, 'Поток офферов не соответствует сохранённой схеме.')
    return stream


def campaign_detail(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int) -> dict:
    remote = client.get_campaign(campaign_id)
    streams = expect_list(client.get_streams(campaign_id), 'потоков')
    owned = db.get(OwnedCampaign, campaign_id)
    can_edit = bool(owned and owned.instance_url == settings.keitaro_base_url and
                    owned.status == 'ready' and owned.name.startswith(settings.campaign_prefix) and
                    _matches_identity(remote, owned) and owned.offers_stream_id and
                    len(streams) == 2 and {s.get('id') for s in streams} ==
                    {owned.geo_stream_id, owned.offers_stream_id})
    offers_stream = next((s for s in streams if owned and s.get('id') == owned.offers_stream_id), None)
    offers = offers_stream.get('offers') if offers_stream else []
    return {
        'id': campaign_id,
        'name': remote.get('name') if isinstance(remote, dict) else '',
        'status': remote.get('state') if isinstance(remote, dict) else '',
        'streams': [{'id': s.get('id'), 'name': s.get('name'), 'type': s.get('type'),
                     'schema': s.get('schema'), 'offers': s.get('offers') or []} for s in streams],
        'can_edit': can_edit,
        'revision': revision(offers or []) if offers_stream else None,
        'owned_status': owned.status if owned else None,
        'notice': 'Редактирование разрешено только для кампаний, созданных этим приложением.' if not can_edit else '',
    }


