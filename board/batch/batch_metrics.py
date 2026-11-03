"""Native HLS candidate fixtures and validation-only metrics (no retraining)."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'build/output/native_evaluation'
FIXTURES = RESULTS / 'fixtures'
MODELS = ROOT / 'data/models'
GOLDEN_INPUT = ROOT / 'data/golden/model/input.npy'
GOLDEN_REFERENCE = ROOT / 'data/golden/model/onnx_out.npy'
OPERATING_POINT = ROOT / 'data/golden/model/meta.json'
SOURCE = MODELS / 'model.onnx'
EXPECTED_SOURCE = '39e60c35b055870a1c333507be662754124ad15a61a9aae730cd256c295b2785'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def probability(logits, temperature):
    logits = np.asarray(logits, dtype=np.float64)
    if (logits.ndim != 2 or logits.shape[1] != 2 or len(logits) == 0
            or not np.isfinite(logits).all() or not np.isfinite(temperature) or temperature <= 0):
        raise ValueError('Expected nonempty finite [N,2] logits and positive temperature')
    scaled = logits / temperature
    scaled -= scaled.max(axis=1, keepdims=True)
    exp = np.exp(scaled)
    return exp[:, 1] / exp.sum(axis=1)


def metrics(labels, logits, temperature, threshold):
    labels = np.asarray(labels)
    logits = np.asarray(logits, dtype=np.float64)
    if (labels.ndim != 1 or len(labels) == 0 or logits.shape != (len(labels), 2)
            or not np.isin(labels, [0, 1]).all() or not np.isfinite(threshold)
            or not 0 <= threshold <= 1):
        raise ValueError('Invalid binary labels, logits, or threshold')
    prob = probability(logits, temperature)
    pred = prob >= threshold
    tn = int(np.sum((labels == 0) & ~pred))
    fp = int(np.sum((labels == 0) & pred))
    fn = int(np.sum((labels == 1) & ~pred))
    tp = int(np.sum((labels == 1) & pred))
    recall = tp / (tp + fn) if tp + fn else None
    spec = tn / (tn + fp) if tn + fp else None
    pos, neg = prob[labels == 1], prob[labels == 0]
    # Pairwise definition handles tied ranks explicitly, without new sklearn dependency.
    auc = float(np.mean((pos[:, None] > neg) + .5 * (pos[:, None] == neg))) if len(pos) and len(neg) else None
    f1pos = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.
    f1neg = 2 * tn / (2 * tn + fp + fn) if 2 * tn + fp + fn else 0.
    scaled = logits / temperature
    margin = scaled[:, 1] - scaled[:, 0]
    nll = float(np.mean(np.logaddexp(0., margin) - labels * margin))
    return {'n': len(labels), 'temperature': float(temperature), 'threshold': float(threshold),
            'comparison': '>=', 'auc': auc, 'confusion_matrix': [[tn, fp], [fn, tp]],
            'TP': tp, 'FN': fn, 'TN': tn, 'FP': fp, 'positive_recall': recall,
            'specificity': spec, 'balanced_accuracy': (recall + spec)/2 if recall is not None and spec is not None else None,
            'macro_f1': (f1pos + f1neg)/2, 'precision': tp/(tp+fp) if tp+fp else 0.,
            'accuracy': (tp+tn)/len(labels), 'NLL': nll,
            'Brier': float(np.mean((prob-labels)**2))}


def compare(actual, reference, temperature, threshold):
    actual, reference = np.asarray(actual, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    if actual.shape != reference.shape:
        raise ValueError('Actual/reference shape mismatch')
    ap, rp = probability(actual, temperature), probability(reference, temperature)
    diff = np.abs(actual-reference)
    return {'sample_count': len(actual), 'max_abs_logits_error': float(diff.max()),
            'mean_abs_logits_error': float(diff.mean()),
            'argmax_mismatches': int(np.sum(actual.argmax(1) != reference.argmax(1))),
            'threshold_decision_mismatches': int(np.sum((ap >= threshold) != (rp >= threshold))),
            'max_abs_positive_probability_error': float(np.abs(ap-rp).max()),
            'mean_abs_positive_probability_error': float(np.abs(ap-rp).mean())}


def prepare(image_root=None):
    """Use the existing CPU environment's PIL, not a new dependency in PL venv."""
    save_json(RESULTS / 'fixed_eval_fixtures.json', {'status': 'PREPARING'})
    import onnxruntime as ort
    from dataset_io import read_split, load_image_tensor
    package = MODELS
    if sha(SOURCE) != EXPECTED_SOURCE:
        raise ValueError('Delivered source CNN identity changed')
    image_root = Path(image_root).resolve() if image_root is not None else ROOT / 'data/dataset'
    rows = read_split(package / 'split.json', 'val', image_root)
    if len(rows) != 342:
        raise ValueError('Expected the frozen 342-image validation split')
    pp = json.loads((package / 'preprocess.json').read_text(encoding='utf-8'))
    if pp['channel_order'] != 'RGB' or pp['resize'] != [128, 128]:
        raise ValueError('Unexpected preprocessing contract')
    golden = np.load(GOLDEN_INPUT, allow_pickle=False)
    values = [golden]
    records = []
    for i, row in enumerate(rows):
        values.append(load_image_tensor(row.path, tuple(pp['mean']), tuple(pp['std'])))
        records.append({'relative_path': row.relative_path, 'label': row.label,
                        'disease': row.disease, 'image_sha256': sha(row.path),
                        'patient_id': row.patient_id, 'lesion_id': row.lesion_id})
        if (i+1) % 100 == 0:
            print(f'prepared validation images {i+1}/{len(rows)}', flush=True)
    nchw = np.concatenate(values).astype(np.float32)
    if nchw.shape != (348, 3, 128, 128) or not np.isfinite(nchw).all():
        raise ValueError('Invalid fixture shapes/values')
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(SOURCE), options, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name
    outputs = np.concatenate([session.run(None, {name: x[None]})[0] for x in nchw])
    golden_reference = np.load(GOLDEN_REFERENCE, allow_pickle=False)
    if np.max(np.abs(outputs[:6] - golden_reference)) > 1e-5:
        raise ValueError('Fresh original ONNX reference disagrees with frozen golden')
    FIXTURES.mkdir(parents=True, exist_ok=True)
    inputs = FIXTURES / 'inputs.bin'
    np.ascontiguousarray(nchw.transpose(0, 2, 3, 1), dtype='<f4').tofile(inputs)
    refs = FIXTURES / 'reference.npy'
    np.save(refs, outputs)
    labels = FIXTURES / 'labels.npy'
    np.save(labels, np.array([x.label for x in rows], dtype=np.int64))
    op = json.loads(OPERATING_POINT.read_text(encoding='utf-8'))
    manifest = {'status': 'PREPARED', 'source_sha256': sha(SOURCE),
                'sample_count': 348, 'golden_count': 6, 'validation_count': 342,
                'partition': 'val', 'test_used': False, 'input_layout': 'NHWC',
                'input_format': 'little-endian float32 raw; [348,128,128,3]',
                'inputs': str(inputs), 'reference': str(refs), 'labels': str(labels),
                'inputs_sha256': sha(inputs), 'reference_sha256': sha(refs), 'labels_sha256': sha(labels),
                'golden_input_sha256': sha(GOLDEN_INPUT),
                'split_sha256': sha(package / 'split.json'),
                'preprocess_sha256': sha(package / 'preprocess.json'),
                'operating_point_sha256': sha(OPERATING_POINT),
                'temperature': op['temperature'], 'threshold': op['frozen_threshold'],
                'records': records, 'prepare_script_sha256': sha(__file__)}
    save_json(RESULTS / 'fixed_eval_fixtures.json', manifest)
    print(json.dumps({'status': 'PREPARED', 'sample_count': 348, 'fixtures_dir': str(FIXTURES)}))


