"""SYS-Round00: three-mode UI on an already loaded, validated Round41 overlay.

Default invocation verifies files only. --run explicitly enables hardware.
No installation, bitstream download, clock change or calibration fitting.
"""
import argparse
import asyncio
from dataclasses import asdict, replace
import gc
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid

import numpy as np

try:
    from .system_risk_core import MENU_ITEMS, MODES, RiskController
    from .system_result_store import ResultStore, export_results
except ImportError:
    from system_risk_core import MENU_ITEMS, MODES, RiskController
    from system_result_store import ResultStore, export_results


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quality_function(implementation):
    if implementation == 'baseline':
        from frame_quality import assess_frame
        return assess_frame
    if implementation == 'optimized':
        try:
            from .frame_quality_candidate import assess_frame
        except ImportError:
            from quality_equivalent import assess_frame
        return assess_frame
    raise ValueError('Unknown system implementation')


def verify_tools(here, root):
    here, root = Path(here).resolve(), Path(root).resolve()
    tools = json.loads((here / 'system_tools_manifest.json').read_text(encoding='utf-8'))
    for name, sha in tools['files'].items():
        path = (here / name).resolve()
        if not path.is_relative_to(here) or digest(path) != sha:
            raise ValueError('System tool identity mismatch: ' + name)
    try:
        from .board_accel import check_manifest
    except ImportError:
        from board_accel import check_manifest
    manifest = check_manifest(root)
    if digest(root / 'manifest.json') != tools['model_manifest_sha256']:
        raise ValueError('Expected frozen Round41 model package')
    return tools, manifest


