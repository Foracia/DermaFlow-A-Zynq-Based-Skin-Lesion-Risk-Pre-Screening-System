"""Diagnostic PYNQ golden test for the corrected complete overlay.

No training, package installation, video start, threshold fitting or SSH control.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import time
import uuid
import numpy as np
try:
    from .board_trace import call as traced,event as trace_event,TracedMMIO
except ImportError:
    from board_trace import call as traced,event as trace_event,TracedMMIO


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def confirm_loaded(active,expected_sha):
    if not active or not Path(active).is_file() or digest(active)!=expected_sha:
        raise RuntimeError('Corrected overlay not recorded as loaded; no PL access attempted')


def check_manifest(root):
    root=Path(root).resolve()
    data=json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
    if data['status']!='PACKAGED':
        raise ValueError('Unexpected package status')
    for name, expected in data['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or digest(path)!=expected:
            raise ValueError('Artifact hash mismatch: '+name)
    return data


def load_golden(root):
    root=Path(root)
    words=np.loadtxt(root/'input.hex',dtype=np.uint32,converters={0:lambda s:int(s,16)})
    expected=[int(s,16) for s in (root/'expected.hex').read_text().split()]
    if words.shape!=(65536,) or len(expected)!=4:
        raise ValueError('Exactly four 16384-pixel golden frames required')
    if np.any(words>0xffffff) or any(v<0 or v>0xffff for v in expected):
        raise ValueError('Golden data must be 24-bit pixels and 16-bit outputs')
    return words.reshape(4,16384),expected


def decode_logits(raw):
    raw=int(raw)
    if raw<0 or raw>0xffff:
        raise ValueError('Unexpected upper output bits')
    values=[raw&255,(raw>>8)&255]
    return [(v-256 if v>=128 else v)/32.0 for v in values]


def postprocess(raw,point):
    if point['positive_class_index']!=1 or point['comparison']!='>=':
        raise ValueError('Unexpected frozen working point')
    logits=np.asarray(decode_logits(raw),dtype=np.float64)
    scaled=logits/float(point['temperature'])
    probability=float(1.0/(1.0+np.exp(scaled[0]-scaled[1])))
    return dict(logits=logits.tolist(),positive_probability=probability,
                prediction=int(probability>=float(point['threshold'])))


def wait_until(predicate,*,timeout,interval=.001):
    deadline=time.monotonic()+timeout
    while True:
        value=predicate()
        if value:
            return value
        if time.monotonic()>=deadline:
            raise TimeoutError('Bounded hardware wait expired')
        time.sleep(interval)


def dma_completed(mmio):
    tx,rx=int(mmio.read(4)),int(mmio.read(0x34))
    if (tx|rx)&0x70:
        raise RuntimeError('DMA error tx=%#x rx=%#x'%(tx,rx))
    return bool(tx&2 and rx&2 and not(tx&1 or rx&1))


def reset_dma(mmio,timeout):
    # AXI DMA simple-mode reset is common to both channels.
    mmio.write(0,4)
    wait_until(lambda:not(int(mmio.read(0))&4 or int(mmio.read(0x30))&4),timeout=timeout)
    wait_until(lambda:bool(int(mmio.read(4))&1 and int(mmio.read(0x34))&1),timeout=timeout)


def check_hp1_reset(slcr):
    value=int(slcr.read(0x240))
    if value&0x00200000:
        raise RuntimeError('HP1 AXDS1 reset is asserted; refuse AFI/DMA access')
    return value


def configure_hp1_32(afi,state):
    # Exact writes from this project's AMD-generated ps7_init.c AFI1 setup.
    # Zynq7000 Overlay.download does not perform this PS configuration for us.
    state['before']={str(offset):int(afi.read(offset)) for offset in (0,0x14)}
    state['after']={}
    for offset in (0,0x14):
        afi.write(offset,state['before'][str(offset)]|1)
        value=int(afi.read(offset));state['after'][str(offset)]=value
        if not value&1:
            raise RuntimeError('HP1 32-bit mode readback failed')


def restore_hp1(afi,state):
    if 'before' not in state:
        return
    for offset in (0,0x14):
        value=int(afi.read(offset))
        bit=state['before'][str(offset)]&1
        afi.write(offset,(value&~1)|bit)
        if int(afi.read(offset))&1!=bit:
            raise RuntimeError('HP1 original mode restore failed')


def hold_until_dma_halted(dma,lease,*,timeout,reset_fn=None,wait_fn=time.sleep):
    """Keep the process and buffer lease alive until DMA is proven halted.

    This exceptional recovery has no time limit: exiting could release physical
    pages still referenced by DMA. If it cannot recover, power-cycle the board;
    do not force-kill this process. Normal golden tests retain bounded waits.
    """
    if reset_fn is None:
        reset_fn=reset_dma
    try:
        print('DMA_STOP_UNCONFIRMED: BUFFER_LEASE_HELD; retrying reset. Power-cycle board if unrecoverable; do not kill process.',flush=True)
    except BaseException:
        pass
    while True:
        try:
            reset_fn(dma,timeout)
            return
        except BaseException:
            try:
                wait_fn(1)
            except BaseException:
                pass


def request_termination(state,signum):
    if state.get('requested'):
        return
    state['requested']=True
    context=globals().get('_unsafe_dma_context')
    if context is not None and context.get('cleanup_active'):
        return
    raise KeyboardInterrupt('Signal '+str(signum))


def recover_unsafe_context(timeout):
    context=globals().get('_unsafe_dma_context')
    if context is None:
        return
    context['cleanup_active']=True
    hold_until_dma_halted(context['dma'],context,timeout=timeout)
    # Only reaching this line proves both DMA channels halted.
    errors=[]
    try:
        if context['core'] is not None:context['core'].write(4,2)
        if context['afi'] is not None:restore_hp1(context['afi'],context['hp1_state'])
    except BaseException as error:
        errors.append(repr(error))
    globals().pop('_unsafe_dma_context',None)
    for buffer in context['buffers']:
        if buffer is not None:
            try:traced(context.get('trace'),'late_free_buffer',buffer.freebuffer)
            except BaseException as error:errors.append(repr(error))
    record=context['record']
    record['cleanup'].update(dma_reset_and_halted=True,buffers_freed=not errors,
                             late_recovery=True,late_recovery_errors=errors)
    record['status']='FAILED_CLEANUP_RECOVERED' if not errors else 'FAILED_CLEANUP'
    context['output'].write_text(json.dumps(record,indent=2)+'\n')


def execute(root,timeout,download=True,diagnostic=True):
    if globals().get('_unsafe_dma_context') is not None:
        raise RuntimeError('Prior DMA context has not been safely stopped')
    root=Path(root).resolve()
    manifest=check_manifest(root)
    words,expected=load_golden(root)
    point=json.loads((root/'working_point.json').read_text())
    from pynq import Overlay,MMIO,allocate,Clocks,PL
    result=dict(status='RUNNING',board_wall_clock_utc_unverified=datetime.now(timezone.utc).isoformat(),
                elapsed_clock='time.perf_counter_ns',frames=[],cleanup={},
                scope='Four fixed raw golden inputs; not camera, complete dataset accuracy or continuous video throughput',
                timing_scope='DIAGNOSTIC ONLY: START through completion includes persistent MMIO tracing; not a performance benchmark',
                manifest_sha256=digest(root/'manifest.json'))
    output=root/('board_result_'+uuid.uuid4().hex+'.json')
    if not diagnostic:output=root/('board_timing_batch_'+uuid.uuid4().hex+'.json')
    result['result_file']=str(output)
    trace=output.with_suffix('.jsonl') if diagnostic else None
    result['stage_trace']=str(trace) if trace is not None else None
    result['diagnostic_trace']=diagnostic
    result['poll_interval_seconds']=.001
    if not diagnostic:
        result['timing_scope']='Prepared input: START through DMA/core completion polling (1ms polling); excludes input copy/flush, output invalidate/check, model setup and postprocess'
    ol=dma=core=afi=txbuf=rxbuf=None
    hp1_state={}
    safe_to_free=False
    try:
        print('LOADING_COMPLETE_OVERLAY' if download else 'ATTACHING_ALREADY_LOADED_OVERLAY',flush=True)
        started=time.perf_counter_ns()
        if not download:
            active=traced(trace,'read_active_bit_record',lambda:PL.bitfile_name)
            confirm_loaded(active,manifest['files']['cnn_system.bit'])
        ol=traced(trace,'overlay_load' if download else 'attach_loaded_metadata',
                  lambda:Overlay(str(root/'cnn_system.bit'),download=download))
        result['overlay_load_ms']=(time.perf_counter_ns()-started)/1e6
        for name,address in (('cnn_accel_0',0x43c90000),('cnn_dma',0x40400000)):
            if ol.ip_dict[name]['phys_addr']!=address:
                raise RuntimeError('Unexpected HWH address for '+name)
        if abs(traced(trace,'read_ps_fclk0',lambda:float(Clocks.fclk0_mhz))-100.0)>.1:
            raise RuntimeError('Expected 100MHz source for fixed 80MHz CNN clock')
        slcr=TracedMMIO(traced(trace,'map_slcr',lambda:MMIO(0xf8000000,4096)),trace,'slcr')
        result['fpga_rst_ctrl']=traced(trace,'read_hp1_reset_status',lambda:check_hp1_reset(slcr))
        core=TracedMMIO(traced(trace,'map_core',lambda:MMIO(0x43c90000,4096)),trace,'core')
        dma=TracedMMIO(traced(trace,'map_dma',lambda:MMIO(0x40400000,65536)),trace,'dma')
        # Establish the lease before allocating or advertising any DMA buffers.
        context=dict(dma=dma,core=core,afi=None,hp1_state=hp1_state,buffers=(None,None),
                     overlay=ol,record=result,output=output,trace=trace,cleanup_active=False)
        globals()['_unsafe_dma_context']=context
        abi=traced(trace,'read_cnn_abi',lambda:int(core.read(0)))
        geometry=traced(trace,'read_cnn_geometry',lambda:int(core.read(0x24)))
        clock_register=traced(trace,'read_cnn_clock',lambda:int(core.read(0x28)))
        if abi!=0x434e4e01 or geometry!=16384 or clock_register!=80000000:
            raise RuntimeError('CNN ABI/geometry/clock register mismatch')
        traced(trace,'initial_dma_reset',lambda:reset_dma(dma,timeout))
        afi=TracedMMIO(traced(trace,'map_afi1',lambda:MMIO(0xf8009000,4096)),trace,'afi1')
        context['afi']=afi
        result['hp1_afi_mode']=hp1_state
        traced(trace,'configure_hp1_32',lambda:configure_hp1_32(afi,hp1_state))
        traced(trace,'soft_reset_cnn',lambda:core.write(4,2))
        wait_until(lambda:bool(int(core.read(8))&8) and not(int(core.read(8))&0x11),timeout=timeout)
        txbuf=traced(trace,'allocate_tx',lambda:allocate(shape=(16384,),dtype=np.uint32))
        context['buffers']=(txbuf,None)
        rxbuf=traced(trace,'allocate_rx',lambda:allocate(shape=(1,),dtype=np.uint32))
        context['buffers']=(txbuf,rxbuf)
        for buffer in (txbuf,rxbuf):
            address=int(buffer.physical_address)
            if address%8 or address<0x00100000 or address+buffer.nbytes>0x20000000:
                raise RuntimeError('DMA buffer outside aligned physical DDR mapping')
        result['buffers']=[dict(physical_address=int(b.physical_address),bytes=int(b.nbytes)) for b in (txbuf,rxbuf)]
        for frame in range(4):
            trace_event(trace,'frame_'+str(frame),'BEGIN')
            txbuf[:]=words[frame];rxbuf[0]=0xdeadbeef
            traced(trace,'flush_tx',txbuf.flush);traced(trace,'flush_rx',rxbuf.flush)
            dma.write(4,0x7000);dma.write(0x34,0x7000)
            dma.write(0,1);dma.write(0x30,1)
            wait_until(lambda:not(int(dma.read(4))&1 or int(dma.read(0x34))&1),timeout=timeout)
            dma.write(0x48,int(rxbuf.physical_address))
            dma.write(0x58,4)  # S2MM is armed before the core and MM2S.
            began=time.perf_counter_ns()
            core.write(4,1)
            dma.write(0x18,int(txbuf.physical_address))
            dma.write(0x28,65536)
            def complete():
                status=int(core.read(8))
                if status&4:
                    raise RuntimeError('CNN framing/control error code=%#x'%int(core.read(0x20)))
                return bool(dma_completed(dma) and status&2 and not status&1)
            wait_until(complete,timeout=timeout)
            api_ms=(time.perf_counter_ns()-began)/1e6
            traced(trace,'invalidate_rx',rxbuf.invalidate);raw=int(rxbuf[0]);mirror=int(core.read(0x18))
            if raw!=expected[frame] or raw!=mirror:
                raise RuntimeError('Golden mismatch frame=%d got=%#x mirror=%#x expected=%#x'%(frame,raw,mirror,expected[frame]))
            if int(core.read(0x0c))!=16384 or int(core.read(0x10))!=1:
                raise RuntimeError('Unexpected frame token counts')
            cycles=int(core.read(0x14))
            api_with_output_ms=(time.perf_counter_ns()-began)/1e6
            row=dict(frame=frame,raw_hex='%04x'%raw,expected_hex='%04x'%expected[frame],
                     transaction_ms=api_ms,transaction_with_output_check_ms=api_with_output_ms,hardware_transaction_cycles=cycles,
                     hardware_transaction_ms=cycles/80000.0,**postprocess(raw,point))
            result['frames'].append(row)
            trace_event(trace,'frame_'+str(frame),'COMPLETE')
            if diagnostic:print('GOLDEN_FRAME_PASS',json.dumps(row),flush=True)
        result['status']='FOUR_FRAME_BOARD_GOLDEN_PASS'
    except BaseException as error:
        result.update(status='FAILED',error=repr(error))
        raise
    finally:
        context=globals().get('_unsafe_dma_context')
        if context is not None:context['cleanup_active']=True
        errors=[]
        if dma is not None:
            try:
                reset_dma(dma,timeout)
                result['cleanup']['dma_reset_and_halted']=True
                safe_to_free=True
            except BaseException as error:
                errors.append('DMA cleanup '+repr(error))
        else:
            safe_to_free=True
        if core is not None:
            try:
                core.write(4,2)
                result['cleanup']['core_reset_requested']=True
            except BaseException as error:
                errors.append('Core cleanup '+repr(error))
        if safe_to_free:
            if afi is not None:
                try:
                    restore_hp1(afi,hp1_state)
                    result['cleanup']['hp1_mode_restored']=True
                except BaseException as error:
                    errors.append('HP1 restore '+repr(error))
            globals().pop('_unsafe_dma_context',None)
            for buffer in (txbuf,rxbuf):
                if buffer is not None:
                    traced(trace,'free_buffer',buffer.freebuffer)
        result['cleanup']['errors']=errors
        result['cleanup']['buffers_freed']=safe_to_free
        if errors:
            result['status']='FAILED_CLEANUP'
        output.write_text(json.dumps(result,indent=2)+'\n')
        print('BOARD_RESULT',str(output),result['status'],flush=True)
    return result


def run_guarded(action,timeout):
    """Shared signal and DMA lease handling for diagnostic and timing runs."""
    termination={}
    def interrupted(signum,frame):request_termination(termination,signum)
    prior={}
    for name in ('SIGTERM','SIGINT','SIGHUP'):
        if hasattr(signal,name):
            number=getattr(signal,name);prior[number]=signal.signal(number,interrupted)
    try:
        try:result=action()
        except BaseException:
            recover_unsafe_context(timeout)
            raise
        recover_unsafe_context(timeout)
        return result
    finally:
        for number,handler in prior.items():signal.signal(number,handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--timeout',type=float,default=3.0)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--load',action='store_true',help='Load full overlay and test; prefer staged probe then --use-loaded')
    modes.add_argument('--use-loaded',action='store_true',help='Require matching active bit record; test without reprogramming')
    args=parser.parse_args()
    if not .1<=args.timeout<=30:
        parser.error('Timeout must be0.1..30 seconds')
    if not args.load and not args.use_loaded:
        check_manifest(args.root);load_golden(args.root)
        print('PACKAGE_VERIFIED_NO_HARDWARE_ACCESSED; use --load to run')
        return
    # Normal termination signals must run DMA cleanup rather than release pages
    # while a transaction may still be live. SIGKILL cannot be intercepted.
    result=run_guarded(lambda:execute(args.root,args.timeout,download=not args.use_loaded),args.timeout)
    if result['status']!='FOUR_FRAME_BOARD_GOLDEN_PASS':
        raise SystemExit(1)


if __name__=='__main__':
    main()
