"""Frozen v12 CNN numerical contracts; no training or CPU-model modifications."""
import copy
import json
from pathlib import Path
import re
import numpy as np
import onnx
from onnx import numpy_helper,helper

import hashlib

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
SOURCE_SHA256 = '39e60c35b055870a1c333507be662754124ad15a61a9aae730cd256c295b2785'
OPS = ['Conv', 'Relu', 'MaxPool', 'Conv', 'Relu', 'MaxPool', 'Conv', 'Relu', 'MaxPool', 'Conv', 'Relu', 'AveragePool', 'Flatten', 'Gemm']
import fixed_arithmetic as a

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'data/models/pl_quantized'
KINDS=('legacy8','refined8','stem16')


def parse(text):
    match=re.fullmatch(r'fixed<(\d+),(-?\d+),AP_RND_CONV,AP_SAT>',text)
    if not match:raise ValueError('Unexpected original arithmetic format')
    return a.Format(int(match[1]),int(match[2]))


def tight_integer(values,width):
    for integer in range(-8,width+1):
        fmt=a.Format(width,integer)
        if values.min()>=fmt.low*2.**-fmt.fractional and values.max()<=fmt.high*2.**-fmt.fractional:return integer
    raise ValueError('Cannot cover parameter range')


class Model:
    def __init__(self,kind):
        if kind not in KINDS:raise ValueError('Unknown candidate')
        self.kind=kind;source=ROOT/'data/models/model.onnx'
        if sha(source)!=SOURCE_SHA256:raise ValueError('Source model changed')
        model=onnx.load(str(source));self.nodes=list(model.graph.node)
        if [n.op_type for n in self.nodes]!=OPS:raise ValueError('Unexpected source graph')
        self.original={t.name:numpy_helper.to_array(t).astype(np.float64) for t in model.graph.initializer}
        report_path=ROOT/'data/models/pl_quantized/recipe.json'
        report=json.loads(report_path.read_text(encoding='utf-8'));self.recipe=report['precision_recipe']
        if report['source_sha256_after_generation']!=SOURCE_SHA256:raise ValueError('Old recipe source mismatch')
        self.formats={name:{role:parse(value) for role,value in types.items()} for name,types in self.recipe['layer_precisions'].items()}
        if kind!='legacy8':
            for i in range(4):
                key=f'Conv_{i}';node=self.nodes[i*3]
                self.formats[key]['weight']=a.Format(8,tight_integer(self.original[node.input[1]],8))
                self.formats[key]['bias']=a.Format(16,self.formats[key]['bias'].integer)
            self.formats['MatMul_0']['weight']=a.Format(8,tight_integer(self.original[self.nodes[-1].input[1]],8))
            self.formats['MatMul_0']['bias']=a.Format(16,1)
            self.formats['Add_0']['bias']=a.Format(16,1)
            self.formats['Add_0']['result']=a.Format(16,3)
            if kind=='stem16':
                for name in ('global_in','Conv_0','Relu_0','MaxPool_0'):
                    self.formats[name]['result']=a.Format(16,self.formats[name]['result'].integer)
        for constant,mapping in self.recipe['initializer_mapping'].items():
            self.formats[constant]['result']=self.formats[mapping['target']][mapping['role']]
        self.parameters={};self.weights={};self.bias={};self.bounds={}
        previous=self.formats['global_in']['result']
        for i in range(4):
            key=f'Conv_{i}';node=self.nodes[i*3];types=self.formats[key]
            self.weights[key]=self.parameter(node.input[1],types['weight'])
            self.bias[key]=self.parameter(node.input[2],types['bias'])
            self.bounds[key]=a.bound(self.weights[key],self.bias[key],previous,types['weight'],types['bias'])
            previous=self.formats[f'MaxPool_{i}']['result'] if i<3 else self.formats['Relu_3']['result']
        node=self.nodes[-1];types=self.formats['MatMul_0']
        self.weights['MatMul_0']=self.parameter(node.input[1],types['weight'])
        self.bias['MatMul_0']=np.zeros(2,dtype=np.int64)
        self.bias['Add_0']=self.parameter(node.input[2],self.formats['Add_0']['bias'])
        self.bounds['MatMul_0']=a.bound(self.weights['MatMul_0'],self.bias['MatMul_0'],self.formats['AveragePool_0']['result'],types['weight'],types['bias'])
        head=self.bounds['MatMul_0']['maximum_absolute_raw']+max(abs(int(v)) for v in self.bias['Add_0'])*(1<<(24-self.formats['Add_0']['bias'].fractional))
        if head>(1<<47)-1:raise ValueError('Head addition exceeds48')
        self.bounds['Add_0']=dict(maximum_absolute_raw=head,all_partial_sums_covered=True)

    def parameter(self,name,fmt):
        raw,stats=a.quantize(self.original[name],fmt)
        error=np.abs(raw*2.**-fmt.fractional-self.original[name])
        self.parameters[name]=dict(stats,format=fmt.json(),max_abs_error=float(error.max()),mean_abs_error=float(error.mean()),shape=list(raw.shape))
        return raw

    def contract(self):
        return dict(candidate=self.kind,source_sha256=SOURCE_SHA256,
                    formats={name:{role:fmt.json() for role,fmt in types.items()} for name,types in self.formats.items()},
                    parameter_quantization=self.parameters,accumulator_bounds=self.bounds,
                    accumulator='signed48/24 AP_RND_CONV/AP_SAT',identity_scale='exact one; native tooling uint1 unchanged',
                    parameter_basis='original FP32 initializers, not rounded16 weights',activation_basis='unchanged old train-only signed minmax8; stem precision is explicit')

    def run(self,image,tracker=None,trace=False):
        if image.shape!=(128,128,3):raise ValueError('Expected finite NHWC128 RGB tensor')
        xf=self.formats['global_in']['result'];x,stats=a.quantize(image,xf)
        if tracker is not None:
            old=tracker.setdefault('input',dict(elements=0,rounded_saturation_count=0,min_rounded_raw=stats['min_rounded_raw'],max_rounded_raw=stats['max_rounded_raw']))
            old['elements']+=stats['elements'];old['rounded_saturation_count']+=stats['rounded_saturation_count']
            old['min_rounded_raw']=min(old['min_rounded_raw'],stats['min_rounded_raw']);old['max_rounded_raw']=max(old['max_rounded_raw'],stats['max_rounded_raw'])
        traces={}
        def emit(name,values,fmt):
            if trace:traces[name]=(values.copy(),fmt)
        for i in range(4):
            key=f'Conv_{i}';node=self.nodes[i*3];attrs={v.name:helper.get_attribute_value(v) for v in node.attribute}
            pads=attrs['pads'];strides=attrs['strides']
            if len(set(pads))!=1 or len(set(strides))!=1 or attrs.get('group',1)!=1 or attrs.get('dilations',[1,1])!=[1,1]:raise ValueError('Unsupported Conv attributes')
            emit(f'zp2d_Conv2D_Conv_{i}',np.pad(x,((pads[0],pads[0]),(pads[0],pads[0]),(0,0))),xf)
            types=self.formats[key];yf=types['result']
            x=a.conv(x,self.weights[key],self.bias[key],xf,types['weight'],types['bias'],yf,strides[0],pads[0],tracker,key)
            xf=yf;emit(f'Conv2D_Conv_{i}',x,xf)
            key=f'Relu_{i}';yf=self.formats[key]['result']
            x=a.requantize(np.maximum(x,0),xf.fractional,yf,tracker,key);xf=yf;emit(key,x,xf)
            if i<3:
                node=self.nodes[i*3+2];attrs={v.name:helper.get_attribute_value(v) for v in node.attribute}
                if attrs.get('ceil_mode',0)!=0:raise ValueError('Unexpected ceil pool')
                key=f'MaxPool_{i}';yf=self.formats[key]['result']
                x=a.maxpool(x,xf,yf,attrs['kernel_shape'][0],attrs['strides'][0],attrs.get('pads',[0])[0],tracker,key)
                xf=yf;emit(key,x,xf)
        yf=self.formats['AveragePool_0']['result'];x=a.gap(x,xf,yf,tracker,'AveragePool_0');xf=yf;emit('AveragePool_0',x,xf)
        types=self.formats['MatMul_0'];yf=types['result']
        x=a.dense(x,self.weights['MatMul_0'],self.bias['MatMul_0'],xf,types['weight'],types['bias'],yf,tracker,'MatMul_0');xf=yf
        emit('Dense_MatMul_0',x,xf)
        types=self.formats['Add_0'];x=x+(self.bias['Add_0']<<(24-types['bias'].fractional))
        yf=types['result'];x=a.requantize(x,24,yf,tracker,'Add_0');emit('bn_Add_0',x,yf)
        return x.astype(np.float64)*2.**-yf.fractional,traces
