"""Remove overlapping straight contours in Manrope's A for Blender's font fill.

Uses the existing font's coordinates, not a replacement letter design. This
small SFNT helper deliberately rejects curves/composites; it only repairs A.
Intersections are rounded to the nearest TrueType unit (1/2000 em).
"""
import struct as st
from itertools import pairwise


def tables(raw):
    return {raw[12+i*16:16+i*16]: st.unpack_from('>II', raw, 20+i*16)
            for i in range(st.unpack_from('>H', raw, 4)[0])}


def contours(glyph):
    count = st.unpack_from('>h', glyph)[0]
    if count <= 0:
        raise ValueError('Expected simple glyph A')
    ends = st.unpack_from(f'>{count}H', glyph, 10)
    pos = 10 + 2 * count
    pos += 2 + st.unpack_from('>H', glyph, pos)[0]
    flags = []
    while len(flags) <= ends[-1]:
        flag = glyph[pos]
        pos += 1
        repeat = glyph[pos] if flag & 8 else 0
        pos += bool(flag & 8)
        flags.extend([flag] * (repeat + 1))
    if not all(f & 1 for f in flags):
        raise ValueError('A changed: curved points require a different union method')
    axes = []
    for short, same in ((2, 16), (4, 32)):
        coord, values = 0, []
        for flag in flags:
            if flag & short:
                delta = glyph[pos] * (1 if flag & same else -1)
                pos += 1
            elif flag & same:
                delta = 0
            else:
                delta = st.unpack_from('>h', glyph, pos)[0]
                pos += 2
            coord += delta
            values.append(coord)
        axes.append(values)
    result, start = [], 0
    for end in ends:
        result.append(list(zip(axes[0][start:end+1], axes[1][start:end+1])))
        start = end + 1
    return result


def union(polygons):
    edges = [(a, b) for p in polygons for a, b in zip(p, p[1:] + p[:1])]

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def minus(a, b):
        return a[0] - b[0], a[1] - b[1]

    def filled(p):
        winding = 0
        for a, b in edges:
            side = cross(minus(b, a), minus(p, a))
            if a[1] <= p[1] < b[1] and side > 0:
                winding += 1
            if b[1] <= p[1] < a[1] and side < 0:
                winding -= 1
        return winding != 0

    boundary = []
    for a, b in edges:
        direction = minus(b, a)
        cuts = {0.0, 1.0}
        for c, d in edges:
            other = minus(d, c)
            denom = cross(direction, other)
            if abs(denom) < 1e-10:
                continue
            t = cross(minus(c, a), other) / denom
            u = cross(minus(c, a), direction) / denom
            if 0 < t < 1 and 0 <= u <= 1:
                cuts.add(t)
        cuts = sorted(cuts)
        length = (direction[0]**2 + direction[1]**2)**0.5
        normal = (-direction[1] / length * 0.001, direction[0] / length * 0.001)
        for t0, t1 in pairwise(cuts):
            mid = tuple(a[k] + (t0 + t1) / 2 * direction[k] for k in (0, 1))
            left = filled(tuple(mid[k] + normal[k] for k in (0, 1)))
            right = filled(tuple(mid[k] - normal[k] for k in (0, 1)))
            if left == right:
                continue
            v0 = tuple(round(a[k] + t0 * direction[k]) for k in (0, 1))
            v1 = tuple(round(a[k] + t1 * direction[k]) for k in (0, 1))
            if v0 != v1:
                boundary.append((v0, v1) if right else (v1, v0))
    result = []
    while boundary:
        a, b = boundary.pop(0)
        polygon = [a]
        while b != polygon[0]:
            polygon.append(b)
            matches = [i for i, edge in enumerate(boundary) if edge[0] == b]
            if len(matches) != 1:
                raise ValueError('Ambiguous union boundary')
            _, b = boundary.pop(matches[0])
        result.append(polygon)
    return result


