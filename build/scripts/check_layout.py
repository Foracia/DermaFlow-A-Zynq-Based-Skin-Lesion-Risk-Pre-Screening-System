"""Check packaging names, Python syntax and local manifests; no experiment replay."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    try:
        return path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        return path.read_text(encoding='gb18030')


def main():
    errors, count = [], 0
    for dirname in ['src', 'sim', 'build', 'board', 'data', 'skill', 'report']:
        if not (ROOT / dirname).is_dir():
            errors.append('Missing directory: ' + dirname)
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if any(x in {'.git', '__pycache__', 'runs', 'work', 'output'} for x in rel.parts):
            continue
        count += p.is_file()
        for part in rel.parts:
            if part in {'README.md', 'SKILL.md', 'LICENSE'}:
                continue
            if not re.fullmatch(r'[a-z0-9_.-]+', part):
                errors.append('Naming: ' + rel.as_posix())
            if re.search(r'(^|[_-])(round\d+|ver\d+|v\d+([_.]\d+)*|20\d{6})([_.-]|$)', part):
                errors.append('Iteration label: ' + rel.as_posix())
        if p.suffix == '.py':
            try:
                ast.parse(read(p), filename=rel.as_posix(), feature_version=(3, 10))
            except (SyntaxError, UnicodeError) as error:
                errors.append('Python syntax: ' + rel.as_posix() + ': ' + str(error))
        if p.name == 'README.md' and re.search(r'(?i)\b(?:round\s*\d+|sys[-_]round|ver\s*\d+|v\d+\.\d+)', read(p)):
            errors.append('README contains iteration naming: ' + rel.as_posix())
    boot = ROOT / 'board/boot/boot.py'
    if not boot.is_file():
        errors.append('Missing boot configuration: board/boot/boot.py')
    else:
        boot_sha = hashlib.sha256(boot.read_bytes()).hexdigest()
        for directory in ['src/system_ui', 'board/system_ui']:
            binding = json.loads((ROOT / directory / 'terminal_binding.json').read_text(encoding='utf-8'))
            if binding['expected_nonloading_boot_sha256'] != boot_sha:
                errors.append('Boot configuration binding: ' + directory)
    specs = [ROOT / 'board/hardware/manifest.json', ROOT / 'board/cpu/manifest.json']
    specs += [ROOT / d / 'system_tools_manifest.json' for d in ['src/system_ui', 'board/system_ui']]
    specs += [ROOT / 'board/batch/batch_tools_manifest.json']
    for spec in specs:
        if not spec.is_file():
            errors.append('Missing manifest: ' + spec.relative_to(ROOT).as_posix())
            continue
        data = json.loads(read(spec))
        for name, value in data['files'].items():
            p = (spec.parent / name).resolve()
            if not p.is_relative_to(ROOT) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != value:
                errors.append('Package binding: ' + p.relative_to(ROOT).as_posix())
    print(json.dumps({'files': count, 'errors': errors, 'scope': 'layout, syntax, deployment-copy bindings only'}, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
