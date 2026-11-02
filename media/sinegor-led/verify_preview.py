"""Inspect actual Blender PNGs and create small previews on three backgrounds.

Requires the already available Pillow and NumPy, not used by scene generation.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from led_config import load_configuration
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE / 'output')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--preset', choices=('original', 'A', 'B', 'C'))
    parser.add_argument('--check-only', action='store_true', help='Read images without writing thumbnails/reports')
    args = parser.parse_args()
    out = args.out.resolve()
    preview = out / 'preview'
    if (out / 'preview_in_progress').exists():
        parser.error('Preview render is incomplete; finish --mode preview before verification')
    snapshot = out / 'render_config.json'
    if snapshot.exists():
        cfg = json.loads(snapshot.read_text())
        if args.config is not None or args.preset is not None:
            requested = load_configuration(args.config or HERE / 'config.json', args.preset)
            if requested != cfg:
                parser.error('Requested configuration does not match render_config.json')
        config_source = str(snapshot)
    else:
        if out != (HERE / 'output').resolve() and args.config is None:
            parser.error('render_config.json missing; pass --config for legacy output')
        cfg = load_configuration(args.config or HERE / 'config.json', args.preset)
        config_source = str(args.config or HERE / 'config.json') + ' (legacy: no snapshot)'
    names = ('intro_0001', 'intro_mid', 'intro_end', 'steady', 'loop_max',
             'loop_min', 'loop_last', 'loop_virtual_next')
    images = {name: Image.open(preview / f'{name}.png') for name in names}
    for name, im in images.items():
        header = (preview / f'{name}.png').read_bytes()[:29]
        assert header[24] == int(cfg['png_depth']) and header[25] == 6, (name, 'PNG bit depth / RGBA type')
        assert im.mode == 'RGBA', (name, im.mode)
        assert im.size == (cfg['width'], cfg['height']), (name, im.size)
    arrays = {name: np.array(im).astype(np.int16) for name, im in images.items()}
    steady = arrays['steady']
    alpha = steady[:, :, 3]
    assert np.all(arrays['intro_0001'][:, :, 3] == 0), 'First frame must be invisible'
    assert np.array_equal(arrays['intro_end'], steady), 'Intro does not join the loop'
    assert np.array_equal(arrays['loop_virtual_next'], steady), 'Virtual frame N+1 differs from frame 1'
    border = np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))
    assert not np.any(border), 'Halo touches canvas edges'
    assert np.any(alpha == 0) and np.any(alpha == 255) and np.any((alpha > 0) & (alpha < 255))
    opaque = alpha == 255
    assert np.array_equal(arrays['loop_max'][opaque], arrays['loop_min'][opaque]), 'Opaque letters must remain constant'
    if cfg['loop_amplitude'] > 0 and cfg['glow_intensity'] > 0:
        assert np.any(arrays['loop_max'][:, :, 3] > arrays['loop_min'][:, :, 3]), 'Halo animation is missing'
    for color in (cfg['sinegor_color'], cfg['lab_color']):
        rgb = np.array([int(color[i:i+2], 16) for i in (1, 3, 5)])
        count = np.count_nonzero(np.all(steady[:, :, :3] == rgb, axis=2) & opaque)
        assert count > 100, f'Exact face color missing: {color}'
    seam = np.abs(arrays['loop_last'] - steady)
    assert seam.max() <= 1, f'Visible step at seam: {seam.max()}'
    if not args.check_only:
        small = images['steady'].resize((683, 239), Image.Resampling.LANCZOS)
        small.save(preview / 'small_rgba_683x239.png')
        backgrounds = []
        for color in ('#151D24', '#F2F3F3'):
            backgrounds.append(Image.new('RGBA', small.size, color))
        checker = Image.new('RGBA', small.size, '#777F87')
        draw = ImageDraw.Draw(checker)
        for y in range(0, 239, 16):
            for x in range(0, 683, 16):
                if (x // 16 + y // 16) % 2:
                    draw.rectangle((x, y, x+15, y+15), fill='#ABB0B5')
        backgrounds.append(checker)
        sheet = Image.new('RGB', (683, 3 * (239+26)), '#202830')
        draw = ImageDraw.Draw(sheet)
        for i, (bg, title) in enumerate(zip(backgrounds, ('DARK | 683 x 239', 'LIGHT | 683 x 239', 'CHECKER | 683 x 239'))):
            bg.alpha_composite(small)
            y = i * 265
            sheet.paste(bg.convert('RGB'), (0, y+26))
            draw.text((12, y+7), title, fill='white')
            bg.convert('RGB').save(preview / f'small_{("dark", "light", "checker")[i]}.png')
        sheet.save(preview / 'review_sheet.png')
        for name in ('steady', 'intro_mid', 'loop_max', 'loop_min'):
            bg = Image.new('RGBA', images[name].size, '#151D24')
            bg.alpha_composite(images[name])
            bg.convert('RGB').save(preview / f'{name}_on_dark.png')
    report = {
        'png_size': [cfg['width'], cfg['height']], 'mode': 'RGBA',
        'small_size': [683, 239], 'transparent_pixels': int(np.sum(alpha == 0)),
        'partial_alpha_pixels': int(np.sum((alpha > 0) & (alpha < 255))),
        'opaque_pixels': int(np.sum(opaque)), 'border_alpha_max': int(border.max()),
        'intro_first_invisible': True, 'intro_end_equals_loop_start': True,
        'virtual_frame_equals_start': True, 'last_to_first_max_8bit_step': int(seam.max()),
        'last_to_first_changed_pixels': int(np.sum(np.any(seam > 0, axis=2))),
        'opaque_letters_constant': True, 'exact_face_colors_present': True,
        'checked_preview_frames': len(names), 'comparison_depth': 8,
        'configuration_source': config_source,
        'scope': 'Only the selected preview images were inspected; final export history and Shotcut playback are not checked.'
    }
    if not args.check_only:
        (out / 'preview_checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