def testbench(project_name, inputs, output, count):
    if (not str(inputs).isascii() or not str(output).isascii()
            or not re.fullmatch(r'derm_(minmax16|minmax8|float)', project_name)
            or count not in (6, 348)):
        raise ValueError('Invalid native testbench identity, count or ASCII paths')
    ip, op = inputs.as_posix(), output.as_posix()
    if any(c in ip+op for c in ('"', '\n', '\r')):
        raise ValueError('Unsafe C++ path')
    return f'''#include <fstream>
#include <iostream>
#include <iomanip>
#include <cmath>
#include <map>
#include <string>
#include "firmware/{project_name}.h"
#include "firmware/nnet_utils/nnet_helpers.h"
namespace nnet {{ bool trace_enabled = false; std::map<std::string, void*>* trace_outputs = NULL; size_t trace_type_size = sizeof(double); }}
int main() {{
    static_assert(input_t::size == 3 && result_t::size == 2, "Unexpected external packing");
    std::ifstream fin("{ip}", std::ios::binary);
    std::ofstream fout("{op}", std::ios::trunc);
    if (!fin || !fout) {{ std::cerr << "Fixture/output open failed"; return 2; }}
    fout << std::setprecision(17);
    hls::stream<input_t> global_in("global_in");
    hls::stream<result_t> output("output");
    for (unsigned sample = 0; sample < {count}; ++sample) {{
        for (unsigned pixel = 0; pixel < 128*128; ++pixel) {{
            float raw[3]; fin.read(reinterpret_cast<char*>(raw), sizeof(raw));
            if (!fin) {{ std::cerr << "Truncated input"; return 3; }}
            input_t pack;
            for (unsigned c=0; c<3; ++c) {{
                if (!std::isfinite(raw[c])) return 4;
                pack[c] = raw[c];
            }}
            global_in.write(pack);
        }}
        {project_name}(global_in, output);
        if (!global_in.empty() || output.empty()) {{ std::cerr << "Stream consumption/output failure"; return 5; }}
        result_t result = output.read();
        if (!output.empty()) return 6;
        double a = static_cast<double>(result[0]), b = static_cast<double>(result[1]);
        if (!std::isfinite(a) || !std::isfinite(b)) return 7;
        fout << sample << ' ' << a << ' ' << b << " 16384 1 0 0\\n";
        fout.flush();
        if (!fout) return 8;
        if ((sample+1)%20 == 0 || sample+1 == {count}) std::cout << "Completed " << sample+1 << "/{count}" << std::endl;
    }}
    return 0;
}}
'''


