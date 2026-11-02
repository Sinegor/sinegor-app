"""Validate every final PNG, its sequence, face stability and the loop seam.

python3 media/sinegor-led/verify_export.py --out media/sinegor-led/output/final_B
Requires Pillow and NumPy. Does not render or change any PNG.
"""
import argparse
import hashlib
import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


def numbered_frames(directory, prefix, count):
    expected = [directory / f'{prefix}_{frame:04d}.png' for frame in range(1, count+1)]
    actual = set(directory.glob('*.png'))
    if actual != set(expected):
        missing = sorted(p.name for p in set(expected) - actual)
        extra = sorted(p.name for p in actual - set(expected))
        raise ValueError(f'{directory}: missing={missing[:8]}, unexpected={extra[:8]}')
    return expected


def read_rgba(path, size):
    with path.open('rb') as stream:
        header = stream.read(29)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[24:26] != bytes((8, 6)):
        raise ValueError(f'{path}: expected 8-bit RGBA PNG')
    with Image.open(path) as image:
        if image.mode != 'RGBA' or image.size != size:
            raise ValueError(f'{path}: {image.mode} {image.size}, expected RGBA {size}')
        return np.array(image)


def graphite(rgba):
    alpha = rgba[:, :, 3:4].astype(np.float32) / 255
    rgb = rgba[:, :, :3].astype(np.float32)
    bg = np.array([23, 28, 32], dtype=np.float32)
    return bg + (rgb - bg) * alpha


def step(a, b):
    diff = np.abs(a - b)
    return {'max_rgb': float(diff.max()), 'mean_rgb': float(diff.mean())}


