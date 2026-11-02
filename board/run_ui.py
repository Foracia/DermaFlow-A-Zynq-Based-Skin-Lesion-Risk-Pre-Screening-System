"""Run the packaged system; device access requires --run."""
from pathlib import Path
import subprocess
import sys
HERE = Path(__file__).resolve().parent
if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, '-B', str(HERE / 'system_ui/board_terminal_service.py'), '--root', str(HERE / 'hardware'), *sys.argv[1:]]))
