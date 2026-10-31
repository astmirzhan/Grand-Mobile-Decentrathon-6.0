import csv
import json

import pytest

from locqa.arb import load_arb, update_arb_file
from locqa.fix import apply_decisions
from locqa.icu import extract_placeholders, validate_plural
from locqa.sheet import load_decisions
from locqa.validation import validate_files, validate_text
from scripts.validate_flutter import resource_mapping


@pytest.mark.parametrize('compact', [False, True])
def test_arb_update_handles_full_metadata_and_preserves_sections(tmp_path, compact):
    src = tmp_path/'target.arb'
    text = '''{
  "@@comment": "first",
  "a": "old",
  "@a": {
    "description": "keep",
    "placeholders": {"name": {"type": "String"}}
  },
  "@@comment": "second",
  "b": "untouched"
}'''
    if compact:
        text = text.replace('\n', '').replace('  ', '')
    src.write_text(text)
    doc = load_arb(src)
    meta = {**doc.meta['a'], 'x-reviewed': True}
    out = tmp_path/'fixed.arb'
    update_arb_file(src, out, {'a': 'new', 'missing': 'inserted'}, ['a', 'missing', 'b'], {'a': meta})
    fixed = load_arb(out)
    assert fixed.values == {'a': 'new', 'missing': 'inserted', 'b': 'untouched'}
    assert fixed.order == ['a', 'missing', 'b']
    assert fixed.meta['a']['placeholders']['name']['type'] == 'String'
    assert [v for k, v in fixed.raw_pairs if k == '@@comment'] == ['first', 'second']
    update_arb_file(out, out, {'a': 'again'}, review_meta={'a': meta})
    assert load_arb(out).values['a'] == 'again'
    assert sum(k == '@a' for k, _ in load_arb(out).raw_pairs) == 1


@pytest.mark.parametrize('text', [
    '{n, plural, one {бір}}',
    '{n, plural, other {зат} rubbish}',
    '{n, plural, other {бір} other {екі}}',
    '{n, plural, wrong {бір} other {екі}}',
    '{gender, select, male {{n, plural, one {бір}}} other {адам}}',
])
def test_invalid_icu_rejected(text):
    assert validate_plural(text)


def test_valid_icu_and_apostrophes():
    assert not validate_plural('{n, plural, other {# зат}}')
    assert not validate_plural('{n, plural, offset:1 =0 {жоқ} other {# зат}}')
    assert extract_placeholders("Player's {name}") == {'name'}
    assert extract_placeholders("'{'literal'}' {name}") == {'name'}


def test_fix_rejects_icu_tags_and_printf_without_losing_existing_output(tmp_path):
    source = tmp_path/'ru.arb'; target = tmp_path/'kk.arb'; out = tmp_path/'fixed.arb'
    values = {'p': '{n, plural, other {# items}}', 'tag': '<g>word</g>', 'printf': '%s level', 'empty': ''}
    source.write_text(json.dumps(values)); target.write_text(json.dumps(values))
    decisions = tmp_path/'decisions.csv'
    with decisions.open('w') as f:
        w = csv.DictWriter(f, fieldnames=['key', 'final_text', 'reviewer']);w.writeheader()
        for key, text in [('p', '{n, plural, one {бір}}'), ('tag', 'word'), ('printf', 'деңгей'), ('empty', '{extra}')]:
            w.writerow({'key': key, 'final_text': text, 'reviewer': 'test'})
    assert apply_decisions(decisions, target, out, source) == (0, 4)
    assert load_arb(out).values == values


def test_preserve_review_text_boundary_spaces(tmp_path):
    path = tmp_path/'review.csv'
    with path.open('w') as f:
        w = csv.DictWriter(f, fieldnames=['key', 'решение', 'итоговый_текст']);w.writeheader()
        w.writerow({'key': 'k', 'решение': '✏', 'итоговый_текст': ' мәтін '})
    decisions, warnings = load_decisions([path], {'k': ' text '})
    assert warnings == [] and decisions[0]['final_text'] == ' мәтін '


def test_complete_file_validation_catches_unmodified_bad_parameter(tmp_path):
    source = tmp_path/'ru.arb';target = tmp_path/'kk.arb'
    source.write_text(json.dumps({'k': '{platformColor}'}))
    target.write_text(json.dumps({'k': '{platformColo}'}))
    assert not validate_files(source, target)['valid']
    assert validate_text('{name} {name}', '{name}')


def test_flutter_mapping_detects_collision(tmp_path):
    path = tmp_path/'file.arb'
    path.write_text(json.dumps({'Upper': 'a', 'upper': 'b'}))
    with pytest.raises(ValueError, match='collides'):
        resource_mapping([load_arb(path)])


def test_metadata_empty_array_is_not_converted_to_object(tmp_path):
    path = tmp_path/'meta.arb'
    path.write_text('{"k":"x","@k":{"examples":[],"placeholders":{}}}')
    doc = load_arb(path)
    assert doc.meta['k']['examples'] == []
    assert doc.meta['k']['placeholders'] == {}


