from pathlib import Path
import sys

TARGETS = [
    Path('services/sources_pipeline.py'),
    Path('handlers/sources.py'),
    Path('bot.py'),
]

BAD_PATTERNS = (
    '<<<<<<<',
    '=======',
    '>>>>>>>',
    'diff --git',
)


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f'{path}: file not found']

    data = path.read_bytes()
    if data.startswith(b'\xef\xbb\xbf'):
        errors.append(f'{path}: UTF-8 BOM detected')

    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()

    if lines:
        if lines[0].startswith((' ', '\t')):
            errors.append(f'{path}: unexpected indent on line 1')

    for i, line in enumerate(lines, start=1):
        for pat in BAD_PATTERNS:
            if pat in line:
                errors.append(f'{path}:{i}: merge/diff artifact: {pat}')
        if line.startswith('index ') and line.rstrip().endswith(' 100644'):
            errors.append(f'{path}:{i}: git index artifact detected')

    return errors


def main() -> int:
    all_errors: list[str] = []
    for target in TARGETS:
        all_errors.extend(check_file(target))

    if all_errors:
        print('Validation failed:')
        for err in all_errors:
            print(f' - {err}')
        return 1

    print('Validation OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
