"""Shared glow-only presets. Original config.json remains the baseline."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GLOW_KEYS = {'glow_near_px', 'glow_far_px', 'glow_near_opacity',
             'glow_far_opacity', 'glow_intensity'}


def load_configuration(path, preset=None):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text())
    if preset is not None:
        presets = json.loads((HERE / 'glow_presets.json').read_text())
        if preset not in presets:
            raise ValueError(f'Unknown glow preset: {preset}')
        overrides = presets[preset]
        if set(overrides) - GLOW_KEYS:
            raise ValueError('Glow presets may not change geometry, colors, or animation')
        cfg.update(overrides)
    cfg['font'] = str((path.parent / cfg['font']).resolve())
    return cfg