def validate_loop_steps(steps):
    # B's maximum gain change is 2*.04*sin(pi/750) < .000336/frame.
    # Its unquantized alpha change is < .12/255, hence <=1 after rounding.
    # Allow two RGB levels for the independent 8-bit RGB/alpha quantization.
    for frame, value in enumerate(steps, 2):
        if value['max_rgb'] > 2.01 or value['max_alpha'] > 1:
            raise ValueError(f'Unexpected halo jump into loop frame {frame}: {value}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE / 'output/final_B')
    parser.add_argument('--approved-preview', type=Path, default=HERE / 'output/glow_revision/B')
    args = parser.parse_args()
    out, approved = args.out.resolve(), args.approved_preview.resolve()
    cfg = json.loads((out / 'scene_config.json').read_text())
    if cfg != json.loads((approved / 'render_config.json').read_text()):
        raise ValueError('Final configuration differs from the approved preview')
    if (cfg['width'], cfg['height'], cfg['fps'], cfg['intro_frames'], cfg['loop_frames'], cfg['png_depth']) != (2048, 720, 25, 50, 750, '8'):
        raise ValueError('Final delivery must be 2048x720, 25 FPS, 50+750 frames, 8-bit RGBA')
    size = (cfg['width'], cfg['height'])
    intro = numbered_frames(out / 'intro', 'intro', cfg['intro_frames'])
    loop = numbered_frames(out / 'loop', 'loop', cfg['loop_frames'])
    first = read_rgba(loop[0], size)
    if not np.array_equal(first, read_rgba(approved / 'preview/steady.png', size)):
        raise ValueError('Loop start differs from the selected B preview')
    opaque = first[:, :, 3] == 255
    reference_faces = first[opaque]
    for color in (cfg['sinegor_color'], cfg['lab_color']):
        rgb = np.array([int(color[i:i+2], 16) for i in (1, 3, 5)])
        assert np.count_nonzero(np.all(reference_faces[:, :3] == rgb, axis=1)) > 100, color
    hashes, intro_alpha, loop_alpha, steps = {}, [], [], []
    first_proxy, prev_proxy, last = graphite(first), None, None
    preview_matches = {'intro': {1: 'intro_0001', 25: 'intro_mid', 50: 'intro_end'},
                       'loop': {1: 'steady', 188: 'loop_max', 563: 'loop_min', 750: 'loop_last'}}
    outside = ~opaque
    for kind, files in (('intro', intro), ('loop', loop)):
        for frame, path in enumerate(files, 1):
            rgba = read_rgba(path, size)
            alpha = rgba[:, :, 3]
            assert not any(np.any(edge) for edge in (alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1])), path
            hashes[str(path.relative_to(out))] = hashlib.sha256(path.read_bytes()).hexdigest()
            if frame in preview_matches[kind]:
                preview_path = approved / 'preview' / (preview_matches[kind][frame] + '.png')
                assert np.array_equal(rgba, read_rgba(preview_path, size)), (path, 'approved preview mismatch')
            if kind == 'intro':
                intro_alpha.append(int(alpha.sum()))
                if frame == 1:
                    assert not np.any(alpha), 'Intro starts visible'
                if frame == len(files):
                    assert np.array_equal(rgba, first), 'Intro/loop join differs'
            else:
                assert np.array_equal(rgba[opaque], reference_faces), (path, 'face brightness or position changed')
                assert np.array_equal(alpha == 255, opaque), (path, 'opaque geometry changed')
                loop_alpha.append(float(alpha[outside].mean()))
                proxy = graphite(rgba)
                if prev_proxy is not None:
                    change = step(proxy, prev_proxy)
                    change['max_alpha'] = int(np.abs(alpha.astype(np.int16) - last[:, :, 3].astype(np.int16)).max())
                    steps.append(change)
                prev_proxy = proxy
                last = rgba
            if frame % 100 == 0 or frame == len(files):
                print(f'Checked {kind}: {frame}/{len(files)}', flush=True)
    assert all(a <= b for a, b in pairwise(intro_alpha)), 'Intro is not monotonic'
    assert np.array_equal(first, read_rgba(approved / 'preview/loop_virtual_next.png', size))
    raw_seam = int(np.abs(last.astype(np.int16) - first.astype(np.int16)).max())
    assert raw_seam <= 1, ('Large seam step', raw_seam)
    seam = step(prev_proxy, first_proxy)
    seam['max_alpha'] = int(np.abs(last[:, :, 3].astype(np.int16) - first[:, :, 3].astype(np.int16)).max())
    validate_loop_steps(steps + [seam])
    local = steps[:5] + steps[-5:]
    assert seam['max_rgb'] <= max(s['max_rgb'] for s in local) + 0.01, 'Seam exceeds neighboring steps'
    assert seam['mean_rgb'] <= max(s['mean_rgb'] for s in local) * 1.15 + 0.0001, 'Seam is an outlier'
    gains = [1 + cfg['loop_amplitude'] * math.sin(2*math.pi*f/len(loop)) for f in range(len(loop))]
    correlation = float(np.corrcoef(gains, loop_alpha)[0, 1])
    assert correlation > 0.999, ('Unexpected halo evolution', correlation)
    report = {
        'selected_preset': 'B', 'checked_frames': len(intro)+len(loop),
        'intro_frames': len(intro), 'loop_frames': len(loop),
        'size': list(size), 'fps': cfg['fps'], 'intro_seconds': 2, 'loop_seconds': 30,
        'format': 'PNG RGBA 8-bit', 'all_frame_perimeters_transparent': True,
        'first_intro_frame_transparent': True, 'intro_alpha_monotonic': True,
        'all_opaque_loop_faces_constant': True, 'opaque_pixels': int(opaque.sum()),
        'brand_face_colors_present': True, 'approved_preview_matches': True,
        'intro_end_equals_loop_start': True, 'virtual_frame_751_equals_start': True,
        'seam_raw_rgba_max_step_8bit': raw_seam, 'seam_on_graphite': seam,
        'all_adjacent_steps_checked': len(steps)+1,
        'all_steps_max_rgb': max(s['max_rgb'] for s in steps + [seam]),
        'all_steps_max_alpha': max(s['max_alpha'] for s in steps + [seam]),
        'neighboring_steps_max_rgb': max(s['max_rgb'] for s in local),
        'neighboring_steps_max_mean_rgb': max(s['mean_rgb'] for s in local),
        'halo_alpha_sine_correlation': correlation, 'loop_amplitude': cfg['loop_amplitude'],
        'scope': 'All final PNGs checked; simulated graphite comparisons. GUI playback is a separate check.'
    }
    (out / 'png_sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    (out / 'export_checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
