"""Bounded video + quality statistics on the already loaded Round41 overlay."""
import argparse
import asyncio
from dataclasses import asdict,replace
import gc
import hashlib
import json
from pathlib import Path
import signal
import time
import traceback
import uuid


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def video_dma_is_idle(tx_control,rx_control,tx_status,rx_status):
    return not((tx_control|rx_control)&1) and bool(tx_status&rx_status&1)


def configure_input(vin,pixel_format,init_timeout,report):
    """Keep VideoIn.configure, but give its native frontend an explicit timeout.

    PYNQ VideoIn.configure does not expose HDMIInFrontend.start's timeout.
    The per-instance adapter lasts only for this configure call; SDK files and
    class methods are untouched, including on exceptions.
    """
    frontend=vin._hdmi
    original=frontend.start
    had_override='start' in vars(frontend)
    previous=vars(frontend).get('start')
    frontend.start=lambda:original(init_timeout=init_timeout)
    started=time.monotonic()
    try:vin.configure(pixel_format)
    finally:
        if had_override:frontend.start=previous
        else:del frontend.start
        report['input_configuration_seconds']=time.monotonic()-started


def cancel_pending(loop):
    pending=list(asyncio.all_tasks(loop))
    for task in pending:task.cancel()
    if pending:loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
    # A retained cancelled Task can retain coroutine arguments via its traceback.
    for task in pending:
        try:failure=task.exception()
        except asyncio.CancelledError as failure:
            failure.__traceback__=failure.__context__=failure.__cause__=None
        else:
            if failure is not None:failure.__traceback__=failure.__context__=failure.__cause__=None
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(asyncio.sleep(0))
    return len(pending)


def release_created_uio(loop,registry,baseline):
    """Release only this standalone process's newly created PYNQ UI objects.

    PYNQ3.1 caches controllers; their destructors need the live current loop.
    DMA must already be stopped. No MMIO or interrupt-register writes here.
    """
    if registry is None:return dict(released_uio=0,released_controllers=0)
    old_controllers,old_devices=baseline
    new_keys=[key for key,value in registry._uio_devices.items() if old_devices.get(key)!=id(value)]
    for key in new_keys:loop.remove_reader(registry._uio_devices[key].uio)
    count=len(registry._controllers)
    registry._controllers[:]=[c for c in registry._controllers if id(c) in old_controllers]
    count-=len(registry._controllers)
    for key in new_keys:del registry._uio_devices[key]
    gc.collect()
    return dict(released_uio=len(new_keys),released_controllers=count)


def validate_snapshot(sample,cfg,cid,evaluate):
    if not sample.present or sample.config_id!=cid:return False
    if (sample.x0,sample.y0,sample.width,sample.height)!=(cfg.x0,cfg.y0,cfg.width,cfg.height):
        raise ValueError('Quality ROI differs from submitted configuration')
    if not sample.valid or sample.pixel_count!=cfg.width*cfg.height or sample.gradient_count!=(cfg.width-2)*(cfg.height-2):
        raise ValueError('Quality statistics invalid')
    stats={k:getattr(sample,k) for k in ('pixel_count','luma_sum','dark_count','bright_count','gradient_count','gradient_sum')}
    if (sample.valid,sample.exposure_ok,sample.sharpness_ok,sample.quality_ok)!=evaluate(stats,cfg,1280,720):
        raise ValueError('PL/reference predicate mismatch')
    return True


