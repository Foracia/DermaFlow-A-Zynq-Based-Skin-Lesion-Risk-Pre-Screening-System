"""One explicit hardware phase per command. No DMA transfers in this tool."""
import argparse
import json
from pathlib import Path
import uuid
import board_accel as b
from board_trace import call,event


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase',required=True,choices=('metadata','load','control'))
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    a=p.parse_args();root=a.root.resolve();manifest=b.check_manifest(root)
    trace=root/('stage_'+a.phase+'_'+uuid.uuid4().hex+'.jsonl')
    print('TRACE_FILE',str(trace),flush=True)
    pynq=call(trace,'import_pynq',lambda:__import__('pynq'))
    if a.phase in ('metadata','load'):
        ol=call(trace,'parse_overlay_without_download',lambda:pynq.Overlay(str(root/'cnn_system.bit'),download=False))
        actual={n:ol.ip_dict[n]['phys_addr'] for n in ('cnn_accel_0','cnn_dma')}
        if actual!={'cnn_accel_0':0x43c90000,'cnn_dma':0x40400000}:raise RuntimeError('HWH address mismatch')
        print('HWH_ADDRESSES',json.dumps(actual),flush=True)
        if a.phase=='load':call(trace,'download_only_no_cnn_or_dma_mmio',ol.download)
    else:
        active=call(trace,'read_active_bit_record',lambda:pynq.PL.bitfile_name)
        b.confirm_loaded(active,manifest['files']['cnn_system.bit'])
        clock=call(trace,'read_ps_fclk0',lambda:float(pynq.Clocks.fclk0_mhz))
        if abs(clock-100)>.1:raise RuntimeError('FCLK0 must be100MHz')
        core=call(trace,'map_cnn_control',lambda:pynq.MMIO(0x43c90000,4096))
        values={}
        for name,address,expected in [('abi',0,0x434e4e01),('input_words',0x24,16384),('clock_hz',0x28,80000000)]:
            value=call(trace,'read_cnn_'+name,lambda address=address:int(core.read(address)))
            if value!=expected:raise RuntimeError('CNN '+name+' mismatch '+hex(value))
            values[name]=value
        values['status']=call(trace,'read_cnn_status',lambda:int(core.read(8)))
        if values['status']&0x11:raise RuntimeError('CNN busy or resetting after load')
        dma=call(trace,'map_dma_control',lambda:pynq.MMIO(0x40400000,65536))
        values['dma_tx_status']=call(trace,'read_dma_tx_status',lambda:int(dma.read(4)))
        values['dma_rx_status']=call(trace,'read_dma_rx_status',lambda:int(dma.read(0x34)))
        print('CONTROL_VALUES',json.dumps(values),flush=True)
    event(trace,a.phase,'PHASE_PASS')
    print('PHASE_PASS',a.phase,'NO_DMA_TRANSFER',flush=True)


if __name__=='__main__':main()
