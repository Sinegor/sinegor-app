"""Final export checks must reject gaps, stale tails, and lost alpha."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class FinalExportTest(unittest.TestCase):
    def checker(self):
        self.assertIsNotNone(importlib.util.find_spec('verify_export'), 'Final sequence checker is missing')
        import verify_export
        return verify_export

    def test_numbered_sequence_has_exact_order(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('loop_0002.png', 'loop_0001.png'):
                (root / name).touch()
            self.assertEqual([p.name for p in checker.numbered_frames(root, 'loop', 2)],
                             ['loop_0001.png', 'loop_0002.png'])

    def test_missing_frame_is_rejected(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'loop_0001.png').touch()
            with self.assertRaises(ValueError):
                checker.numbered_frames(root, 'loop', 2)

    def test_stale_numbered_tail_is_rejected(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for n in (1, 2, 3):
                (root / f'loop_{n:04d}.png').touch()
            with self.assertRaises(ValueError):
                checker.numbered_frames(root, 'loop', 2)

    def test_flash_in_middle_of_loop_is_rejected(self):
        checker = self.checker()
        self.assertTrue(hasattr(checker, 'validate_loop_steps'), 'Whole-loop step validation is missing')
        normal = {'max_rgb': 1.0, 'mean_rgb': 0.003, 'max_alpha': 1}
        steps = [normal] * 749
        steps[298] = {'max_rgb': 18.0, 'mean_rgb': 0.003, 'max_alpha': 1}
        with self.assertRaises(ValueError):
            checker.validate_loop_steps(steps)

    def test_quantized_smooth_steps_are_accepted(self):
        checker = self.checker()
        self.assertTrue(hasattr(checker, 'validate_loop_steps'), 'Whole-loop step validation is missing')
        checker.validate_loop_steps([{'max_rgb': 1.8, 'mean_rgb': 0.004, 'max_alpha': 1}])

    def test_rgb_file_cannot_pass_as_rgba(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'frame.png'
            Image.new('RGB', (4, 4), 'white').save(path)
            with self.assertRaises(ValueError):
                checker.read_rgba(path, (4, 4))


if __name__ == '__main__':
    unittest.main()
