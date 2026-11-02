"""Persistent, single-thread CNN transactions on an already validated overlay.

This module never downloads a bitstream, changes clocks, or touches video DMA.
It retains the existing board_accel DMA lease/recovery protocol. Host tests of
this adapter do not establish hardware correctness; board validation is separate.
"""
import json
import math
from numbers import Integral
from pathlib import Path
import threading
import time
import uuid

import numpy as np

try:
    from . import board_accel as b
except ImportError:
    import board_accel as b


class CnnSession:
    def __init__(self,root,overlay,timeout=3.0,trace=None,record_dir=None,persist_each_inference=True):
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('CNN timeout must be positive and at most 30 seconds')
        self.root=Path(root).resolve()
        self.overlay=overlay
        self.timeout=float(timeout)
        self.trace=trace
        self.persist_each_inference=bool(persist_each_inference)
        directory=Path(record_dir).resolve() if record_dir is not None else self.root
        if not directory.is_dir():
            raise ValueError('CNN record_dir must already exist')
        self.record_file=directory/('cnn_session_'+uuid.uuid4().hex+'.json')
        self.record=dict(status='NEW',root=str(self.root),bitstream_reprogrammed=False,
                         setup_reused=True,inferences=[],cleanup={},
                         timing_scope='START through completion polling; output-check variant includes invalidate, raw/mirror/token/cycle checks; input copy/flush, setup, postprocess and JSON writes excluded',
                         diagnostic_trace=trace is not None)
        self.record['per_inference_disk_writes']=self.persist_each_inference
        self.golden_words=None
        self.golden_expected=None
        self.core=self.dma=self.afi=self.txbuf=self.rxbuf=None
        self._context=None
        self._state='NEW'
        self._owner=None
        self._busy=False
        self._poisoned=False

    def _check_thread(self):
        if self._owner is not None and self._owner != threading.get_ident():
            raise RuntimeError('CNN session must stay on its owning thread')

    def _persist(self):
        self.record_file.write_text(json.dumps(self.record,indent=2,allow_nan=False)+'\n',encoding='utf-8')

    def open(self):
        self._check_thread()
        if self._state=='OPEN':return self
        if self._state!='NEW':raise RuntimeError('Closed or failed CNN session cannot reopen')
        if b.__dict__.get('_unsafe_dma_context') is not None:
            raise RuntimeError('Prior DMA lease has not been safely stopped')
        self._owner=threading.get_ident()
        self._state='OPENING'
        try:
            manifest=b.check_manifest(self.root)
            self.record['model_manifest_sha256']=b.digest(self.root/'manifest.json')
            self.point=json.loads((self.root/'working_point.json').read_text(encoding='utf-8-sig'))
            temperature=float(self.point['temperature']);threshold=float(self.point['threshold'])
            if not(math.isfinite(temperature) and temperature>0 and math.isfinite(threshold) and 0<=threshold<=1):
                raise ValueError('Invalid frozen working point')
            b.postprocess(0,self.point)
            self.record['working_point']=dict(self.point)
            self.golden_words,expected=b.load_golden(self.root)
            self.golden_words.setflags(write=False)
            self.golden_expected=tuple(expected)
            from pynq import MMIO,allocate,Clocks,PL
            b.confirm_loaded(PL.bitfile_name,manifest['files']['cnn_system.bit'])
            b.confirm_loaded(self.overlay.bitfile_name,manifest['files']['cnn_system.bit'])
            for name,address in (('cnn_accel_0',0x43c90000),('cnn_dma',0x40400000)):
                if self.overlay.ip_dict[name]['phys_addr']!=address:
                    raise RuntimeError('Unexpected CNN HWH address for '+name)
            if abs(float(Clocks.fclk0_mhz)-100.)>.1:
                raise RuntimeError('Expected 100MHz source for fixed 80MHz CNN clock')
            slcr=b.TracedMMIO(MMIO(0xf8000000,4096),self.trace,'slcr')
            self.record['fpga_rst_ctrl']=b.check_hp1_reset(slcr)
            self.core=b.TracedMMIO(MMIO(0x43c90000,4096),self.trace,'core')
            self.dma=b.TracedMMIO(MMIO(0x40400000,65536),self.trace,'dma')
            state={}
            self._context=dict(dma=self.dma,core=self.core,afi=None,hp1_state=state,
                               buffers=(None,None),overlay=self.overlay,record=self.record,
                               output=self.record_file,trace=self.trace,cleanup_active=False)
            b._unsafe_dma_context=self._context
            if (int(self.core.read(0)),int(self.core.read(0x24)),int(self.core.read(0x28)))!=(0x434e4e01,16384,80000000):
                raise RuntimeError('CNN ABI/geometry/clock mismatch')
            b.reset_dma(self.dma,self.timeout)
            self.afi=b.TracedMMIO(MMIO(0xf8009000,4096),self.trace,'afi1')
            self._context['afi']=self.afi
            b.configure_hp1_32(self.afi,state)
            self.record['hp1_afi_mode']=state
            self.core.write(4,2)
            b.wait_until(lambda:bool(int(self.core.read(8))&8) and not(int(self.core.read(8))&0x11),timeout=self.timeout)
            self.txbuf=allocate(shape=(16384,),dtype=np.uint32)
            self._context['buffers']=(self.txbuf,None)
            self.rxbuf=allocate(shape=(1,),dtype=np.uint32)
            self._context['buffers']=(self.txbuf,self.rxbuf)
            for buffer,nbytes in ((self.txbuf,65536),(self.rxbuf,4)):
                address=int(buffer.physical_address)
                if int(buffer.nbytes)!=nbytes or address%8 or address<0x00100000 or address+nbytes>0x20000000:
                    raise RuntimeError('Unexpected/alignment-unsafe CNN DMA buffer')
            self.record['buffers']=[dict(physical_address=int(v.physical_address),bytes=int(v.nbytes))
                                    for v in (self.txbuf,self.rxbuf)]
            self.record['status']='OPEN'
            self._state='OPEN'
            self._persist()
            return self
        except BaseException as error:
            self._poisoned=True
            self.record.update(status='FAILED_OPEN',error=repr(error))
            self._close_impl()
            raise

    @staticmethod
    def _words(words):
        values=np.asarray(words)
        if values.shape!=(16384,) or not np.issubdtype(values.dtype,np.integer):
            raise ValueError('CNN input must be exactly 16384 integer words')
        if np.any(values<0) or np.any(values>0xffffff):
            raise ValueError('CNN input must contain only low 24-bit packed signed RGB')
        return np.ascontiguousarray(values,dtype=np.uint32)

    def infer(self,words,expected_raw=None):
        self._check_thread()
        if self._state!='OPEN' or self._poisoned or self._busy:
            raise RuntimeError('CNN session is not available for inference')
        if b.__dict__.get('_unsafe_dma_context') is not self._context:
            self._poisoned=True
            raise RuntimeError('CNN DMA lease was recovered or changed; cannot reuse buffers')
        values=self._words(words)
        if expected_raw is not None:
            if isinstance(expected_raw,(bool,np.bool_)) or not isinstance(expected_raw,Integral) or not 0<=expected_raw<=0xffff:
                raise ValueError('Expected CNN raw output must be a 16-bit integer')
            expected_raw=int(expected_raw)
        self._busy=True
        try:
            self.txbuf[:]=values
            self.rxbuf[0]=0xdeadbeef
            self.txbuf.flush();self.rxbuf.flush()
            self.dma.write(4,0x7000);self.dma.write(0x34,0x7000)
            self.dma.write(0,1);self.dma.write(0x30,1)
            b.wait_until(lambda:not(int(self.dma.read(4))&1 or int(self.dma.read(0x34))&1),timeout=self.timeout)
            self.dma.write(0x48,int(self.rxbuf.physical_address))
            self.dma.write(0x58,4)
            started_ns=time.monotonic_ns()
            began=time.perf_counter_ns()
            self.core.write(4,1)
            self.dma.write(0x18,int(self.txbuf.physical_address))
            self.dma.write(0x28,65536)
            def complete():
                status=int(self.core.read(8))
                if status&4:
                    raise RuntimeError('CNN framing/control error code=%#x'%int(self.core.read(0x20)))
                return bool(b.dma_completed(self.dma) and status&2 and not status&1)
            b.wait_until(complete,timeout=self.timeout)
            transaction_ms=(time.perf_counter_ns()-began)/1e6
            self.rxbuf.invalidate()
            raw=int(self.rxbuf[0]);mirror=int(self.core.read(0x18))
            if raw>0xffff or raw<0:raise ValueError('Unexpected upper output bits')
            if raw!=mirror:raise RuntimeError('CNN output/mirror mismatch')
            if expected_raw is not None and raw!=expected_raw:
                raise RuntimeError('Golden mismatch got=%#x expected=%#x'%(raw,expected_raw))
            input_tokens=int(self.core.read(0xc));output_tokens=int(self.core.read(0x10))
            if input_tokens!=16384 or output_tokens!=1:
                raise RuntimeError('Unexpected CNN frame token counts')
            cycles=int(self.core.read(0x14))
            if cycles<=0:raise RuntimeError('Invalid CNN hardware cycle count')
            api_ms=(time.perf_counter_ns()-began)/1e6
            ended_ns=time.monotonic_ns()
            row=dict(index=len(self.record['inferences']),raw_hex='%04x'%raw,
                     expected_hex=None if expected_raw is None else '%04x'%expected_raw,
                     mirror_hex='%04x'%mirror,input_tokens=input_tokens,output_tokens=output_tokens,
                     transaction_ms=transaction_ms,transaction_with_output_check_ms=api_ms,
                     hardware_transaction_cycles=cycles,hardware_transaction_ms=cycles/80000.,
                     start_monotonic_ns=started_ns,end_monotonic_ns=ended_ns,
                     **b.postprocess(raw,self.point))
            self.record['inferences'].append(row)
            if self.persist_each_inference:self._persist()
            return row
        except BaseException as error:
            self._poisoned=True
            self.record.update(status='FAILED_INFERENCE',error=repr(error))
            self._close_impl()
            raise
        finally:self._busy=False

    def _close_impl(self):
        cleanup=self.record['cleanup']
        if self._state=='CLOSED':return cleanup
        context=b.__dict__.get('_unsafe_dma_context')
        # The caller's signal guard may already have recovered/freed this lease.
        if self._context is not None and context is None and cleanup.get('late_recovery'):
            return self._adopt_recovery()
        if context is not None and context is not self._context:
            raise RuntimeError('Foreign DMA lease present during CNN session close')
        if self._context is not None:
            self._context['cleanup_active']=True
            if context is None:b._unsafe_dma_context=self._context
        errors=[]
        if self.dma is not None:
            try:
                b.reset_dma(self.dma,self.timeout)
                cleanup['dma_reset_and_halted']=True
            except BaseException as error:
                self._poisoned=True
                cleanup['initial_halt_error']=repr(error)
                # Existing recovery holds all references and retries until halt;
                # only after that does it restore HP1 and free the leased buffers.
                try:b.recover_unsafe_context(self.timeout)
                except BaseException as recovery_error:
                    # The helper writes its record after halting/freeing. A
                    # recording failure at that point must not free a second time.
                    if b.__dict__.get('_unsafe_dma_context') is not None or not cleanup.get('late_recovery'):
                        raise
                    cleanup.setdefault('errors',[]).append('recovery record '+repr(recovery_error))
                return self._adopt_recovery()
        else:
            cleanup.update(dma_reset_and_halted=False,dma_not_mapped=True)
        if self.core is not None:
            try:self.core.write(4,2);cleanup['core_reset_requested']=True
            except BaseException as error:errors.append('core reset '+repr(error))
        if self.afi is not None:
            try:
                b.restore_hp1(self.afi,self._context['hp1_state'])
                cleanup['hp1_mode_restored']=True
            except BaseException as error:errors.append('HP1 restore '+repr(error))
        if b.__dict__.get('_unsafe_dma_context') is self._context:
            b.__dict__.pop('_unsafe_dma_context',None)
        freed=True
        for buffer in (self.txbuf,self.rxbuf):
            if buffer is not None:
                try:buffer.freebuffer()
                except BaseException as error:freed=False;errors.append('buffer free '+repr(error))
        cleanup.update(buffers_freed=freed,errors=errors)
        self._state='CLOSED'
        self.record['status']='FAILED_CLOSED' if self._poisoned or errors else 'CLOSED'
        self._persist_cleanup()
        return cleanup

    def _adopt_recovery(self):
        cleanup=self.record['cleanup']
        errors=cleanup.setdefault('errors',[])
        for error in cleanup.get('late_recovery_errors',[]):
            if error not in errors:errors.append(error)
        if not cleanup.get('late_recovery_errors'):
            cleanup.update(core_reset_requested=self.core is not None,hp1_mode_restored=self.afi is not None)
        self._poisoned=True
        self._state='CLOSED'
        self.record['status']='FAILED_CLOSED'
        self._persist_cleanup()
        return cleanup

    def _persist_cleanup(self):
        try:self._persist()
        except BaseException as error:
            self.record['cleanup'].setdefault('errors',[]).append('record write '+repr(error))

    def close(self):
        self._check_thread()
        if self._busy:raise RuntimeError('Cannot close a concurrent CNN transaction')
        return self._close_impl()
