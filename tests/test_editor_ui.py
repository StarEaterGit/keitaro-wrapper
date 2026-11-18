"""UI regression checks for the manual offer editor and isolated demo."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'app/static/index.html').read_text(encoding='utf-8')
JS=(ROOT/'app/static/app.js').read_text(encoding='utf-8')


def test_no_separate_safety_navigation_and_single_editor_offer_input():
    assert 'data-tab="about"' not in HTML
    assert 'id="about"' not in HTML
    assert 'id="editor-offer-query"' in HTML
    assert 'id="editor-offer-combobox"' in HTML
    assert 'id="editor-offer-options"' in HTML
    assert 'id="offer-search"' not in HTML
    assert 'id="offer-results"' not in HTML
    assert 'id="editor-offer-id"' not in HTML


def test_demo_is_not_remote_editor_and_visible_as_demo():
    assert 'id="demo-start"' in HTML
    assert 'id="demo-alert"' in HTML
    assert 'id="demo-exit"' in HTML
    assert 'if(demoMode){demoStage(' in JS
    assert 'if(demoMode){demoCancel();return;}' in JS
    assert 'if(demoMode){demoPush();return;}' in JS
    assert 'if(demoMode){demoFetch();return;}' in JS
    assert 'Демо · изменения только в браузере' in HTML


def test_editor_has_only_three_useful_columns():
    assert "['Оффер','Доля','Действие']" in JS
    assert 'Share / Stats / Trends / Actions' not in HTML
    assert 'Share — доля распределения трафика' not in HTML
    assert "element('td','—'),element('td','—')" not in JS


def test_manual_demo_without_guided_scenarios():
    assert 'Сценарии из видео' not in HTML
    assert 'id="scenario-panel"' not in HTML
    assert 'demoScenarioTo' not in JS
    assert 'id="demo-reset"' in HTML
    assert 'id="add-offer"' in HTML
    assert 'id="editor-offer-query"' in HTML
    assert 'id="push-editor"' in HTML
    assert 'id="cancel-editor"' in HTML
    assert 'id="demo-remote-remove"' in HTML
    assert "['Оффер','Доля','Действие']" in JS
    assert "if(demoMode){demoFetch();return;}" in JS


def test_real_editor_remains_protected():
    assert "if(demoMode){demoStage(action,offer_id,extra);return;}" in JS
    assert "if(demoMode){demoPush();return;}" in JS
    assert "if(demoMode){demoFetch();return;}" in JS
    assert "if(!draft||!current||!current.can_edit)return;" in JS
