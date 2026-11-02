"""Offline, integer-exact threshold candidates with acquisition-level holdout.

Never learns labels from hardware accept/reject flags. Does not access a board.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from statistics import median

try:
    from .reference import Config, evaluate
except ImportError:
    from reference import Config, evaluate

LABELS = ('normal', 'dark', 'bright', 'blur')
CONDITIONS = LABELS + ('low_texture', 'unlabelled')
STATS = ('pixel_count', 'luma_sum', 'dark_count', 'bright_count',
         'gradient_count', 'gradient_sum')
ABI = '0x51475402'


def integer(value, name, low=0, high=0xffffffff):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name}: expected integer in [{low}, {high}]')
    return value


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ': nonempty string required')
    return value


def config_from_run(run):
    try:
        cfg = Config(**run['config'])
    except (KeyError, TypeError) as error:
        raise ValueError('Invalid configuration record') from error
    fw = integer(run['frame_width'], 'frame_width', 3, 4095)
    fh = integer(run['frame_height'], 'frame_height', 3, 4095)
    if fw * fh > 1048575:
        raise ValueError('Frame exceeds hardware counter width')
    bounds = dict(enable=(0, 1), x0=(0, 4095), y0=(0, 4095), width=(3, 4095),
                  height=(3, 4095), mean_min=(0, 255), mean_max=(0, 255),
                  dark_level=(0, 255), bright_level=(0, 255), dark_max_bp=(0, 10000),
                  bright_max_bp=(0, 10000), sharp_min=(0, 2040), stable_n=(1, 255))
    for name, (low, high) in bounds.items():
        integer(getattr(cfg, name), name, low, high)
    if (cfg.x0 + cfg.width > fw or cfg.y0 + cfg.height > fh
            or cfg.mean_min > cfg.mean_max or cfg.dark_level >= cfg.bright_level):
        raise ValueError('Invalid ROI or threshold ordering')
    return cfg


def cohort_key(run, cfg):
    bit = run['bit_sha256']
    if not isinstance(bit, str) or len(bit) != 64 or any(c not in '0123456789abcdef' for c in bit):
        raise ValueError('bit_sha256 must be lowercase SHA256')
    if run.get('abi') != ABI:
        raise ValueError('Unsupported ABI')
    return dict(bit_sha256=bit, abi=ABI, frame_width=run['frame_width'],
                frame_height=run['frame_height'], x0=cfg.x0, y0=cfg.y0,
                width=cfg.width, height=cfg.height, dark_level=cfg.dark_level,
                bright_level=cfg.bright_level)


def validate_dataset(dataset):
    if type(dataset.get('schema_version')) is not int or dataset['schema_version'] != 1:
        raise ValueError('Expected schema_version=1')
    if not isinstance(dataset.get('runs'), list) or not dataset['runs']:
        raise ValueError('At least one acquisition record is required')
    run_ids, frame_keys = set(), set()
    split_by_acquisition = defaultdict(set)
    cohorts = {}
    for run in dataset['runs']:
        if run.get('status') != 'complete':
            raise ValueError('Failed or incomplete acquisitions cannot enter calibration')
        rid = nonempty(run.get('run_id'), 'run_id')
        acquisition = nonempty(run.get('acquisition_id'), 'acquisition_id')
        if rid in run_ids:
            raise ValueError('Duplicate run_id: ' + rid)
        run_ids.add(rid)
        label, split = run.get('condition'), run.get('split')
        source_kind = run.get('source_kind', 'real_scene')
        if source_kind not in ('real_scene', 'screen_original', 'screen_digital'):
            raise ValueError('Unknown source_kind in ' + rid)
        if source_kind == 'screen_digital' and label != 'unlabelled':
            raise ValueError('Digital screen stimuli cannot fit real-camera thresholds')
        if label not in CONDITIONS or split not in ('train', 'validation', 'unassigned'):
            raise ValueError('Unknown condition or split in ' + rid)
        if label != 'unlabelled' and run.get('label_source') != 'operator':
            raise ValueError('Quality condition requires an operator label')
        if label == 'unlabelled' and split != 'unassigned':
            raise ValueError('Unlabelled data cannot enter training or validation')
        if split != 'unassigned':
            split_by_acquisition[acquisition].add(split)
        cfg = config_from_run(run)
        key = cohort_key(run, cfg)
        cid = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
        group = cohorts.setdefault(cid, dict(key=key, runs=[], excluded=Counter()))
        if not isinstance(run.get('samples'), list):
            raise ValueError('samples must be a list')
        expected_config = integer(run['config_id'], 'config_id')
        eligible = []
        for sample in run['samples']:
            frame = integer(sample['frame_id'], 'frame_id')
            if integer(sample['config_id'], 'sample config_id') != expected_config:
                raise ValueError('Result belongs to a different configuration: ' + rid)
            identity = (acquisition, frame)
            if identity in frame_keys:
                raise ValueError('Duplicate frame within one acquisition: ' + repr(identity))
            frame_keys.add(identity)
            for name in ('present', 'valid'):
                if type(sample[name]) is not bool:
                    raise ValueError(name + ': bool required')
            for name in STATS:
                integer(sample[name], name)
            for name in ('x0', 'y0', 'width', 'height'):
                if integer(sample[name], name) != getattr(cfg, name):
                    raise ValueError('Snapshot ROI disagrees with source configuration')
            if not cfg.enable or not sample['present'] or not sample['valid']:
                group['excluded']['disabled_absent_or_invalid'] += 1
                continue
            n, g = cfg.width * cfg.height, (cfg.width - 2) * (cfg.height - 2)
            if sample['pixel_count'] != n or sample['gradient_count'] != g:
                raise ValueError('Malformed pixel/window count in ' + rid)
            if (sample['luma_sum'] > 255 * n or sample['gradient_sum'] > 2040 * g
                    or sample['dark_count'] + sample['bright_count'] > n):
                raise ValueError('Out-of-range accumulated statistics in ' + rid)
            dark, bright = sample['dark_count'], sample['bright_count']
            middle = n - dark - bright
            minimum = cfg.dark_level * middle + (cfg.bright_level + 1) * bright
            maximum = (cfg.dark_level - 1) * dark + cfg.bright_level * middle + 255 * bright
            if ((cfg.dark_level == 0 and dark) or (cfg.bright_level == 255 and bright)
                    or not minimum <= sample['luma_sum'] <= maximum):
                raise ValueError('Histogram counts contradict luma sum in ' + rid)
            eligible.append(sample)
        group['runs'].append(dict(run=run, config=cfg, eligible=eligible,
                                  excluded=len(run['samples']) - len(eligible)))
    for acquisition, splits in split_by_acquisition.items():
        if len(splits) > 1:
            raise ValueError('Train/validation leakage from acquisition ' + acquisition)
    return cohorts


def _ceil(value):
    return -(-value.numerator // value.denominator)


def fit_normal_envelope(samples, config):
    """Tightest integer accept box retaining every recorded normal training frame."""
    if not samples:
        raise ValueError('No normal training samples')
    mean = [Fraction(s['luma_sum'], s['pixel_count']) for s in samples]
    dark = [Fraction(10000 * s['dark_count'], s['pixel_count']) for s in samples]
    bright = [Fraction(10000 * s['bright_count'], s['pixel_count']) for s in samples]
    sharp = [Fraction(s['gradient_sum'], s['gradient_count']) for s in samples]
    return replace(config, enable=1, mean_min=int(min(mean)), mean_max=_ceil(max(mean)),
                   dark_max_bp=_ceil(max(dark)), bright_max_bp=_ceil(max(bright)),
                   sharp_min=int(min(sharp)), stable_n=3)


def evaluate_runs(rows, cfg):
    """Check expected rejection reason, not just aggregate bad-frame accuracy."""
    totals = defaultdict(Counter)
    examples = []
    for row in rows:
        label = row['run']['condition']
        if label not in LABELS:
            continue
        for sample in row['eligible']:
            valid, exposure, sharp, quality = evaluate(sample, cfg,
                row['run']['frame_width'], row['run']['frame_height'])
            correct = (quality if label == 'normal' else
                       not exposure if label in ('dark', 'bright') else
                       exposure and not sharp)
            correct = valid and correct
            totals[label]['samples'] += 1
            totals[label]['correct'] += bool(correct)
            totals[label]['errors'] += not correct
            if not correct and len(examples) < 20:
                examples.append(dict(run_id=row['run']['run_id'], frame_id=sample['frame_id'],
                                     condition=label, exposure_ok=exposure, sharpness_ok=sharp))
    return dict(by_condition={k: dict(v) for k, v in totals.items()}, error_examples=examples,
                errors=sum(v['errors'] for v in totals.values()))


def analyze_dataset(dataset, *, min_samples=10, min_train_acquisitions=2):
    integer(min_samples, 'min_samples', 1)
    integer(min_train_acquisitions, 'min_train_acquisitions', 1)
    groups = validate_dataset(dataset)
    result = dict(schema_version=1, method='tight_integer_envelope_from_normal_training_only',
                  automatically_applied=False, stable_n_calibrated=False, cohorts={})
    for cid, group in groups.items():
        rows = group['runs']
        eligible = [s for r in rows for s in r['eligible']]
        analysis = dict(cohort=group['key'], total_samples=sum(len(r['run']['samples']) for r in rows),
                        eligible_samples=len(eligible), excluded=dict(group['excluded']),
                        labels=dict(Counter(r['run']['condition'] for r in rows)),
                        blockers=[], candidate_config=None, ready_for_controlled_board_validation=False)
        analysis['ranges'] = {}
        for name, numerator, denominator in [('mean_luma', 'luma_sum', 'pixel_count'),
                ('dark_ratio', 'dark_count', 'pixel_count'), ('bright_ratio', 'bright_count', 'pixel_count'),
                ('sharpness_score', 'gradient_sum', 'gradient_count')]:
            values = [s[numerator] / s[denominator] for s in eligible]
            analysis['ranges'][name] = dict(min=min(values), median=median(values), max=max(values)) if values else None
        coverage = {}
        for split, required in [('train', min_train_acquisitions), ('validation', 1)]:
            coverage[split] = {}
            for label in LABELS:
                selected = [r for r in rows if r['run']['split'] == split and r['run']['condition'] == label]
                good = {r['run']['acquisition_id'] for r in selected if len(r['eligible']) >= min_samples and r['excluded'] == 0}
                coverage[split][label] = len(good)
                if len(good) < required:
                    analysis['blockers'].append(f'{split}:{label}:need_{required}_independent_acquisitions_with_{min_samples}_valid_frames')
        analysis['coverage'] = coverage
        training = [r for r in rows if r['run']['split'] == 'train' and r['run']['condition'] in LABELS]
        validation = [r for r in rows if r['run']['split'] == 'validation' and r['run']['condition'] in LABELS]
        train_ready = all(coverage['train'][label] >= min_train_acquisitions for label in LABELS)
        if any(r['excluded'] for r in training + validation):
            analysis['blockers'].append('labelled_acquisition_contains_invalid_or_disabled_frames')
        if train_ready:
            normal = [s for r in training if r['run']['condition'] == 'normal' for s in r['eligible']]
            candidate = fit_normal_envelope(normal, training[0]['config'])
            analysis['candidate_config'] = asdict(candidate)
            analysis['training_evaluation'] = evaluate_runs(training, candidate)
            analysis['validation_evaluation'] = evaluate_runs(validation, candidate)
            if analysis['training_evaluation']['errors']:
                analysis['blockers'].append('training_candidate_condition_mismatches')
            if analysis['validation_evaluation']['errors']:
                analysis['blockers'].append('independent_validation_errors_do_not_retune_on_holdout')
        analysis['ready_for_controlled_board_validation'] = bool(train_ready and not analysis['blockers'])
        analysis['status'] = ('candidate_ready_for_controlled_board_validation'
                              if analysis['ready_for_controlled_board_validation'] else 'more_data_or_review_required')
        result['cohorts'][cid] = analysis
    return result