def validate_fixtures(manifest):
    if (manifest.get('status') != 'PREPARED' or manifest.get('partition') != 'val'
            or manifest.get('sample_count') != 348 or manifest.get('golden_count') != 6
            or manifest.get('validation_count') != 342 or manifest.get('test_used') is not False
            or manifest['source_sha256'] != sha(SOURCE) or sha(SOURCE) != EXPECTED_SOURCE):
        raise ValueError('Fixture source/count/partition identity failed')
    for key in ('inputs', 'reference', 'labels'):
        if sha(manifest[key]) != manifest[key+'_sha256']:
            raise ValueError(f'Fixture hash changed: {key}')
    package = MODELS
    for key, path in (('split', package/'split.json'), ('preprocess', package/'preprocess.json'),
                      ('operating_point', OPERATING_POINT), ('golden_input', GOLDEN_INPUT)):
        if sha(path) != manifest[key+'_sha256']:
            raise ValueError(f'Frozen contract hash changed: {key}')
    op = json.loads(OPERATING_POINT.read_text(encoding='utf-8'))
    validate_operating_point(manifest, op)

    rows = json.loads((package/'split.json').read_text(encoding='utf-8'))['val']
    labels = np.load(manifest['labels'], allow_pickle=False)
    if len(rows) != 342 or not np.array_equal(labels, [r[1] for r in rows]):
        raise ValueError('Fixture labels differ from frozen validation split')
    if len(manifest['records']) != len(rows) or any(
            record['relative_path'] != row[0] or record['label'] != row[1]
            or record['patient_id'] != str(row[2]) or record['lesion_id'] != str(row[3])
            or record['disease'] != Path(row[0]).stem.rsplit('_', 1)[-1]
            for record, row in zip(manifest['records'], rows)):
        raise ValueError('Fixture records differ from frozen validation split')
    reference = np.load(manifest['reference'], allow_pickle=False)
    if reference.shape != (348, 2) or reference.dtype != np.float32 or not np.isfinite(reference).all():
        raise ValueError('Invalid original ONNX reference array')
    if Path(manifest['inputs']).stat().st_size != 348*128*128*3*4:
        raise ValueError('Input binary length inconsistent with NHWC fixture count')


