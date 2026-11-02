"""SYS03 persistent owner for frozen SYS02 functionality; explicit --run only.

Default verifies files, without importing PYNQ, opening devices, installing a
service, changing clocks, or downloading a bitstream. Runtime remains single
threaded and inherits the existing video/CNN DMA lease and cleanup protocol.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import sys
import time
import uuid


class ShutdownRequested(Exception):
    """Confirmed home-screen request, handled only after original app cleanup."""


class HomeShutdownFlow:
    """Wrap the frozen three-mode flow; KEY3 changes only on the home page."""
    def __init__(self, base):
        self.base = base
        self.visible = False

    def confirmation_presented(self):
        if self.state == 'shutdown_confirm':
            self.visible = True

    @property
    def state(self): return self.base.state
    @state.setter
    def state(self, value): self.base.state = value
    @property
    def selected(self): return self.base.selected
    @selected.setter
    def selected(self, value): self.base.selected = value
    @property
    def mode(self): return self.base.mode
    @mode.setter
    def mode(self, value): self.base.mode = value

    def key(self, key):
        if self.state == 'shutdown_confirm':
            if key == 2:
                return 'poweroff' if self.visible else None
            if key == 3:
                self.state = 'menu'
                return 'menu'
            return None
        if self.state == 'menu' and key == 3:
            self.state = 'shutdown_confirm'
            self.visible = False
            return 'shutdown_confirm'
        return self.base.key(key)


def safe_poweroff_cleanup(report):
    cleanup = report.get('cleanup', {})
    cnn = cleanup.get('cnn', {})
    return (cleanup.get('video_dma_stopped') is True and
            cleanup.get('event_loop_closed') is True and not cleanup.get('errors') and
            all(cnn.get(k) is True for k in ('dma_reset_and_halted', 'core_reset_requested',
                                            'hp1_mode_restored', 'buffers_freed')) and
            not cnn.get('errors'))


def request_poweroff():
    # Only called after cleanup and a persisted session record. No shell expansion.
    import subprocess  # Runtime only; default verification imports no device helpers.
    os.sync()
    subprocess.run(['/bin/systemctl', '--no-block', 'poweroff'], check=True, timeout=10)


def wait_board_ready(*, paths=None, timeout=60):
    paths = [Path('/dev/dri/renderD128'), Path('/sys/class/fpga_manager/fpga0/state')] if paths is None else paths
    started = time.monotonic()
    while True:
        missing = [str(p) for p in paths if not Path(p).exists()]
        if not missing:
            return dict(status='BOARD_NODES_READY', elapsed_seconds=time.monotonic()-started,
                        scope='Device node presence only; normal PYNQ open still verifies access')
        if time.monotonic() - started >= timeout:
            raise TimeoutError('Board device nodes unavailable: '+', '.join(missing))
        time.sleep(.25)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch_persistent_source(name, raw):
    if name != 'board_system_ui.py':
        raise ValueError('Only the guarded UI loop patch is supported')
    before = b'while time.monotonic() - started < seconds:'
    after = b'while seconds is None or time.monotonic() - started < seconds:'
    if raw.count(before) != 1:
        raise ValueError('Frozen finite loop changed; do not patch unknown source')
    return raw.replace(before, after)


def bound_history(report, session=None):
    limits = dict(captures=64, health_checks=512, exports=32, export_errors=32)
    dropped = report.setdefault('diagnostic_history_dropped', {})
    for key, limit in limits.items():
        rows = report.get(key)
        if isinstance(rows, list) and len(rows) > limit:
            count = len(rows) - limit
            dropped[key] = dropped.get(key, 0) + count
            del rows[:count]
    for exported in report.get('exports', []):
        if isinstance(exported, dict) and 'report' in exported:
            # The immutable business ZIP already contains the complete catalog.
            # Keeping it again in every session entry grows with all past cases.
            del exported['report']
            exported['full_report_in_archive'] = 'export_report.json'
    if session is not None:
        rows = session.record.get('inferences', [])
        if len(rows) > 128:
            count = len(rows) - 128
            session.record['discarded_inference_count'] = session.record.get('discarded_inference_count', 0) + count
            del rows[:count]
    report['history_scope'] = 'Bounded diagnostic window; complete successfully archived business cases remain on disk; no automatic photo deletion'


def reject_service_owners(proc_root=Path('/proc'), own_pid=None):
    own_pid = os.getpid() if own_pid is None else own_pid
    ancestors, current = set(), own_pid
    while current > 0:
        try:
            status = (proc_root / str(current) / 'status').read_text()
            parent = int(next(s.split(':', 1)[1] for s in status.splitlines() if s.startswith('PPid:')))
        except (OSError, ValueError, StopIteration):
            break
        if parent <= 0 or parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    blocked = {'board_terminal_service.py', 'ipykernel_launcher', 'ipykernel_launcher.py'}
    for child in proc_root.iterdir():
        if not child.name.isdigit() or int(child.name) == own_pid:
            continue
        try:
            args = (child / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:
            continue
        if int(child.name) in ancestors and args and Path(args[0]).name in ('sudo', 'env'):
            continue
        if any(Path(arg).name in blocked for arg in args):
            raise RuntimeError('Existing terminal/notebook owner PID %s; stop explicitly before loading hardware' % child.name)


@contextmanager
def exclusive_owner(path=Path('/run/lock/derm-terminal.lock')):
    import fcntl  # Linux runtime only, never imported by the default check.
    handle = path.open('a+')
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another persistent terminal owns the FPGA lock') from error
        yield
    finally:
        handle.close()  # Do not unlink a lock inode that a waiter may still hold.


def verify(here, root):
    here, root = Path(here).resolve(), Path(root).resolve()
    tools = json.loads((here / 'system_tools_manifest.json').read_text(encoding='utf-8'))
    for name, expected in tools['files'].items():
        file = (here / name).resolve()
        if not file.is_relative_to(here) or digest(file) != expected:
            raise ValueError('Terminal tool identity changed: ' + name)
    if digest(root / 'manifest.json') != tools['model_manifest_sha256']:
        raise ValueError('Wrong hardware package; use the separately bound terminal candidate')
    model = json.loads((root / 'manifest.json').read_text(encoding='utf-8-sig'))
    if model['status'] != 'PACKAGED' or model['round'] not in (41, 42):
        raise ValueError('Unsupported hardware package')
    for name, expected in model['files'].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root) or digest(file) != expected:
            raise ValueError('Hardware artifact changed: ' + name)
    return tools, model


def check_boot_owner(here, boot_path=Path('/boot/boot.py')):
    binding = json.loads((Path(here) / 'terminal_binding.json').read_text(encoding='utf-8'))
    if not boot_path.is_file() or digest(boot_path) != binding['expected_nonloading_boot_sha256']:
        raise RuntimeError('boot.py identity is not the previously inspected no-BaseOverlay hook; inspect before proceeding. No boot file changed.')


def load_overlay(root, model):
    from pynq import Overlay
    overlay = Overlay(str(Path(root) / 'cnn_system.bit'), download=False)
    expected = {'cnn_accel_0': 0x43c90000, 'cnn_dma': 0x40400000, 'video/quality_gate_0': 0x43c80000}
    actual = {name: overlay.ip_dict[name]['phys_addr'] for name in expected}
    if actual != expected:
        raise RuntimeError('Unexpected CNN/DMA/quality HWH addresses; no download attempted')
    print('TERMINAL_DOWNLOADING Round%d %s' % (model['round'], model['files']['cnn_system.bit']), flush=True)
    overlay.download()
    print('TERMINAL_DOWNLOAD_COMPLETE', flush=True)
    # No driver construction or MMIO access here; normal app.open attaches next.


def reclaim_startup_cache(*, meminfo=Path('/proc/meminfo'),
                          drop_path=Path('/proc/sys/vm/drop_caches'), sync_fn=None):
    """One synchronous reclaim before creating DMA buffers, never a DMA free.

    Caller must hold the exclusive owner lock and reject previous owners first.
    An unchanged CmaFree is valid: cache reclaim cannot promise contiguous space.
    """
    def sample():
        values = {line.split(':',1)[0]:int(line.split()[1])
                  for line in meminfo.read_text().splitlines() if ':' in line}
        return {name:values[name] for name in ('MemAvailable','Cached','CmaTotal','CmaFree')}
    before = sample()
    started = time.monotonic_ns()
    if sync_fn is None:
        sync_fn = os.sync  # Linux-only explicit runtime; not used by default check.
    sync_fn()
    with drop_path.open('w', encoding='ascii') as stream:
        stream.write('3\n')
    return dict(status='STARTUP_CACHE_RECLAIM_COMPLETE', before=before, after=sample(),
        elapsed_ms=(time.monotonic_ns()-started)/1e6, drop_caches_value=3,
        scope='One startup sync+drop_caches; reclaimable caches only; no DMA buffer free or periodic reclaim')


def make_app(root, here, output, input_timeout, active_low, model, *, standalone=False):
    from system_app import Round02App
    class PersistentApp(Round02App):
        def __init__(self):
            super().__init__(root, here, output, candidate='combined', input_timeout=input_timeout,
                             active_low=active_low, implementation='optimized')
            self.report.update(hardware_round=model['round'], deployment_round='SYS-Round03',
                persistent_entry=True, software_numeric_baseline='SYS02-v2 combined unchanged',
                automatic_restart=False)
            if standalone:
                self.flow = HomeShutdownFlow(self.flow)
                for page in self.views.menus:
                    self.views.team.fill_rect(page, 0, 640, 1280, 80, (24, 26, 30))
                    self.views.text(page, 'KEY0 / KEY1 选择  KEY2 确认  KEY3 关机', 656, x=240)
                self.page = self.views.menus[self.flow.selected]
                self.report['home_key3'] = 'confirm poweroff; KEY2 confirms; KEY3 cancels'

        def action(self, action):
            if standalone and action == 'shutdown_confirm':
                super().action('menu')  # cancel capture and disable gate using existing path
                self.page = self.views.message('确认关机', ['KEY2 确认关机', 'KEY3 返回菜单',
                    '请保持设备运行'], hint='KEY2 确认    KEY3 返回菜单')
                return
            if standalone and action == 'poweroff':
                raise ShutdownRequested()
            return super().action(action)

        def persist(self):
            bound_history(self.report, self.session)
            return super().persist()

        async def write_owned(self, frame):
            bound_history(self.report, self.session)
            value = await super().write_owned(frame)
            if standalone:
                self.flow.confirmation_presented()
            return value
    return PersistentApp()


def run_app(app, seconds):
    previous = {}
    def interrupted(number, frame):
        if not app.closing:
            raise KeyboardInterrupt('operator signal %d' % number)
    for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, interrupted)
    code, shutdown = 0, False
    try:
        app.open()
        print('TERMINAL_MENU_READY', 'persistent' if seconds is None else seconds, flush=True)
        app.loop.run_until_complete(app.run_loop(seconds))
    except ShutdownRequested:
        shutdown = True
        app.report.update(status='BOARD_POWEROFF_CONFIRMED',
                          poweroff=dict(status='CONFIRMED_PENDING_CLEANUP'))
    except KeyboardInterrupt:
        app.report['status'] = 'OPERATOR_STOPPED'
    except BaseException as error:
        app.report.update(status='FAILED', error=repr(error))
        print('TERMINAL_ERROR', repr(error), flush=True)
        code = 1
    finally:
        try:
            app.close()
        except BaseException as error:
            print('TERMINAL_CLEANUP_ERROR', repr(error), flush=True)
            code = 1
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
    print('TERMINAL_RECORD', app.record_path, app.report.get('status'), flush=True)
    failed = app.report.get('status', '').startswith('FAILED') or app.report.get('cleanup', {}).get('errors')
    if shutdown:
        if code or failed or not safe_poweroff_cleanup(app.report):
            app.report.update(status='FAILED_POWEROFF_CLEANUP',
                              poweroff=dict(status='BLOCKED_UNSAFE_CLEANUP'))
            app.persist()
            print('POWEROFF_BLOCKED_UNSAFE_CLEANUP', flush=True)
            return 1
        try:
            app.report['poweroff'] = dict(status='REQUESTED',
                scope='Linux poweroff requested after verified DMA/buffer cleanup; physical halt not confirmed by this process')
            app.persist()
            print('BOARD_POWEROFF_REQUESTING_AFTER_SAFE_CLEANUP', flush=True)
            request_poweroff()
        except BaseException as error:
            app.report.update(status='FAILED_POWEROFF_REQUEST', poweroff=dict(status='FAILED', error=repr(error)))
            app.persist()
            print('BOARD_POWEROFF_REQUEST_FAILED', repr(error), flush=True)
            return 1
    return 1 if failed else code


def unit_text(here, root, *, standalone=False):
    here, root = (PurePosixPath(Path(value).as_posix()) for value in (here, root))
    for path in (here, root):
        if not path.is_absolute() or not str(path).isascii() or any(c in str(path) for c in (' ', '\n', '\r', '%', '"', "'", '\\')):
            raise ValueError('Use absolute ASCII board paths without whitespace or unit expansion')
    text = '''[Unit]
Description=Skin image risk screening terminal
After=local-fs.target jupyter.service pynq-jupyter.service derm-ui.service
Conflicts=derm-ui.service
StartLimitIntervalSec=300
StartLimitBurst=1

[Service]
Type=simple
User=root
WorkingDirectory=%s
Environment=XILINX_XRT=/usr
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONUTF8=1
Environment=PATH=/usr/local/share/pynq-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStartPre=/bin/sleep 15
ExecStart=/usr/local/share/pynq-venv/bin/python3 %s/board_terminal_service.py --root %s --load --run
Restart=no
KillSignal=SIGTERM
KillMode=control-group
TimeoutStopSec=infinity
SendSIGKILL=no
StandardOutput=journal
StandardError=journal
LogRateLimitIntervalSec=30s
LogRateLimitBurst=80
UMask=0022

[Install]
WantedBy=multi-user.target
''' % (here.as_posix(), here.as_posix(), root.as_posix())
    if standalone:
        text = text.replace('After=local-fs.target jupyter.service pynq-jupyter.service derm-ui.service',
                            'After=local-fs.target systemd-udev-trigger.service derm-ui.service')
        text = text.replace('ExecStartPre=/bin/sleep 15\n', '')
    return text


def parse_args(argv=None):
    def bounded(low, high):
        def checked(value):
            try:
                result = int(value)
            except ValueError as error:
                raise argparse.ArgumentTypeError('Integer required') from error
            if not low <= result <= high:
                raise argparse.ArgumentTypeError('Expected %d..%d' % (low, high))
            return result
        return checked
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--load', action='store_true', help='One download before attach; requires --run')
    parser.add_argument('--seconds', type=bounded(10,3600), default=None)
    parser.add_argument('--input-timeout', type=bounded(5,60), default=30)
    parser.add_argument('--active-low', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.load and not args.run:
        parser.error('--load requires explicit --run')
    return args


def main(argv=None):
    args = parse_args(argv)
    here, root = Path(__file__).resolve().parent, args.root.resolve()
    tools, model = verify(here, root)
    if not args.run:
        print('SYSTEM_PACKAGE_VERIFIED_NO_HARDWARE_ACCESSED', tools['revision'], 'Round%d' % model['round'])
        return 0
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RuntimeError('Explicit runtime requires root on the Linux board')
    with exclusive_owner():
        reject_service_owners()
        from system_app import reject_round02_owners
        reject_round02_owners()
        check_boot_owner(here)
        standalone = tools.get('standalone_controls', False)
        if standalone:
            print('BOARD_READINESS', json.dumps(wait_board_ready()), flush=True)
        if args.load:
            load_overlay(root, model)
        output = args.output or here / 'runs'
        output.mkdir(parents=True, exist_ok=True)
        startup_path = output / ('startup_memory_' + uuid.uuid4().hex + '.json')
        try:
            startup = reclaim_startup_cache()
        except BaseException as error:
            startup_path.write_text(json.dumps(dict(status='STARTUP_CACHE_RECLAIM_FAILED', error=repr(error)))+'\n',encoding='utf-8')
            print('STARTUP_MEMORY_RECORD', startup_path, 'FAILED', flush=True)
            raise
        startup_path.write_text(json.dumps(startup,indent=2)+'\n',encoding='utf-8')
        print('STARTUP_CACHE_RECLAIM', json.dumps(startup), flush=True)
        app_args = (root, here, output, args.input_timeout, args.active_low, model)
        app = make_app(*app_args, standalone=True) if standalone else make_app(*app_args)
        app.report.update(startup_memory=startup, startup_memory_record=str(startup_path))
        return run_app(app, args.seconds)


if __name__ == '__main__':
    raise SystemExit(main())
