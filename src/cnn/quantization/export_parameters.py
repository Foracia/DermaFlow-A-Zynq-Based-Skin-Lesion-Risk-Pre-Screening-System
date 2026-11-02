"""Export deployed PL fixed-point parameters and the packed HLS weight header."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from fixed_model import Model, ROOT


def packed_header(model):
    text = ''
    for which, lanes in [(0, 16), (1, 8), (2, 8), (3, 8)]:
        weights = model.weights['Conv_' + str(which)]
        bias = model.bias['Conv_' + str(which)]
        cout, cin, kh, kw = weights.shape
        bank = weights.transpose(0, 2, 3, 1).reshape(cout // lanes, lanes, kh * kw * cin).transpose(0, 2, 1).reshape(-1, lanes)
        literals = ['"0x' + format(sum((int(v) & 255) << (8 * i) for i, v in enumerate(row)), '0%dx' % (lanes * 2)) + '"' for row in bank]
        text += 'const ap_uint<%d> weights_%d[%d]={' % (8 * lanes, which, len(bank)) + ','.join(literals) + '};\n'
        text += 'const ap_int<32> biases_%d[%d]={' % (which, len(bias)) + ','.join(str(int(v)) for v in bias) + '};\n'
    w, b = model.weights['MatMul_0'], model.bias['Add_0']
    words = [(int(w[0, k]) & 255) | ((int(w[1, k]) & 255) << 8) for k in range(128)]
    text += 'const ap_uint<16> weights_head[128]={' + ','.join(str(v) for v in words) + '};\n'
    text += 'const ap_int<8> bias_head[2]={' + ','.join(str(int(v)) for v in b) + '};\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new output directory')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a new output directory')
    model = Model('legacy8')
    exported = {}
    for role, arrays in [('weight', model.weights), ('bias', model.bias)]:
        for layer, raw in arrays.items():
            key = layer + '_' + role
            name = key.lower() + '.npy'
            expected = np.load(ROOT / 'data/models/pl_quantized/parameters' / name, allow_pickle=False)
            if not np.array_equal(raw, expected):
                raise ValueError('Frozen parameter differs: ' + key)
            exported[name] = raw.astype(expected.dtype)
    header = packed_header(model)
    if header != (ROOT / 'src/cnn/hls/weights.h').read_text(encoding='utf-8'):
        raise ValueError('Packed header differs from deployed HLS weights')
    args.out.mkdir(parents=True)
    for name, array in exported.items():
        np.save(args.out / name, array, allow_pickle=False)
    (args.out / 'weights.h').write_text(header, encoding='utf-8', newline='\n')
    (args.out / 'quantization.json').write_text(json.dumps(model.contract(), indent=2) + '\n', encoding='utf-8')
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir() if p.is_file()}
    (args.out / 'export_manifest.json').write_text(json.dumps({'status': 'PARAMETERS_AND_HLS_HEADER_MATCH', 'files': files, 'inference_executed': False}, indent=2) + '\n', encoding='utf-8')
    print('PARAMETERS_AND_HLS_HEADER_MATCH parameters=%d; no inference or hardware build' % len(exported))


if __name__ == '__main__':
    main()