def validate_operating_point(manifest, operating_point):
    if (manifest['temperature'] != operating_point['temperature']
            or manifest['threshold'] != operating_point['frozen_threshold']):
        raise ValueError('Fixture operating point differs from frozen source contract')


def firmware_hashes(project):
    files = sorted((project/'firmware').rglob('*'))
    return {p.relative_to(project).as_posix(): sha(p) for p in files if p.is_file()}


def install(report_path, count):
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    kind = report['precision_kind']
    if kind not in ('minmax16', 'minmax8', 'float'):
        raise ValueError('Unexpected candidate kind')
    save_json(RESULTS/f'{kind}_fixed_evaluation.json', {'status': 'NOT_RUN', 'sample_count': count})
    manifest = json.loads((RESULTS / 'fixed_eval_fixtures.json').read_text(encoding='utf-8'))
    validate_fixtures(manifest)
    if report['status'] != 'READY_FOR_CSIM' or report['io_type'] != 'io_stream':
        raise ValueError('Candidate generation has not passed stream safety gates')
    project = Path(report['project_dir'])
    if not project.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or not str(project).isascii():
        raise ValueError('Testbench must be installed only in ASCII temporary generated project')
    name = 'derm_' + kind
    output = project/'tb_data/fixed_eval_results.tsv'
    if output.exists():
        output.unlink()  # Exact generated transient result, never a delivered source artifact.
    tb = project/(name+'_test.cpp')
    tb.write_text(testbench(name, Path(manifest['inputs']), output, count), encoding='utf-8')
    execution = {'status': 'AWAITING_NATIVE_RUN', 'sample_count': count, 'project_dir': str(project),
                 'precision_kind': kind, 'output': str(output), 'testbench_sha256': sha(tb),
                 'firmware_sha256': firmware_hashes(project), 'build_tcl_sha256': sha(project/'build_prj.tcl'),
                 'build_options_sha256': sha(project/'build_opt.tcl'), 'generation_report_sha256': sha(report_path),
                 'generation_report': str(Path(report_path).resolve()),
                 'fixture_manifest_sha256': sha(RESULTS/'fixed_eval_fixtures.json'),
                 'source_sha256': sha(SOURCE), 'temperature': manifest['temperature'], 'threshold': manifest['threshold']}
    save_json(RESULTS/f'{kind}_native_eval_manifest.json', execution)
    print(json.dumps({'status': execution['status'], 'project_dir': str(project), 'sample_count': count}))


def read_outputs(path, count):
    data = np.loadtxt(path, ndmin=2)
    if data.shape != (count, 7) or not np.isfinite(data).all():
        raise ValueError('Native output row/count/finite check failed')
    expected = np.tile([16384, 1, 0, 0], (count, 1))
    if not np.array_equal(data[:, 0], np.arange(count)) or not np.array_equal(data[:, 3:], expected):
        raise ValueError('Native sequence or stream counts failed')
    return data[:, 1:3]


