"""Regression: verify the selected output, never silently verify old defaults."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PreviewPathsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('verify_preview.py', 'led_config.py', 'glow_presets.json'):
            shutil.copyfile(HERE / name, self.root / name)
        self.out = self.root / 'selected-output'
        (self.out / 'preview').mkdir(parents=True)
        for name in ('intro_0001', 'intro_mid', 'intro_end', 'steady', 'loop_max',
                     'loop_min', 'loop_last', 'loop_virtual_next'):
            shutil.copyfile(HERE / 'output/preview' / (name + '.png'),
                            self.out / 'preview' / (name + '.png'))
        cfg = json.loads((HERE / 'config.json').read_text())
        cfg['font'] = str((HERE / cfg['font']).resolve())
        (self.out / 'render_config.json').write_text(json.dumps(cfg))

    def run_verifier(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'verify_preview.py'),
                               '--out', str(self.out), '--check-only', *args],
                              capture_output=True, text=True, check=False)

    def test_custom_output_uses_its_own_snapshot_without_writing(self):
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.out / 'preview_checks.json').exists())
        self.assertIn('virtual_frame_equals_start', result.stdout)

    def test_interrupted_preview_is_not_verified_as_complete(self):
        (self.out / 'preview_in_progress').touch()
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('incomplete', result.stderr)

    def test_mismatched_source_config_is_rejected(self):
        cfg = json.loads((self.out / 'render_config.json').read_text())
        cfg['glow_intensity'] = 100
        path = self.root / 'different.json'
        path.write_text(json.dumps(cfg))
        result = self.run_verifier('--config', str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)


if __name__ == '__main__':
    unittest.main()
