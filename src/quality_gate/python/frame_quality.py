"""Quality checks on the pixels actually retained for a capture.

RGB/RGBA uint8 only. No PYNQ, camera, network, disease classifier or threshold
learning. Consumer sequence numbers are NOT FPGA frame IDs. This software check
does not establish correspondence between PL statistics and a VDMA buffer.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import io
import json
import math
from numbers import Integral
from pathlib import Path
import uuid

import numpy as np

try:
    from .calibration import config_from_run
    from .reference import Config, display_statistics, evaluate
except ImportError:
    from calibration import config_from_run
    from reference import Config, display_statistics, evaluate


def assess_frame(frame, config):
    """Copy an unannotated ROI, then measure and judge that exact owned copy.

    Caller must keep the input buffer exclusively owned during this call and
    invoke it BEFORE handing the buffer to display/DMA or drawing a HUD.
    Returns (JSON-compatible assessment, owned RGB ROI).
    """
    if not isinstance(config, Config):
        raise TypeError('config must be Config')
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] not in (3, 4)):
        raise ValueError('Expected uint8 HxWx3 RGB or HxWx4 RGBA pixels')
    h, w = frame.shape[:2]
    config_from_run(dict(config=asdict(config), frame_width=w, frame_height=h))
    c = config
    rgb = frame[c.y0:c.y0+c.height, c.x0:c.x0+c.width, :3].copy(order='C')
    p = rgb.astype(np.int32)
    y = (77*p[:, :, 0] + 150*p[:, :, 1] + 29*p[:, :, 2] + 128) >> 8
    gx = (y[:-2, 2:] + 2*y[1:-1, 2:] + y[2:, 2:]
          - y[:-2, :-2] - 2*y[1:-1, :-2] - y[2:, :-2])
    gy = (y[2:, :-2] + 2*y[2:, 1:-1] + y[2:, 2:]
          - y[:-2, :-2] - 2*y[:-2, 1:-1] - y[:-2, 2:])
    stats = dict(pixel_count=c.width*c.height, luma_sum=int(y.sum(dtype=np.int64)),
                 dark_count=int((y < c.dark_level).sum()),
                 bright_count=int((y > c.bright_level).sum()),
                 gradient_count=(c.width-2)*(c.height-2),
                 gradient_sum=int((abs(gx)+abs(gy)).sum(dtype=np.int64)))
    valid, exposure, sharp, quality = evaluate(stats, c, w, h)
    reasons = []
    if not valid:
        reasons.append('disabled_or_invalid')
    else:
        n = stats['pixel_count']
        if stats['luma_sum'] < c.mean_min*n: reasons.append('mean_too_dark')
        if stats['luma_sum'] > c.mean_max*n: reasons.append('mean_too_bright')
        if stats['dark_count']*10000 > c.dark_max_bp*n: reasons.append('too_many_dark_pixels')
        if stats['bright_count']*10000 > c.bright_max_bp*n: reasons.append('too_many_bright_pixels')
        if not sharp: reasons.append('insufficient_gradient')
    return dict(stats=stats, metrics=display_statistics(stats), valid=valid,
                exposure_ok=exposure, sharpness_ok=sharp, quality_ok=quality,
                reasons=reasons, config=asdict(c), frame_width=w, frame_height=h,
                roi_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest()), rgb


@dataclass(frozen=True)
class Capture:
    rgb: np.ndarray
    metadata: dict


class SameFrameCaptureGate:
    """One-shot capture after N consecutive *delivered* passing images.

    This supplements the existing PL gate; it never relabels a consumer sequence
    as a PL frame_id. Gaps, stale frames and invalid pixels break the streak.
    Bounded storage: no frame history, only the final accepted ROI is returned.
    No claim of camera calibration or suitability for disease diagnosis.
    """
    def __init__(self, config, *, max_gap_seconds=0.5):
        if not isinstance(config, Config):
            raise TypeError('config must be Config')
        # Validate all fields without allocating an image.
        config_from_run(dict(config=asdict(config),
                             frame_width=max(3, config.x0+config.width),
                             frame_height=max(3, config.y0+config.height)))
        if (type(max_gap_seconds) not in (int, float) or not math.isfinite(max_gap_seconds)
                or max_gap_seconds <= 0):
            raise ValueError('max_gap_seconds must be finite and positive')
        self._config = config
        self.max_gap_seconds = max_gap_seconds
        self.rearm()

    @property
    def config(self):
        return self._config

    def rearm(self):
        self.arm_id = str(uuid.uuid4())
        self.streak = 0
        self.last_sequence = self.last_time = self.last_shape = None
        self.latched = False

    def consume(self, frame, *, sequence, captured_monotonic):
        """Return (event, Capture or None). sequence is caller-owned and increasing.

        Call once for every delivered image. Dropped/unobserved source frames
        remain possible; this is not N consecutive HDMI SOFs. A fresh controller
        is required for a different configuration or source session.
        """
        if self.latched:
            raise RuntimeError('Capture already latched; explicitly rearm before consuming more')
        if (isinstance(sequence, bool) or not isinstance(sequence, Integral) or sequence < 0
                or type(captured_monotonic) not in (int, float)
                or not math.isfinite(captured_monotonic) or captured_monotonic < 0):
            self.streak = 0
            raise ValueError('Require nonnegative integer sequence and finite monotonic timestamp')
        sequence = int(sequence)
        if self.last_sequence is not None and (sequence <= self.last_sequence or captured_monotonic <= self.last_time):
            self.streak = 0
            return dict(status='discarded', reason='stale_sequence_or_timestamp', stable_count=0), None
        interrupted = self.last_sequence is not None and (
            sequence != self.last_sequence+1 or captured_monotonic-self.last_time > self.max_gap_seconds)
        self.last_sequence, self.last_time = sequence, captured_monotonic
        try:
            assessment, rgb = assess_frame(frame, self.config)
        except BaseException:
            self.streak = 0
            raise
        shape = (assessment['frame_width'], assessment['frame_height'])
        if interrupted or (self.last_shape is not None and shape != self.last_shape):
            self.streak = 0
        self.last_shape = shape
        self.streak = min(self.config.stable_n, self.streak+1) if assessment['quality_ok'] else 0
        accepted = self.streak >= self.config.stable_n
        event = dict(status='capture_ready' if accepted else 'waiting' if assessment['quality_ok'] else 'rejected',
                     arm_id=self.arm_id, consumer_sequence=sequence, captured_monotonic=captured_monotonic,
                     stable_count=self.streak, continuity_reset=bool(interrupted), assessment=assessment)
        if not accepted:
            return event, None
        self.latched = True
        metadata = dict(schema_version=1, scope='same_pixels_software_quality_recheck',
                        configuration_status='caller_supplied_not_certified_by_this_module',
                        hardware_frame_binding_verified=False, source_sof_continuity_verified=False,
                        sequence_scope='consumer_delivered_images', semantic_rejection_implemented=False,
                        cnn_invoked=False, event=event)
        rgb.setflags(write=False)
        return event, Capture(rgb=rgb, metadata=metadata)


def save_capture(capture, destination):
    """Save a fresh directory containing lossless ROI PNG and its pixel-bound record.

    Refuses mutated/mismatched pixels and never overwrites an existing capture.
    A directory without a complete capture.json is an incomplete artifact.
    """
    from PIL import Image
    assessment = capture.metadata['event']['assessment']
    cfg = Config(**assessment['config'])
    event = capture.metadata['event']
    if (event['status'] != 'capture_ready' or not assessment['quality_ok']
            or event['stable_count'] < cfg.stable_n):
        raise ValueError('Capture does not contain a passing latched decision')
    if capture.rgb.dtype != np.uint8 or capture.rgb.shape != (cfg.height, cfg.width, 3):
        raise ValueError('Capture pixels have changed shape or dtype')
    digest = hashlib.sha256(capture.rgb.tobytes()).hexdigest()
    if digest != assessment['roi_rgb_sha256']:
        raise ValueError('Capture pixels no longer match the assessed ROI')
    recomputed, _ = assess_frame(capture.rgb, replace(cfg, x0=0, y0=0))
    if not recomputed['quality_ok'] or recomputed['stats'] != assessment['stats']:
        raise ValueError('Saved pixels do not reproduce the passing statistics')
    buffer = io.BytesIO()
    Image.fromarray(capture.rgb).save(buffer, format='PNG')
    data = buffer.getvalue()
    metadata = dict(capture.metadata, artifact=dict(file='capture.png', png_sha256=hashlib.sha256(data).hexdigest(),
                                                   rgb_sha256=digest, width=cfg.width, height=cfg.height))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination/'capture.png').open('xb') as output:
        output.write(data)
    with (destination/'capture.json').open('x', encoding='utf-8') as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2, allow_nan=False)
    return metadata
