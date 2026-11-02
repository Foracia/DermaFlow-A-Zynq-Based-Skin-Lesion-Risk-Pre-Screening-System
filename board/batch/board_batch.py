"""Reusable prepared-input CPU/PL batch=1 evaluation; never programs an overlay."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import uuid
import numpy as np

from batch_metrics import metrics,compare,probability,sha


def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def statistics(values):
    if not values:return None
    a=np.asarray(values,dtype=np.float64)
    return dict(runs=len(values),mean_ms=float(a.mean()),median_ms=float(np.median(a)),
                p95_ms=float(np.percentile(a,95)),min_ms=float(a.min()),max_ms=float(a.max()))


def checked(logits):
    value=np.asarray(logits,dtype=np.float64)
    if value.shape!=(2,) or not np.isfinite(value).all():raise ValueError('Expected two finite logits')
    return value.copy()


def scores(labels,logits,point):
    result=metrics(labels,logits,point['temperature'],point['threshold'])
    if len(np.unique(labels))<2:
        result['macro_f1']=None
        result['macro_f1_note']='Single ground-truth class; omit fixed-two-class macro average'
    return result


def load_payload(root,spec):
    root=Path(root).resolve();path=(root/spec['file']).resolve()
    if not path.is_relative_to(root):raise ValueError('Payload escapes bundle root')
    if sha(path)!=spec['sha256']:raise ValueError('Payload SHA mismatch')
    with np.load(path,allow_pickle=False) as archive:data={key:archive[key] for key in archive.files}
    n=len(spec['samples'])
    if data['inputs'].shape!=(n,3,128,128) or data['inputs'].dtype!=np.dtype('<f4') or not np.isfinite(data['inputs']).all():
        raise ValueError('Invalid normalized FP32 inputs')
    if data['packed'].shape!=(n,16384) or data['packed'].dtype!=np.dtype('<u4') or np.any(data['packed']>0xffffff):
        raise ValueError('Invalid packed PL input')
    if data['labels'].shape!=(n,) or not np.isin(data['labels'],[0,1]).all():raise ValueError('Invalid labels')
    if data['pl_raw'].shape!=(n,) or np.any(data['pl_raw']<0) or np.any(data['pl_raw']>0xffff):raise ValueError('Invalid raw reference')
    for name in ('pl','fp32','kl','eq'):
        if data[name+'_logits'].shape!=(n,2) or not np.isfinite(data[name+'_logits']).all():raise ValueError('Invalid reference logits')
    for i,row in enumerate(spec['samples']):
        if row['label']!=int(data['labels'][i]):raise ValueError('Label/order mismatch')
        for key,value in (('tensor_sha256',data['inputs'][i:i+1]),('packed_sha256',data['packed'][i])):
            if hashlib.sha256(value.tobytes()).hexdigest()!=row[key]:raise ValueError('Sample input SHA mismatch')
    return data


def evaluate_backend(engine,spec,data,out,warmup=30,runs=300):
    if type(warmup) is not int or type(runs) is not int or not 0<=warmup<=1000 or not 0<=runs<=5000:
        raise ValueError('Invalid warmup/runs')
    out=Path(out);name=engine.name;prefix=spec['split']+'_'+name;point=spec['point']
    output=out/(prefix+'_result.json')
    if output.exists():raise FileExistsError(output)
    result=dict(status='RUNNING',backend=name,split=spec['split'],working_point=point,
                samples=len(spec['samples']),completed_samples=0,warmup=warmup,measured_runs=runs,
                batch=1,quality_gate_applied=False,threshold_refitted=False,temperature_refitted=False,
                timing=None,timing_samples=[],prediction_rows=[])
    actual=[];current=None
    def infer(index):
        prepared=engine.prepare(data['inputs'][index:index+1],data['packed'][index])
        logits,extra=engine.infer(prepared);logits=checked(logits)
        if name=='pl' and int(extra['raw_hex'],16)!=int(data['pl_raw'][index]):
            raise RuntimeError('PL raw mismatch sample=%d got=%s expected=%04x'%(index,extra['raw_hex'],int(data['pl_raw'][index])))
        return logits,extra
    save(output,result)
    try:
        fields=['sample_index','relative_path','label','disease','patient_id','lesion_id','tensor_sha256','packed_sha256',
                'logit0','logit1','positive_probability','prediction']
        with (out/(prefix+'_predictions.csv')).open('x',newline='',encoding='utf-8-sig') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for index,row in enumerate(spec['samples']):
                current=index;logits,extra=infer(index);actual.append(logits)
                p=float(probability(logits[None],point['temperature'])[0])
                entry={key:row.get(key,'') for key in fields if key in row}
                entry.update(sample_index=index,logit0=float(logits[0]),logit1=float(logits[1]),
                             positive_probability=p,prediction=int(p>=point['threshold']))
                writer.writerow(entry)
                result['completed_samples']+=1
                if (index+1)%50==0:print('BATCH_ACCURACY',name,index+1,'/',len(spec['samples']),flush=True)
        values=np.asarray(actual);np.save(out/(prefix+'_logits.npy'),values,allow_pickle=False)
        result['accuracy']=scores(data['labels'],values,point)
        diseases=np.array([row['disease'] for row in spec['samples']])
        result['by_disease']={d:scores(data['labels'][diseases==d],values[diseases==d],point) for d in sorted(set(diseases))}
        result['reference_comparison']=compare(values,data[name+'_logits'],point['temperature'],point['threshold'])
        if name=='pl':result['reference_comparison']['raw_mismatches']=0
        result['accuracy_source']='Actual backend outputs on all selected frozen split samples; no quality filtering'
        speed_count=min(6,len(spec['samples']))
        result['timing_input_indices']=list(range(speed_count))
        for i in range(warmup):current=i%speed_count;infer(current)
        for i in range(runs):
            current=i%speed_count;start=time.perf_counter_ns()
            prepared=engine.prepare(data['inputs'][current:current+1],data['packed'][current])
            adapter_end=time.perf_counter_ns()
            logits,extra=engine.infer(prepared);logits=checked(logits);api_end=time.perf_counter_ns()
            if name=='pl' and int(extra['raw_hex'],16)!=int(data['pl_raw'][current]):raise RuntimeError('PL raw mismatch during timing')
            p=float(probability(logits[None],point['temperature'])[0]);prediction=int(p>=point['threshold'])
            post_end=time.perf_counter_ns()
            row=dict(run=i,sample_index=current,adapter_ms=(adapter_end-start)/1e6,
                     prepared_api_ms=(api_end-adapter_end)/1e6,postprocess_ms=(post_end-api_end)/1e6,
                     normalized_input_to_logits_ms=(api_end-start)/1e6,
                     normalized_input_to_prediction_ms=(post_end-start)/1e6)
            for key in ('transaction_ms','transaction_with_output_check_ms','hardware_transaction_ms'):
                if key in extra:row[key]=extra[key]
            result['timing_samples'].append(row)
        if runs:
            keys=[key for key in result['timing_samples'][0] if key not in ('run','sample_index')]
            result['timing']={key:statistics([r[key] for r in result['timing_samples']]) for key in keys}
        result.update(status='COMPLETE',logits_file=prefix+'_logits.npy',logits_sha256=sha(out/(prefix+'_logits.npy')),
                      timing_scope='Accuracy traversal separate. Timed loop starts at normalized FP32 tensor, includes adapter and complete backend call; reports stages separately. Excludes NPZ/decode, model/session setup, warmup, CSV/JSON writes.',
                      caveat='PL complete call includes its own checks and postprocess; internal transaction/output-check and hardware-cycle times are additionally preserved. Not pure MAC time.')
    except BaseException as error:
        result.update(status='FAILED',failed_sample_index=current,error=repr(error));raise
    finally:save(output,result)
    return result


class CpuEngine:
    def __init__(self,name,root,contract):
        import ncnn
        self.name=name;self.net=ncnn.Net();self.net.opt.num_threads=1;self.net.opt.use_vulkan_compute=False
        self.contract=contract;self.point=contract['cpu_points'][name]
        directory=root/'models'/name
        for file,expected in contract['cpu_model_sha256'][name].items():
            if sha(directory/file)!=expected:raise ValueError('CPU model SHA changed '+name+'/'+file)
        if sha(root/'interface/working_points.json')!=contract['cpu_interface_sha256']:raise ValueError('CPU interface SHA changed')
        if getattr(ncnn,'__version__','unknown')!=contract['expected_ncnn_version']:raise ValueError('Unexpected ncnn runtime version')
        points=json.loads((root/'interface/working_points.json').read_text(encoding='utf-8'))
        if points['candidates'][name]['temperature']!=self.point['temperature'] or points['candidates'][name]['threshold']!=self.point['threshold']:
            raise ValueError('CPU working point changed')
        if self.net.load_param(str(directory/'model.param'))!=0 or self.net.load_model(str(directory/'model.bin'))!=0:
            raise RuntimeError('ncnn model load failed')
        self.input_name,self.output_name=points['input_blob'],points['output_blob']
        self.identity=dict(runtime='ncnn',version=getattr(ncnn,'__version__','unknown'),module=ncnn.__file__,threads=1,vulkan=False)
    def prepare(self,tensor,packed):
        import ncnn
        return ncnn.Mat(np.ascontiguousarray(tensor[0]))
    def infer(self,prepared):
        extractor=self.net.create_extractor()
        if extractor.input(self.input_name,prepared)!=0:raise RuntimeError('ncnn input failed')
        status,value=extractor.extract(self.output_name)
        if status!=0:raise RuntimeError('ncnn extract failed')
        return np.asarray(value.numpy(),dtype=np.float32).reshape(-1).copy(),{}
    def close(self):self.net=None;return dict(errors=[])


class PlEngine:
    name='pl'
    def __init__(self,root,contract,out,timeout):
        import board_accel as b
        self.session=None;self.point=contract['pl_point']
        self.identity=dict(runtime='PYNQ',model_manifest_sha256=b.digest(root/'manifest.json'))
        if self.identity['model_manifest_sha256']!=contract['pl_model_manifest_sha256']:raise ValueError('PL model identity changed')
        from pynq import PL,Overlay,MMIO
        model=b.check_manifest(root);b.confirm_loaded(PL.bitfile_name,model['files']['cnn_system.bit'])
        overlay=Overlay(str(root/'cnn_system.bit'),download=False)
        ip=overlay.ip_dict['video/axi_vdma'];vdma=MMIO(ip['phys_addr'],ip['addr_range'])
        if (int(vdma.read(0))|int(vdma.read(0x30)))&1 or not(int(vdma.read(4))&int(vdma.read(0x34))&1):
            raise RuntimeError('Video DMA is owned/running; stop video before isolated benchmark')
        from board_session import CnnSession
        self.session=CnnSession(root,overlay,record_dir=out,timeout=timeout,persist_each_inference=False)
        self.session.open()
        if any(self.session.point[k]!=self.point[k] for k in ('temperature','threshold')):raise ValueError('PL working point changed')
        for words,raw in zip(self.session.golden_words,self.session.golden_expected):self.session.infer(words,expected_raw=raw)
        print('PL_FOUR_GOLDEN_SELF_CHECK_PASS',flush=True)
    def prepare(self,tensor,packed):
        from camera_input import pack_normalized
        actual=pack_normalized(tensor)
        if not np.array_equal(actual,packed):raise ValueError('Board input quantization differs from frozen payload')
        return actual
    def infer(self,prepared):
        row=self.session.infer(prepared)
        return np.asarray(row['logits']),row
    def close(self):return self.session.close() if self.session is not None else dict(errors=[])


def verify_tools(here,manifest):
    for name,expected in manifest['files'].items():
        path=(here/name).resolve()
        if not path.is_relative_to(here) or sha(path)!=expected:raise ValueError('Batch tool SHA changed '+name)
    if sha(here/'payload_manifest.json')!=manifest['payload_manifest_sha256']:raise ValueError('Payload manifest SHA changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu-root',type=Path,default=Path(__file__).resolve().parents[1]/'cpu')
    parser.add_argument('--pl-root',type=Path,default=Path(__file__).resolve().parents[1]/'hardware')
    parser.add_argument('--backends',nargs='+',choices=('fp32','kl','eq','pl'),default=['pl'])
    parser.add_argument('--split',choices=('val','test','all'),default='test')
    parser.add_argument('--warmup',type=int,default=30);parser.add_argument('--runs',type=int,default=300)
    parser.add_argument('--timeout',type=float,default=3.);parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if len(set(args.backends))!=len(args.backends) or not 0<=args.warmup<=1000 or not 0<=args.runs<=5000 or not .1<=args.timeout<=30:
        parser.error('Invalid duplicate backend or timing arguments')
    here=Path(__file__).resolve().parent
    tools=json.loads((here/'batch_tools_manifest.json').read_text(encoding='utf-8'));verify_tools(here,tools)
    manifest=json.loads((here/'payload_manifest.json').read_text(encoding='utf-8'))
    selected=('val','test') if args.split=='all' else (args.split,)
    if args.verify_only:
        for split in selected:load_payload(here,manifest['splits'][split])
        print('BATCH_INPUTS_AND_TOOLS_VERIFIED_NO_HARDWARE_ACCESSED',flush=True);return
    if args.cpu_root.is_dir():sys.path.insert(0,str(args.cpu_root/'python_deps'))
    out=here/('batch_run_'+uuid.uuid4().hex);out.mkdir()
    report=dict(status='RUNNING',platform=platform.platform(),python=sys.version,numpy=np.__version__,
                payload_manifest_sha256=sha(here/'payload_manifest.json'),batch_tools_manifest_sha256=sha(here/'batch_tools_manifest.json'),
                selected_splits=list(selected),backends=args.backends,results={},cleanup={},
                bitstream_reprogrammed=False,quality_gate_applied=False,test_scope='Source development-evaluation split, not untouched blind test')
    def action():
        for split in selected:
            spec=manifest['splits'][split];data=load_payload(here,spec)
            for name in args.backends:
                engine=None
                try:
                    engine=PlEngine(args.pl_root.resolve(),manifest,out,args.timeout) if name=='pl' else CpuEngine(name,args.cpu_root.resolve(),manifest)
                    point=manifest['pl_point'] if name=='pl' else manifest['cpu_points'][name]
                    result=evaluate_backend(engine,dict(spec,split=split,point=point),data,out,args.warmup,args.runs)
                    result['runtime_identity']=engine.identity
                    save(out/(split+'_'+name+'_result.json'),result)
                    report['results'][split+'_'+name]=dict(file=split+'_'+name+'_result.json',status=result['status'],
                                                        accuracy=result['accuracy'],timing=result['timing'],reference_comparison=result['reference_comparison'])
                finally:
                    if engine is not None:
                        cleanup=engine.close();report['cleanup'][split+'_'+name]=cleanup
                        if cleanup.get('errors') or cleanup.get('late_recovery'):raise RuntimeError('Backend cleanup failure '+name)
            del data
        report['status']='COMPLETE'
    try:
        if 'pl' in args.backends:
            import board_accel as b
            b.run_guarded(action,args.timeout)
        else:action()
    except BaseException as error:
        report.update(status='FAILED',error=repr(error));raise
    finally:
        save(out/'summary.json',report);print('BATCH_RESULT',str(out/'summary.json'),report['status'],flush=True)
    for name,result in report['results'].items():
        print('BATCH_SUMMARY',json.dumps(dict(backend=name,accuracy=result['accuracy'],timing=result['timing'],
              reference_comparison=result['reference_comparison']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
