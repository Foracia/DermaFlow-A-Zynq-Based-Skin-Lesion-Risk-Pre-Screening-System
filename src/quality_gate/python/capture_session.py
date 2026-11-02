"""Bounded PL request + software same-image recheck; caller owns device setup.

Does not load an overlay, open a network connection, save a file or invoke CNN.
PL requests are scheduling hints, never proof of a VDMA image's frame identity.
"""
import asyncio
from dataclasses import asdict, replace
import math
import time

try:
    from .frame_quality import SameFrameCaptureGate
except ImportError:
    from frame_quality import SameFrameCaptureGate


async def capture_bounded(gate, vin, vout, *, config, seconds=10.0, warmup=1.0,
                          max_gap_seconds=0.5, stop_requested=None, health=None, record=None):
    """Run at most 20 s of video and return (record, accepted RGB ROI or None).

    Cancellation/stop/input stalls always disable the gate and stop both devices.
    Caller must additionally bound overlay/HDMI setup and close its owned kernel.
    New, explicit configuration required; there is no auto-calibrated default.
    """
    for name, value in [('seconds', seconds), ('warmup', warmup)]:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(name+' must be finite')
    if not 0.5 <= seconds <= 20 or not 0 <= warmup < seconds:
        raise ValueError('Require 0.5..20 seconds and 0 <= warmup < seconds')
    checker = SameFrameCaptureGate(config, max_gap_seconds=max_gap_seconds)
    outcome = record if record is not None else {}
    outcome.update(schema_version=1, status='starting', frames=0, checked_frames=0,
                   config=asdict(config), seconds_limit=seconds, warmup_seconds=warmup,
                   cleanup={}, health=[], hardware_frame_binding_verified=False,
                   capture_policy='matching_PL_request_then_N_delivered_images_software_rechecked',
                   semantic_rejection_implemented=False, cnn_invoked=False)
    started = None
    owned = capture = None
    primary_error = False
    request = None
    latest_hw_frame = last_hw_progress = None
    distinct_hw_results = 0

    def check_memory(stage):
        if health is None:
            return
        sample = health(stage)
        outcome['health'].append(sample)
        available = 180 if stage == 'before_video' else 96
        cma = 48 if stage == 'before_video' else 8
        if sample['MemAvailable_kB'] < available*1024 or sample['CmaFree_kB'] < cma*1024:
            raise RuntimeError('Memory reserve reached')

    try:
        cid = gate.configure(config, arm=True)
        outcome['config_id'] = cid
        check_memory('before_video')
        vin.start()
        vout.start()
        started = time.monotonic()
        last_health = started
        outcome['status'] = 'running'
        while time.monotonic()-started < seconds:
            if stop_requested is not None and stop_requested.is_set():
                outcome['status'] = 'stopped'
                break
            remaining = seconds-(time.monotonic()-started)
            if remaining <= 0:
                break
            try:
                owned = await asyncio.wait_for(vin.readframe_async(), min(0.25, remaining))
            except asyncio.TimeoutError:
                if time.monotonic()-started >= seconds:
                    break
                # A bounded input wait lets an explicit stop be observed promptly.
                # Missing input also breaks any passing streak.
                checker.rearm()
                if stop_requested is not None and stop_requested.is_set():
                    outcome['status'] = 'stopped'
                    break
                if time.monotonic()-started >= 2 and outcome['frames'] == 0:
                    raise RuntimeError('HDMI input is not delivering frames')
                if outcome.get('last_frame_monotonic') is not None and time.monotonic()-outcome['last_frame_monotonic'] >= 2:
                    raise RuntimeError('HDMI input stopped delivering frames')
                continue
            now = time.monotonic()
            outcome['frames'] += 1
            outcome['last_frame_monotonic'] = now
            sample = gate.snapshot()
            if sample.present and sample.config_id == cid:
                if (sample.x0, sample.y0, sample.width, sample.height) != (config.x0, config.y0, config.width, config.height):
                    raise RuntimeError('Hardware result ROI differs from committed config')
                if sample.frame_id != latest_hw_frame:
                    latest_hw_frame, last_hw_progress = sample.frame_id, now
                    distinct_hw_results += 1
                if sample.capture_pending and sample.capture_config_id == cid:
                    request = dict(frame_id=sample.capture_frame_id, config_id=sample.capture_config_id)
            elif sample.present:
                raise RuntimeError('Unexpected hardware configuration; exclusive ownership lost')
            if request is not None and last_hw_progress is not None and now-last_hw_progress > 1:
                raise RuntimeError('Hardware quality results stopped progressing')
            if now-started >= warmup and request is not None and distinct_hw_results >= 2:
                if not (sample.present and sample.config_id == cid and sample.valid):
                    checker.rearm()
                else:
                    event, capture = checker.consume(owned, sequence=outcome['frames'], captured_monotonic=now)
                    outcome['checked_frames'] += 1
                    outcome['last_event'] = event
                    if capture is not None:
                        capture.metadata['hardware_request_hint'] = request
                        capture.metadata['hardware_config_id'] = cid
            remaining = seconds-(time.monotonic()-started)
            if remaining <= 0:
                capture = None  # do not save a result after the session deadline
                break
            await asyncio.wait_for(vout.writeframe_async(owned), min(0.5, remaining))
            owned = None  # ownership transferred; no reading/drawing/freeing afterwards
            if capture is not None:
                outcome['status'] = 'captured'
                outcome['capture'] = capture.metadata
                break
            if time.monotonic()-last_health >= 2:
                check_memory('video')
                last_health = time.monotonic()
        if outcome['status'] == 'running':
            outcome['status'] = 'timeout_no_capture'
    except BaseException:
        primary_error = True
        outcome['status'] = 'failed'
        raise
    finally:
        outcome['video_seconds'] = time.monotonic()-started if started is not None else 0
        errors = []
        try:
            gate.configure(replace(config, enable=0), arm=True)
            outcome['cleanup']['disabled_and_request_cleared'] = True
        except Exception as error:
            errors.append('gate: '+repr(error))
        for name, device in [('input', vin), ('output', vout)]:
            try:
                device.stop()
                outcome['cleanup'][name+'_stopped'] = True
            except Exception as error:
                errors.append(name+': '+repr(error))
        owned = None
        outcome['cleanup']['errors'] = errors
        if errors:
            outcome['status'] = 'failed'
            if not primary_error:
                raise RuntimeError('Cleanup failed: '+'; '.join(errors))
    return outcome, capture
