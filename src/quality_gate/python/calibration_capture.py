"""Board-side bounded sampler. Caller owns/configures devices and closes its kernel.

This module does not load overlays, infer human labels, save images, or call CNN.
"""
import asyncio
from dataclasses import asdict, replace
import math
import time

try:
    from .reference import Config
except ImportError:
    from reference import Config


async def collect_bounded(gate, vin, vout, *, config=None, seconds=8.0,
                          warmup=1.0, sample_interval=0.1, record=None, health=None):
    """Start exclusive video devices and always disable/stop them on completion.

    config supplies ROI and dark/bright levels; acceptance thresholds are relaxed
    for acquisition. Human condition/split metadata is supplied by the host.
    """
    for name, value in [('seconds', seconds), ('warmup', warmup), ('sample_interval', sample_interval)]:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(name + ' must be a finite number')
    if not 0.5 <= seconds <= 10 or not 0 <= warmup < seconds or not 0.05 <= sample_interval <= 1:
        raise ValueError('Require 0.5..10 seconds, shorter warmup, and 0.05..1 second sampling interval')
    if config is None:
        config = Config()
    if not isinstance(config, Config):
        raise TypeError('config must be Config')
    cfg = replace(config, enable=1, mean_min=0, mean_max=255, dark_max_bp=10000,
                  bright_max_bp=10000, sharp_min=0)
    result = record if record is not None else {}
    result.update(seconds_limit=seconds, warmup_seconds=warmup, frames=0, samples=[],
                  config=asdict(cfg), cleanup={}, health=[])
    started = None
    primary_error = False
    owned = None
    try:
        result['config_id'] = gate.configure(cfg, arm=False)
        if health:
            snapshot = health('before_video')
            result['health'].append(snapshot)
            if snapshot['MemAvailable_kB'] < 180 * 1024 or snapshot['CmaFree_kB'] < 48 * 1024:
                raise RuntimeError('Insufficient memory before video')
        vin.start()
        vout.start()
        started = time.monotonic()
        result['started_monotonic'] = started
        last_poll = -1.0
        last_health = started
        last_frame = None
        while time.monotonic() - started < seconds:
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                owned = await asyncio.wait_for(vin.readframe_async(), timeout=min(2, remaining))
            except asyncio.TimeoutError:
                if time.monotonic() - started >= seconds - 0.02:
                    break
                raise RuntimeError('HDMI input stopped delivering frames')
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(vout.writeframe_async(owned), timeout=min(2, remaining))
            except asyncio.TimeoutError:
                if time.monotonic() - started >= seconds - 0.02:
                    break
                raise RuntimeError('HDMI output stopped accepting frames')
            owned = None  # ownership transferred to the output driver
            result['frames'] += 1
            elapsed = time.monotonic() - started
            if elapsed >= warmup and elapsed - last_poll >= sample_interval:
                sample = gate.snapshot()
                last_poll = elapsed
                if (sample.present and sample.config_id == result['config_id']
                        and sample.frame_id != last_frame):
                    if (sample.x0, sample.y0, sample.width, sample.height) != (cfg.x0, cfg.y0, cfg.width, cfg.height):
                        raise RuntimeError('Result ROI differs from committed configuration')
                    if (sample.pixel_count != cfg.width * cfg.height or
                            sample.gradient_count != (cfg.width - 2) * (cfg.height - 2)):
                        raise RuntimeError('Invalid hardware statistics counts')
                    item = asdict(sample)
                    item['elapsed'] = elapsed
                    result['samples'].append(item)
                    last_frame = sample.frame_id
                    if not sample.valid:
                        raise RuntimeError('Hardware reported an invalid input frame')
            if health and time.monotonic() - last_health >= 2:
                snapshot = health('video')
                result['health'].append(snapshot)
                if snapshot['MemAvailable_kB'] < 96 * 1024 or snapshot['CmaFree_kB'] < 8 * 1024:
                    raise RuntimeError('Memory reserve reached; stop short acquisition')
                last_health = time.monotonic()
        if len(result['samples']) < 2:
            raise RuntimeError('Insufficient distinct valid quality frames; check result progress')
    except BaseException:
        primary_error = True
        raise
    finally:
        result['video_seconds'] = time.monotonic() - started if started is not None else 0
        errors = []
        try:
            gate.configure(replace(cfg, enable=0), arm=True)
            result['cleanup']['disabled_and_request_cleared'] = True
        except Exception as error:
            errors.append('gate: ' + repr(error))
        for name, device in [('input', vin), ('output', vout)]:
            try:
                device.stop()
                result['cleanup'][name + '_stopped'] = True
            except Exception as error:
                errors.append(name + ': ' + repr(error))
        owned = None
        result['cleanup']['errors'] = errors
        if errors and not primary_error:
            raise RuntimeError('Cleanup failed: ' + '; '.join(errors))
    return result
