"""Launch prepared-input evaluation without changing the loaded overlay."""
from pathlib import Path
import argparse
import subprocess
import sys

HERE = Path(__file__).resolve().parent
if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--split', choices=['val', 'test', 'all'], default='test')
    args, _ = parser.parse_known_args()
    if '--help' not in sys.argv and '-h' not in sys.argv:
        required = ['val', 'test'] if args.split == 'all' else [args.split]
        missing = [str(HERE / 'batch' / (s + '_inputs.npz')) for s in required
                   if not (HERE / 'batch' / (s + '_inputs.npz')).is_file()]
        if missing:
            print('External dataset payload is not included. Use stage_batch_inputs.py first:\n' + '\n'.join(missing), file=sys.stderr)
            raise SystemExit(2)
    raise SystemExit(subprocess.call([sys.executable, '-B', str(HERE / 'batch/board_batch.py'),
                                     '--cpu-root', str(HERE / 'cpu'), '--pl-root', str(HERE / 'hardware'),
                                     *sys.argv[1:]]))
