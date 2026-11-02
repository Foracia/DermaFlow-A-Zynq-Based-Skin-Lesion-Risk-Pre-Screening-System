"""SYS02 exact software candidates; copied/frozen SYS01 helpers stay unchanged.

No hardware, model execution, threshold tuning, or persistence changes.
Quality arithmetic is derived from the team's frame_quality and SYS01 copy.
"""
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import asdict
import hashlib

import numpy as np
from PIL import Image

from reference import Config, display_statistics, evaluate
from calibration import config_from_run
from verify_ncnn import DEFAULT_MEAN, DEFAULT_STD
from board_system_ui import Views

PROFILES = ('baseline','display','input','quality','combined')


def choices(profile):
    if profile not in PROFILES:
        raise ValueError('Unknown SYS02 profile')
    return dict(display=profile in ('display','combined'),
                input=profile in ('input','combined'),quality=profile in ('quality','combined'))


_VALUES = np.arange(256, dtype=np.float32)[None, :] / 255.0
_NORMAL = (_VALUES - np.asarray(DEFAULT_MEAN, np.float32)[:, None]) / np.asarray(DEFAULT_STD, np.float32)[:, None]
_ROUNDED = np.rint(_NORMAL.astype(np.float64) * 16)
_BYTES = np.clip(_ROUNDED, -128, 127).astype(np.int8).view(np.uint8).astype(np.uint32)
_WORDS = np.stack([_BYTES[c] << (8*c) for c in range(3)])
_HAS_SATURATION = bool(np.any((_ROUNDED < -128) | (_ROUNDED > 127)))


def prepare_roi(rgb, profiler=None):
    """Exact frozen float32 normalization + F4 words via 3x256-value tables."""
    span = profiler.span if profiler is not None else lambda name: nullcontext()
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 1:
        raise ValueError('Require nonempty HxWx3 uint8 RGB')
    with span('resize_normalize'):
        resized = np.asarray(Image.fromarray(rgb).resize((128,128), getattr(Image,'Resampling',Image).BILINEAR))
        tensor = np.empty((1,3,128,128), np.float32)
        for c in range(3):
            tensor[0,c] = _NORMAL[c, resized[:,:,c]]
    with span('quantize_pack'):
        words = (_WORDS[0,resized[:,:,0]] | _WORDS[1,resized[:,:,1]] | _WORDS[2,resized[:,:,2]])
        words = np.ascontiguousarray(words.reshape(-1), dtype='<u4')
    with span('input_metadata'):
        saturated = 0
        if _HAS_SATURATION:
            saturated = sum(int(np.count_nonzero((_ROUNDED[c,resized[:,:,c]] < -128) |
                            (_ROUNDED[c,resized[:,:,c]] > 127))) for c in range(3))
        record = dict(roi_shape=list(rgb.shape), roi_rgb_sha256=hashlib.sha256(rgb.tobytes(order='C')).hexdigest(),
            tensor_shape=list(tensor.shape),tensor_dtype='float32',tensor_layout='NCHW RGB',
            tensor_sha256=hashlib.sha256(tensor.astype('<f4',copy=False).tobytes()).hexdigest(),
            packed_shape=list(words.shape),packed_dtype='little-endian uint32',packed_nbytes=int(words.nbytes),
            packed_sha256=hashlib.sha256(words.tobytes()).hexdigest(),
            pixel_order='row-major HWC; R bits7:0, G bits15:8, B bits23:16, top byte zero',
            quantization='signed8 F4, step1/16, zero0, float64 multiply then ties-even rounding and saturation',
            saturated_values=saturated,normalized_min=float(tensor.min()),normalized_max=float(tensor.max()),
            model_executed=False,quality_acceptance_verified_by_this_module=False)
    return tensor, words, record


