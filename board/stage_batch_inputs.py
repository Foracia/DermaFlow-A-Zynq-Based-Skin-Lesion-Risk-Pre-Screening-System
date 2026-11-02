"""Copy existing external prepared payloads; does not generate or evaluate a dataset."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--split', choices=['val', 'test', 'all'], default='all')
    args = parser.parse_args()
    target = Path(__file__).resolve().parent / 'batch'
    spec = json.loads((target / 'payload_manifest.json').read_text(encoding='utf-8'))
    selected = ['val', 'test'] if args.split == 'all' else [args.split]
    for split in selected:
        item = spec['splits'][split]
        source = args.source / item['file']
        if not source.is_file():
            raise FileNotFoundError(source)
        if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Prepared input does not match the frozen manifest: ' + split)
        dest = target / item['file']
        if dest.exists():
            raise FileExistsError('Existing payload retained: ' + str(dest))
        shutil.copy2(source, dest)
    print('External payload staged; no inference or board access performed.')


if __name__ == '__main__':
    main()
