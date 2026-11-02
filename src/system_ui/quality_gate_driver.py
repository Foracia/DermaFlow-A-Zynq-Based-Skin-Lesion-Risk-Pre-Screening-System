"""PYNQ-compatible quality-gate ABI v2 driver. Backend needs read/write(offset, value).

One configuration writer owns an IP instance. Snapshot reads detect other readers
replacing the global frozen snapshot; no PYNQ import is needed for offline tests.
"""
from dataclasses import dataclass
from numbers import Integral
import math
import threading
import time

try:
    from .reference import Config
except ImportError:
    from reference import Config

ABI_ID = 0x51475402
COMMAND, COMMIT_ID, LIVE_STATUS = 0x04, 0x08, 0x0C
SNAPSHOT_SEQ, DIMENSIONS = 0x14, 0x1C
SHADOW_BASE, SNAPSHOT_BASE = 0x20, 0x40
APPLY, REARM, SNAPSHOT = 1, 2, 4
MASK32 = 0xFFFFFFFF


@dataclass(frozen=True)
class Result:
    snapshot_seq: int
    frame_id: int
    config_id: int
    present: bool
    valid: bool
    exposure_ok: bool
    sharpness_ok: bool
    quality_ok: bool
    stable_ok: bool
    frame_state: int
    stable_count: int
    x0: int
    y0: int
    width: int
    height: int
    pixel_count: int
    luma_sum: int
    dark_count: int
    bright_count: int
    gradient_count: int
    gradient_sum: int
    capture_pending: bool
    capture_frame_id: int
    capture_config_id: int

    @property
    def mean_luma(self):
        return self.luma_sum / self.pixel_count if self.pixel_count else None

    @property
    def dark_ratio(self):
        return self.dark_count / self.pixel_count if self.pixel_count else None

    @property
    def bright_ratio(self):
        return self.bright_count / self.pixel_count if self.pixel_count else None

    @property
    def sharpness_score(self):
        return self.gradient_sum / self.gradient_count if self.gradient_count else None


