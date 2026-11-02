"""Pin the existing Manrope variable font to wght=600 using local HarfBuzz.

No downloads. Run with system Python on Linux; the resulting static font is
portable and Blender itself needs no HarfBuzz Python binding.
"""
import ctypes as c
import ctypes.util
import struct
from pathlib import Path

from font_outline import repair_a

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'apps/web/assets/fonts/Manrope-variable.ttf'
TARGET = HERE / 'fonts/Manrope-SemiBold.ttf'


def prepare():
    hb = c.CDLL(ctypes_path('harfbuzz'))
    sub = c.CDLL(ctypes_path('harfbuzz-subset'))

    def bind(lib, name, result, *args):
        f = getattr(lib, name)
        f.restype, f.argtypes = result, args
        return f

    ptr, uint = c.c_void_p, c.c_uint
    blob_new = bind(hb, 'hb_blob_create_from_file_or_fail', ptr, c.c_char_p)
    face_new = bind(hb, 'hb_face_create', ptr, ptr, uint)
    input_new = bind(sub, 'hb_subset_input_create_or_fail', ptr)
    unicode_set = bind(sub, 'hb_subset_input_unicode_set', ptr, ptr)
    invert = bind(hb, 'hb_set_invert', None, ptr)
    pin = bind(sub, 'hb_subset_input_pin_axis_location', c.c_int,
               ptr, ptr, uint, c.c_float)
    subset = bind(sub, 'hb_subset_or_fail', ptr, ptr, ptr)
    font_new = bind(hb, 'hb_font_create', ptr, ptr)
    nominal = bind(hb, 'hb_font_get_nominal_glyph', c.c_int, ptr, uint, c.POINTER(uint))
    font_destroy = bind(hb, 'hb_font_destroy', None, ptr)
    face_blob = bind(hb, 'hb_face_reference_blob', ptr, ptr)
    data = bind(hb, 'hb_blob_get_data', ptr, ptr, c.POINTER(uint))
    blob_destroy = bind(hb, 'hb_blob_destroy', None, ptr)
    face_destroy = bind(hb, 'hb_face_destroy', None, ptr)
    input_destroy = bind(sub, 'hb_subset_input_destroy', None, ptr)
    blob = blob_new(str(SOURCE).encode())
    if not blob:
        raise RuntimeError(f'Cannot read font: {SOURCE}')
    face, inp = face_new(blob, 0), input_new()
    result = output_blob = None
    try:
        if not face or not inp:
            raise RuntimeError('HarfBuzz allocation failed')
        invert(unicode_set(inp))  # Keep all Unicode characters, not just the title.
        if not pin(inp, face, int.from_bytes(b'wght', 'big'), 600.0):
            raise RuntimeError('Manrope wght axis could not be pinned')
        result = subset(face, inp)
        if not result:
            raise RuntimeError('Font instancing failed')
        output_blob = face_blob(result)
        size = uint()
        raw = c.string_at(data(output_blob, c.byref(size)), size.value)
        count = struct.unpack_from('>H', raw, 4)[0]
        tables = {raw[12 + i * 16:16 + i * 16]:
                  struct.unpack_from('>II', raw, 20 + i * 16)
                  for i in range(count)}
        assert b'fvar' not in tables, 'Output is still variable'
        os2, _ = tables[b'OS/2']
        assert struct.unpack_from('>H', raw, os2 + 4)[0] == 600
        font = font_new(result)
        glyph_id = uint()
        try:
            if not nominal(font, ord('A'), c.byref(glyph_id)):
                raise RuntimeError('Missing A glyph')
            raw = repair_a(raw, glyph_id.value)
        finally:
            font_destroy(font)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(raw)
        print(f'Created static Manrope, weight 600: {TARGET} ({len(raw)} bytes)')
    finally:
        if output_blob:
            blob_destroy(output_blob)
        if result:
            face_destroy(result)
        if inp:
            input_destroy(inp)
        if face:
            face_destroy(face)
        blob_destroy(blob)


def ctypes_path(name):
    path = c.util.find_library(name)
    if not path:
        raise RuntimeError(f'Local library {name} unavailable; supply a licensed static Manrope SemiBold instead')
    return path


if __name__ == '__main__':
    prepare()
