"""Optional bounded, in-memory diagnostics; never writes in the video loop."""
import time


def stats(values):
    values=sorted(values)
    if not values:return dict(calls=0,total_ms=0.,mean_ms=None,p95_ms=None,max_ms=None)
    index=(len(values)-1)*.95;low=int(index);high=min(low+1,len(values)-1)
    return dict(calls=len(values),total_ms=sum(values),mean_ms=sum(values)/len(values),
                p95_ms=values[low]+(values[high]-values[low])*(index-low),max_ms=values[-1])


class _Span:
    def __init__(self,profile,name,phase):self.profile,self.name,self.phase=profile,name,phase
    def __enter__(self):
        if self.profile.enabled:self.start=self.profile.clock()
        return self
    def __exit__(self,kind,error,tb):
        if not self.profile.enabled:return
        row=dict(name=self.name,duration_ms=(self.profile.clock()-self.start)/1e6,
                 failed=kind is not None,error_type=kind.__name__ if kind else None)
        frame=self.profile.current_frame
        rows=frame.stages if frame is not None else self.profile.setup_stages
        # Bounds also apply to unexpectedly repeated spans within one frame.
        if len(rows)<64:rows.append(row)
        else:self.profile.dropped_stages+=1


class _Frame:
    def __init__(self,profile,sequence,phase):
        self.profile,self.sequence,self.phase=profile,sequence,phase
        self.submitted=False;self.stages=[]
    def __enter__(self):
        if self.profile.enabled:
            if self.profile.current_frame is not None:raise RuntimeError('Nested profile frames')
            self.start=self.profile.clock();self.profile.current_frame=self
        return self
    def __exit__(self,kind,error,tb):
        p=self.profile
        if not p.enabled:return
        end=p.clock();p.current_frame=None
        row=dict(sequence=self.sequence,phase=self.phase,start_monotonic_ns=self.start,
                 end_monotonic_ns=end,duration_ms=(end-self.start)/1e6,
                 submitted=self.submitted,failed=kind is not None,stages=self.stages)
        if len(p.frames)<p.max_frames:p.frames.append(row)
        else:p.dropped_frames+=1


class PipelineProfile:
    def __init__(self,enabled=True,max_frames=4096,clock=None):
        self.enabled=enabled;self.max_frames=max_frames
        self.clock=clock or time.monotonic_ns
        self.frames=[];self.setup_stages=[];self.current_frame=None
        self.dropped_frames=0;self.dropped_stages=0

    def span(self,name):return _Span(self,name,'setup')
    def frame(self,sequence,phase):return _Frame(self,sequence,phase)

    def report(self):
        phases={}
        for row in self.frames:
            phase=phases.setdefault(row['phase'],dict(rows=[],stages={}))
            phase['rows'].append(row)
            for stage in row['stages']:
                phase['stages'].setdefault(stage['name'],[]).append(stage)
        for phase in phases.values():
            rows=phase.pop('rows')
            wall=(rows[-1]['end_monotonic_ns']-rows[0]['start_monotonic_ns'])/1e6
            submitted=sum(row['submitted'] for row in rows)
            phase.update(attempted_frames=len(rows),submitted_frames=submitted,
                         failed_frames=sum(row['failed'] for row in rows),elapsed_wall_ms=wall,
                         submitted_fps=submitted*1000/wall if wall>0 else None,
                         frame_total=stats([row['duration_ms'] for row in rows]))
            phase['stages']={name:dict(stats([s['duration_ms'] for s in samples]),
                                      failed_calls=sum(s['failed'] for s in samples))
                             for name,samples in phase['stages'].items()}
        return dict(schema_version=1,enabled=self.enabled,clock='time.monotonic_ns',
                    diagnostic_not_benchmark=True,nested_stages_are_inclusive=True,
                    phase_fps_scope='Submitted frames / phase wall window, including waits; not HDMI source FPS or optical display latency',
                    summary_retained_frames_only=bool(self.dropped_frames),max_frames=self.max_frames,
                    dropped_frames=self.dropped_frames,dropped_stages=self.dropped_stages,
                    phases=phases,setup_stages=list(self.setup_stages),frames=list(self.frames))
