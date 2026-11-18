"""Video-spec stream editor: local draft -> explicit Push to Keitaro.

Only Keitaro-owned campaigns and the one registered offers stream can be modified.
Local draft methods NEVER call Keitaro POST/PUT/DELETE.
"""
import copy
import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, StreamDraft
from app.services.campaigns import (
    DomainError, _owned_row, _verified_stream, require_writes, revision,
)
from app.services.keitaro import KeitaroClient


def _loads(value: str) -> list[dict]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise DomainError(500, 'В локальной базе повреждён список офферов.')
    return loaded


def _json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, separators=(',', ':'))


def _validate_remote(offers: list) -> list[dict]:
    """Normalize API's offer items without treating remote disabled as removed."""
    rows = []
    seen = set()
    for item in offers:
        if not isinstance(item, dict) or not isinstance(item.get('offer_id'), int) or not isinstance(item.get('share'), int):
            raise DomainError(502, 'Keitaro вернул неожиданную структуру офферов.')
        id_ = item['offer_id']
        if id_ <= 0 or id_ in seen or item['share'] < 0:
            raise DomainError(502, 'В списке Keitaro есть повтор или неверный вес оффера.')
        state = item.get('state') or 'active'
        if state not in ('active', 'disabled'):
            raise DomainError(502, 'Неподдерживаемое состояние оффера. Изменение заблокировано.')
        rows.append({'offer_id': id_, 'share': item['share'], 'state': state, 'removed': False, 'pinned': False})
        seen.add(id_)
    return rows


def _rebalance(rows: list[dict]) -> None:
    """Keep pins intact; distribute remaining integer percentages deterministically."""
    active = [r for r in rows if not r['removed'] and r['state'] == 'active']
    free = [r for r in active if not r['pinned']]
    pinned_total = sum(r['share'] for r in active if r['pinned'])
    if pinned_total > 100:
        raise DomainError(422, 'Закреплённые доли в сумме превышают 100%.')
    remaining = 100 - pinned_total
    if active and not free and remaining:
        raise DomainError(422, 'Невозможно распределить 100%: все доли закреплены и сумма не равна 100%. Снимите одно закрепление.')
    if free and remaining < len(free):
        raise DomainError(422, 'Слишком много офферов или слишком высокие закреплённые доли: свободным офферам нужно хотя бы 1%.')
    if free:
        base, extra = divmod(remaining, len(free))
        for i, r in enumerate(free):
            r['share'] = base + (1 if i < extra else 0)
    for row in rows:
        if row['removed']:
            row['share'] = 0


def _get_row(db: Session, campaign_id: int, stream_id: int, lock=False) -> StreamDraft | None:
    stmt = select(StreamDraft).where(StreamDraft.campaign_id == campaign_id, StreamDraft.stream_id == stream_id)
    if lock:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _owned_stream(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, lock=True):
    owned = _owned_row(db, settings, campaign_id, lock=lock)
    stream = _verified_stream(client, owned)
    return owned, stream


def _view(row: StreamDraft, stream: dict | None = None) -> dict:
    return {
        'campaign_id': row.campaign_id,
        'stream_id': row.stream_id,
        'version': row.version,
        'dirty': row.dirty,
        'rows': _loads(row.draft_json),
        'remote_revision': row.base_revision,
        'stream_name': stream.get('name', 'Offers') if stream else 'Offers',
        'notice': ('Жёлтый черновик — Keitaro пока НЕ изменён.' if row.dirty else 'Данные синхронизированы; неопубликованных изменений нет.'),
    }


def fetch_streams(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int):
    """FETCH STREAMS FROM KT; read-only towards Keitaro and preserve removed history."""
    owned, stream = _owned_stream(db, client, settings, campaign_id)
    row = _get_row(db, campaign_id, owned.offers_stream_id, lock=True)
    if row and row.dirty:
        raise DomainError(409, 'Есть неопубликованные изменения. Сначала Push to KT или Cancel, затем повторите Fetch.')
    remote_rows = _validate_remote(stream['offers'])
    last = _loads(row.published_json) if row else []
    previous = {x['offer_id']: x for x in last}
    incoming = {x['offer_id'] for x in remote_rows}
    # Pin remains local metadata, except when a remote edit changed its share.
    for r in remote_rows:
        old = previous.get(r['offer_id'])
        if old and not old['removed'] and old['state'] == r['state'] and old['share'] == r['share']:
            r['pinned'] = old['pinned']
    for old in last:
        if old['offer_id'] not in incoming:
            remote_rows.append(dict(old, removed=True, share=0, pinned=False))
    payload = _json(remote_rows)
    if row is None:
        row = StreamDraft(
            campaign_id=campaign_id, stream_id=owned.offers_stream_id,
            published_json=payload, draft_json=payload, base_revision=revision(stream['offers']),
            version=1, dirty=False,
        )
        db.add(row)
    else:
        row.published_json = payload
        row.draft_json = payload
        row.base_revision = revision(stream['offers'])
        row.version += 1
        row.dirty = False
    db.add(AuditLog(campaign_id=campaign_id, action='fetch_streams', details=f'stream_id={owned.offers_stream_id}; local only'))
    db.commit()
    return _view(row, stream)


def view_draft(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int):
    """Read local draft; first open is a safe read-only FETCH from Keitaro."""
    owned, stream = _owned_stream(db, client, settings, campaign_id, lock=False)
    row = _get_row(db, campaign_id, owned.offers_stream_id)
    if row is None:
        return fetch_streams(db, client, settings, campaign_id)
    return _view(row, stream)


