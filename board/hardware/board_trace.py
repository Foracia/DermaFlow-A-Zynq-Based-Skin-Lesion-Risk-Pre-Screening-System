"""Persist BEFORE each potentially blocking call; this is observation, not a bus timeout."""
import json
import os
import time


def event(path,stage,event_name):
    row=dict(stage=stage,event=event_name,monotonic_ns=time.monotonic_ns(),pid=os.getpid())
    with open(path,'a',encoding='utf-8') as stream:
        stream.write(json.dumps(row)+'\n');stream.flush();os.fsync(stream.fileno())
    print('STAGE',event_name,stage,flush=True)


def call(path,stage,action):
    event(path,stage,'BEGIN')
    value=action()
    event(path,stage,'COMPLETE')
    return value


class TracedMMIO:
    def __init__(self,raw,path,label):
        self.raw,self.path,self.label=raw,path,label

    def read(self,offset):
        return call(self.path,self.label+'_read_'+hex(offset),lambda:self.raw.read(offset))

    def write(self,offset,value):
        return call(self.path,self.label+'_write_'+hex(offset),lambda:self.raw.write(offset,value))
