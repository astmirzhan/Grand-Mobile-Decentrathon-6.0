"""Package code separately from private case-derived deliverables; no network or Git writes.

python scripts/package_submission.py --final-dir out/final --out-dir out/submission
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--final-dir', required=True);parser.add_argument('--out-dir', required=True)
    args=parser.parse_args(argv)
    final=Path(args.final_dir).resolve();out=Path(args.out_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((final/'manifest.json').read_text())
    if not manifest['structural']['valid']:
        raise ValueError('Release has not passed validation')
    if 'flutter' not in manifest or not manifest['flutter']['valid']:
        raise ValueError('Release has not passed Flutter verification')
    for name, expected in manifest.get('outputs', {}).items():
        if hashlib.sha256((final/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Release file changed after validation: {name}')
    code=out/'locqa-source.zip' 
    # Include new uncommitted source too, without including data/, out/, .env or caches.
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    excluded={'.env','data','out','.locqa_cache','.venv','venv','build','dist','__pycache__','.pytest_cache'}
    with zipfile.ZipFile(code,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(names)):
            p=ROOT/name
            if not p.is_file() or set(Path(name).parts)&excluded or p.suffix in {'.zip','.tgz','.pdf'}:
                continue
            if p.suffix=='.arb' and 'tests/fixtures/' not in name:
                continue
            z.write(p,'locqa/'+name)
    private=out/'grand-loc-results-PRIVATE.zip'
    with zipfile.ZipFile(private,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(final.rglob('*')):
            if p.is_file():z.write(p,'results/'+str(p.relative_to(final)))
        z.write(ROOT/'glossary.csv','results/glossary.csv')
    checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [code,private]}
    (out/'SHA256SUMS.json').write_text(json.dumps(checksums,indent=2)+'\n')
    (out/'README.txt').write_text('locqa-source.zip: code and synthetic tests. No original ARB, review CSVs, API keys or caches.\n'
        'grand-loc-results-PRIVATE.zip: case-derived results for organizers only. Do not publish.\n'
        'Keep the original-name intl_kk_fixed.arb for the game integration. The flutter/ copies use\n'
        'the documented key_mapping.json for isolated standard Flutter validation.\n'
        f"{manifest['structural']['human_reviewed_changes']} changed strings are human-reviewed; "
        f"{manifest['structural']['unreviewed_changes']} remain unreviewed. See agent_corrections.json for provenance.\n")
    print(json.dumps(checksums,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