def finish(kind, native_exit):
    output_report = RESULTS/f'{kind}_fixed_evaluation.json'
    result = {'status': 'FAILED_VALIDATION', 'native_exit_code': native_exit,
              'synthesis': 'NOT_RUN', 'board_inference': 'NOT_RUN'}
    save_json(output_report, result)  # Never preserve a previous successful check on failure.
    try:
        if native_exit != 0:
            raise ValueError('Native C simulation did not exit successfully')
        execution = json.loads((RESULTS/f'{kind}_native_eval_manifest.json').read_text(encoding='utf-8'))
        manifest_path = RESULTS/'fixed_eval_fixtures.json'
        if sha(manifest_path) != execution['fixture_manifest_sha256']:
            raise ValueError('Fixture manifest changed after testbench installation')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        validate_fixtures(manifest)
        project = Path(execution['project_dir'])
        if execution['sample_count'] not in (6, 348) or execution['precision_kind'] != kind:
            raise ValueError('Native manifest candidate/count identity failed')
        if sha(execution['generation_report']) != execution['generation_report_sha256']:
            raise ValueError('Candidate generation report changed after installation')
        if firmware_hashes(project) != execution['firmware_sha256']:
            raise ValueError('Generated firmware changed during native run')
        for path, key in ((project/f'derm_{kind}_test.cpp', 'testbench_sha256'),
                          (project/'build_prj.tcl', 'build_tcl_sha256'),
                          (project/'build_opt.tcl', 'build_options_sha256')):
            if sha(path) != execution[key]:
                raise ValueError('Native testbench/build configuration changed')
        count = execution['sample_count']
        actual = read_outputs(Path(execution['output']), count)
        reference = np.load(manifest['reference'], allow_pickle=False)[:count]
        t, threshold = manifest['temperature'], manifest['threshold']
        result.update({'status': 'NATIVE_EVALUATION_COMPLETE', 'precision_kind': kind,
                       'sample_count': count, 'project_dir': str(project),
                       'source_sha256': sha(SOURCE), 'fixture_manifest_sha256': sha(manifest_path),
                       'native_manifest_sha256': sha(RESULTS/f'{kind}_native_eval_manifest.json'),
                       'output_sha256': sha(execution['output']),
                       'temperature': t, 'frozen_threshold': threshold, 'threshold_refitted': False,
                       'test_used': False, 'golden': compare(actual[:6], reference[:6], t, threshold),
                       'actual_logits': actual.tolist(), 'finish_script_sha256': sha(__file__),
                       'actual_internal_saturation_instrumentation': 'NOT_IMPLEMENTED',
                       'note': 'Real native candidate outputs; evaluation completion is not a quantization acceptance verdict.'})
        if count == 348:
            labels = np.load(manifest['labels'], allow_pickle=False)
            result['validation'] = metrics(labels, actual[6:], t, threshold)
            result['reference_validation'] = metrics(labels, reference[6:], t, threshold)
            result['validation_comparison'] = compare(actual[6:], reference[6:], t, threshold)
            result['by_disease_validation'] = {}
            diseases = np.array([r['disease'] for r in manifest['records']])
            for disease in sorted(set(diseases)):
                selected = diseases == disease
                result['by_disease_validation'][disease] = {
                    'actual': metrics(labels[selected], actual[6:][selected], t, threshold),
                    'reference': metrics(labels[selected], reference[6:][selected], t, threshold)}
    except Exception as exc:
        result['status'] = 'FAILED_VALIDATION'
        result['error'] = str(exc)
    save_json(output_report, result)
    print(json.dumps({k: result[k] for k in ('status', 'precision_kind', 'sample_count', 'golden',
                                         'validation', 'validation_comparison', 'error') if k in result}))
    return 0 if result['status'] == 'NATIVE_EVALUATION_COMPLETE' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--image-root', type=Path, default=ROOT / 'data/dataset',
                      help='External image root containing the paths recorded in data/models/split.json')
    inst = sub.add_parser('install')
    inst.add_argument('--generation-report', type=Path, required=True)
    inst.add_argument('--count', type=int, choices=(6, 348), default=6)
    done = sub.add_parser('finish')
    done.add_argument('--precision', choices=('minmax16', 'minmax8', 'float'), required=True)
    done.add_argument('--native-exit-code', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.image_root)
    elif args.command == 'install':
        install(args.generation_report, args.count)
    else:
        return finish(args.precision, args.native_exit_code)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
