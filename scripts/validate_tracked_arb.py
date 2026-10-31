"""Validate all tracked intl_*.arb pairs against their sibling intl_ru.arb in CI."""
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locqa.validation import validate_files


def main():
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '--', '*.arb'], text=True).splitlines()
    checked, failed = 0, False
    for path in sorted(set(paths)):
        target = Path(path)
        if target.name == 'intl_ru.arb' or not target.name.startswith('intl_'):
            continue
        source = target.with_name('intl_ru.arb')
        if not source.exists():
            continue
        result = validate_files(source, target)
        checked += 1
        print(f'{path}: {"OK" if result["valid"] else "FAIL"}')
        for issue in result['issues']:
            print(f'  {issue["key"]}: {issue["error"]}')
        failed |= not result['valid']
    print(f'Validated {checked} ARB pairs')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
