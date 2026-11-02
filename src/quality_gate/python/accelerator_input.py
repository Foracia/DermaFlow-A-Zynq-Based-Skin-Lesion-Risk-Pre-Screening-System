"""Verified quality ROI -> model-contract FP32 input; no model execution/PTQ."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from .frame_quality import assess_frame
    from .reference import Config
except ImportError:
    from frame_quality import assess_frame
    from reference import Config


def model_input(rgb, contract, preprocess):
    """Apply the existing v12 model's RGB bilinear stretch + normalization.

    The quality ROI has already been selected; no second crop/pad/colour swap.
    Returns C-contiguous little-endian float32 [1,3,128,128]. INT8 scales belong
    to the accelerator's separately validated quantization contract.
    """
    if (not isinstance(rgb,np.ndarray) or rgb.dtype != np.uint8
            or rgb.ndim != 3 or rgb.shape[2] != 3):
        raise ValueError('Require uint8 HWC RGB ROI')
    if (contract.get('input_shape') != [1,3,128,128] or contract.get('input_dtype') != 'float32'
            or contract.get('input_layout') != 'NCHW, RGB'
            or preprocess.get('channel_order') != 'RGB' or preprocess.get('resize') != [128,128]
            or not preprocess.get('resize_interpolation','').startswith('PIL BILINEAR')):
        raise ValueError('Unsupported model input contract; do not guess accelerator format')
    norm=contract['input_normalization']
    if norm['mean'] != preprocess['mean'] or norm['std'] != preprocess['std']:
        raise ValueError('Contract/preprocess normalization mismatch')
    mean=np.asarray(norm['mean'],dtype=np.float32)
    std=np.asarray(norm['std'],dtype=np.float32)
    if mean.shape != (3,) or std.shape != (3,) or not np.isfinite(mean).all() or not np.isfinite(std).all() or (std<=0).any():
        raise ValueError('Invalid normalization')
    resampling=getattr(Image,'Resampling',Image)
    resized=np.asarray(Image.fromarray(rgb).resize((128,128),resampling.BILINEAR),dtype=np.float32)
    tensor=resized.transpose(2,0,1)/np.float32(255)
    tensor=(tensor-mean[:,None,None])/std[:,None,None]
    return np.ascontiguousarray(tensor[None],dtype='<f4')


def prepare_input(image_path, quality_path, contract_path, preprocess_path, destination):
    """Verify quality/pixels first, then write a new tensor artifact directory."""
    image_path,quality_path,contract_path,preprocess_path=map(Path,(image_path,quality_path,contract_path,preprocess_path))
    payload=image_path.read_bytes()
    quality=json.loads(quality_path.read_text(encoding='utf-8-sig'))
    event=quality['event'];a=event['assessment'];cfg=Config(**a['config'])
    if event['status']!='capture_ready' or not a['quality_ok'] or event['stable_count']<cfg.stable_n:
        raise ValueError('Image is not accompanied by a latched quality acceptance')
    if hashlib.sha256(payload).hexdigest()!=quality['artifact']['png_sha256']:
        raise ValueError('Image file SHA256 mismatch')
    with Image.open(io.BytesIO(payload)) as image:
        if image.mode!='RGB' or image.size!=(cfg.width,cfg.height):raise ValueError('Expected original RGB ROI PNG')
        rgb=np.asarray(image).copy()
    digest=hashlib.sha256(rgb.tobytes()).hexdigest()
    if digest!=a['roi_rgb_sha256'] or digest!=quality['artifact']['rgb_sha256']:
        raise ValueError('Image pixels differ from quality acceptance')
    measured,_=assess_frame(rgb,replace(cfg,x0=0,y0=0))
    if not measured['quality_ok'] or measured['stats']!=a['stats']:
        raise ValueError('Quality recheck does not match saved image')
    contract_raw=contract_path.read_bytes();preprocess_raw=preprocess_path.read_bytes()
    contract=json.loads(contract_raw.decode('utf-8-sig'));preprocess=json.loads(preprocess_raw.decode('utf-8-sig'))
    tensor=model_input(rgb,contract,preprocess)
    raw=tensor.tobytes(order='C')
    record=dict(schema_version=1,status='verified_fp32_input_ready',model_executed=False,
                input_name=contract['input_name'],shape=list(tensor.shape),layout='NCHW, RGB',
                dtype='float32',byte_order='little_endian',nbytes=len(raw),normalization_applied=True,
                int8_quantization_applied=False,source_roi_size=[cfg.width,cfg.height],
                png_sha256=quality['artifact']['png_sha256'],rgb_sha256=digest,
                tensor_bin_sha256=hashlib.sha256(raw).hexdigest(),
                model_contract_sha256=hashlib.sha256(contract_raw).hexdigest(),
                preprocess_contract_sha256=hashlib.sha256(preprocess_raw).hexdigest(),
                files=dict(tensor='input.npy',raw_tensor='input_f32le.bin'),
                tensor_min=float(tensor.min()),tensor_max=float(tensor.max()),
                hardware_frame_binding_verified=False,
                note='FP32 software reference only; PTQ scales, accelerator AXI format and inference remain downstream work.')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    with (destination/'input.npy').open('xb') as f:np.save(f,tensor,allow_pickle=False)
    with (destination/'input_f32le.bin').open('xb') as f:f.write(raw)
    with (destination/'input_contract.json').open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2,allow_nan=False)
    return record
