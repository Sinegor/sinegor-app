"""SINEGOR LAB: Blender 5.1.1 scene builder and explicitly gated PNG export.

blender -b --factory-startup --python-exit-code 1 --python generate.py -- --mode preview
No installation, network, external scripts, handlers, or Blender MCP.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Blender --python does not consistently add the script directory to sys.path.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from led_config import load_configuration

HERE = Path(__file__).resolve().parent


def srgb(hex_color):
    values = [int(hex_color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                 for v in values) + (1.0,)


def node(tree, kind, name, x, y):
    result = tree.nodes.new(kind)
    result.name = result.label = name
    result.location = (x, y)
    return result


def math_node(tree, name, operation, x, y, a=None, b=None):
    n = node(tree, 'ShaderNodeMath', name, x, y)
    n.operation = operation
    for index, value in enumerate((a, b)):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            n.inputs[index].default_value = value
        else:
            tree.links.new(value, n.inputs[index])
    return n.outputs[0]


def animated_value(tree, name, expression, x, y):
    n = node(tree, 'ShaderNodeValue', name, x, y)
    n.outputs[0].default_value = 1.0
    n.outputs[0].driver_add('default_value').driver.expression = expression
    return n.outputs[0]


def material(name, color, cfg):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = srgb(color)
    t = mat.node_tree
    t.nodes.clear()
    geo = node(t, 'ShaderNodeNewGeometry', 'Bevel normal', -650, -100)
    dot = node(t, 'ShaderNodeVectorMath', 'Front facing', -450, -100)
    dot.operation = 'DOT_PRODUCT'
    dot.inputs[1].default_value = (0, 0, 1)
    t.links.new(geo.outputs['Normal'], dot.inputs[0])
    rim = math_node(t, 'Bevel contrast', 'MULTIPLY', -250, -100,
                    dot.outputs['Value'], 1 - cfg['edge_brightness'])
    strength = math_node(t, 'Front + edge', 'ADD', -50, -100,
                         rim, cfg['edge_brightness'])
    strength = math_node(t, 'LED face strength', 'MULTIPLY', 150, -100,
                         strength, cfg['face_strength'])
    emission = node(t, 'ShaderNodeEmission', 'LED', 350, 100)
    emission.inputs['Color'].default_value = srgb(color)
    t.links.new(strength, emission.inputs['Strength'])
    output = node(t, 'ShaderNodeOutputMaterial', 'Surface', 570, 100)
    t.links.new(emission.outputs[0], output.inputs['Surface'])
    return mat


def scale_alpha(tree, image, factor, name, x, y):
    # Explicit unpremultiply -> replace alpha -> premultiply prevents dark fringes.
    separate = node(tree, 'CompositorNodeSeparateColor', name + ' alpha', x, y - 130)
    tree.links.new(image, separate.inputs['Image'])
    alpha = math_node(tree, name + ' opacity', 'MULTIPLY', x + 190, y - 130,
                      separate.outputs['Alpha'], factor)
    straight = node(tree, 'CompositorNodePremulKey', name + ' to straight', x, y)
    straight.inputs['Type'].default_value = 'To Straight'
    tree.links.new(image, straight.inputs['Image'])
    replace = node(tree, 'CompositorNodeSetAlpha', name + ' replace alpha', x + 390, y)
    replace.inputs['Type'].default_value = 'Replace Alpha'
    tree.links.new(straight.outputs['Image'], replace.inputs['Image'])
    tree.links.new(alpha, replace.inputs['Alpha'])
    premul = node(tree, 'CompositorNodePremulKey', name + ' to premult', x + 590, y)
    premul.inputs['Type'].default_value = 'To Premultiplied'
    tree.links.new(replace.outputs['Image'], premul.inputs['Image'])
    return premul.outputs['Image']


def over(tree, foreground, background, name, x, y):
    n = node(tree, 'CompositorNodeAlphaOver', name, x, y)
    tree.links.new(background, n.inputs['Background'])
    tree.links.new(foreground, n.inputs['Foreground'])
    n.inputs['Factor'].default_value = 1.0
    return n.outputs['Image']


def compositor(scene, cfg, intro):
    t = bpy.data.node_groups.new(scene.name + ' — transparent LED', 'CompositorNodeTree')
    scene.compositing_node_group = t
    t.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    layers = node(t, 'CompositorNodeRLayers', 'Letters', -1100, 500)
    layers.scene = scene
    if intro:
        u = f'min(1,max(0,(frame-1)/{cfg["intro_frames"] - 1}))'
        power_expr = f'({u})**3*(10-15*({u})+6*({u})**2)'
        halo_expr = str(cfg['glow_intensity'])
    else:
        power_expr = '1'
        halo_expr = (f'{cfg["glow_intensity"]}*(1+{cfg["loop_amplitude"]}'
                     f'*sin(2*pi*(frame-1)/{cfg["loop_frames"]}))')
    power = animated_value(t, 'Power — smooth start', power_expr, -1100, 800)
    halo = animated_value(t, 'Halo — periodic intensity', halo_expr, -1100, -600)
    core = scale_alpha(t, layers.outputs['Image'], power, 'Letter fade', -800, 750)
    halos = []
    for i, kind in enumerate(('near', 'far')):
        y = 250 - i * 550
        blur = node(t, 'CompositorNodeBlur', kind + ' soft halo', -800, y)
        blur.inputs['Type'].default_value = 'Gaussian'
        blur.inputs['Size'].default_value = (cfg[f'glow_{kind}_px'],) * 2
        t.links.new(layers.outputs['Image'], blur.inputs['Image'])
        gain = math_node(t, kind + ' strength', 'MULTIPLY', -1000, y - 150,
                         halo, cfg[f'glow_{kind}_opacity'])
        gain = math_node(t, kind + ' fade', 'MULTIPLY', -800, y - 200, gain, power)
        halos.append(scale_alpha(t, blur.outputs['Image'], gain, kind, -550, y))
    combined = over(t, halos[0], halos[1], 'Two soft halos', 250, 0)
    final = over(t, core, combined, 'Letters over halo', 480, 500)
    out = node(t, 'NodeGroupOutput', 'RGBA output', 720, 500)
    t.links.new(final, out.inputs['Image'])


def make_scene(name, cfg, font, intro):
    scene = bpy.data.scenes.new(name)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = cfg['samples']
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = cfg['width'], cfg['height']
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
    scene.render.fps, scene.render.fps_base = cfg['fps'], 1.0
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = cfg['png_depth']
    scene.render.image_settings.compression = 35
    scene.render.use_compositing = True
    scene.render.compositor_device = 'CPU'
    scene.display_settings.display_device = 'sRGB'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
    scene.frame_start = 1
    scene.frame_end = cfg['intro_frames'] if intro else cfg['loop_frames']
    scene.world = bpy.data.worlds.new(name + ' World')
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
    curve = bpy.data.curves.new(name + ' editable text', 'FONT')
    curve.body = 'SINEGOR LAB'
    curve.font = font
    curve.size = cfg['font_size']
    curve.space_character = cfg['tracking']
    curve.extrude, curve.bevel_depth = cfg['depth'], cfg['bevel']
    curve.bevel_resolution, curve.resolution_u = cfg['bevel_resolution'], 16
    curve.fill_mode = 'BOTH'
    curve.materials.append(material(name + ' cold white', cfg['sinegor_color'], cfg))
    curve.materials.append(material(name + ' mint', cfg['lab_color'], cfg))
    for index, char in enumerate(curve.body_format):
        char.material_index = int(index >= 8)
    text = bpy.data.objects.new('SINEGOR LAB — editable Manrope SemiBold', curve)
    scene.collection.objects.link(text)
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    text.scale *= cfg['camera_width'] * cfg['text_width_fraction'] / text.dimensions.x
    bpy.context.view_layer.update()
    center = sum((text.matrix_world @ Vector(v) for v in text.bound_box), Vector()) / 8
    text.location.x -= center.x
    text.location.y -= center.y
    camera_data = bpy.data.cameras.new(name + ' frontal orthographic')
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = cfg['camera_width']
    camera = bpy.data.objects.new(name + ' camera', camera_data)
    camera.location = (0, 0, 20)
    scene.collection.objects.link(camera)
    scene.camera = camera
    compositor(scene, cfg, intro)
    scene['parameters'] = json.dumps(cfg, ensure_ascii=False, indent=2)
    scene['notes'] = 'RGBA, premultiplied compositor, straight PNG. Loop virtual frame N+1 equals frame 1.'
    scene.frame_set(1)
    return scene


def render(scene, frame, path):
    bpy.context.window.scene = scene
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True, scene=scene.name)


def validate(cfg):
    for key in ('width', 'height', 'fps', 'intro_frames', 'loop_frames', 'samples'):
        if not isinstance(cfg[key], int) or cfg[key] < (2 if key.endswith('frames') else 1):
            raise ValueError(f'{key}: expected positive integer')
    if not 0 <= cfg['loop_amplitude'] <= 0.05:
        raise ValueError('loop_amplitude must be 0..0.05')
    if not 0 < cfg['text_width_fraction'] < 0.95:
        raise ValueError('Leave safe margins for the halo: text_width_fraction < 0.95')
    if cfg['png_depth'] not in ('8', '16'):
        raise ValueError('png_depth must be "8" or "16"')
    for key in ('font_size', 'camera_width', 'face_strength'):
        if cfg[key] <= 0:
            raise ValueError(f'{key} must be positive')
    for key in ('depth', 'bevel', 'glow_intensity', 'glow_near_opacity', 'glow_far_opacity',
                'glow_near_px', 'glow_far_px'):
        if cfg[key] < 0:
            raise ValueError(f'{key} must be nonnegative')
    for key in ('sinegor_color', 'lab_color'):
        if len(cfg[key]) != 7 or not cfg[key].startswith('#'):
            raise ValueError(f'{key}: expected #RRGGBB')
        srgb(cfg[key])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=HERE / 'config.json')
    p.add_argument('--out', type=Path, help='Default: output, or output/glow_revision/PRESET')
    p.add_argument('--preset', choices=('original', 'A', 'B', 'C'))
    p.add_argument('--mode', choices=('build', 'preview', 'final'), default='preview')
    p.add_argument('--approved-final', action='store_true', help='Use only after visual approval')
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if args.mode == 'final' and not args.approved_final:
        p.error('Full export requires --approved-final after user approval')
    if bpy.app.version[:3] != (5, 1, 1):
        raise RuntimeError(f'This scene targets Blender 5.1.1; found {bpy.app.version_string}')
    cfg = load_configuration(args.config, args.preset)
    if args.out is None:
        args.out = HERE / 'output'
        if args.preset is not None:
            args.out /= Path('glow_revision') / args.preset
    validate(cfg)
    font_path = (args.config.resolve().parent / cfg['font']).resolve()
    if not font_path.is_file():
        raise FileNotFoundError(f'Provide local static Manrope SemiBold: {font_path}')
    # This is a dedicated scene generator. Run in a new process with --factory-startup.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    font = bpy.data.fonts.load(str(font_path), check_existing=True)
    font.pack()
    intro = make_scene('01 — Включение', cfg, font, True)
    loop = make_scene('02 — Цикл', cfg, font, False)
    for old in list(bpy.data.scenes):
        if old not in (intro, loop):
            bpy.data.scenes.remove(old)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    intro.render.filepath = str(args.out / 'intro/intro_')
    loop.render.filepath = str(args.out / 'loop/loop_')
    bpy.context.window.scene = loop
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
    (args.out / 'scene_config.json').write_text(json.dumps(cfg, indent=2) + '\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out / 'SINEGOR_LAB.blend'))
    if args.mode == 'preview':
        preview = args.out / 'preview'
        preview.mkdir(exist_ok=True)
        in_progress = args.out / 'preview_in_progress'
        in_progress.touch()
        cases = [(intro, 1, 'intro_0001'), (intro, (cfg['intro_frames'] + 1) // 2, 'intro_mid'),
                 (intro, cfg['intro_frames'], 'intro_end'), (loop, 1, 'steady'),
                 (loop, 1 + round(cfg['loop_frames'] / 4), 'loop_max'),
                 (loop, 1 + round(3 * cfg['loop_frames'] / 4), 'loop_min'),
                 (loop, cfg['loop_frames'], 'loop_last'),
                 (loop, cfg['loop_frames'] + 1, 'loop_virtual_next')]
        for scene, frame, name in cases:
            render(scene, frame, preview / (name + '.png'))
        (args.out / 'render_config.json').write_text(json.dumps(cfg, indent=2) + '\n')
        in_progress.unlink()
    elif args.mode == 'final':
        for scene, folder, prefix in ((intro, 'intro', 'intro'), (loop, 'loop', 'loop')):
            (args.out / folder).mkdir(exist_ok=True)
            bpy.context.window.scene = scene
            scene.frame_set(scene.frame_start)
            scene.render.filepath = str(args.out / folder / (prefix + '_'))
            bpy.ops.render.render(animation=True, scene=scene.name)
    print(f'Finished {args.mode}: {args.out}. Full export is never run by preview mode.')


if __name__ == '__main__':
    main()