def assess_frame(frame, config):
    """Same owned pixels/stats/predicates; fewer allocations and bounded sums."""
    if not isinstance(config, Config):
        raise TypeError('config must be Config')
    if not isinstance(frame,np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] not in (3,4):
        raise ValueError('Expected uint8 HxWx3 RGB or HxWx4 RGBA pixels')
    h,w = frame.shape[:2]
    config_from_run(dict(config=asdict(config),frame_width=w,frame_height=h))
    c = config
    rgb = frame[c.y0:c.y0+c.height,c.x0:c.x0+c.width,:3].copy(order='C')
    y = rgb[:,:,0].astype(np.uint16)
    y *= 77
    work = rgb[:,:,1].astype(np.uint16)
    work *= 150
    y += work
    work = rgb[:,:,2].astype(np.uint16)
    work *= 29
    y += work
    y += 128
    y >>= 8
    y = y.view(np.int16)
    gx = y[:-2,2:] - y[:-2,:-2]
    work = y[1:-1,2:] - y[1:-1,:-2]
    work *= 2
    gx += work
    gx += y[2:,2:]
    gx -= y[2:,:-2]
    gy = y[2:,:-2] - y[:-2,:-2]
    work = y[2:,1:-1] - y[:-2,1:-1]
    work *= 2
    gy += work
    gy += y[2:,2:]
    gy -= y[:-2,2:]
    np.abs(gx,out=gx)
    np.abs(gy,out=gy)
    gx += gy
    # config_from_run caps total frame pixels at 1048575 and bounds ROI.
    # Luma sum <= 1048575*255; gradient sum <= 1048575*2040 < INT32_MAX.
    stats = dict(pixel_count=c.width*c.height,luma_sum=int(y.sum(dtype=np.int32)),
        dark_count=int(np.count_nonzero(y<c.dark_level)),bright_count=int(np.count_nonzero(y>c.bright_level)),
        gradient_count=(c.width-2)*(c.height-2),gradient_sum=int(gx.sum(dtype=np.int32)))
    valid,exposure,sharp,quality = evaluate(stats,c,w,h)
    reasons=[]
    if not valid:
        reasons.append('disabled_or_invalid')
    else:
        n=stats['pixel_count']
        if stats['luma_sum'] < c.mean_min*n: reasons.append('mean_too_dark')
        if stats['luma_sum'] > c.mean_max*n: reasons.append('mean_too_bright')
        if stats['dark_count']*10000 > c.dark_max_bp*n: reasons.append('too_many_dark_pixels')
        if stats['bright_count']*10000 > c.bright_max_bp*n: reasons.append('too_many_bright_pixels')
        if not sharp: reasons.append('insufficient_gradient')
    return dict(stats=stats,metrics=display_statistics(stats),valid=valid,exposure_ok=exposure,
        sharpness_ok=sharp,quality_ok=quality,reasons=reasons,config=asdict(c),frame_width=w,frame_height=h,
        roi_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest()),rgb


class FastViews(Views):
    """Static result templates + bounded RGBA text sprites, independent outputs."""
    def __init__(self, here):
        super().__init__(here)
        self.text_cache = OrderedDict()
        self.templates = {}
        for mode in ('normal','fusion'):
            page = self.blank()
            self.text(page,'三帧融合推理结果' if mode=='fusion' else '单帧风险预筛结果',32)
            self.text(page,'KEY2 再次采集    KEY3 返回菜单',684 if mode=='fusion' else 668)
            self.templates[mode] = page

    def _line(self,page,text,y,color=(235,238,242)):
        key=(str(text),tuple(color))
        if key not in self.text_cache:
            width=self.body.text_width(key[0])
            if width+48>page.shape[1]:
                raise ValueError('UI text exceeds frame width')
            sprite=np.empty((self.body.height,width,4),np.uint8)
            sprite[:]=(24,26,30,255)
            cx=0
            for char in key[0]:
                glyph=self.body.glyphs.get(char)
                if glyph is None:
                    raise ValueError('UI font missing character: '+repr(char))
                gh,gw=glyph.shape
                sprite[:gh,cx:cx+gw][glyph]=(*color,255)
                cx+=gw
            self.text_cache[key]=sprite
            if len(self.text_cache)>32:
                self.text_cache.popitem(last=False)
        sprite=self.text_cache[key]
        self.text_cache.move_to_end(key)
        top=y-(self.body.height-self.body.pixel_size)//2
        page[top:top+sprite.shape[0],48:48+sprite.shape[1]]=sprite

    def result(self,packet,save_status='pending',error=None):
        result=packet['result']
        fused=result['mode']=='fusion'
        page=self.templates[result['mode']].copy()
        self._line(page,result['risk_label'],87,(245,120,110) if result['prediction'] else (110,230,150))
        label='融合风险概率' if fused else '模型风险概率'
        self._line(page,label+' %.2f%%    判定阈值 %.6f' %
                   (100*result['refer_probability'],result['decision_threshold']),137)
        if fused:
            values=[float(row['positive_probability']) for row in result['inferences']]
            if len(values)!=3 or any(not 0<=v<=1 for v in values):
                raise ValueError('Fusion display requires three actual finite probabilities')
            self._line(page,'（三帧推理：%.2f%%，%.2f%%，%.2f%%）' % tuple(100*v for v in values),181)
        self._line(page,'参与推理 %d 帧    推理耗时 %.1f ms' %
                   (result['frame_count'],result['inference_latency_ms']),218 if fused else 184)
        rgb=packet['frames'][-1]['rgb']
        if rgb.shape==(360,640,3):
            top=264 if fused else 232
            page[top:top+360,320:960,:3]=rgb
        status={'pending':'保存中','complete':'保存成功','failed':'保存失败，请重试'}[save_status]
        self._line(page,status,636 if fused else 612,(245,120,110) if save_status=='failed' else (160,220,175))
        return page
