import json

import pytest

from locqa.arb import load_arb
from locqa._load import read_arb
from locqa.cli import main
from locqa.fix import apply_decisions
from locqa.llm import LLM
from scripts.translit_kk import main as transliterate


def test_all_loaders_support_bom_and_effective_duplicate_order(tmp_path):
    path = tmp_path/'input.arb'
    path.write_text('\ufeff{"a":"old","b":"B","a":"new","@a":{"examples":[]}}')
    doc = load_arb(path)
    assert doc.order == ['a', 'b']
    assert doc.values == {'a': 'new', 'b': 'B'}
    assert read_arb(path)[:2] == (doc.values, doc.order)
    assert doc.meta['a']['examples'] == []


@pytest.mark.parametrize('payload', ['[]', '{"k":42}', '{"k":null}', '{"k":{}}'])
def test_invalid_arb_types_fail_instead_of_becoming_translations(tmp_path, payload):
    path = tmp_path/'input.arb'; path.write_text(payload)
    with pytest.raises(ValueError):
        load_arb(path)


def test_fix_missing_source_does_not_overwrite_output(tmp_path):
    target = tmp_path/'target.arb'; target.write_text('{"k":"old"}')
    out = tmp_path/'out.arb'; out.write_text('previous result')
    with pytest.raises(FileNotFoundError):
        apply_decisions(tmp_path/'decisions.csv', target, out, tmp_path/'missing.arb')
    assert out.read_text() == 'previous result'


@pytest.mark.parametrize('option', ['--en', '--uz', '--glossary'])
def test_explicit_missing_reference_is_an_error(tmp_path, option):
    source = tmp_path/'ru.arb'; source.write_text('{"k":"Hello"}')
    with pytest.raises(FileNotFoundError):
        main(['check', '--source', str(source), '--target', str(source),
              option, str(tmp_path/'missing'), '--no-llm', '--out', str(tmp_path/'out.json')])
    assert not (tmp_path/'out.json').exists()


def test_no_llm_has_priority_over_offline_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCQA_OFFLINE', '1')
    llm = LLM(enabled=False, cache_dir=tmp_path)
    assert not llm.enabled


def test_transliteration_handles_compact_arb_and_new_directories(tmp_path):
    source = tmp_path/'kk.arb'
    source.write_text(json.dumps({'@@locale': 'kk', 'k': 'Қазақстан {name}',
                                 '@k': {'description': 'Қазақша'}}))
    out = tmp_path/'new/result.arb'; report = tmp_path/'reports/growth.csv'
    transliterate([str(source), '--out', str(out), '--report', str(report)])
    result = json.loads(out.read_text())
    assert result['k'] == 'Qazaqstan {name}'
    assert result['@k']['description'] == 'Қазақша'
    assert result['@@locale'] == 'kk'
    assert report.is_file()
