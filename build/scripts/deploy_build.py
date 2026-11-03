"""Install rebuilt system hardware and refresh the associated runtime manifests."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ADDRESSES = {
    '/cnn_accel_0': 0x43C90000,
    '/cnn_dma': 0x40400000,
    '/video/quality_gate_0': 0x43C80000,
}


def validate_bit(path):
    data = path.read_bytes()
    position = 0

    def take(count):
        nonlocal position
        if position + count > len(data):
            raise ValueError('Truncated BIT file: ' + str(path))
        value = data[position:position + count]
        position += count
        return value

    if take(int.from_bytes(take(2), 'big')) != bytes.fromhex('0ff00ff00ff00ff000'):
        raise ValueError('Invalid Xilinx BIT header')
    if take(2) != b'\x00\x01':
        raise ValueError('Invalid BIT field marker')
    part = None
    for expected in (b'a', b'b', b'c', b'd'):
        if take(1) != expected:
            raise ValueError('Invalid BIT metadata fields')
        value = take(int.from_bytes(take(2), 'big'))
        if expected == b'b':
            part = value.rstrip(b'\x00').decode('ascii')
    if part != '7z020clg400':
        raise ValueError('BIT device must be 7z020clg400, got ' + str(part))
    if take(1) != b'e':
        raise ValueError('BIT configuration payload is missing')
    size = int.from_bytes(take(4), 'big')
    if not size or size != len(data) - position:
        raise ValueError('BIT payload length does not match its header')


def validate_hwh(path):
    tree = ET.parse(path).getroot()
    system = tree.find('SYSTEMINFO')
    expected = {'ARCH': 'zynq', 'DEVICE': '7z020', 'PACKAGE': 'clg400', 'SPEEDGRADE': '-1'}
    if system is None or any(system.get(key) != value for key, value in expected.items()):
        raise ValueError('HWH device must be xc7z020clg400-1')
    modules = {module.get('FULLNAME'): module for module in tree.iter('MODULE')}
    for name, address in EXPECTED_ADDRESSES.items():
        if name not in modules:
            raise ValueError('HWH module missing: ' + name)
        instance = modules[name].get('INSTANCE')
        ranges = {int(item.get('BASEVALUE'), 0) for item in tree.iter('MEMRANGE')
                  if item.get('INSTANCE') == instance and item.get('MEMTYPE') == 'REGISTER'}
        if ranges != {address}:
            raise ValueError('HWH register address mismatch: ' + name)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    handle, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_paths(root):
    paths = {root / 'board/hardware' / name for name in
             ('cnn_system.bit', 'cnn_system.hwh', 'manifest.json')}
    source = root / 'src/system_ui'
    paths.add(source / 'terminal_binding.json')
    if source.is_dir():
        for path in source.iterdir():
            if path.is_file() and (path.suffix in {'.py', '.service'} or
                                   path.name.startswith('ui_font_') or path.name == 'terminal_binding.json'):
                paths.add(root / 'board/system_ui' / path.name)
    for directory in ('src/system_ui', 'board/system_ui'):
        paths.update(root / directory / name for name in
                     ('system_tools_manifest.json', 'video_tools_manifest.json'))
    paths.update(root / 'board/batch' / name for name in
                 ('payload_manifest.json', 'batch_tools_manifest.json'))
    paths.update(root / 'board/cpu' / name for name in ('manifest.json', 'sha256sums'))
    return paths


def refresh_runtime(root):
    for name in ('prepare_runtime.py', 'check_layout.py'):
        subprocess.run([sys.executable, '-B', str(root / 'build/scripts' / name)], check=True)


def deploy(source, root=ROOT):
    source, root = Path(source).resolve(), Path(root).resolve()
    bit, hwh = source / 'system.bit', source / 'system.hwh'
    for path in (bit, hwh):
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError('Build output missing or empty: ' + str(path))
    validate_bit(bit)
    validate_hwh(hwh)
    payload = {'cnn_system.bit': bit.read_bytes(), 'cnn_system.hwh': hwh.read_bytes()}
    previous = {path: path.read_bytes() if path.is_file() else None for path in runtime_paths(root)}
    try:
        for name, data in payload.items():
            atomic_write(root / 'board/hardware' / name, data)
        refresh_runtime(root)
    except Exception:
        for path, data in previous.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, data)
        raise
    return {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/output',
                        help='Directory containing system.bit and system.hwh')
    args = parser.parse_args()
    print(json.dumps({'deployed_files': deploy(args.source)}, indent=2))


if __name__ == '__main__':
    main()
