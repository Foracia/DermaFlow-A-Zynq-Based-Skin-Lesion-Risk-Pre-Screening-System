"""Actual RGB ROI -> frozen CPU FP32 reference -> Round41 packed fixed-point input.

No board access, quality acceptance, model inference or new quantization fitting.
Caller supplies an owned RGB copy already selected/checked by the quality gate.
"""
import hashlib
from contextlib import nullcontext

import numpy as np


def pack_normalized(tensor):
    """Mirror core_rtl_probe: FP32 -> float64, ties-even F4, signed RGB bytes."""
    x=np.asarray(tensor)
    if x.shape!=(1,3,128,128) or x.dtype!=np.float32 or not np.isfinite(x).all():
        raise ValueError('Require finite FP32 RGB NCHW [1,3,128,128]')
    signed=np.clip(np.rint(x.astype(np.float64)*16),-128,127).astype(np.int8)
    rgb=signed[0].transpose(1,2,0).view(np.uint8).astype(np.uint32)
    words=rgb[:,:,0] | (rgb[:,:,1]<<8) | (rgb[:,:,2]<<16)
    return np.ascontiguousarray(words.reshape(-1),dtype='<u4')


def prepare_roi(rgb,profiler=None):
    """Reuse the accepted CPU preprocessing function; keep all three boundaries."""
    span=profiler.span if profiler is not None else lambda name:nullcontext()
    with span('preprocess_imports'):
        try:
            from quantization.board_cpu_baseline.verify_ncnn import preprocess_rgb_uint8
        except ModuleNotFoundError as error:
            if error.name not in ('quantization','quantization.board_cpu_baseline','quantization.board_cpu_baseline.verify_ncnn'):
                raise
            # Standalone board package includes an unchanged copy of this helper.
            from verify_ncnn import preprocess_rgb_uint8
    rgb=np.asarray(rgb)
    with span('resize_normalize'):tensor=preprocess_rgb_uint8(rgb)
    with span('quantize_pack'):words=pack_normalized(tensor)
    with span('input_metadata'):
        rounded=np.rint(tensor.astype(np.float64)*16)
        record=dict(
            roi_shape=list(rgb.shape),roi_rgb_sha256=hashlib.sha256(rgb.tobytes(order='C')).hexdigest(),
            tensor_shape=list(tensor.shape),tensor_dtype='float32',tensor_layout='NCHW RGB',
            tensor_sha256=hashlib.sha256(tensor.astype('<f4',copy=False).tobytes()).hexdigest(),
            packed_shape=list(words.shape),packed_dtype='little-endian uint32',packed_nbytes=int(words.nbytes),
            packed_sha256=hashlib.sha256(words.tobytes()).hexdigest(),
            pixel_order='row-major HWC; R bits7:0, G bits15:8, B bits23:16, top byte zero',
            quantization='signed8 F4, step1/16, zero0, float64 multiply then ties-even rounding and saturation',
            saturated_values=int(np.count_nonzero((rounded < -128) | (rounded > 127))),
            normalized_min=float(tensor.min()),normalized_max=float(tensor.max()),
            model_executed=False,quality_acceptance_verified_by_this_module=False)
    return tensor,words,record
