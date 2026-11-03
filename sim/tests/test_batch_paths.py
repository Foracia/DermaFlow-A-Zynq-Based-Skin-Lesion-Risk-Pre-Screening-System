"""Check that development fixture helpers use the published project layout."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('batch_metrics_paths', ROOT / 'board/batch/batch_metrics.py')
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


class BatchPathTests(unittest.TestCase):
    def test_packaged_references_exist(self):
        for path in (METRICS.GOLDEN_INPUT, METRICS.GOLDEN_REFERENCE, METRICS.OPERATING_POINT,
                     METRICS.MODELS / 'split.json', METRICS.MODELS / 'preprocess.json'):
            self.assertTrue(path.is_file(), str(path))
        self.assertEqual(np.load(METRICS.GOLDEN_INPUT, allow_pickle=False).shape, (6, 3, 128, 128))
        self.assertEqual(np.load(METRICS.GOLDEN_REFERENCE, allow_pickle=False).shape, (6, 2))

    def test_generated_files_go_to_build_output(self):
        self.assertTrue(METRICS.RESULTS.is_relative_to(ROOT / 'build/output'))
        self.assertTrue(METRICS.FIXTURES.is_relative_to(METRICS.RESULTS))

    def test_local_dataset_reader_accepts_external_image_root(self):
        spec = importlib.util.spec_from_file_location('dataset_io_paths', ROOT / 'board/batch/dataset_io.py')
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            image = base / 'external_images/ACK/sample_ACK.png'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'image placeholder; reader checks paths only')
            split = base / 'split.json'
            split.write_text(json.dumps({'val': [['ACK/sample_ACK.png', 1, 'p1', 'l1']]}))
            rows = module.read_split(split, 'val', base / 'external_images')
            self.assertEqual(rows[0].path, image.resolve())
            self.assertEqual((rows[0].label, rows[0].disease), (1, 'ACK'))

    def test_fixture_validator_uses_current_split_and_metadata(self):
        rows = json.loads((METRICS.MODELS / 'split.json').read_text(encoding='utf-8'))['val']
        point = json.loads(METRICS.OPERATING_POINT.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            inputs, reference, labels = base / 'inputs.bin', base / 'reference.npy', base / 'labels.npy'
            with inputs.open('wb') as stream:
                stream.truncate(348 * 128 * 128 * 3 * 4)
            np.save(reference, np.zeros((348, 2), dtype=np.float32))
            np.save(labels, np.asarray([row[1] for row in rows], dtype=np.int64))
            manifest = {'status': 'PREPARED', 'partition': 'val', 'sample_count': 348,
                        'golden_count': 6, 'validation_count': 342, 'test_used': False,
                        'source_sha256': METRICS.sha(METRICS.SOURCE),
                        'temperature': point['temperature'], 'threshold': point['frozen_threshold'],
                        'records': [{'relative_path': row[0], 'label': row[1], 'patient_id': str(row[2]),
                                     'lesion_id': str(row[3]), 'disease': Path(row[0]).stem.rsplit('_', 1)[-1]}
                                    for row in rows]}
            for key, path in [('inputs', inputs), ('reference', reference), ('labels', labels),
                              ('split', METRICS.MODELS / 'split.json'),
                              ('preprocess', METRICS.MODELS / 'preprocess.json'),
                              ('operating_point', METRICS.OPERATING_POINT),
                              ('golden_input', METRICS.GOLDEN_INPUT)]:
                manifest[key] = str(path)
                manifest[key + '_sha256'] = METRICS.sha(path)
            METRICS.validate_fixtures(manifest)


if __name__ == '__main__':
    unittest.main()