def _edit(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, version: int,
          operation: Literal['add', 'remove', 'restore', 'pin'], offer_id: int, pinned: bool | None = None):
    """Local DB only; validates ownership before accepting edits, but never writes upstream."""
    # Local draft mutations NEVER write to Keitaro. The write switch only guards remote POST/PUT.
    owned, _ = _owned_stream(db, client, settings, campaign_id)
    row = _get_row(db, campaign_id, owned.offers_stream_id, lock=True)
    if row is None:
        raise DomainError(409, 'Сначала нажмите Fetch streams from KT.')
    if version != row.version:
        raise DomainError(409, 'Черновик изменился в другой вкладке. Обновите страницу.')
    rows = _loads(row.draft_json)
    target = next((r for r in rows if r['offer_id'] == offer_id), None)
    if operation == 'add':
        if target:
            raise DomainError(409, 'Оффер уже есть в истории потока. Используйте Bring back, если он удалён.')
        offer = client.get_offer(offer_id)
        if not isinstance(offer, dict) or offer.get('id') != offer_id or offer.get('state') == 'deleted':
            raise DomainError(422, 'Оффер отсутствует или архивирован в Keitaro.')
        rows.append({'offer_id': offer_id, 'share': 0, 'state': 'active', 'removed': False, 'pinned': False})
    else:
        if target is None:
            raise DomainError(404, 'Оффер не найден в черновике.')
        if operation == 'remove':
            if target['removed']:
                raise DomainError(409, 'Оффер уже удалён из черновика.')
            target['removed'], target['pinned'] = True, False
        elif operation == 'restore':
            if not target['removed']:
                raise DomainError(409, 'Оффер уже активен в черновике.')
            offer = client.get_offer(offer_id)
            if not isinstance(offer, dict) or offer.get('id') != offer_id or offer.get('state') == 'deleted':
                raise DomainError(422, 'Оффер удалён из глобального списка Keitaro.')
            target['removed'], target['pinned'], target['state'] = False, False, 'active'
        elif operation == 'pin':
            if target['removed'] or target['state'] != 'active':
                raise DomainError(409, 'Можно закреплять только доли активных офферов.')
            target['pinned'] = bool(pinned)
        else:
            raise DomainError(400, 'Неизвестная операция.')
    _rebalance(rows)  # can raise before we commit; draft untouched on failure
    row.draft_json = _json(rows)
    row.dirty = (row.draft_json != row.published_json)
    row.version += 1
    db.add(AuditLog(campaign_id=campaign_id, action='stage_' + operation, details=f'offer_id={offer_id}; local only'))
    db.commit()
    return _view(row)


def stage_add(db, client, settings, campaign_id, version, offer_id):
    return _edit(db, client, settings, campaign_id, version, 'add', offer_id)


def stage_remove(db, client, settings, campaign_id, version, offer_id):
    return _edit(db, client, settings, campaign_id, version, 'remove', offer_id)


def stage_restore(db, client, settings, campaign_id, version, offer_id):
    return _edit(db, client, settings, campaign_id, version, 'restore', offer_id)


def stage_pin(db, client, settings, campaign_id, version, offer_id, pinned):
    return _edit(db, client, settings, campaign_id, version, 'pin', offer_id, pinned)


def cancel(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, version: int):
    # Cancel discards local changes only; do not require remote write access.
    owned, _ = _owned_stream(db, client, settings, campaign_id)
    row = _get_row(db, campaign_id, owned.offers_stream_id, lock=True)
    if row is None or row.version != version:
        raise DomainError(409, 'Черновик отсутствует или изменился. Обновите страницу.')
    row.draft_json = row.published_json
    row.dirty = False
    row.version += 1
    db.add(AuditLog(campaign_id=campaign_id, action='cancel_draft', details='local only'))
    db.commit()
    return _view(row)


def push(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, version: int):
    """The ONLY editor operation allowed to PUT in Keitaro."""
    require_writes(settings)
    owned, remote_stream = _owned_stream(db, client, settings, campaign_id)
    row = _get_row(db, campaign_id, owned.offers_stream_id, lock=True)
    if row is None or version != row.version:
        raise DomainError(409, 'Черновик отсутствует или изменился. Обновите страницу.')
    if not row.dirty:
        raise DomainError(409, 'Нет изменений для публикации.')
    # Re-read live before any PUT. Avoid overwriting manual or concurrent remote edits.
    if revision(remote_stream['offers']) != row.base_revision:
        raise DomainError(409, 'Keitaro изменился после Fetch. Push заблокирован. Cancel → Fetch для получения актуального состояния.')
    rows = _loads(row.draft_json)
    _rebalance(rows)
    items = [{'offer_id': r['offer_id'], 'share': r['share'], 'state': r['state']}
             for r in rows if not r['removed']]
    if not items or not any(x['state'] == 'active' for x in items):
        raise DomainError(422, 'Нельзя опубликовать поток без активных офферов.')
    if sum(x['share'] for x in items if x['state'] == 'active') != 100:
        raise DomainError(422, 'Сумма долей активных офферов должна быть 100%.')
    # No DELETE operations and no updates to any other stream.
    client.replace_stream_offers(owned.offers_stream_id, items)
    actual = client.get_stream(owned.offers_stream_id)
    if not isinstance(actual, dict) or not isinstance(actual.get('offers'), list) or revision(actual['offers']) != revision(items):
        # Keep dirty state, so operator can safely inspect the tracker before retrying.
        raise DomainError(502, 'Keitaro не подтвердил результат после PUT. Проверьте поток непосредственно в Keitaro перед новым Push.')
    row.base_revision = revision(actual['offers'])
    row.published_json = _json(rows)  # removed entries persist as gray archive!
    row.draft_json = row.published_json
    row.dirty = False
    row.version += 1
    db.add(AuditLog(campaign_id=campaign_id, action='pushed_stream', details=f'stream_id={owned.offers_stream_id}; only offers changed'))
    db.commit()
    return _view(row)