def health():
    m={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    return {key:m[key] for key in ('MemAvailable','CmaFree','SwapFree')}


def check_memory(sample,stage,record):
    row=dict(sample,stage=stage,monotonic_ns=time.monotonic_ns())
    record.setdefault('health_checks',[]).append(row)
    available,cma=(180*1024,48*1024) if stage=='before_video' else (96*1024,8*1024)
    if sample['MemAvailable']<available or sample['CmaFree']<cma:
        record['memory_guard_triggered']=row
        raise RuntimeError('Memory reserve reached at '+stage+': '+json.dumps(sample))


def verify(root,here):
    tools=json.loads((here/'video_tools_manifest.json').read_text())
    for directory,manifest in ((here,tools),(root,json.loads((root/'manifest.json').read_text()))):
        for name,sha in manifest['files'].items():
            path=(directory/name).resolve()
            if not path.is_relative_to(directory) or digest(path)!=sha:raise ValueError('File identity changed '+name)
    if digest(root/'manifest.json')!=tools['model_manifest_sha256']:raise ValueError('Expected validated Round41 model')
    return tools


def main(processor=None):
    p=argparse.ArgumentParser(description=processor.description if processor else __doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=30 if processor else 20,choices=range(5,61))
    p.add_argument('--input-timeout',type=int,default=10,choices=range(5,61))
    p.add_argument('--profile',action='store_true',help='Bounded in-memory per-stage diagnostics; not a benchmark');a=p.parse_args()
    try:from .pipeline_profile import PipelineProfile
    except ImportError:from pipeline_profile import PipelineProfile
    profile=PipelineProfile(enabled=a.profile)
    if processor:processor.profiler=profile
    root=a.root.resolve();here=Path(__file__).resolve().parent
    with profile.span('package_verify'):tools=verify(root,here)
    from board_trace import call,event
    from quality_gate_driver import QualityGate
    from reference import Config,evaluate
    cfg=Config(**json.loads((here/'runtime_profile_v0.3.json').read_text(encoding='utf-8-sig'))['config'])
    token=uuid.uuid4().hex;output=here/('video_result_'+token+'.json');trace=output.with_suffix('.jsonl')
    r=dict(status='FAILED',frames=0,samples=[],cleanup={},config=asdict(cfg),seconds_limit=a.seconds,
           input_initialization_timeout_seconds=a.input_timeout,
           overall_alarm_seconds=a.input_timeout+a.seconds+40+(processor.setup_extra_seconds if processor else 0),
           model_manifest_sha256=digest(root/'manifest.json'),video_tools_manifest_sha256=digest(here/'video_tools_manifest.json'),
           scope='Video preview and advancing PL quality statistics only; no image capture, CNN invocation, same-frame binding or threshold calibration',
           trace=str(trace),health_before=health())
    if processor:
        r['scope']='One process camera preview + delivered-image quality verification + one accepted ROI CNN inference; not strict PL frame binding or clinical accuracy validation'
    state=dict(cleanup=False,owned=None,owns_video=False);ol=vin=vout=gate=None
    irq_registry=None;irq_baseline=(set(),{})
    # UIO interrupt callbacks bind to get_event_loop during driver construction.
    # Keep construction, async frames and cleanup on that same loop lifecycle.
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    prior={}
    def interrupted(signum,frame):
        if state['cleanup']:return
        if signum==signal.SIGALRM:raise TimeoutError('Overall video setup/preview deadline')
        raise KeyboardInterrupt('Operator termination')
    numbers=[signal.SIGINT,signal.SIGTERM,signal.SIGALRM]
    if hasattr(signal,'SIGHUP'):numbers.append(signal.SIGHUP)
    for number in numbers:
        prior[number]=signal.signal(number,interrupted)
    signal.alarm(r['overall_alarm_seconds'])
    try:
        check_memory(r['health_before'],'before_video',r)
        ext4=Path('/sys/fs/ext4/mmcblk0p2/errors_count')
        r['ext4_errors_before']=int(ext4.read_text())
        if r['ext4_errors_before']:raise RuntimeError('Existing EXT4 errors')
        import pynq
        from pynq.interrupt import _InterruptController
        irq_registry=_InterruptController
        irq_baseline=(set(map(id,irq_registry._controllers)),{k:id(v) for k,v in irq_registry._uio_devices.items()})
        from pynq.lib.video import PIXEL_RGBA
        active=call(trace,'read_active_bit_record',lambda:pynq.PL.bitfile_name)
        model=json.loads((root/'manifest.json').read_text())
        if not active or not Path(active).is_file() or digest(active)!=model['files']['cnn_system.bit']:
            raise RuntimeError('Expected corrected overlay not loaded; no video access attempted')
        ol=call(trace,'attach_metadata_no_download',lambda:pynq.Overlay(str(root/'cnn_system.bit'),download=False))
        ip=ol.ip_dict['video/axi_vdma'];dma=pynq.MMIO(ip['phys_addr'],ip['addr_range'])
        r['vdma_before']=call(trace,'check_video_dma_unowned',lambda:{name:int(dma.read(offset)) for name,offset in
                            [('tx_control',0),('rx_control',0x30),('tx_status',4),('rx_status',0x34)]})
        if not video_dma_is_idle(**r['vdma_before']):raise RuntimeError('Video DMA not fully halted; leave other owner untouched')
        state['owns_video']=True
        ip=ol.ip_dict['video/quality_gate_0']
        if ip['phys_addr']!=0x43c80000:raise RuntimeError('Unexpected quality MMIO address')
        gate=call(trace,'quality_gate_abi',lambda:QualityGate(pynq.MMIO(ip['phys_addr'],ip['addr_range'])))
        if (gate.frame_width,gate.frame_height)!=(1280,720):raise RuntimeError('Expected quality dimensions1280x720')
        if processor:
            with profile.span(getattr(processor,'setup_profile_stage','cnn_session_setup')):
                call(trace,getattr(processor,'setup_stage','open_cnn_session_once'),lambda:processor.setup(root,ol,cfg,r,here))
        vin,vout=ol.video.hdmi_in,ol.video.hdmi_out
        with profile.span('hdmi_input_setup'):
            call(trace,'configure_hdmi_input',lambda:configure_input(vin,PIXEL_RGBA,a.input_timeout,r))
        print('HDMI_INPUT_CONFIGURED',round(r['input_configuration_seconds'],3),'seconds',flush=True)
        if (vin.mode.width,vin.mode.height)!=(1280,720):raise RuntimeError('Camera must supply1280x720')
        with profile.span('hdmi_output_setup'):
            call(trace,'configure_hdmi_output',lambda:vout.configure(vin.mode,PIXEL_RGBA))
        r['mode']=str(vin.mode);cid=call(trace,'configure_quality_gate',lambda:gate.configure(cfg,arm=processor is not None))
        r['quality_config_id']=cid
        call(trace,'start_input',vin.start);call(trace,'start_output',vout.start)
        async def preview():
            start=time.monotonic();last_poll=-1;last_print=0;last_frame=None;last_progress=start
            r['video_loop_start_monotonic_ns']=time.monotonic_ns()
            print('VIDEO_RUNNING',r['mode'],a.seconds,'seconds',flush=True)
            while time.monotonic()-start<a.seconds:
                remaining=a.seconds-(time.monotonic()-start)
                if remaining<=0:break
                before=bool(processor and processor.inferred)
                phase=('after_result' if before else 'before_capture') if processor else 'preview'
                with profile.frame(r['frames']+1,phase) as frame_profile:
                    try:
                        with profile.span('read_frame_wait'):
                            state['owned']=await asyncio.wait_for(vin.readframe_async(),min(2.,remaining))
                    except asyncio.TimeoutError:
                        if time.monotonic()-start>=a.seconds-.03:break
                        raise RuntimeError('Camera frame timeout')
                    elapsed=time.monotonic()-start
                    poll_due=elapsed-last_poll>=1
                    needs_fresh_sample=processor is not None and not processor.inferred
                    if poll_due or needs_fresh_sample:
                        with profile.span('quality_snapshot_validate'):
                            sample=gate.snapshot()
                            if validate_snapshot(sample,cfg,cid,evaluate) and sample.frame_id!=last_frame:
                                if poll_due:
                                    row=asdict(sample);row.update(elapsed=elapsed,mean_luma=sample.mean_luma,
                                        sharpness_score=sample.sharpness_score,dark_ratio=sample.dark_ratio,bright_ratio=sample.bright_ratio)
                                    r['samples'].append(row)
                                last_frame=sample.frame_id;last_progress=time.monotonic()
                            if elapsed>3 and time.monotonic()-last_progress>2:raise RuntimeError('Quality statistics not advancing')
                        if poll_due:
                            last_poll=elapsed
                            with profile.span('health_check'):check_memory(health(),'video',r)
                    if processor:
                        try:
                            with profile.span('processor_total'):
                                processor.process(state['owned'],sample,r['frames']+1,elapsed,time.monotonic())
                        finally:
                            if not before and processor.inferred:frame_profile.phase='capture'
                        with profile.span('hud_copy'):processor.paint(state['owned'])
                    remaining=a.seconds-(time.monotonic()-start)
                    if remaining<=0:break
                    try:
                        with profile.span('write_frame_wait'):
                            await asyncio.wait_for(vout.writeframe_async(state['owned']),min(2.,remaining))
                    except asyncio.TimeoutError:
                        if time.monotonic()-start>=a.seconds-.03:break
                        raise RuntimeError('Display frame timeout')
                    state['owned']=None;r['frames']+=1;frame_profile.submitted=True
                    if processor:processor.output_submitted()
                    if elapsed-last_print>=5:
                        last_print=elapsed;print('VIDEO_PROGRESS',r['frames'],'frames',round(r['frames']/elapsed,2),'fps',flush=True)
            r['video_seconds']=time.monotonic()-start
            r['video_loop_end_monotonic_ns']=time.monotonic_ns()
        call(trace,'video_loop',lambda:loop.run_until_complete(preview()))
        if r['frames']<1 or len(r['samples'])<2:raise RuntimeError('Insufficient video/quality progress')
        r.update(status='VIDEO_GATE_PREVIEW_PASS',fps=r['frames']/r['video_seconds'],quality_samples=len(r['samples']))
        r['video_validation_passed']=True
        if processor:r['status']=processor.finish(r)
    except BaseException as error:
        r.update(status='FAILED',error=repr(error),traceback=traceback.format_exc());print('VIDEO_ERROR',repr(error),flush=True)
    finally:
        state['cleanup']=True;signal.alarm(0);errors=[]
        if gate is not None:
            try:gate.configure(replace(cfg,enable=0),arm=True);r['cleanup']['gate_disabled_request_cleared']=True
            except BaseException as error:errors.append('gate '+repr(error))
        if state['owns_video']:
            announced=False
            while True:
                attempt=[]
                for name,obj in [('input',vin),('output',vout)]:
                    if obj is not None:
                        try:obj.stop();r['cleanup'][name+'_stopped']=True
                        except BaseException as error:attempt.append(name+' '+repr(error))
                try:
                    stopped=not ol.video.axi_vdma.writechannel.running and not ol.video.axi_vdma.readchannel.running
                except BaseException as error:stopped=False;attempt.append('DMA status '+repr(error))
                if stopped:
                    r['cleanup']['dma_stopped']=True;errors.extend(attempt);state['owned']=None;break
                if not announced:
                    print('VIDEO_STOP_UNCONFIRMED: keeping buffers/process alive; power-cycle board if recovery fails.',flush=True);announced=True
                    r.update(status='FAILED_STOP_PENDING');output.write_text(json.dumps(r,indent=2))
                try:time.sleep(1)
                except BaseException:pass
        if processor:
            try:processor.close(r)
            except BaseException as error:errors.append('CNN close '+repr(error))
        r['cleanup']['errors']=errors
        r['cleanup']['cancelled_pending_tasks']=cancel_pending(loop)
        ol=vin=vout=gate=None;obj=dma=None;gc.collect()
        try:r['cleanup']['uio_release']=release_created_uio(loop,irq_registry,irq_baseline)
        except Exception as error:errors.append('UIO release '+repr(error))
        if irq_registry is None or not irq_registry._uio_devices:
            loop.close();asyncio.set_event_loop(None);r['cleanup']['event_loop_closed']=True
        else:r['cleanup']['event_loop_closed']=False
        r['health_after']=health()
        r['health_measurement_scope']='Inside the process after DMA/owned UIO cleanup; libraries still resident, not post-process memory'
        if errors:r['status']='FAILED_CLEANUP'
        try:r['ext4_errors_after']=int(Path('/sys/fs/ext4/mmcblk0p2/errors_count').read_text())
        except OSError:r['ext4_errors_after']=None
        if r['ext4_errors_after']!=0:r['status']='FAILED_FILESYSTEM_CHECK'
        if a.profile:
            timing=profile.report()
            timing.update(run_status=r['status'],model_manifest_sha256=r['model_manifest_sha256'],
                          video_tools_manifest_sha256=r['video_tools_manifest_sha256'],video_result_file=str(output))
            live=r.get('live',{});accepted=live.get('capture_accepted_monotonic_ns');submitted=live.get('first_result_submitted_monotonic_ns')
            timing['response']=dict(
                scope='Software acceptance to first successful output submission; not exposure/button-to-screen latency',
                acceptance_to_result_submission_ms=(submitted-accepted)/1e6 if accepted is not None and submitted is not None else None,
                video_start_to_acceptance_ms=(accepted-r['video_loop_start_monotonic_ns'])/1e6 if accepted is not None else None)
            profile_path=output.with_name('pipeline_profile_'+token+'.json')
            profile_path.write_text(json.dumps(timing,indent=2)+'\n',encoding='utf-8')
            r['pipeline_profile_file']=str(profile_path)
            r['pipeline_profile_summary']=dict(phases=timing['phases'],response=timing['response'],
                                             dropped_frames=timing['dropped_frames'],dropped_stages=timing['dropped_stages'])
            print('PIPELINE_PROFILE',str(profile_path),flush=True)
            for name,phase in timing['phases'].items():
                # Parent spans contain their children; do not rank them as separate work.
                leaves=[(stage,values) for stage,values in phase['stages'].items()
                        if stage not in ('processor_total','preprocess_total')]
                leaves.sort(key=lambda item:item[1]['total_ms'],reverse=True)
                top=[dict(stage=stage,**values) for stage,values in leaves[:5]]
                print('PROFILE_PHASE',json.dumps(dict(phase=name,submitted_frames=phase['submitted_frames'],
                      submitted_fps=phase['submitted_fps'],top_stages_by_total_ms=top)),flush=True)
            print('PROFILE_RESPONSE',json.dumps(timing['response']),flush=True)
        output.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
        for number,handler in prior.items():signal.signal(number,handler)
        print('LIVE_RESULT' if processor else 'VIDEO_RESULT',str(output),r['status'],flush=True)
        print(json.dumps({k:r.get(k) for k in ('status','frames','video_seconds','fps','quality_samples','cleanup','health_before','health_after','memory_guard_triggered','live')},indent=2),flush=True)
    expected=processor.success_status if processor else 'VIDEO_GATE_PREVIEW_PASS'
    if r['status']!=expected:raise SystemExit(2 if r['status']=='VIDEO_PASS_NO_ACCEPTED_ROI' else 1)


if __name__=='__main__':main()
