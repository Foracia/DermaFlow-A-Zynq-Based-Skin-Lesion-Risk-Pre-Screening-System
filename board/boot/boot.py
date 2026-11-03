#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record PYNQ startup; the DermaFlow terminal loads the FPGA configuration."""
import time

now = time.strftime('%Y-%m-%d %H:%M:%S')
message = 'DermaFlow boot at %s; FPGA configuration is managed by the terminal.\n' % now
print('[boot.py] ' + message.strip())
for path in ('/boot/boot_hook.log', '/mnt/boot/boot_hook.log'):
    try:
        with open(path, 'w') as stream:
            stream.write(message)
        break
    except OSError as error:
        print('[boot.py] %s: %s' % (path, error))