def test_finalize_retains_native_labels_and_separates_agent_edits(tmp_path):
    from scripts.finalize import run
    source = tmp_path/'ru.arb';target = tmp_path/'kk.arb'
    source.write_text(json.dumps({'native': 'Слово', 'agent': '{name}'}))
    target.write_text(json.dumps({'native': 'Қате', 'agent': '{typo}'}))
    review = tmp_path/'review.csv'
    fields = ['id', 'key', 'issue_type', 'severity', 'ru', 'kk_сейчас', 'suggestion',
              'решение', 'итоговый_текст', 'кто_проверил', 'verdict']
    with review.open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        w.writerow(dict(id='1',key='native',issue_type='orthography',severity='medium',ru='Слово',
            kk_сейчас='Қате',suggestion='Сөз',решение='✅',кто_проверил='A',verdict='1'))
        w.writerow(dict(id='2',key='agent',issue_type='placeholder_mismatch',severity='high',ru='{name}',
            kk_сейчас='{typo}',suggestion='{name}',решение='❌',кто_проверил='A',verdict='0'))
    original = review.read_bytes()
    overrides = tmp_path/'overrides.json'
    overrides.write_text(json.dumps([dict(key='agent',text='{name}',issue_type='placeholder_mismatch',reason='technical')]))
    result = run(source,target,[review],tmp_path/'final',overrides_path=overrides)
    assert result['structural']['valid']
    fixed=load_arb(tmp_path/'final/intl_kk_fixed.arb')
    assert fixed.meta['native']['x-reviewed'] is True
    assert fixed.meta['agent']['x-reviewed'] is False
    assert review.read_bytes() == original
    metrics=json.loads((tmp_path/'final/metrics.json').read_text())
    assert metrics['all_candidates']['total']['precision_labelled'] == .5
    corrections = json.loads(overrides.read_text())
    corrections[0]['human_confirmation'] = {
        'reviewer': 'native_1', 'text': '{name}', 'date': '2026-10-31',
        'evidence': 'Explicit confirmation by the original native reviewer',
    }
    overrides.write_text(json.dumps(corrections))
    confirmed = run(source, target, [review], tmp_path/'confirmed', overrides_path=overrides)
    assert confirmed['structural']['human_reviewed_changes'] == 2
    assert confirmed['structural']['unreviewed_changes'] == 0
    assert confirmed['agent_corrections_confirmed_by_native'] == 1
    assert load_arb(tmp_path/'confirmed/intl_kk_fixed.arb').meta['agent']['x-reviewer'] == 'native_1'
    assert (tmp_path/'confirmed/metrics.json').read_bytes() == (tmp_path/'final/metrics.json').read_bytes()
    assert review.read_bytes() == original
    overrides.write_text(json.dumps(corrections + corrections))
    with pytest.raises(ValueError, match='Duplicate override'):
        run(source, target, [review], tmp_path/'duplicate_override', overrides_path=overrides)
    corrections[0]['text'] = 'Changed {name}'
    overrides.write_text(json.dumps(corrections))
    with pytest.raises(ValueError, match='Invalid human confirmation'):
        run(source, target, [review], tmp_path/'stale', overrides_path=overrides)
    with pytest.raises(ValueError, match='Duplicate review'):
        run(source,target,[review,review],tmp_path/'duplicate')


def test_signal_number_words_and_loanwords_do_not_hide_real_errors():
    from locqa.models import Context
    from locqa.checks import basic, signals
    ctx=Context(ru={'good':'4 игрока','bad':'4 игрока'},kk={'good':'төрт ойыншы','bad':'үш ойыншы'},order=['good','bad'])
    assert [f.key for f in signals.number_mismatch(ctx)] == ['bad']
    ctx=Context(ru={'balance':'БАЛАНС','bad':'Шоколад готов'},kk={'balance':'БАЛАНС','bad':'Шоколад готов'},order=['balance','bad'])
    assert [f.key for f in basic.check(ctx)] == ['bad']


def test_missing_first_key_uses_source_order(tmp_path):
    target=tmp_path/'target.arb';out=tmp_path/'out.arb'
    target.write_text('{"@@comment":"section","b":"B"}')
    update_arb_file(target,out,{'a':'A'},['a','b'])
    assert load_arb(out).order == ['a','b']


def test_baseline_capabilities_are_declared_instead_of_assumed():
    from scripts.compare_baselines import tools
    declared=tools()
    assert len(declared['basic rules'][1]) == 6
    assert len(declared['locqa, no LLM'][1]) == 11


def test_failed_finalization_does_not_replace_previous_result(tmp_path):
    from scripts.finalize import run
    source=tmp_path/'ru.arb';target=tmp_path/'kk.arb';review=tmp_path/'review.csv'
    source.write_text('{"k":"{name}"}');target.write_text('{"k":"{wrong}"}')
    fields=['key','issue_type','severity','ru','kk_сейчас','suggestion','решение','verdict']
    with review.open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        w.writerow({'key':'k','issue_type':'placeholder_mismatch','severity':'high','ru':'{name}',
                    'kk_сейчас':'{wrong}','suggestion':'','решение':'❌','verdict':'0'})
    final=tmp_path/'final';final.mkdir();(final/'sentinel').write_text('previous good build')
    with pytest.raises(ValueError, match='full-file validation'):
        run(source,target,[review],final)
    assert (final/'sentinel').read_text() == 'previous good build'


def test_fix_cannot_silently_remove_or_change_source_plural():
    source='{n, plural, one {one} other {many}}'
    assert validate_text(source,'{n} зат')
    assert validate_text(source,'{n, select, other {зат}}')
    assert not validate_text(source,'{n, plural, other {зат}}')
