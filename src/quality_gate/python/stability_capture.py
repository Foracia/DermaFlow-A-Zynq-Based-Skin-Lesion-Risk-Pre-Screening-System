"""Bounded video/quality resource checks; no image saving or classifier calls."""
import asyncio
from dataclasses import asdict, replace
import math
import time

try:
    from .frame_quality import assess_frame
    from .reference import evaluate
except ImportError:
    from frame_quality import assess_frame
    from reference import evaluate


async def check_stability(gate, vin, vout, *, config, durations=(20, 20, 120),
                          health, sample_interval=5.0, software_interval=2.0,
                          stop_requested=None, record=None, progress=None):
    """Exercise start/stop cycles and streaming for at most 180 video seconds.

    health(stage) supplies MemAvailable_kB/CmaFree_kB/SwapFree_kB/Rss_kB.
    Caller bounds setup, verifies DMA idle, and closes its owned kernel.
    Resource limits are engineering checks, not lifetime reliability claims.
    """
    if (not durations or len(durations) > 3
            or any(type(x) not in (int, float) or not math.isfinite(x) or not .2 <= x <= 120 for x in durations)
            or sum(durations) > 180):
        raise ValueError('Require 1..3 bounded phases, each .2..120 s, total <=180 s')
    for value in (sample_interval, software_interval):
        if type(value) not in (int, float) or not math.isfinite(value) or not .02 <= value <= 10:
            raise ValueError('Sampling intervals must be finite and within .02..10 s')
    r = record if record is not None else {}
    r.update(status='running', config=asdict(config), phases=[], video_limit_seconds=sum(durations),
             cnn_invoked=False, images_saved=False, hardware_frame_binding_verified=False)
    initial_swap = None

    def memory(stage, phase=None, elapsed=0):
        nonlocal initial_swap
        h = dict(health(stage), elapsed=elapsed)
        if initial_swap is None: initial_swap = h['SwapFree_kB']
        if phase is not None: phase['health'].append(h)
        available, cma = (180, 48) if stage == 'before_video' else (96, 8)
        if h['MemAvailable_kB'] < available*1024 or h['CmaFree_kB'] < cma*1024:
            raise RuntimeError('Memory/CMA reserve reached')
        if initial_swap-h['SwapFree_kB'] > 4096:
            raise RuntimeError('More than 4 MiB additional swap use')
        return h

    for index, seconds in enumerate(durations, 1):
        phase = dict(index=index, seconds_limit=seconds, frames=0, results=0,
                     software_checks=0, health=[], cleanup={}, status='running')
        r['phases'].append(phase)
        started = None
        owned = None
        primary_error = False
        try:
            phase['config_id'] = gate.configure(config, arm=False)
            memory('before_video', phase)
            vin.start(); vout.start()
            started = time.monotonic()
            if progress: progress('phase_start', dict(index=index, seconds=seconds))
            last_poll = last_software = last_health = 0
            last_result_at = None
            last_frame = None
            while time.monotonic()-started < seconds:
                if stop_requested is not None and stop_requested.is_set():
                    raise asyncio.CancelledError('Explicit stability stop')
                remaining = seconds-(time.monotonic()-started)
                if remaining <= 0: break
                try:
                    owned = await asyncio.wait_for(vin.readframe_async(), min(2, remaining))
                except asyncio.TimeoutError:
                    if time.monotonic()-started >= seconds-.03: break
                    raise RuntimeError('HDMI input stopped delivering frames')
                elapsed = time.monotonic()-started
                if elapsed-last_poll >= min(.2, sample_interval):
                    s = gate.snapshot(); last_poll = elapsed
                    if s.present and s.config_id == phase['config_id'] and s.frame_id != last_frame:
                        if (s.x0,s.y0,s.width,s.height) != (config.x0,config.y0,config.width,config.height):
                            raise RuntimeError('Result ROI mismatch')
                        stats = {k:getattr(s,k) for k in ('pixel_count','luma_sum','dark_count','bright_count','gradient_count','gradient_sum')}
                        if not s.valid or (s.valid,s.exposure_ok,s.sharpness_ok,s.quality_ok) != evaluate(stats,config,gate.frame_width,gate.frame_height):
                            raise RuntimeError('Invalid result or hardware predicate mismatch')
                        phase['results'] += 1
                        last_frame = s.frame_id; last_result_at = elapsed
                if elapsed > 3 and (last_result_at is None or elapsed-last_result_at > 2):
                    raise RuntimeError('Quality results stopped progressing')
                if elapsed-last_software >= software_interval:
                    a, roi = assess_frame(owned, config)
                    if not a['valid']: raise RuntimeError('Software statistics invalid')
                    phase['software_checks'] += 1
                    phase['last_software_metrics'] = a['metrics']
                    roi = None  # no pixel history retained
                    last_software = time.monotonic()-started
                remaining = seconds-(time.monotonic()-started)
                if remaining <= 0: break
                try:
                    await asyncio.wait_for(vout.writeframe_async(owned), min(2, remaining))
                except asyncio.TimeoutError:
                    if time.monotonic()-started >= seconds-.03: break
                    raise RuntimeError('HDMI output stopped accepting frames')
                owned = None  # output owns the buffer now
                phase['frames'] += 1
                elapsed = time.monotonic()-started
                if elapsed-last_health >= sample_interval:
                    h = memory('video', phase, elapsed)
                    if progress: progress('health', dict(index=index, **h))
                    settled = [x for x in phase['health'] if x.get('stage') == 'video' and x['elapsed'] >= min(10,seconds/3)]
                    if len(settled) >= 2 and h['Rss_kB']-settled[0]['Rss_kB'] > 16384:
                        raise RuntimeError('RSS grew more than 16 MiB after warmup')
                    last_health = elapsed
            if phase['frames'] == 0 or phase['results'] < 2:
                raise RuntimeError('Insufficient video/result progress')
            settled = [x for x in phase['health'] if x.get('stage') == 'video' and x['elapsed'] >= min(10,seconds/3)]
            if len(settled) >= 2:
                phase['settled_rss_growth_kB'] = settled[-1]['Rss_kB']-settled[0]['Rss_kB']
                phase['settled_cma_span_kB'] = max(x['CmaFree_kB'] for x in settled)-min(x['CmaFree_kB'] for x in settled)
                if phase['settled_rss_growth_kB'] > 8192 or phase['settled_cma_span_kB'] > 8192:
                    raise RuntimeError('Settled RSS growth or CMA variation exceeded 8 MiB')
            phase['status'] = 'complete'
        except BaseException:
            primary_error = True
            phase['status'] = r['status'] = 'failed'
            raise
        finally:
            phase['video_seconds'] = time.monotonic()-started if started is not None else 0
            phase['fps'] = phase['frames']/phase['video_seconds'] if phase['video_seconds'] else 0
            errors = []
            try:
                gate.configure(replace(config,enable=0),arm=True)
                phase['cleanup']['gate_disabled_request_cleared'] = True
            except Exception as e: errors.append('gate '+repr(e))
            for name, device in [('input',vin),('output',vout)]:
                try: device.stop(); phase['cleanup'][name+'_stopped'] = True
                except Exception as e: errors.append(name+' '+repr(e))
            owned = None
            phase['cleanup']['errors'] = errors
            if errors:
                phase['status'] = r['status'] = 'failed'
                if not primary_error: raise RuntimeError('Cleanup failed: '+'; '.join(errors))
        phase['after_stop_health'] = memory('after_phase')
        if progress: progress('phase_stopped',dict(index=index,frames=phase['frames'],fps=phase['fps']))
        await asyncio.sleep(0)
    r['status'] = 'complete'
    return r
