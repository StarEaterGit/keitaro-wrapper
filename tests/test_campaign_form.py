"""The UI sends full prefixed names without weakening server-side validation."""
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.config import Settings
from app.schemas import CampaignCreate

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"
HTML = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
JS = (ROOT / 'app/static/app.js').read_text(encoding='utf-8')


def test_prefix_is_read_only_and_suffix_is_editable():
    assert 'id="name-prefix"' in HTML
    assert 'id="name-suffix"' in HTML
    assert 'id="full-name"' in HTML
    assert 'id="name" type="hidden"' in HTML
    assert 'function syncCampaignName(' in JS
    assert "$('name').value=full;" in JS
    assert 'if(suffix.startsWith(prefix))' in JS
    assert "validateCampaignFields()" in JS


def test_backend_expects_complete_name_and_validates_full_prefix():
    Settings(campaign_prefix='test_yakimenkoVS_')
    payload = CampaignCreate(name='test_yakimenkoVS_campaign1', country='DE', offer_id=18813)
    assert payload.name == 'test_yakimenkoVS_campaign1'
    try:
        CampaignCreate(name='test_yakimenkoVS_камапания', country='DE', offer_id=18813)
        assert False, 'Invalid full name accepted'
    except ValidationError:
        pass


def test_only_one_documentation_file():
    docs = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('*.md') if '.pytest_cache' not in p.parts)
    assert docs == ['README.md']
    assert not list(ROOT.rglob('preview*.png'))


def test_create_form_has_exactly_one_searchable_offer_field():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert html.count('id="offer-query"') == 1
    assert 'role="combobox"' in html
    assert 'aria-controls="offer-options"' in html
    assert 'id="offer_pick"' not in html
    assert 'id="verify-offer"' not in html
    assert 'id="offer_id"' in html  # hidden, canonical ID sent to the API


def test_combobox_can_resolve_exact_id_not_returned_in_short_list():
    js = (STATIC / 'app.js').read_text(encoding='utf-8')
    assert '/api/offers/${item.id}/lookup' in js
    assert "$('offer_id').value=validOfferId(raw)?raw:''" in js
    assert '/api/preview' in js


def test_three_user_inputs_are_required_and_advanced_ids_are_optional_in_the_form():
    form = CampaignCreate(name='test_yakimenkoVS_campaign1', country='DE', offer_id=18813)
    assert form.domain_id is None and form.group_id is None and form.traffic_source_id is None
    with pytest.raises(ValidationError):
        CampaignCreate(name='test_yakimenkoVS_campaign1', country='DE', offer_id=0)
    with pytest.raises(ValidationError):
        CampaignCreate(name='test_yakimenkoVS_campaign1', country='DE', offer_id=18813, domain_id=0)
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert '<details id="advanced-settings"' in html
    assert 'id="settings-status"' in html
    assert '<select id="domain_id" required' not in html


def test_single_submit_validates_inline_and_previews_before_remote_creation():
    assert 'id="campaign-form" novalidate' in HTML
    assert HTML.count('id="create-button"') == 1
    assert 'id="preview-card"' not in HTML
    assert 'Проверить параметры</button>' not in HTML
    for error_id in ('country-error', 'offer-error', 'domain-error', 'group-error', 'source-error'):
        assert f'id="{error_id}"' in HTML
    assert 'function validateCampaignFields()' in JS
    assert "fieldError('country'" in JS
    assert "fieldError('offer_id'" in JS
    assert "const plan=await post('/api/preview',data);" in JS
    assert 'if(!answer)return;' in JS
    assert "const result=await post('/api/campaigns',data);" in JS
    assert 'if(createBusy||createBlocked)return;' in JS
    assert 'createBlocked=true;' in JS