def reject_other_owners(proc_root=Path('/proc'), own_pid=None):
    own_pid = os.getpid() if own_pid is None else own_pid
    ancestors, current = set(), own_pid
    while current > 0:
        try:
            status = (proc_root / str(current) / 'status').read_text()
            parent = int(next(line.split(':', 1)[1] for line in status.splitlines()
                              if line.startswith('PPid:')))
        except (OSError, ValueError, StopIteration):
            break
        if parent <= 0 or parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    blocked = {'ui_app.py', 'board_system_ui.py', 'board_live_hud.py', 'board_live_demo.py',
               'board_video_probe.py', 'board_hud_compare.py', 'board_accel.py', 'board_timing.py'}
    for child in proc_root.iterdir():
        if not child.name.isdigit() or int(child.name) == own_pid:
            continue
        try:
            args = (child / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except (OSError, ProcessLookupError):
            continue
        # sudo/env may retain this command in argv while waiting for its child.
        # Exempt only our own launcher ancestors, never a sibling launch or UI.
        if int(child.name) in ancestors and args and Path(args[0]).name in ('sudo', 'env'):
            continue
        if any(Path(arg).name in blocked for arg in args):
            raise RuntimeError('Other UI/CNN/video owner PID ' + child.name + '; stop it explicitly first')


class Flow:
    def __init__(self):
        self.state, self.selected, self.mode = 'menu', 0, 'normal'

    def key(self, key):
        if key == 3:
            self.state = 'menu'
            return 'menu'
        if self.state == 'menu':
            if key in (0, 1):
                self.selected = (self.selected + (-1 if key == 0 else 1)) % 3
                return 'redraw'
            if key == 2:
                self.mode = MODES[self.selected]
                self.state = 'export' if self.mode == 'export' else 'capture'
                return self.mode
        elif self.state in ('result', 'error') and key == 2:
            self.state = 'export' if self.mode == 'export' else 'capture'
            return self.mode
        return None


def team_modules():
    """Use frozen copied UI helpers in a bundle; source-tree fallback for tests."""
    try:
        import ui_menu
    except ModuleNotFoundError as exc:
        if exc.name != 'ui_menu':
            raise
        source = Path(__file__).resolve().parents[2] / 'ui_delivery_v0.1_20261029/python'
        sys.path.insert(0, str(source))
        import ui_menu
    import ui_live
    import ui_buttons
    return ui_menu, ui_live, ui_buttons


class Views:
    def __init__(self, here):
        self.team, _, _ = team_modules()
        self.body = self.team.FontSet(Path(here) / 'ui_font_24.json')
        self.title = self.team.FontSet(Path(here) / 'ui_font_40.json')
        self.menus = [self.menu(i) for i in range(3)]

    def blank(self):
        page = np.zeros((720, 1280, 4), dtype=np.uint8)
        page[:, :, :3] = (24, 26, 30)
        page[:, :, 3] = 255
        return page

    def text(self, page, text, y, *, color=(235, 238, 242), title=False, x=48):
        font = self.title if title else self.body
        self.team.draw_text(page, font, x, y - (font.height - font.pixel_size) // 2, str(text), color)

    def menu(self, selected):
        page = self.blank()
        self.text(page, '皮肤病变风险预筛终端', 42, title=True, x=360)
        self.text(page, '请选择工作模式', 108, color=(150, 155, 165), x=530)
        for i, (label, description) in enumerate(MENU_ITEMS):
            y = 174 + i * 142
            on = i == selected
            self.team.fill_rect(page, 130, y, 1020, 114, (28, 52, 42) if on else (32, 35, 41))
            self.team.stroke_rect(page, 130, y, 1020, 114, (78, 200, 120) if on else (68, 74, 86), t=3)
            self.text(page, label, y + 17, x=174)
            self.text(page, description, y + 64, x=174, color=(160, 165, 175))
        self.text(page, 'KEY0 / KEY1 选择    KEY2 确认', 656, x=375)
        return page

    def message(self, heading, lines, *, bad=False, hint='KEY2 重试    KEY3 返回菜单'):
        page = self.blank()
        self.text(page, heading, 70, title=False, color=(245, 120, 110) if bad else (110, 230, 150))
        for i, line in enumerate(lines):
            # Long filenames use ASCII tokens; never silently truncate result labels.
            self.text(page, str(line)[:76], 142 + i * 54)
        self.text(page, hint, 660)
        return page

    def processing(self):
        return self.message('正在复核与推理', ['请保持设备运行', '完成后自动显示结果'],
                            hint='正在处理，请稍候')

    def result(self, packet, save_status='pending', error=None):
        result = packet['result']
        page = self.blank()
        name = '三帧融合推理结果' if result['mode'] == 'fusion' else '单帧风险预筛结果'
        self.text(page, name, 32, title=False)
        self.text(page, result['risk_label'], 87,
                  color=(245, 120, 110) if result['prediction'] else (110, 230, 150))
        fused = result['mode'] == 'fusion'
        label = '融合风险概率' if fused else '模型风险概率'
        self.text(page, label + ' %.2f%%    判定阈值 %.6f' %
                  (100 * result['refer_probability'], result['decision_threshold']), 137)
        if fused:
            probabilities = [float(row['positive_probability']) for row in result['inferences']]
            if len(probabilities) != 3 or any(not 0 <= p <= 1 for p in probabilities):
                raise ValueError('Fusion display requires three actual finite probabilities')
            self.text(page, '（三帧推理：%.2f%%，%.2f%%，%.2f%%）' %
                      tuple(100 * p for p in probabilities), 181)
        self.text(page, '参与推理 %d 帧    推理耗时 %.1f ms' %
                  (result['frame_count'], result['inference_latency_ms']), 218 if fused else 184)
        rgb = packet['frames'][-1]['rgb']
        if rgb.shape == (360, 640, 3):
            image_y = 264 if fused else 232
            page[image_y:image_y + 360, 320:960, :3] = rgb
        status = {'pending': '保存中', 'complete': '保存成功', 'failed': '保存失败，请重试'}[save_status]
        self.text(page, status, 636 if fused else 612,
                  color=(245, 120, 110) if save_status == 'failed' else (160, 220, 175))
        self.text(page, 'KEY2 再次采集    KEY3 返回菜单', 684 if fused else 668)
        return page


class SystemApp:
    def __init__(self, root, here, output, *, input_timeout=10, active_low=False,
                 implementation='optimized'):
        if implementation not in ('baseline', 'optimized'):
            raise ValueError('Unknown system implementation')
        self.implementation = implementation
        self.png_compress_level = 6 if implementation == 'baseline' else 1
        self.root, self.here, self.output = Path(root), Path(here), Path(output)
        self.input_timeout, self.active_low = input_timeout, active_low
        self.flow, self.views = Flow(), Views(here)
        self.output.mkdir(parents=True, exist_ok=True)
        self.store = ResultStore(self.output / 'captures', png_compress_level=self.png_compress_level)
        self.report = dict(status='NEW', hardware_round=41, software_round='SYS-Round01',
                           implementation=implementation, png_compress_level=self.png_compress_level,
                           captures=[], cleanup={}, bitstream_reprogrammed=False,
                           working_point_refitted=False)
        self.record_path = self.output / ('system_session_' + uuid.uuid4().hex + '.json')
        self.session = self.ol = self.vin = self.vout = self.gate = self.controller = None
        self.owns_video = False
        self.closing = False
        self.loop = self.registry = self.poller = None
        self.irq_baseline = (set(), {})
        self.page, self.pending_packet = self.views.menus[0], None
        self.owned_frame = self.output_owned = None
        self.sequence, self.cid, self.request_seen = 0, None, False

    def persist(self):
        self.record_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

    def open(self):
        reject_other_owners()
        try:
            from . import board_video_probe as video, board_accel as accel
            from .board_session import CnnSession
            from .camera_input import prepare_roi
        except ImportError:
            import board_video_probe as video, board_accel as accel
            from board_session import CnnSession
            from camera_input import prepare_roi
        self.video, self.accel = video, accel
        tools, manifest = verify_tools(self.here, self.root)
        self.report.update(model_manifest_sha256=tools['model_manifest_sha256'],
                           tools_revision=tools['revision'],
                           tools_manifest_sha256=digest(self.here / 'system_tools_manifest.json'),
                           bitstream_sha256=manifest['files']['cnn_system.bit'],
                           health_before=video.health())
        video.check_memory(self.report['health_before'], 'before_video', self.report)
        ext4 = Path('/sys/fs/ext4/mmcblk0p2/errors_count')
        if ext4.read_text().strip() != '0':
            raise RuntimeError('Existing EXT4 errors')
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        from pynq import PL, Overlay, MMIO
        from pynq.interrupt import _InterruptController
        from pynq.lib.video import PIXEL_RGBA
        from quality_gate_driver import QualityGate
        from reference import Config
        assess_frame = quality_function(self.implementation)
        self.registry = _InterruptController
        self.irq_baseline = (set(map(id, self.registry._controllers)),
                             {k: id(v) for k, v in self.registry._uio_devices.items()})
        accel.confirm_loaded(PL.bitfile_name, manifest['files']['cnn_system.bit'])
        self.ol = Overlay(str(self.root / 'cnn_system.bit'), download=False)
        ip = self.ol.ip_dict['video/axi_vdma']
        dma = MMIO(ip['phys_addr'], ip['addr_range'])
        state = dict(zip(('tx_control', 'rx_control', 'tx_status', 'rx_status'),
                         (int(dma.read(n)) for n in (0, 0x30, 4, 0x34))))
        if not video.video_dma_is_idle(**state):
            raise RuntimeError('Video DMA already owned; no takeover attempted')
        self.owns_video = True
        ip = self.ol.ip_dict['video/quality_gate_0']
        if ip['phys_addr'] != 0x43c80000:
            raise RuntimeError('Unexpected quality gate address')
        self.gate = QualityGate(MMIO(ip['phys_addr'], ip['addr_range']))
        if (self.gate.frame_width, self.gate.frame_height) != (1280, 720):
            raise RuntimeError('Quality dimensions differ')
        self.cfg = Config(enable=1, x0=320, y0=180, width=640, height=360,
                          mean_min=40, mean_max=210, dark_level=16, bright_level=239,
                          dark_max_bp=500, bright_max_bp=200, sharp_min=20, stable_n=3)
        self.session = CnnSession(self.root, self.ol, record_dir=self.output, persist_each_inference=False)
        self.session.open()
        self.report['golden'] = [self.session.infer(words, expected_raw=int(expected))
                                 for words, expected in zip(self.session.golden_words, self.session.golden_expected)]
        print('SYS01_FOUR_GOLDEN_PASS', self.implementation, flush=True)
        self.controller = RiskController(self.session, self.session.point, self.cfg,
                                         assess_fn=assess_frame, prepare_fn=prepare_roi,
                                         model_identity=tools['model_manifest_sha256'],
                                         bitstream_version='Round%d:' % int(manifest['round']) + manifest['files']['cnn_system.bit'])
        _, ui_live, ui_buttons = team_modules()
        self.hud = ui_live.LiveHUD(self.here / 'ui_font_24.json', roi=asdict(self.cfg))
        self.describe_state = ui_live.describe_state
        self.poller = ui_buttons.ButtonPoller(self.ol.btns_gpio,
                                             ui_buttons.Buttons(active_low=self.active_low, debounce=3))
        self.vin, self.vout = self.ol.video.hdmi_in, self.ol.video.hdmi_out
        video.configure_input(self.vin, PIXEL_RGBA, self.input_timeout, self.report)
        if (self.vin.mode.width, self.vin.mode.height) != (1280, 720):
            raise RuntimeError('Expected 1280x720 input')
        self.vout.configure(self.vin.mode, PIXEL_RGBA)
        self.gate.configure(replace(self.cfg, enable=0), arm=True)
        self.vin.start()
        self.vout.start()
        self.poller.start()
        self.report['status'] = 'RUNNING'
        self.persist()

    async def submit(self, page):
        frame = self.vout.newframe()
        self.output_owned = frame
        frame[:] = page
        await asyncio.wait_for(self.vout.writeframe_async(frame), 2.)
        self.output_owned = None

    async def write_owned(self, frame):
        # Retain the frame on a timeout until the DMA-stop path has run.
        self.owned_frame = frame
        await asyncio.wait_for(self.vout.writeframe_async(frame), 2.)
        self.owned_frame = None

    def archive_pending(self):
        if self.pending_packet is None:
            return
        packet, self.pending_packet = self.pending_packet, None
        packet['result']['save_status'] = 'in_progress'
        archive_started = time.perf_counter_ns()
        try:
            saved = self.store.save(packet['result'], packet['frames'])
            self.report['captures'][-1].update(
                save_status='complete', result_path=saved['result_path'],
                archive_latency_ms=(time.perf_counter_ns() - archive_started) / 1e6,
                archive_latency_scope='Full ResultStore.save call including final manifest fsync/replace; excludes result-page rendering and session JSON write',
                png_nbytes=saved.get('png_nbytes'),
                archive_elapsed_before_commit_ms=saved.get('archive_elapsed_before_commit_ms'),
                png_timings=[{k: image.get(k) for k in
                              ('png_encode_write_ms', 'flush_fsync_ms', 'readback_verify_ms')}
                             for image in saved.get('images', [])])
            if 'capture_accepted_monotonic_ns' in packet['result']:
                self.report['captures'][-1]['accepted_to_archive_complete_ms'] = (
                    time.monotonic_ns() - packet['result']['capture_accepted_monotonic_ns']) / 1e6
            self.page = self.views.result(packet, 'complete')
        except BaseException as error:
            self.report['captures'][-1].update(save_status='failed', save_error=repr(error),
                archive_latency_ms=(time.perf_counter_ns() - archive_started) / 1e6)
            self.page = self.views.result(packet, 'failed')
            if not isinstance(error, Exception):
                self.persist()
                raise
        self.persist()

    def action(self, action):
        if action in ('menu', 'redraw'):
            if self.controller is not None:
                self.controller.cancel()
            self.pending_packet = None
            self.gate.configure(replace(self.cfg, enable=0), arm=True)
            self.page = self.views.menus[self.flow.selected]
        elif action in ('normal', 'fusion'):
            self.controller.start(action)
            self.cid = self.gate.configure(self.cfg, arm=True)
            self.request_seen = False
            self.page = None
        elif action == 'export':
            self.controller.cancel()
            self.gate.configure(replace(self.cfg, enable=0), arm=True)
            self.pending_packet = None

    async def run_loop(self, seconds):
        started = last_health = time.monotonic()
        submitted = 0
        await self.submit(self.page)
        last_page, last_page_submit = self.page, time.monotonic()
        while seconds is None or time.monotonic() - started < seconds:
            # Do not let a queued retry/back key silently discard a published pending result.
            self.archive_pending()
            for key in self.poller.drain():
                action = self.flow.key(key)
                if action:
                    self.action(action)
            frame = await asyncio.wait_for(self.vin.readframe_async(), 2.)
            self.owned_frame = frame
            self.sequence += 1
            now = time.monotonic()
            if now - last_health >= 1:
                self.video.check_memory(self.video.health(), 'video', self.report)
                last_health = now
            if self.flow.state == 'capture':
                sample = self.gate.snapshot()
                if sample.config_id != self.cid:
                    self.controller.frames.clear()
                else:
                    from reference import evaluate
                    if not self.video.validate_snapshot(sample, self.cfg, self.cid, evaluate):
                        self.controller.frames.clear()
                    else:
                        self.request_seen |= bool(sample.capture_pending and sample.capture_config_id == self.cid)
                        if self.request_seen and len(self.controller.frames) == 2:
                            await self.submit(self.views.processing())
                        packet = (self.controller.consume(frame, sequence=self.sequence, captured_monotonic=now)
                                  if self.request_seen else None)
                        if packet is not None:
                            packet['result'].update(
                                implementation=getattr(self, 'implementation', 'baseline'),
                                png_compress_level=getattr(self, 'png_compress_level', 6),
                                software_round='SYS-Round01',
                                tools_revision=self.report.get('tools_revision'),
                                tools_manifest_sha256=self.report.get('tools_manifest_sha256'))
                            self.pending_packet = packet
                            self.report['captures'].append(packet['result'])
                            self.flow.state = 'result'
                            self.page = self.views.result(packet)
                            self.gate.configure(replace(self.cfg, enable=0), arm=True)
                            frame[:] = self.page
                            await self.write_owned(frame)
                            last_page, last_page_submit = self.page, time.monotonic()
                            submitted += 1
                            packet['result']['first_result_submitted_monotonic_ns'] = time.monotonic_ns()
                            packet['result']['accepted_to_first_result_submission_ms'] = (
                                packet['result']['first_result_submitted_monotonic_ns'] -
                                packet['result']['capture_accepted_monotonic_ns']) / 1e6
                            print('SYSTEM_RISK_RESULT', json.dumps(packet['result'], ensure_ascii=False), flush=True)
                            continue  # First result was submitted before synchronous disk archive.
                if self.flow.state == 'capture':
                    s = asdict(sample)
                    text, level, metrics = self.describe_state(s, asdict(self.cfg))
                    progress = len(self.controller.frames) if self.controller.active else 0
                    self.hud.draw(frame, title=MENU_ITEMS[MODES.index(self.flow.mode)][0],
                                  state_text=text, state_level=level, line2=metrics,
                                  hint='质量复核 %d/3    KEY3 返回菜单' % progress)
            elif self.flow.state == 'export':
                try:
                    exported = export_results(self.output / 'captures')
                    name = Path(exported['archive_path']).name
                    self.page = self.views.message('导出完成', ['归档文件 ' + name,
                        '有效结果 %d    跳过 %d' % (exported['complete_count'], exported['skipped_count']),
                        '文件位于 captures/exports，可通过网页或SSH取回'])
                    self.report.setdefault('exports', []).append(exported)
                    self.flow.state = 'result'
                except Exception as error:
                    self.page = self.views.message('导出失败', ['请检查存储空间与结果完整性'], bad=True)
                    self.flow.state = 'error'
                    self.report.setdefault('export_errors', []).append(repr(error))
                self.persist()
            if self.page is not None:
                # Keep input SOFs flowing, but do not copy a static 3.7MB page every frame.
                if self.page is last_page and now - last_page_submit < 2.:
                    self.owned_frame = None
                    del frame
                    continue
                frame[:] = self.page
            await self.write_owned(frame)
            last_page, last_page_submit = self.page, time.monotonic()
            submitted += 1
        self.archive_pending()
        self.report.update(status='SYSTEM_UI_SESSION_COMPLETE', submitted_frames=submitted,
                           elapsed_seconds=time.monotonic() - started)

    def close(self):
        self.closing = True
        errors = []
        if self.pending_packet is not None:
            # Operator cancellation does not silently start more disk work during shutdown.
            self.pending_packet['result'].update(save_status='not_saved_shutdown',
                save_error='Shutdown before archive; inference remains in system session record')
            self.pending_packet = None
        if self.poller is not None:
            self.poller.stop()
        if self.controller is not None:
            self.controller.cancel()
        if self.gate is not None:
            try:
                self.gate.configure(replace(self.cfg, enable=0), arm=True)
            except BaseException as error:
                errors.append('gate ' + repr(error))
        if self.owns_video:
            # Preserve proven ownership discipline: do not release buffers/UIO while DMA runs.
            while True:
                for video in (self.vin, self.vout):
                    if video is not None:
                        try:
                            video.stop()
                        except BaseException as error:
                            errors.append('video stop ' + repr(error))
                try:
                    dma = self.ol.video.axi_vdma
                    stopped = not dma.writechannel.running and not dma.readchannel.running
                except BaseException as error:
                    stopped = False
                    self.report['cleanup']['video_status_error'] = repr(error)
                if stopped:
                    self.report['cleanup']['video_dma_stopped'] = True
                    self.owned_frame = self.output_owned = None
                    break
                print('VIDEO_STOP_UNCONFIRMED; buffers retained. Power-cycle only if recovery fails.', flush=True)
                try:
                    time.sleep(1)
                except BaseException:
                    pass
        if self.session is not None:
            try:
                self.report['cleanup']['cnn'] = self.session.close()
                errors.extend(self.report['cleanup']['cnn'].get('errors', []))
            except BaseException as error:
                errors.append('CNN close ' + repr(error))
                if self.accel.__dict__.get('_unsafe_dma_context') is not None:
                    self.report.update(status='FAILED_CNN_STOP_PENDING')
                    self.report['cleanup']['errors'] = errors
                    self.persist()
                    raise  # Keep all device/buffer references; never claim safe release.
        if self.loop is not None:
            self.report['cleanup']['cancelled_tasks'] = self.video.cancel_pending(self.loop)
            self.controller = None  # It owns a reference to session.overlay too.
            self.ol = self.vin = self.vout = self.gate = self.session = self.poller = None
            video = dma = None  # Stop-loop locals otherwise retain driver hierarchies.
            gc.collect()
            self.report['cleanup']['uio'] = self.video.release_created_uio(self.loop, self.registry, self.irq_baseline)
            if self.registry is None or not self.registry._uio_devices:
                self.loop.close()
                asyncio.set_event_loop(None)
                self.report['cleanup']['event_loop_closed'] = True
            self.report['health_after'] = self.video.health()
            try:
                count = Path('/sys/fs/ext4/mmcblk0p2/errors_count').read_text().strip()
                self.report['ext4_errors_after'] = int(count)
                if count != '0':
                    errors.append('EXT4 error count ' + count)
            except OSError as error:
                errors.append('EXT4 check ' + repr(error))
        self.report['cleanup']['errors'] = errors
        if errors:
            self.report['status'] = 'FAILED_CLEANUP'
        self.persist()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run', action='store_true', help='Explicitly attach already loaded Round41 hardware')
    parser.add_argument('--seconds', type=int, default=120, choices=range(10, 3601))
    parser.add_argument('--input-timeout', type=int, default=10, choices=range(5, 61))
    parser.add_argument('--active-low', action='store_true')
    parser.add_argument('--implementation', choices=('baseline', 'optimized'), default='optimized',
                        help='Same UI: original quality + PNG6, or exact narrow quality + PNG1')
    parser.add_argument('--output', type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    here = Path(__file__).resolve().parent
    verify_tools(here, args.root)
    if not args.run:
        print('SYS01_PACKAGE_VERIFIED_NO_HARDWARE_ACCESSED; use --run after stopping old UI and loading Round41')
        return 0
    app = SystemApp(args.root.resolve(), here, args.output or here / 'runs',
                    input_timeout=args.input_timeout, active_low=args.active_low,
                    implementation=args.implementation)
    prior = {}
    def interrupted(number, frame):
        if app.closing:
            return
        raise KeyboardInterrupt('operator signal %d' % number)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        prior[number] = signal.signal(number, interrupted)
    code = 0
    try:
        app.open()
        print('SYS01_MENU_READY', args.implementation, flush=True)
        app.loop.run_until_complete(app.run_loop(args.seconds))
    except KeyboardInterrupt:
        app.report['status'] = 'OPERATOR_STOPPED'
    except BaseException as error:
        app.report.update(status='FAILED', error=repr(error))
        print('SYSTEM_UI_ERROR', repr(error), flush=True)
        code = 1
    finally:
        try:
            app.close()
        finally:
            for number, handler in prior.items():
                signal.signal(number, handler)
    print('SYSTEM_UI_RECORD', str(app.record_path), app.report['status'], flush=True)
    return 1 if app.report['status'].startswith('FAILED') else code


if __name__ == '__main__':
    raise SystemExit(main())
