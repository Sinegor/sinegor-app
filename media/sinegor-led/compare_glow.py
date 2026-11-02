"""Compare real preset renders at the target size on simulated graphite.

Run after --mode preview --preset A/B/C. No Blender renders are performed here.
All generated comparison files stay under output/glow_revision.
"""
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from led_config import GLOW_KEYS, load_configuration
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'output/glow_revision'
SIZE = (683, 239)
BACKGROUND = '#171C20'
NAMES = ('intro_0001', 'intro_mid', 'intro_end', 'steady', 'loop_max',
         'loop_min', 'loop_last', 'loop_virtual_next')


def read(path):
    with Image.open(path) as image:
        assert image.mode == 'RGBA' and image.size == (2048, 720), path
        return image.copy()


def graphite(image):
    result = Image.new('RGBA', image.size, BACKGROUND)
    result.alpha_composite(image)
    return result.convert('RGB')


def halo_metrics(image, silhouette):
    rgba = np.array(image)
    mask = np.array(silhouette) > 0
    alpha = rgba[:, :, 3]
    delta = np.max(np.array(graphite(image)).astype(int) - [23, 28, 32], axis=2)
    previous, bands = mask, []
    for radius in (2, 4, 8, 12, 18, 24):
        dilated = np.array(silhouette.filter(ImageFilter.MaxFilter(2*radius+1))) > 0
        band = dilated & ~previous
        bands.append({'outer_chebyshev_distance_px': radius,
                      'alpha_mean_8bit': round(float(alpha[band].mean()), 3),
                      'alpha_max_8bit': int(alpha[band].max()),
                      'rgb_lift_mean_8bit': round(float(delta[band].mean()), 3),
                      'rgb_lift_max_8bit': int(delta[band].max())})
        previous = dilated
    return bands


