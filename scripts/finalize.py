"""Build the private submission from immutable native-speaker CSVs, entirely offline.

python scripts/finalize.py --source data/intl_ru.arb --target data/intl_kk.arb \
    --reviewed review_A_done.csv review_B_done.csv review_C_done.csv --out-dir out/final

Optional --overrides contains explicit agent corrections; a text-bound human_confirmation
record is required for human review flags. Metrics always use the original labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locqa.arb import load_arb
from locqa.fix import apply_decisions
from locqa.models import Finding
from locqa.report import write_html_report, write_json_report
from locqa.sheet import DECISION_COLUMNS, _uncell, _write, load_decisions
from locqa.validation import validate_files, validate_text
from scripts.validate_flutter import verify


def read_reviews(paths, ru, kk):
    rows, seen = [], set()
    for path in paths:
        with Path(path).open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                key = row['key']; pair = (key, row['issue_type'])
                if pair in seen:
                    raise ValueError(f'Duplicate review: {pair}; pass every part once')
                if key not in ru.values or _uncell(row['ru']) != ru.values[key]:
                    raise ValueError(f'Review/source version mismatch: {key}')
                if _uncell(row['kk_сейчас']) != kk.values.get(key, ''):
                    raise ValueError(f'Review/target version mismatch: {key}')
                if row.get('verdict', '') not in {'', '0', '1', 't'}:
                    raise ValueError(f'Unknown verdict for {key}')
                seen.add(pair);rows.append(row)
    return rows


def summarize_labels(rows):
    by_type = defaultdict(Counter)
    for row in rows:
        by_type[row['issue_type']][row.get('verdict') or 'unresolved'] += 1
    def score(counts):
        total = sum(counts.get(v, 0) for v in ['1', '0', 't'])
        return {'confirmed': counts.get('1', 0), 'rejected': counts.get('0', 0),
                'wrong_type': counts.get('t', 0), 'unresolved': counts.get('unresolved', 0),
                'labelled': total, 'precision_labelled': counts.get('1', 0) / total if total else None}
    counts = Counter(row.get('verdict') or 'unresolved' for row in rows)
    return {'total': score(counts), 'by_type': {k: score(v) for k, v in sorted(by_type.items())}}


def _build(source, target, reviewed, out_dir, reviewer='native_1', overrides_path=None, with_flutter=False, cost_evidence=None, baselines=None):
    out = Path(out_dir);out.mkdir(parents=True, exist_ok=True)
    ru, kk = load_arb(source), load_arb(target)
    rows = read_reviews(reviewed, ru, kk)
    decisions, warnings = load_decisions(reviewed, ru.values)
    if warnings:
        raise ValueError('\n'.join(warnings))
    for d in decisions:
        d['reviewer'] = reviewer
    _write(out/'decisions.csv', decisions, DECISION_COLUMNS)
    _write(out/'review_all_done.csv', rows, list(rows[0]) if rows else [])
    # Retain exact reviewer inputs, including original part identifiers and labels.
    for path in reviewed:
        shutil.copyfile(path, out/('input_' + Path(path).name))
    applied, skipped = apply_decisions(out/'decisions.csv', target, out/'intl_kk_fixed.arb', source)
    if skipped:
        raise ValueError(f'{skipped} native decisions rejected')
    by_key = {d['key']: d for d in decisions}
    for row in rows:
        if row.get('verdict') == '0' and row['key'] in by_key:
            raise ValueError(f"Contradictory rejection and accepted edit: {row['key']}")
    findings = []
    for row in rows:
        verdict = row.get('verdict')
        if verdict == '0':
            continue
        final = by_key.get(row['key'], {}).get('final_text', '')
        findings.append(Finding(key=row['key'], issue_type=row['issue_type'], severity=row['severity'],
            source=_uncell(row['ru']), target=_uncell(row['kk_сейчас']), evidence=_uncell(row.get('evidence')),
            suggestion=final or _uncell(row.get('suggestion')), reviewed_by_human=verdict in ('1', 't'),
            confidence=1.0 if verdict == '1' else 0.5))

    overrides = json.loads(Path(overrides_path).read_text(encoding='utf-8')) if overrides_path else []
    agent_rows = []
    override_keys = set()
    for row in overrides:
        key = row['key']
        if key in override_keys:
            raise ValueError(f'Duplicate override: {key}')
        override_keys.add(key)
        if key in by_key:
            raise ValueError(f'Agent override would replace a native-approved edit: {key}')
        if key not in ru.values or validate_text(ru.values[key], row['text']):
            raise ValueError(f'Invalid override: {key}')
        confirmation = row.get('human_confirmation')
        confirmed = confirmation is not None
        if confirmed and (not isinstance(confirmation, dict) or
                          confirmation.get('reviewer') != reviewer or
                          confirmation.get('text') != row['text'] or
                          not confirmation.get('evidence') or not confirmation.get('date')):
            raise ValueError(f'Invalid human confirmation: {key}')
        agent_rows.append({'key': key, 'issue_type': row['issue_type'], 'final_text': row['text'],
                           'reviewer': reviewer if confirmed else 'agent_review',
                           'reviewed_by_human': 'true' if confirmed else 'false'})
        findings = [f for f in findings if f.key != key]
        findings.append(Finding(key=key, issue_type=row['issue_type'], severity=row.get('severity', 'medium'),
            source=ru.values[key], target=kk.values.get(key, ''), evidence=row['reason'],
            suggestion=row['text'], confidence=0.9, reviewed_by_human=confirmed))
    if agent_rows:
        _write(out/'agent_decisions.csv', agent_rows, list(agent_rows[0]))
        _, skipped = apply_decisions(out/'agent_decisions.csv', out/'intl_kk_fixed.arb',
                                    out/'intl_kk_fixed.arb', source)
        if skipped:
            raise ValueError('Agent corrections rejected')
    (out/'agent_corrections.json').write_text(json.dumps(overrides, ensure_ascii=False, indent=2)+'\n')
    order = {key: i for i, key in enumerate(ru.order)}
    findings.sort(key=lambda f: order.get(f.key, len(order)))
    write_json_report(findings, out/'report.json');write_html_report(findings, out/'report.html')
    structural = validate_files(source, out/'intl_kk_fixed.arb', target)
    (out/'structural_validation.json').write_text(json.dumps(structural, ensure_ascii=False, indent=2)+'\n')
    if not structural['valid']:
        raise ValueError('Final ARB failed full-file validation; see structural_validation.json')
    sample = random.Random(7).sample(rows, min(100, len(rows)))
    _write(out/'precision_sample_100.csv', sample, list(rows[0]))
    metrics = {'scope': 'Review candidates including semantic candidates, before filtering and agent edits',
               'reviewer_count': 1, 'reviewer_id': reviewer, 'candidate_count': len(rows),
               'all_candidates': summarize_labels(rows), 'random_sample_seed': 7,
               'random_sample_size': len(sample), 'random_sample': summarize_labels(sample),
               'warning': 'Not recall on hidden errors. Candidate agreement is not precision on an independently sampled CLI report.'}
    (out/'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2)+'\n')
    cost = {'new_external_api_calls': 0, 'finalization_external_api_cost_usd': 0,
            'billing_verified': False, 'historical_total_usd': None,
            'note': 'Offline finalization. Historical run cost is an estimate from cached responses, not a billing total; repeated log/cache totals must not be summed.'}
    if cost_evidence:
        import re
        log = Path(cost_evidence).read_text(encoding='utf-8')
        for match in re.finditer(r'(?m)^\{\s*$', log):
            try:
                data, _ = json.JSONDecoder().raw_decode(log[match.start():])
            except ValueError:
                continue
            if isinstance(data, dict) and 'llm' in data:
                cost['historical_run_estimate'] = {k: data['llm'].get(k) for k in
                    ['model', 'complete', 'cost_usd', 'cost_usd_total', 'items_asked', 'items_answered', 'fallback_items']}
                break
        if 'historical_run_estimate' not in cost:
            raise ValueError('No LLM cost summary found in evidence log')
        cost['evidence_sha256'] = hashlib.sha256(Path(cost_evidence).read_bytes()).hexdigest()
        cost['evidence_file'] = Path(cost_evidence).name
    (out/'cost.json').write_text(json.dumps(cost, ensure_ascii=False, indent=2)+'\n')
    manifest = {'native_changes_applied': applied, 'agent_corrections': len(agent_rows),
                'agent_corrections_confirmed_by_native': sum(r['reviewed_by_human'] == 'true' for r in agent_rows),
                'structural': structural, 'report_findings': len(findings), 'reviewers': [reviewer],
                'inputs': {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                           for p in [source, target, *reviewed, *([overrides_path] if overrides_path else [])]}}
    if with_flutter:
        manifest['flutter'] = verify(source, out/'intl_kk_fixed.arb', out/'flutter', target)
        if not manifest['flutter']['valid']:
            raise ValueError('Flutter validation failed')
    if baselines:
        baseline_data = json.loads(Path(baselines).read_text(encoding='utf-8'))
        (out/'baselines.json').write_text(json.dumps(baseline_data, ensure_ascii=False, indent=2)+'\n')
    pending = [{'key': row['key'], 'text': row['text'], 'reason': row['reason'], 'reviewed_by_human': 'false'}
               for row in overrides if not row.get('human_confirmation')]
    _write(out/'pending_native_review.csv', pending, ['key', 'text', 'reason', 'reviewed_by_human'])
    (out/'README.md').write_text(
        '# Private localization submission\n\n'
        f'{structural["changed"]} changed effective values; {structural["human_reviewed_changes"]} human-reviewed. '
        f'{len(pending)} agent corrections await native confirmation.\n\n'
        'Original native inputs are immutable input_*.csv. A/B/C are data partitions, not three reviewers. '
        'Metrics use the original labels before agent corrections or filtering.\n\n'
        'intl_kk_fixed.arb preserves the game resource names. flutter/ contains standard Flutter-compatible '
        'copies and key_mapping.json; raw.log records the original source-template error. '
        'Do not replace game keys without applying this mapping in the integration.\n\n'
        'cost.json distinguishes offline finalization from historical estimates; total billing is not verified. '
        'See manifest.json, structural_validation.json, metrics.json and pending_native_review.csv.\n\n'
        'This directory includes private case-derived data: provide only to the organizers.\n', encoding='utf-8')
    for doc in ['methodology.md', 'methodology_llm.md', 'verification.md']:
        doc_path = Path(__file__).resolve().parents[1]/'docs'/doc
        shutil.copyfile(doc_path, out/doc)
    manifest['outputs'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


def run(source, target, reviewed, out_dir, reviewer='native_1', overrides_path=None, with_flutter=False, cost_evidence=None, baselines=None):
    """Publish a complete, validated directory; retain the previous release on success."""
    import tempfile
    import uuid

    out = Path(out_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=out.name + '.building-', dir=out.parent))
    try:
        result = _build(source, target, reviewed, staging, reviewer, overrides_path, with_flutter, cost_evidence, baselines)
    except Exception:
        # The failed build remains available for diagnostics. Existing final output is untouched.
        print(f'Failed build diagnostics: {staging}', file=sys.stderr)
        raise
    if out.exists():
        out.rename(out.with_name(out.name + '.previous-' + uuid.uuid4().hex[:8]))
    staging.rename(out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--source', required=True);parser.add_argument('--target', required=True)
    parser.add_argument('--reviewed', nargs='+', required=True);parser.add_argument('--out-dir', required=True)
    parser.add_argument('--reviewer', default='native_1');parser.add_argument('--overrides')
    parser.add_argument('--flutter', action='store_true')
    parser.add_argument('--baselines', help='Previously measured baseline JSON to include in the private release')
    parser.add_argument('--cost-evidence', help='Existing run log; read-only cost estimate provenance')
    args = parser.parse_args(argv)
    result = run(args.source, args.target, args.reviewed, args.out_dir, args.reviewer, args.overrides, args.flutter, args.cost_evidence, args.baselines)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
