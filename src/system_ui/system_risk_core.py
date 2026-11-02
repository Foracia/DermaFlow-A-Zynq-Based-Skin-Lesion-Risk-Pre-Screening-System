"""PS orchestration for frozen Round41 single-frame / mean-logits inference.

No PYNQ import, bitstream modification, training or working-point fitting.
Three passing delivered images are a quality condition; they are also the
three inference inputs in fusion mode, not three copies of one input.
"""
import math
from numbers import Integral
import time
import uuid

import numpy as np


MODES = ('normal', 'fusion', 'export')
MENU_ITEMS = (
    ('正常模式', '质量合格后单帧推理并保存结果'),
    ('三帧融合推理', '三张合格图像分别推理后融合结果'),
    ('导出结果', '核对并整理已保存图像和结果'),
)


def decide(logits, point):
    values = np.asarray(logits, dtype=np.float64)
    if values.shape != (2,) or not np.isfinite(values).all():
        raise ValueError('Two finite logits required')
    temperature, threshold = float(point['temperature']), float(point['threshold'])
    if (not math.isfinite(temperature) or temperature <= 0 or
            not math.isfinite(threshold) or not 0 <= threshold <= 1 or
            point['positive_class_index'] != 1 or point['comparison'] != '>='):
        raise ValueError('Invalid frozen working point')
    difference = (float(values[1]) - float(values[0])) / temperature
    probability = (1 / (1 + math.exp(-difference)) if difference >= 0
                   else math.exp(difference) / (1 + math.exp(difference)))
    prediction = int(probability >= threshold)
    return dict(logits=values.tolist(), refer_probability=probability,
                decision_threshold=threshold, temperature=temperature,
                positive_class_index=1, comparison='>=', prediction=prediction,
                risk_label='建议就医' if prediction else '暂未提示明显风险')


class RiskController:
    def __init__(self, session, point, config, *, assess_fn, prepare_fn,
                 model_identity, bitstream_version, max_gap_seconds=0.5):
        decide([0., 0.], point)
        if config.stable_n != 3:
            raise ValueError('SYS-Round00 preserves the three-delivered-image condition')
        if not math.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
            raise ValueError('Invalid delivered-image gap')
        self.session, self.point, self.config = session, dict(point), config
        self.assess_fn, self.prepare_fn = assess_fn, prepare_fn
        self.model_identity, self.bitstream_version = model_identity, bitstream_version
        self.max_gap_seconds = max_gap_seconds
        self.last_assessment = None
        self.cancel()

    def cancel(self):
        self.active = False
        self.frames = []
        self.last_sequence = self.last_time = None
        self.last_assessment = None
        self.quality_attempt_count = 0
        self.quality_attempt_total_ms = 0.

    def start(self, mode):
        if mode not in ('normal', 'fusion'):
            raise ValueError('Inference mode must be normal or fusion')
        self.cancel()
        self.mode, self.capture_id = mode, uuid.uuid4().hex
        self.active = True

    def consume(self, frame, *, sequence, captured_monotonic):
        if not self.active:
            raise RuntimeError('Capture has not been armed, or is already complete')
        if (isinstance(sequence, bool) or not isinstance(sequence, Integral) or sequence < 0 or
                not math.isfinite(captured_monotonic) or captured_monotonic < 0):
            raise ValueError('Invalid delivered image identity')
        if self.last_sequence is not None:
            if sequence <= self.last_sequence or captured_monotonic <= self.last_time:
                raise ValueError('Repeated/reordered image identity')
            if sequence != self.last_sequence + 1 or captured_monotonic - self.last_time > self.max_gap_seconds:
                self.frames.clear()
        self.last_sequence, self.last_time = int(sequence), captured_monotonic
        quality_started = time.perf_counter_ns()
        assessment, rgb = self.assess_fn(frame, self.config)
        quality_ms = (time.perf_counter_ns() - quality_started) / 1e6
        self.quality_attempt_count += 1
        self.quality_attempt_total_ms += quality_ms
        self.last_assessment = assessment
        if not assessment['quality_ok']:
            self.frames.clear()
            return None
        rgb = np.asarray(rgb)
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError('Quality assessment must return owned uint8 RGB')
        owned = np.ascontiguousarray(rgb).copy()
        owned.setflags(write=False)
        self.frames.append(dict(rgb=owned, sequence=int(sequence),
                                captured_monotonic=float(captured_monotonic), assessment=assessment,
                                quality_assessment_ms=quality_ms))
        if len(self.frames) < 3:
            return None
        accepted_ns = time.monotonic_ns()
        checked = self.frames
        selected = checked if self.mode == 'fusion' else [checked[-1]]
        self.frames, self.active = [], False
        rows = []
        started = time.perf_counter_ns()
        for retained in selected:
            _, words, metadata = self.prepare_fn(retained['rgb'])
            row = dict(self.session.infer(words))
            values = np.asarray(row['logits'], dtype=np.float64)
            if values.shape != (2,) or not np.isfinite(values).all():
                raise ValueError('CNN returned invalid logits; no partial fusion result')
            retained['input'] = metadata
            rows.append(row)
        mean_logits = np.mean(np.asarray([row['logits'] for row in rows], dtype=np.float64), axis=0)
        result = decide(mean_logits, self.point)
        elapsed_ms = (time.perf_counter_ns() - started) / 1e6
        result.update(
            schema_version=1, capture_id=self.capture_id, mode=self.mode, frame_count=len(selected),
            fusion_method='mean_logits' if self.mode == 'fusion' else 'single_frame',
            model_identity=self.model_identity, bitstream_version=self.bitstream_version,
            inference_latency_ms=elapsed_ms,
            inference_latency_scope='Accepted owned RGB input(s) through preprocessing, packing, CNN API, logits aggregation and frozen probability decision; excludes quality check, display and archive',
            hardware_transaction_total_ms=sum(float(r.get('hardware_transaction_ms', 0.)) for r in rows),
            quality_sequences=[f['sequence'] for f in checked], inferences=rows,
            quality_attempt_count=self.quality_attempt_count,
            quality_attempt_total_ms=self.quality_attempt_total_ms,
            accepted_group_quality_total_ms=sum(f['quality_assessment_ms'] for f in checked),
            quality_timing_scope='Actual assess_frame calls since arming; total includes rejected attempts, accepted-group total includes only the final three passing delivered images',
            capture_accepted_monotonic_ns=accepted_ns,
            hardware_frame_binding_verified=False, source_sof_continuity_verified=False,
            working_point_policy='Existing single-frame point reused by user decision; not refitted for fusion',
            clinical_probability_validated=False, save_status='pending')
        return dict(result=result, frames=selected)
