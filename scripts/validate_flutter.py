"""Reproducible Flutter verification; original ARB files are never rewritten.

python scripts/validate_flutter.py --source data/intl_ru.arb --target out/final/intl_kk_fixed.arb \
    --original data/intl_kk.arb --out-dir out/flutter-check

Runs the unmodified input first, then (only if necessary) a copy with deterministic,
collision-checked Dart identifier renames. Saves both logs and the explicit mapping.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locqa.arb import _pairs_to_dict, load_arb
from locqa.validation import validate_files

VALID_KEY = re.compile(r"^[a-z][A-Za-z0-9_]*$")


def resource_mapping(documents) -> dict[str, str]:
    keys = {k for doc in documents for k in doc.values}
    mapping = {}
    occupied = set(keys)
    for key in sorted(keys):
        if VALID_KEY.fullmatch(key):
            continue
        parts = re.findall(r"[A-Za-z0-9]+", key)
        replacement = ''.join(p[:1].upper() + p[1:] for p in parts) or 'Resource'
        replacement = replacement[:1].lower() + replacement[1:]
        if not replacement[0].isalpha():
            replacement = 'resource' + replacement
        if replacement in occupied:
            raise ValueError(f"Dart key rename collides: {key} -> {replacement}")
        mapping[key] = replacement
        occupied.add(replacement)
    return mapping


def write_mapped(doc, path: Path, mapping: dict[str, str]):
    pairs = []
    for key, value in doc.raw_pairs:
        if key.startswith('@') and not key.startswith('@@'):
            key = '@' + mapping.get(key[1:], key[1:])
        else:
            key = mapping.get(key, key)
        pairs.append((key, _pairs_to_dict(value)))
    path.write_text('{\n' + ',\n'.join('  ' + json.dumps(k, ensure_ascii=False) + ': ' +
                    json.dumps(v, ensure_ascii=False) for k, v in pairs) + '\n}\n', encoding='utf-8')


def verify(source, target, out_dir, original=None, flutter='flutter') -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    structural = validate_files(source, target, original)
    result = {'structural': structural, 'raw_exit_code': None, 'compatible_exit_code': None,
              'key_mapping': {}, 'valid': False}
    executable = shutil.which(flutter)
    if not structural['valid']:
        result['error'] = 'Structural validation failed; Flutter was not run.'
    elif not executable:
        result['error'] = 'Flutter SDK not found on PATH.'
    else:
        ru, kk = load_arb(source), load_arb(target)
        result['key_mapping'] = resource_mapping([ru, kk])
        with tempfile.TemporaryDirectory(prefix='locqa-flutter-') as temp:
            project = Path(temp)
            arb_dir = project/'lib/l10n'
            arb_dir.mkdir(parents=True)
            (project/'pubspec.yaml').write_text('name: locqa_validation\nenvironment:\n  sdk: ">=3.0.0 <4.0.0"\ndependencies:\n  flutter:\n    sdk: flutter\n  flutter_localizations:\n    sdk: flutter\nflutter:\n  generate: true\n')
            (project/'l10n.yaml').write_text('arb-dir: lib/l10n\ntemplate-arb-file: intl_ru.arb\noutput-localization-file: app_localizations.dart\n')
            shutil.copyfile(source, arb_dir/'intl_ru.arb')
            shutil.copyfile(target, arb_dir/'intl_kk.arb')
            def run(label):
                proc = subprocess.run([executable, 'gen-l10n'], cwd=project, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
                (out/f'{label}.log').write_text(proc.stdout, encoding='utf-8')
                return proc.returncode
            result['flutter_version'] = subprocess.run([executable, '--version'], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30).stdout.strip()
            result['raw_exit_code'] = run('raw')
            if result['raw_exit_code'] == 0:
                result['valid'] = True
            elif result['key_mapping']:
                for lang, doc in [('ru', ru), ('kk', kk)]:
                    write_mapped(doc, arb_dir/f'intl_{lang}.arb', result['key_mapping'])
                    shutil.copyfile(arb_dir/f'intl_{lang}.arb', out/f'intl_{lang}.arb')
                result['compatible_exit_code'] = run('compatible')
                result['valid'] = result['compatible_exit_code'] == 0
            if result['valid']:
                generated = out/'generated'
                generated.mkdir(exist_ok=True)
                for file in arb_dir.glob('*.dart'):
                    shutil.copyfile(file, generated/file.name)
        (out/'key_mapping.json').write_text(json.dumps(result['key_mapping'], ensure_ascii=False, indent=2)+'\n')
    (out/'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--original')
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args(argv)
    result = verify(args.source, args.target, args.out_dir, args.original)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
