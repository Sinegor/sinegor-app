"""Contract checks for glow-only presets; no Blender or rendering required."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class GlowPresetsTest(unittest.TestCase):
    def test_presets_preserve_geometry_colors_and_timing(self):
        self.assertIsNotNone(importlib.util.find_spec('led_config'), 'Glow-only preset loader is missing')
        from led_config import load_configuration
        original = load_configuration(HERE / 'config.json', 'original')
        glow_keys = {'glow_near_px', 'glow_far_px', 'glow_near_opacity',
                     'glow_far_opacity', 'glow_intensity'}
        for preset in ('A', 'B', 'C'):
            cfg = load_configuration(HERE / 'config.json', preset)
            self.assertEqual({k: v for k, v in cfg.items() if k not in glow_keys},
                             {k: v for k, v in original.items() if k not in glow_keys})
            self.assertGreater(cfg['glow_near_px'], original['glow_near_px'])
            self.assertGreater(cfg['glow_far_px'], cfg['glow_near_px'])
            self.assertLessEqual(max(cfg['glow_near_opacity'], cfg['glow_far_opacity']) *
                                 cfg['glow_intensity'] * (1 + cfg['loop_amplitude']), 1)
        self.assertEqual(original['loop_amplitude'], 0.04)

    def test_unknown_preset_fails_without_falling_back(self):
        self.assertIsNotNone(importlib.util.find_spec('led_config'), 'Glow-only preset loader is missing')
        from led_config import load_configuration
        with self.assertRaises(ValueError):
            load_configuration(HERE / 'config.json', 'unknown')

    def test_font_is_resolved_relative_to_custom_config(self):
        self.assertIsNotNone(importlib.util.find_spec('led_config'), 'Glow-only preset loader is missing')
        from led_config import load_configuration
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            cfg = json.loads((HERE / 'config.json').read_text())
            path.write_text(json.dumps(cfg))
            result = load_configuration(path, 'B')
            self.assertEqual(result['font'], str((path.parent / cfg['font']).resolve()))


if __name__ == '__main__':
    unittest.main()