def encode(polygons):
    points = [p for contour in polygons for p in contour]
    xs, ys = list(zip(*points))
    data = st.pack('>hhhhh', len(polygons), min(xs), min(ys), max(xs), max(ys))
    end = -1
    for contour in polygons:
        end += len(contour)
        data += st.pack('>H', end)
    data += b'\0\0'  # No glyph-specific hint program after outline union.
    data += bytes([1] * len(points))  # All points on-curve; signed 16-bit deltas.
    for axis in (xs, ys):
        previous = 0
        for value in axis:
            data += st.pack('>h', value - previous)
            previous = value
    return data


def checksum(data):
    data += b'\0' * (-len(data) % 4)
    return sum(st.unpack(f'>{len(data)//4}I', data)) & 0xffffffff


def repair_a(raw, glyph_id):
    directory = tables(raw)
    parts = {tag: raw[offset:offset+size] for tag, (offset, size) in directory.items()}
    count = st.unpack_from('>H', parts[b'maxp'], 4)[0]
    long_loca = st.unpack_from('>h', parts[b'head'], 50)[0]
    offsets = list(st.unpack(f'>{count+1}{"I" if long_loca else "H"}', parts[b'loca']))
    if not long_loca:
        offsets = [v * 2 for v in offsets]
    glyphs = [parts[b'glyf'][offsets[i]:offsets[i+1]] for i in range(count)]
    original = contours(glyphs[glyph_id])
    repaired = union(original)
    glyphs[glyph_id] = encode(repaired)
    offsets, glyf = [0], b''
    for glyph in glyphs:
        glyf += glyph + b'\0' * (-len(glyph) % 4)
        offsets.append(len(glyf))
    parts[b'glyf'] = glyf
    parts[b'loca'] = st.pack(f'>{count+1}I', *offsets)
    head = bytearray(parts[b'head'])
    head[8:12] = b'\0' * 4
    st.pack_into('>h', head, 50, 1)
    parts[b'head'] = bytes(head)
    # A variable font pinned by HarfBuzz retains its original default names.
    # Label this genuine weight-600 instance correctly in font selectors.
    names = parts[b'name']
    fmt, name_count, strings_offset = st.unpack_from('>HHH', names)
    if fmt != 0:
        raise ValueError('Unsupported name table format')
    labels = {1: 'Manrope', 2: 'SemiBold', 3: 'Manrope SemiBold 600 local static',
              4: 'Manrope SemiBold', 6: 'Manrope-SemiBold', 16: 'Manrope', 17: 'SemiBold'}
    records, strings = b'', b''
    for i in range(name_count):
        platform, encoding, language, name_id, length, offset = st.unpack_from('>6H', names, 6 + i*12)
        value = names[strings_offset+offset:strings_offset+offset+length]
        if name_id in labels:
            value = labels[name_id].encode('utf-16-be' if platform in (0, 3) else 'mac_roman')
        records += st.pack('>6H', platform, encoding, language, name_id, len(value), len(strings))
        strings += value
    parts[b'name'] = st.pack('>3H', 0, name_count, 6+name_count*12) + records + strings
    tags = sorted(parts)
    size = len(tags)
    power = 2**(size.bit_length()-1)
    header = raw[:4] + st.pack('>HHHH', size, power*16, power.bit_length()-1, size*16-power*16)
    records, body, head_offset = b'', b'', None
    for tag in tags:
        data = parts[tag]
        offset = 12 + size*16 + len(body)
        if tag == b'head':
            head_offset = offset
        records += tag + st.pack('>III', checksum(data), offset, len(data))
        body += data + b'\0' * (-len(data) % 4)
    result = bytearray(header + records + body)
    st.pack_into('>I', result, head_offset+8, (0xB1B0AFBA-checksum(bytes(result))) & 0xffffffff)
    assert checksum(bytes(result)) == 0xB1B0AFBA
    print(f'A: {len(original)} overlapping contours -> {len(repaired)} boundaries')
    return bytes(result)
