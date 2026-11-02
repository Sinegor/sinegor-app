"""Run inside Blender with output/SINEGOR_LAB.blend loaded; renders nothing."""
import json
import math
from itertools import pairwise
from pathlib import Path

import bpy

intro = bpy.data.scenes['01 — Включение']
loop = bpy.data.scenes['02 — Цикл']
cfg = json.loads(loop['parameters'])
assert bpy.app.version[:3] == (5, 1, 1)
for scene, total in ((intro, cfg['intro_frames']), (loop, cfg['loop_frames'])):
    assert (scene.frame_start, scene.frame_end) == (1, total)
    assert scene.render.fps == cfg['fps'] and scene.render.fps_base == 1
    assert scene.render.film_transparent
    assert scene.render.image_settings.color_mode == 'RGBA'
    assert (scene.render.resolution_x, scene.render.resolution_y) == (cfg['width'], cfg['height'])
    assert scene.camera.data.type == 'ORTHO' and scene.camera.animation_data is None
    assert len(scene.objects) == 2
    letters = next(o for o in scene.objects if o.type == 'FONT')
    assert letters.data.body == 'SINEGOR LAB'
    assert letters.animation_data is None and letters.data.font.packed_file
    assert [f.material_index for f in letters.data.body_format] == [0] * 8 + [1] * 3
    assert scene.view_settings.view_transform == 'Standard'


def values(scene, frame):
    bpy.context.window.scene = scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    nodes = scene.compositing_node_group.nodes
    return (nodes['Power — smooth start'].outputs[0].default_value,
            nodes['Halo — periodic intensity'].outputs[0].default_value)


start = values(intro, 1)
end = values(intro, cfg['intro_frames'])
assert abs(start[0]) < 1e-7, start
assert abs(end[0] - 1) < 1e-7, end
powers = [values(intro, f)[0] for f in range(1, cfg['intro_frames'] + 1)]
assert all(a <= b + 1e-7 for a, b in pairwise(powers))
loop_values = [values(loop, f) for f in range(1, cfg['loop_frames'] + 2)]
for frame, (power, halo) in enumerate(loop_values, 1):
    expected = cfg['glow_intensity'] * (1 + cfg['loop_amplitude'] * math.sin(2 * math.pi * (frame-1) / cfg['loop_frames']))
    assert abs(power - 1) < 1e-7
    assert abs(halo - expected) < 1e-6, (frame, halo, expected)
assert abs(loop_values[0][1] - loop_values[-1][1]) < 1e-7
result = {
    'blender': bpy.app.version_string, 'scene_count': len(bpy.data.scenes),
    'font_packed': True, 'intro_monotonic': True,
    'loop_parameter_frames_checked': len(loop_values),
    'halo_min': min(v[1] for v in loop_values), 'halo_max': max(v[1] for v in loop_values),
    'parameter_periodic': True, 'renders_in_this_check': 0
}
path = Path(bpy.data.filepath).parent / 'scene_checks.json'
path.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