def main():
    expected_hashes = json.loads((ROOT / 'original_hashes.json').read_text())
    for relative, expected in expected_hashes.items():
        assert hashlib.sha256((HERE / relative).read_bytes()).hexdigest() == expected, relative
    original = ROOT / 'original'
    (original / 'preview').mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        shutil.copyfile(HERE / 'output/preview' / (name + '.png'),
                        original / 'preview' / (name + '.png'))
    base_cfg = load_configuration(HERE / 'config.json', 'original')
    (original / 'render_config.json').write_text(json.dumps(base_cfg, indent=2) + '\n')
    baseline = read(original / 'preview/steady.png')
    opaque = np.array(baseline)[:, :, 3] == 255
    core = read(ROOT / 'diagnosis/core_rgba.png')
    small_core = np.array(core.resize(SIZE, Image.Resampling.LANCZOS))[:, :, 3]
    silhouette = Image.fromarray(np.uint8(small_core > 0) * 255)
    font = ImageFont.truetype(str(HERE / 'fonts/Manrope-SemiBold.ttf'), 17)
    small_font = ImageFont.truetype(str(HERE / 'fonts/Manrope-SemiBold.ttf'), 13)
    sheet = Image.new('RGB', (SIZE[0], 4*(SIZE[1]+65)+42), '#222A30')
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), '683 × 239 px · ИМИТАЦИЯ графита #171C20 · не реальная табличка', font=small_font, fill='white')
    metrics, small_images = {}, {}
    labels = {'original': 'Исходный', 'A': 'A — сдержанный',
              'B': 'B — сбалансированный', 'C': 'C — выраженный'}
    for index, preset in enumerate(('original', 'A', 'B', 'C')):
        folder = ROOT / preset
        cfg = json.loads((folder / 'render_config.json').read_text())
        assert cfg == load_configuration(HERE / 'config.json', preset)
        assert {k: v for k, v in cfg.items() if k not in GLOW_KEYS} == {
            k: v for k, v in base_cfg.items() if k not in GLOW_KEYS}
        image = read(folder / 'preview/steady.png')
        array = np.array(image)
        assert np.array_equal(array[:, :, 3] == 255, opaque), 'Opaque geometry changed'
        assert np.array_equal(array[opaque], np.array(baseline)[opaque]), 'Face pixels changed'
        for name in NAMES:
            alpha = np.array(read(folder / 'preview' / (name + '.png')))[:, :, 3]
            assert not any(np.any(edge) for edge in (alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1])), (preset, name)
        small = image.resize(SIZE, Image.Resampling.LANCZOS)
        small.save(folder / 'steady_683x239_rgba.png')
        matte = graphite(small)
        matte.save(folder / 'steady_683x239_graphite_simulated.png')
        graphite(image).save(folder / 'steady_2048x720_graphite_simulated.png')
        small_images[preset] = small
        y = 42 + index*(SIZE[1]+65)
        draw.text((12, y+5), labels[preset], font=font, fill='#9DE0C4' if preset == 'B' else 'white')
        params = (f'near {cfg["glow_near_px"]:g}px / {cfg["glow_near_opacity"]:g} · '
                  f'far {cfg["glow_far_px"]:g}px / {cfg["glow_far_opacity"]:g} · '
                  f'gain {cfg["glow_intensity"]:g} · pulse ±4%')
        draw.text((12, y+31), params, font=small_font, fill='#CAD5DC')
        sheet.paste(matte, (0, y+65))
        rgba_small = np.array(small)
        outside = (small_core == 0) & (rgba_small[:, :, 3] >= 10)
        x = np.indices((239, 683))[1]
        white_rgb = rgba_small[outside & (x < 420), :3].mean(axis=0)
        mint_rgb = rgba_small[outside & (x > 490), :3].mean(axis=0)
        assert white_rgb.min() > 220 and white_rgb.max() - white_rgb.min() < 6
        assert mint_rgb[1] > mint_rgb[0] + 40 and mint_rgb[2] > mint_rgb[0] + 20
        metrics[preset] = {'glow_parameters': {k: cfg[k] for k in sorted(GLOW_KEYS)},
                           'outside_halo_mean_white_rgb': white_rgb.round(2).tolist(),
                           'outside_halo_mean_mint_rgb': mint_rgb.round(2).tolist(),
                           'face_pixels_equal_original': True,
                           'opaque_geometry_equal_original': True,
                           'transparent_perimeter_all_eight_previews': True,
                           'distance_bands_683x239': halo_metrics(small, silhouette)}
    for a, b in (('original', 'A'), ('A', 'B'), ('B', 'C')):
        delta = np.abs(np.array(graphite(small_images[a])).astype(int) - np.array(graphite(small_images[b])).astype(int))
        assert delta.max() > 5 and np.count_nonzero(np.max(delta, axis=2) >= 3) > 1000, (a, b)
    sheet.save(ROOT / 'comparison_683x239.png')
    pulse = Image.new('RGB', (683, 3*(239+40)), '#222A30')
    draw = ImageDraw.Draw(pulse)
    frames = []
    for index, (name, title) in enumerate((('loop_min', 'B · −4%'), ('steady', 'B · рабочий'), ('loop_max', 'B · +4%'))):
        image = read(ROOT / 'B/preview' / (name + '.png')).resize(SIZE, Image.Resampling.LANCZOS)
        matte = graphite(image)
        draw.text((12, index*279+9), title, font=font, fill='white')
        pulse.paste(matte, (0, index*279+40))
        frames.append(np.array(matte).astype(int))
    pulse.save(ROOT / 'B_pulse_extremes_683x239.png')
    diff = np.abs(frames[2] - frames[0])
    metrics['pulse_B'] = {'amplitude': 0.04, 'min_max_rgb_max_step_8bit': int(diff.max()),
                          'changed_pixels': int(np.sum(np.any(diff > 0, axis=2))),
                          'note': 'Extremes are real rendered frames, not a 30-second playback test.'}
    metrics['background'] = {'hex': BACKGROUND, 'kind': 'uniform simulation, not the actual plate'}
    metrics['old_artifact_hashes_unchanged'] = True
    (ROOT / 'comparison_checks.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print('Comparison created:', ROOT / 'comparison_683x239.png')
    print('B pulse extremes:', metrics['pulse_B'])
    for preset in ('original', 'A', 'B', 'C'):
        print(preset, metrics[preset]['distance_bands_683x239'])


if __name__ == '__main__':
    main()
