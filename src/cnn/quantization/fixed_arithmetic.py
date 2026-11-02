"""Integer dyadic reference: signed AP_RND_CONV/AP_SAT, accumulator48/24.

Matrix accumulation is allowed ONLY after proving products have <=24 fractional
bits and every partial sum fits48. This is not an emulator for arbitrary types.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Format:
    width:int
    integer:int
    def __post_init__(self):
        if self.width not in (8,16,48) or not -8<=self.integer<=self.width or not 0<=self.fractional<=30:
            raise ValueError('Unsupported signed fixed format')
    @property
    def fractional(self):return self.width-self.integer
    @property
    def low(self):return -(1<<(self.width-1))
    @property
    def high(self):return (1<<(self.width-1))-1
    def json(self):return dict(width=self.width,integer=self.integer,fractional=self.fractional,signed=True,zero_point=0,scale=2.**-self.fractional,rounding='AP_RND_CONV',overflow='AP_SAT')


def round_shift(value,shift):
    value=np.asarray(value,dtype=np.int64)
    if not -30<=shift<=48:raise ValueError('Unsupported binary shift')
    if shift<=0:return value<<(-shift)
    denominator=1<<shift;q=value//denominator;r=value-q*denominator;half=denominator//2
    return q+((r>half)|((r==half)&((q&1)!=0)))


def clamp(rounded,fmt):
    rounded=np.asarray(rounded,dtype=np.int64)
    stats=dict(elements=int(rounded.size),rounded_saturation_count=int(np.count_nonzero((rounded<fmt.low)|(rounded>fmt.high))),
               min_rounded_raw=int(rounded.min()),max_rounded_raw=int(rounded.max()))
    return np.clip(rounded,fmt.low,fmt.high),stats


def quantize(value,fmt):
    value=np.asarray(value,dtype=np.float64)
    if not value.size or not np.isfinite(value).all():raise ValueError('Nonempty finite values required')
    scaled=np.ldexp(value,fmt.fractional)
    if np.max(np.abs(scaled))>=2.**62:raise ValueError('Host integer overflow')
    return clamp(np.rint(scaled).astype(np.int64),fmt)


def requantize(value,source_fractional,fmt,tracker=None,name=None):
    result,stats=clamp(round_shift(value,source_fractional-fmt.fractional),fmt)
    if tracker is not None:
        old=tracker.setdefault(name,dict(elements=0,rounded_saturation_count=0,min_rounded_raw=None,max_rounded_raw=None))
        old['elements']+=stats['elements'];old['rounded_saturation_count']+=stats['rounded_saturation_count']
        old['min_rounded_raw']=stats['min_rounded_raw'] if old['min_rounded_raw'] is None else min(old['min_rounded_raw'],stats['min_rounded_raw'])
        old['max_rounded_raw']=stats['max_rounded_raw'] if old['max_rounded_raw'] is None else max(old['max_rounded_raw'],stats['max_rounded_raw'])
    return result


def bound(weights,bias,xf,wf,bf):
    product_fractional=xf.fractional+wf.fractional
    if product_fractional>24 or bf.fractional>24:
        raise ValueError('Per-product rounding unsupported by summed-dot reference')
    sums=np.abs(np.asarray(weights,dtype=np.int64)).reshape(len(bias),-1).sum(axis=1)
    bounds=[((1<<(xf.width-1))*int(s)<<(24-product_fractional))+(abs(int(b))<<(24-bf.fractional)) for s,b in zip(sums,bias)]
    maximum=max(bounds)
    if maximum>(1<<47)-1:raise ValueError('Accumulator48/24 bound exceeded')
    return dict(maximum_absolute_raw=maximum,limit_raw=(1<<47)-1,product_fractional=product_fractional,
                product_exact_at_frac24=True,all_partial_sums_covered=True)


def conv(x,weights,bias,xf,wf,bf,yf,stride,padding,tracker=None,name=None):
    bound(weights,bias,xf,wf,bf)
    kh,kw=weights.shape[2:]
    if x.shape[2]!=weights.shape[1]:raise ValueError('HWC/OIHW channels differ')
    padded=np.pad(x,((padding,padding),(padding,padding),(0,0)))
    patches=np.lib.stride_tricks.sliding_window_view(padded,(kh,kw),axis=(0,1))[::stride,::stride]
    h,w=patches.shape[:2]
    product=patches.reshape(h*w,-1)@weights.reshape(weights.shape[0],-1).T
    accum=(product<<(24-xf.fractional-wf.fractional))+(bias<<(24-bf.fractional))
    return requantize(accum,24,yf,tracker,name).reshape(h,w,-1)


def maxpool(x,xf,yf,kernel,stride,padding,tracker=None,name=None):
    padded=np.pad(x,((padding,padding),(padding,padding),(0,0)),constant_values=xf.low)
    windows=np.lib.stride_tricks.sliding_window_view(padded,(kernel,kernel),axis=(0,1))[::stride,::stride]
    return requantize(windows.max(axis=(-1,-2)),xf.fractional,yf,tracker,name)


def gap(x,xf,yf,tracker=None,name=None):
    count=x.shape[0]*x.shape[1]
    if count!=64:raise ValueError('Only the delivered power-of-two GAP64')
    # Sum at frac24 is exact. Division by64 is dyadic and fits frac24 for the
    # supported input fractions <=18, so the result cast is the only rounding.
    if xf.fractional>18 or count*(1<<(xf.width-1))*(1<<(24-xf.fractional))>(1<<47)-1:
        raise ValueError('GAP arithmetic unsupported')
    return requantize(x.sum(axis=(0,1),dtype=np.int64),xf.fractional+6,yf,tracker,name)


def dense(x,weights,bias,xf,wf,bf,yf,tracker=None,name=None):
    bound(weights,bias,xf,wf,bf)
    accum=((weights@x)<<(24-xf.fractional-wf.fractional))+(bias<<(24-bf.fractional))
    return requantize(accum,24,yf,tracker,name)