class QualityGate:
    def __init__(self, mmio):
        self.mmio = mmio
        self._lock = threading.RLock()
        actual = self._read(0)
        if actual != ABI_ID:
            raise RuntimeError(f'Quality-gate ABI mismatch: expected {ABI_ID:#x}, got {actual:#x}')
        dimensions = self._read(DIMENSIONS)
        self.frame_width = dimensions & 0xFFFF
        self.frame_height = dimensions >> 16
        if not (3 <= self.frame_width <= 4095 and 3 <= self.frame_height <= 4095
                and self.frame_width * self.frame_height <= 1048575):
            raise RuntimeError('Invalid hardware frame dimensions')

    def _read(self, offset):
        return int(self.mmio.read(offset)) & MASK32

    def _write(self, offset, value):
        self.mmio.write(offset, int(value) & MASK32)

    def _validate(self, cfg):
        if not isinstance(cfg, Config):
            raise TypeError('cfg must be a Config instance')
        limits = dict(enable=(0, 1), x0=(0, 4095), y0=(0, 4095),
                      width=(3, 4095), height=(3, 4095), mean_min=(0, 255),
                      mean_max=(0, 255), dark_level=(0, 255), bright_level=(0, 255),
                      dark_max_bp=(0, 10000), bright_max_bp=(0, 10000),
                      sharp_min=(0, 2040), stable_n=(1, 255))
        for field, (low, high) in limits.items():
            value = getattr(cfg, field)
            if not isinstance(value, Integral) or not low <= value <= high:
                raise ValueError(f'{field} must be an integer in [{low}, {high}]')
        if cfg.x0 + cfg.width > self.frame_width or cfg.y0 + cfg.height > self.frame_height:
            raise ValueError('ROI extends outside the hardware frame')
        if cfg.mean_min > cfg.mean_max:
            raise ValueError('mean_min exceeds mean_max')
        if cfg.dark_level >= cfg.bright_level:
            raise ValueError('dark_level must be below bright_level')

    def configure(self, cfg, *, arm=False):
        """Atomically commit six shadow words; return submitted configuration ID.

        The ID is submitted, not proof it has reached SOF. Use wait_for_result
        with config_id=returned_id to observe a result computed with it.
        A repeated APPLY creates a new ID and restarts the quality streak.
        """
        self._validate(cfg)
        if not isinstance(arm, bool):
            raise TypeError('arm must be bool')
        words = [cfg.x0 | cfg.y0 << 16, cfg.width | cfg.height << 16,
                 cfg.mean_min | cfg.mean_max << 8 | cfg.dark_level << 16 | cfg.bright_level << 24,
                 cfg.dark_max_bp | cfg.bright_max_bp << 16,
                 cfg.sharp_min | cfg.stable_n << 16, cfg.enable]
        with self._lock:
            expected = (self._read(COMMIT_ID) + 1) & MASK32
            for i, word in enumerate(words):
                self._write(SHADOW_BASE + 4*i, word)
            self._write(COMMAND, APPLY | (REARM if arm else 0))
            actual = self._read(COMMIT_ID)
            if actual != expected:
                raise RuntimeError('Configuration commit ID changed unexpectedly; ensure one configuration writer')
            return actual

    def rearm(self):
        """Clear the held request and allow one new trigger; does not capture a frame."""
        with self._lock:
            self._write(COMMAND, REARM)

    def snapshot(self, *, retries=3):
        """Return one frozen result and separately labelled held capture-event metadata."""
        if not isinstance(retries, Integral) or retries < 1:
            raise ValueError('retries must be a positive integer')
        with self._lock:
            for _ in range(retries):
                self._write(COMMAND, SNAPSHOT)
                before = self._read(SNAPSHOT_SEQ)
                words = [self._read(SNAPSHOT_BASE + 4*i) for i in range(14)]
                after = self._read(SNAPSHOT_SEQ)
                if before == after:
                    flags = words[1]
                    return Result(snapshot_seq=after, frame_id=words[0], config_id=words[2],
                                  present=bool(flags & 1 << 16), valid=bool(flags & 1),
                                  exposure_ok=bool(flags & 2), sharpness_ok=bool(flags & 4),
                                  quality_ok=bool(flags & 8), stable_ok=bool(flags & 16),
                                  frame_state=(flags >> 6) & 3, stable_count=(flags >> 8) & 255,
                                  x0=words[3] & 4095, y0=(words[3] >> 16) & 4095,
                                  width=words[4] & 4095, height=(words[4] >> 16) & 4095,
                                  pixel_count=words[5], luma_sum=words[6], dark_count=words[7],
                                  bright_count=words[8], gradient_count=words[9], gradient_sum=words[10],
                                  capture_pending=bool(words[11] & 1), capture_frame_id=words[12],
                                  capture_config_id=words[13])
        raise RuntimeError('Snapshot was replaced during reads; coordinate concurrent snapshot clients')

    def wait_for_result(self, *, after_frame_id=None, config_id=None, timeout=2.0, poll_interval=0.01):
        """Wait for a new published result, including invalid-quality results for diagnostics.

        Frame IDs wrap, so new means unequal, not numerically greater. A reset
        also changes IDs; callers must treat a board reset as a new session.
        """
        if not math.isfinite(timeout) or not math.isfinite(poll_interval) or timeout <= 0 or poll_interval < 0:
            raise ValueError('timeout must be positive and poll_interval nonnegative')
        deadline = time.monotonic() + timeout
        while True:
            result = self.snapshot()
            if (result.present and (after_frame_id is None or result.frame_id != after_frame_id)
                    and (config_id is None or result.config_id == config_id)):
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('No matching new frame result; check video input and configuration ID')
            time.sleep(min(poll_interval, remaining))
