"""Inspect by default; install only after a successful manual candidate run.

This script never starts/enables a service, loads an overlay, changes boot.py,
sets a clock, drops caches or installs dependencies. User performs cold-start
validation after explicit installation and enable/start commands.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

UNIT = 'derm-terminal.service'
UNIT_PATH = Path('/etc/systemd/system') / UNIT
BACKUPS = Path('/home/xilinx/derm_terminal_service_backups')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_manual_proof(path, tools, tools_sha, bit_sha):
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = dict(status='SYSTEM_UI_SESSION_COMPLETE', model_manifest_sha256=tools['model_manifest_sha256'],
        bitstream_sha256=bit_sha)
    identities = {(tools['revision'],tools_sha)}
    identities.update((old['revision'],old['tools_manifest_sha256'])
                      for old in tools.get('accepted_previous_manual_proofs', []))
    if (any(record.get(k) != v for k,v in expected.items()) or
            (record.get('tools_revision'),record.get('tools_manifest_sha256')) not in identities):
        raise ValueError('Manual successful session identity/status does not match this candidate')
    rows = record.get('golden', [])
    expected_raw = ['1ce3','ff00','d12f','1ce3']
    if len(rows) != 4 or any(r.get('raw_hex') != raw or r.get('expected_hex') != raw for r,raw in zip(rows,expected_raw)):
        raise ValueError('Candidate must have four successful golden checks')
    captures = record.get('captures', [])
    if not all(any(r.get('mode') == mode and r.get('save_status') == 'complete' for r in captures) for mode in ('normal','fusion')):
        raise ValueError('Manually exercise and save normal and fusion modes before installing')
    cleanup = record.get('cleanup', {})
    cnn = cleanup.get('cnn', {})
    if (cleanup.get('errors') or cnn.get('errors') or not cleanup.get('video_dma_stopped') or
            not cleanup.get('event_loop_closed') or
            not all(cnn.get(key) for key in ('dma_reset_and_halted','buffers_freed','hp1_mode_restored'))):
        raise ValueError('Manual session did not confirm safe cleanup')
    return record


def systemctl(*args, check=False):
    value = subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=30)
    if check and value.returncode != 0:
        raise RuntimeError('systemctl %s: %s' % (' '.join(args), value.stderr.strip()))
    return value.stdout.strip() or value.stderr.strip()


def inactive(unit):
    state = systemctl('is-active', unit)
    if state not in ('inactive','failed','unknown'):
        raise RuntimeError('Stop %s explicitly and confirm DMA cleanup first; state=%s' % (unit,state))
    return state


def enabled_state(unit):
    # is-enabled may emit a localized ENOENT only on stderr for absent units.
    # Read a machine property first; do not infer state from an error sentence.
    loaded = subprocess.run(['systemctl','show',unit,'--property=LoadState','--value'],
                            capture_output=True,text=True,timeout=30)
    state = loaded.stdout.strip()
    if state == 'not-found':
        return state
    if loaded.returncode != 0 or state not in ('loaded','masked'):
        raise RuntimeError('Unable to query structured LoadState for '+unit+': '+loaded.stderr.strip())
    return systemctl('is-enabled',unit)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def validate_service_states(states):
    supported = {'enabled','disabled','static','not-found'}
    for unit, record in states.items():
        if record.get('enabled') not in supported:
            raise ValueError('Unsupported service enable/link state for %s: %s; no configuration changed' %
                             (unit,record.get('enabled')))


def install(here, root, proof):
    from board_terminal_service import verify, check_boot_owner, reject_service_owners, unit_text
    from system_app import reject_round02_owners
    tools, model = verify(here, root)
    check_boot_owner(here)
    reject_service_owners()
    reject_round02_owners()
    before = {unit:dict(active=inactive(unit), enabled=enabled_state(unit)) for unit in (UNIT,'derm-ui.service')}
    validate_service_states(before)
    if UNIT_PATH.is_symlink():
        raise ValueError('Existing terminal unit is a symbolic link; inspect before replacing')
    manual_record = validate_manual_proof(proof, tools, digest(here/'system_tools_manifest.json'), model['files']['cnn_system.bit'])
    target_text = unit_text(here, root, standalone=tools.get('standalone_controls',False))
    backup = BACKUPS / uuid.uuid4().hex
    backup.mkdir(parents=True)
    old = UNIT_PATH.read_bytes() if UNIT_PATH.exists() else None
    if old is not None:
        (backup/'previous_derm-terminal.service').write_bytes(old)
    receipt = dict(status='PREPARED', package=str(here), root=str(root),
        before=before, previous_unit_existed=old is not None,
        previous_unit_sha256=None if old is None else hashlib.sha256(old).hexdigest(),
        installed_unit_sha256=hashlib.sha256(target_text.encode()).hexdigest(),
        proof=str(proof), proof_sha256=digest(proof), model_manifest_sha256=tools['model_manifest_sha256'],
        proof_tools_revision=manual_record['tools_revision'],
        proof_tools_manifest_sha256=manual_record['tools_manifest_sha256'],
        no_service_started=True, no_service_enabled=True, boot_file_changed=False)
    save(backup/'installation.json', receipt)
    temporary = UNIT_PATH.with_name(UNIT+'.sys03-new')
    if temporary.exists():
        raise RuntimeError('Prior deployment temporary file exists; inspect before overwriting')
    temporary.write_text(target_text, encoding='utf-8', newline='\n')
    temporary.replace(UNIT_PATH)
    systemctl('daemon-reload', check=True)
    # Prevent the previous overlay owner from returning at next boot.
    if before['derm-ui.service']['enabled'] == 'enabled':
        systemctl('disable','derm-ui.service', check=True)
    receipt['status'] = 'INSTALLED_NOT_ENABLED_OR_STARTED'
    save(backup/'installation.json', receipt)
    print('SERVICE_INSTALLED_NOT_STARTED', UNIT, 'BACKUP', backup, flush=True)
    print('NEXT_EXPLICIT_COMMAND: sudo systemctl enable --now '+UNIT, flush=True)
    return backup


def rollback(backup):
    backup = Path(backup).resolve()
    if not backup.is_relative_to(BACKUPS.resolve()) or backup.parent != BACKUPS.resolve():
        raise ValueError('Expected one specific deployment backup directory')
    record = json.loads((backup/'installation.json').read_text(encoding='utf-8'))
    validate_service_states(record['before'])
    inactive(UNIT)
    inactive('derm-ui.service')
    if not UNIT_PATH.exists() or digest(UNIT_PATH) != record['installed_unit_sha256']:
        raise ValueError('Current unit changed after installation; refusing to overwrite another configuration')
    systemctl('disable',UNIT, check=True)
    if record['previous_unit_existed']:
        previous = backup/'previous_derm-terminal.service'
        if digest(previous) != record['previous_unit_sha256']:
            raise ValueError('Previous unit backup changed')
        UNIT_PATH.write_bytes(previous.read_bytes())
    else:
        UNIT_PATH.unlink()  # Only this exact hash-verified installed unit is removed.
    systemctl('daemon-reload', check=True)
    for unit in (UNIT,'derm-ui.service'):
        if record['before'][unit]['enabled'] == 'enabled':
            systemctl('enable',unit,check=True)
    print('SERVICE_CONFIGURATION_ROLLED_BACK_NO_SERVICE_STARTED', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--validated-run', type=Path)
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args(argv)
    if args.rollback and (args.install or args.validated_run or args.root):
        parser.error('Rollback is a separate operation')
    if args.install and not args.validated_run:
        parser.error('--install requires --validated-run from this candidate')
    if sys.platform != 'linux':
        raise RuntimeError('Board deployment inspection requires Linux; this PC prepares files only')
    if (args.install or args.rollback) and os.geteuid() != 0:
        raise RuntimeError('Explicit installation/rollback requires root')
    if args.rollback:
        rollback(args.rollback)
        return 0
    here = Path(__file__).resolve().parent
    binding = json.loads((here/'terminal_binding.json').read_text(encoding='utf-8'))
    root = args.root.resolve() if args.root else here.parent / 'hardware'
    if args.install:
        install(here, root, args.validated_run.resolve())
    else:
        from board_terminal_service import verify, check_boot_owner
        tools, model = verify(here, root)
        try:
            check_boot_owner(here)
            boot = dict(matches_inspected_no_overlay_hook=True)
        except RuntimeError as error:
            boot = dict(matches_inspected_no_overlay_hook=False, detail=str(error))
        print(json.dumps(dict(status='READ_ONLY_INSPECTION', revision=tools['revision'], hardware_round=model['round'],
            boot=boot, services={unit:dict(active=systemctl('is-active',unit),enabled=enabled_state(unit))
                               for unit in (UNIT,'derm-ui.service')},
            pynq_boot_services=systemctl('list-unit-files','--no-pager','pynq*','jupyter*'),
            changed=False), indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
