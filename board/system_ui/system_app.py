"""SYS02 independent launcher. Inherit frozen SYS01 ownership/cleanup unchanged."""
import argparse
import os
from pathlib import Path

import board_system_ui as ui
from camera_input import prepare_roi as original_prepare
from quality_equivalent import assess_frame as original_assess
from runtime_options import FastViews, PROFILES, choices, prepare_roi, assess_frame
from runtime_timing import StageTimes

_ACTIVE='combined'


def reject_round02_owners(proc_root=Path('/proc'),own_pid=None):
    """Extend the old guard to the new launcher, preserving own sudo ancestors."""
    own_pid=os.getpid() if own_pid is None else own_pid
    ui.reject_other_owners(proc_root,own_pid=own_pid)
    ancestors,current=set(),own_pid
    while current>0:
        try:
            status=(proc_root/str(current)/'status').read_text()
            parent=int(next(s.split(':',1)[1] for s in status.splitlines() if s.startswith('PPid:')))
        except (OSError,ValueError,StopIteration):
            break
        if parent<=0 or parent in ancestors:
            break
        ancestors.add(parent)
        current=parent
    for child in proc_root.iterdir():
        if not child.name.isdigit() or int(child.name)==own_pid:
            continue
        try:
            args=(child/'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:
            continue
        if int(child.name) in ancestors and args and Path(args[0]).name in ('sudo','env'):
            continue
        if any(Path(arg).name in ('system_app.py','board_system_round02.py','board_sys02_compare.py') for arg in args):
            raise RuntimeError('Other SYS02 owner PID '+child.name+'; stop it explicitly first')


class Round02App(ui.SystemApp):
    def __init__(self,*args,candidate=None,**kwargs):
        self.candidate=candidate or _ACTIVE
        self.flags=choices(self.candidate)
        if kwargs.get('implementation','optimized')!='optimized':
            raise ValueError('SYS02 baseline is frozen SYS01 optimized, not PNG6')
        super().__init__(*args,**kwargs)
        self.timings=StageTimes()
        self.report.update(software_round='SYS-Round02',candidate=self.candidate,
                           sys02_baseline='Frozen SYS01 optimized; PNG1 unchanged')
        if self.flags['display']:
            self.views=FastViews(self.here)
            self.page=self.views.menus[0]
        original_result=self.views.result
        def result(packet,*args,**kwargs):
            packet['result'].update(sys02_candidate=self.candidate,software_round='SYS-Round02')
            with self.timings.span('result_page_total'):
                return original_result(packet,*args,**kwargs)
        self.views.result=result

    def bind_controller(self):
        assess=assess_frame if self.flags['quality'] else original_assess
        prepare=prepare_roi if self.flags['input'] else original_prepare
        def measured_assess(*args,**kwargs):
            with self.timings.span('quality_total'):
                return assess(*args,**kwargs)
        def measured_prepare(rgb):
            with self.timings.span('preprocess_total'):
                return prepare(rgb,profiler=self.timings)
        self.controller.assess_fn=measured_assess
        self.controller.prepare_fn=measured_prepare

    def open(self):
        reject_round02_owners()
        super().open()
        self.bind_controller()
        print('SYS02_CONTROLLER_BOUND',self.candidate,flush=True)

    async def write_owned(self,frame):
        with self.timings.span('video_output_wait'):
            return await super().write_owned(frame)

    def persist(self):
        if hasattr(self,'timings'):
            self.report['sys02_timings']=self.timings.report()
        super().persist()


def main(argv=None):
    global _ACTIVE
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--candidate',choices=PROFILES,default='combined')
    selected,remaining=parser.parse_known_args(argv)
    if '--implementation' in remaining:
        parser.error('Use --candidate; SYS02 always retains PNG1')
    _ACTIVE=selected.candidate
    original_class=ui.SystemApp
    ui.SystemApp=Round02App
    try:
        return ui.main(remaining)
    finally:
        ui.SystemApp=original_class


if __name__=='__main__':
    raise SystemExit(main())
