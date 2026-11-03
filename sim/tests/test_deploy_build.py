"""Check rebuilt-hardware deployment with temporary files and no board access."""
from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('deploy_build', ROOT / 'build/scripts/deploy_build.py')
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


class DeployBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'build/output'
        self.target = self.root / 'board/hardware'
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        for ext in ('bit', 'hwh'):
            shutil.copy2(ROOT / f'board/hardware/cnn_system.{ext}', self.source / f'system.{ext}')
            (self.target / f'cnn_system.{ext}').write_bytes(b'previous-' + ext.encode())
        (self.target / 'manifest.json').write_text('{"original": true}', encoding='utf-8')

    def test_complete_pair_is_copied_before_manifest_refresh(self):
        def refresh(root):
            self.assertEqual(root, self.root)
            for ext in ('bit', 'hwh'):
                self.assertEqual((self.source / f'system.{ext}').read_bytes(),
                                 (self.target / f'cnn_system.{ext}').read_bytes())
        with patch.object(DEPLOY, 'refresh_runtime', side_effect=refresh) as action:
            DEPLOY.deploy(self.source, self.root)
            action.assert_called_once_with(self.root)

    def test_missing_hwh_keeps_current_hardware(self):
        (self.source / 'system.hwh').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            DEPLOY.deploy(self.source, self.root)
        self.assertEqual((self.target / 'cnn_system.bit').read_bytes(), b'previous-bit')

    def test_wrong_ip_address_keeps_current_hardware(self):
        p = self.source / 'system.hwh'
        p.write_bytes(p.read_bytes().replace(b'0x43C90000', b'0x43CA0000'))
        with self.assertRaises(ValueError):
            DEPLOY.deploy(self.source, self.root)
        self.assertEqual((self.target / 'cnn_system.bit').read_bytes(), b'previous-bit')

    def test_incorrect_bit_device_is_rejected(self):
        p = self.source / 'system.bit'
        p.write_bytes(p.read_bytes().replace(b'7z020clg400', b'7z010clg400', 1))
        with self.assertRaises(ValueError):
            DEPLOY.deploy(self.source, self.root)
        self.assertEqual((self.target / 'cnn_system.hwh').read_bytes(), b'previous-hwh')

    def test_truncated_bitstream_is_rejected(self):
        p = self.source / 'system.bit'
        p.write_bytes(p.read_bytes()[:-16])
        with self.assertRaises(ValueError):
            DEPLOY.deploy(self.source, self.root)

    def test_failed_refresh_restores_hardware_and_manifests(self):
        ui = self.root / 'board/system_ui'
        ui.mkdir(parents=True)
        (ui / 'system_tools_manifest.json').write_bytes(b'previous-ui-manifest')
        def fail(root):
            (self.target / 'manifest.json').write_bytes(b'partial-manifest')
            (ui / 'system_tools_manifest.json').write_bytes(b'partial-ui-manifest')
            binding = root / 'src/system_ui/terminal_binding.json'
            binding.parent.mkdir(parents=True, exist_ok=True)
            binding.write_bytes(b'partial-boot-binding')
            raise RuntimeError('Refresh interrupted')
        with patch.object(DEPLOY, 'refresh_runtime', side_effect=fail):
            with self.assertRaises(RuntimeError):
                DEPLOY.deploy(self.source, self.root)
        self.assertEqual((self.target / 'cnn_system.bit').read_bytes(), b'previous-bit')
        self.assertEqual((self.target / 'manifest.json').read_text(encoding='utf-8'), '{"original": true}')
        self.assertEqual((ui / 'system_tools_manifest.json').read_bytes(), b'previous-ui-manifest')
        self.assertFalse((self.root / 'src/system_ui/terminal_binding.json').exists())


if __name__ == '__main__':
    unittest.main()
