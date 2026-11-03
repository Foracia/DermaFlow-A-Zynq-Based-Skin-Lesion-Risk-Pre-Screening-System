"""Refresh copied runtime files and their local manifests, without device access."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    source, target = ROOT / 'src/system_ui', ROOT / 'board/system_ui'
    binding_path = source / 'terminal_binding.json'
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    binding['expected_nonloading_boot_sha256'] = digest(ROOT / 'board/boot/boot.py')
    save(binding_path, binding)
    for p in source.iterdir():
        if p.is_file() and (p.suffix in {'.py', '.service'} or p.name.startswith('ui_font_') or p.name == 'terminal_binding.json'):
            shutil.copy2(p, target / p.name)
    hardware = ROOT / 'board/hardware'
    files = {p.name: digest(p) for p in sorted(hardware.iterdir()) if p.is_file() and p.name not in {'manifest.json', 'README.md'}}
    save(hardware / 'manifest.json', {'status': 'PACKAGED', 'round': 42, 'part': 'xc7z020clg400-1', 'files': files})
    model_sha = digest(hardware / 'manifest.json')
    for dirname in ['src/system_ui', 'board/system_ui']:
        directory = ROOT / dirname
        files = {p.name: digest(p) for p in sorted(directory.iterdir())
                 if p.is_file() and p.name not in {'system_tools_manifest.json', 'video_tools_manifest.json', 'README.md'}}
        spec = {'status': 'PACKAGED', 'model_manifest_sha256': model_sha, 'files': files,
                'run_requires_explicit_flag': True, 'revision': 'release',
                'standalone_controls': True, 'accepted_previous_manual_proofs': []}
        save(directory / 'system_tools_manifest.json', spec)
        save(directory / 'video_tools_manifest.json', spec)
    batch = ROOT / 'board/batch'
    contract = json.loads((batch / 'payload_manifest.json').read_text(encoding='utf-8'))
    contract['pl_model_manifest_sha256'] = model_sha
    save(batch / 'payload_manifest.json', contract)
    files = {p.name: digest(p) for p in sorted(batch.iterdir()) if p.is_file() and p.suffix == '.py'}
    save(batch / 'batch_tools_manifest.json', {'status': 'PACKAGED', 'files': files,
         'payload_manifest_sha256': digest(batch / 'payload_manifest.json')})
    cpu = ROOT / 'board/cpu'
    files = {p.relative_to(cpu).as_posix(): digest(p) for p in sorted(cpu.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.name not in {'manifest.json', 'sha256sums'}}
    save(cpu / 'manifest.json', {'status': 'PACKAGED', 'files': files})
    (cpu / 'sha256sums').write_text(''.join(f'{value}  {key}\n' for key, value in files.items()), encoding='utf-8')
    print('Runtime copies and file manifests prepared; no hardware accessed.')


if __name__ == '__main__':
    main()
