"""Bounded in-memory stage timings; nested spans must not be added together."""
from contextlib import contextmanager
import time

import numpy as np


class StageTimes:
    def __init__(self, limit=4096):
        self.limit,self.rows,self.dropped=limit,[],0

    @contextmanager
    def span(self,name):
        started=time.perf_counter_ns()
        failed=False
        try:
            yield
        except BaseException:
            failed=True
            raise
        finally:
            elapsed=(time.perf_counter_ns()-started)/1e6
            if len(self.rows)<self.limit:
                self.rows.append(dict(stage=name,ms=elapsed,failed=failed))
            else:
                self.dropped+=1

    def report(self):
        out={}
        for name in sorted({r['stage'] for r in self.rows}):
            rows=[r for r in self.rows if r['stage']==name]
            values=np.asarray([r['ms'] for r in rows],np.float64)
            out[name]=dict(n=len(rows),mean_ms=float(values.mean()),median_ms=float(np.median(values)),
                           p95_ms=float(np.percentile(values,95)),max_ms=float(values.max()),
                           failed=sum(r['failed'] for r in rows))
        return dict(clock='perf_counter_ns',nested_stages_inclusive=True,
                    dropped_samples=self.dropped,stages=out,raw_rows=list(self.rows))
