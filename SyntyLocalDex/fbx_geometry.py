# SPDX-License-Identifier: GPL-3.0-only
"""Small, dependency-free FBX mesh preview reader (NOT a complete FBX importer).

Supports geometry in common binary 7.x and ASCII 7.x FBX files. It ignores
materials, rigs, scene transforms and animation; no downloaded asset is modified.
Only numeric mesh vertices and polygon indices are ever returned to the browser.
"""
from __future__ import annotations

import io
import math
import re
import struct
import zlib
from dataclasses import dataclass
from typing import Iterator

FBX_MAGIC = b'Kaydara FBX Binary  \x00\x1a\x00'
MAX_FBX_BYTES = 96 * 1024 * 1024
MAX_ARRAY_ITEMS = 1_500_000
MAX_VERTICES = 180_000
MAX_TRIANGLES = 125_000


class FBXPreviewError(ValueError):
    pass


@dataclass
class Node:
    name: str
    props_start: int
    props_len: int
    end: int
    children_start: int


def _headers(data: memoryview, start: int, end: int, wide: bool) -> Iterator[Node]:
    fmt = '<QQQB' if wide else '<IIIB'
    header_size = struct.calcsize(fmt)
    pos = start
    while pos + header_size <= end:
        stop, prop_count, prop_len, name_len = struct.unpack_from(fmt, data, pos)
        if stop == 0:  # FBX null-node footer
            return
        name_start = pos + header_size
        children_start = name_start + name_len + prop_len
        if stop <= pos or stop > end or children_start > stop or name_len > 240:
            raise FBXPreviewError('Invalid FBX node structure')
        name = bytes(data[name_start:name_start + name_len]).decode('utf-8', 'replace')
        yield Node(name, name_start + name_len, prop_len, stop, children_start)
        pos = stop


def _properties(data: memoryview, node: Node) -> list[object]:
    pos = node.props_start
    stop = pos + node.props_len
    values: list[object] = []
    while pos < stop:
        code = chr(data[pos]); pos += 1
        if code in ('Y', 'C', 'I', 'F', 'D', 'L'):
            fmt = {'Y': '<h', 'C': '<B', 'I': '<i', 'F': '<f', 'D': '<d', 'L': '<q'}[code]
            values.append(struct.unpack_from(fmt, data, pos)[0]); pos += struct.calcsize(fmt)
        elif code in ('S', 'R'):
            if pos + 4 > stop: raise FBXPreviewError('Truncated FBX property')
            n, = struct.unpack_from('<I', data, pos); pos += 4
            if n > stop - pos: raise FBXPreviewError('Invalid FBX property length')
            values.append(bytes(data[pos:pos + n]).decode('utf-8', 'replace') if code == 'S' else None)
            pos += n
        elif code in ('f', 'd', 'i', 'l', 'b', 'c'):
            if pos + 12 > stop: raise FBXPreviewError('Truncated FBX numeric array')
            length, encoding, byte_len = struct.unpack_from('<III', data, pos); pos += 12
            if length > MAX_ARRAY_ITEMS or byte_len > stop - pos:
                raise FBXPreviewError('FBX array too large or incomplete')
            if encoding == 1:
                try:
                    decompressor = zlib.decompressobj()
                    raw = decompressor.decompress(data[pos:pos + byte_len], MAX_ARRAY_ITEMS * 8 + 1)
                    raw += decompressor.flush(MAX_ARRAY_ITEMS * 8 + 1 - len(raw))
                except zlib.error as exc:
                    raise FBXPreviewError('Invalid compressed FBX array') from exc
                if len(raw) > MAX_ARRAY_ITEMS * 8 or not decompressor.eof:
                    raise FBXPreviewError('FBX decompressed array too large')
            elif encoding == 0:
                raw = bytes(data[pos:pos + byte_len])
            else:
                raise FBXPreviewError('Unsupported FBX array encoding')
            pos += byte_len
            letter = {'f': 'f', 'd': 'd', 'i': 'i', 'l': 'q', 'b': 'B', 'c': 'B'}[code]
            item_size = struct.calcsize('<' + letter)
            if len(raw) != length * item_size:
                raise FBXPreviewError('FBX array length mismatch')
            values.append(list(struct.unpack('<' + str(length) + letter, raw)))
        else:
            raise FBXPreviewError('Unrecognized FBX property type')
        if len(values) > 12:  # Geometry has a handful of scalar props, a vertex array only one.
            raise FBXPreviewError('Unexpected FBX property count')
    return values


def _binary_meshes(data: bytes) -> list[tuple[list[float], list[int]]]:
    if len(data) < 27 or not data.startswith(FBX_MAGIC):
        raise FBXPreviewError('Invalid binary FBX header')
    version, = struct.unpack_from('<I', data, 23)
    if not 7000 <= version <= 9000:
        raise FBXPreviewError(f'Unsupported FBX version {version}')
    wide = version >= 7500
    buf = memoryview(data)
    meshes: list[tuple[list[float], list[int]]] = []
    for root in _headers(buf, 27, len(buf), wide):
        if root.name != 'Objects':
            continue
        for entry in _headers(buf, root.children_start, root.end, wide):
            if entry.name != 'Geometry':
                continue
            # The 3rd property identifies geometries containing triangle/polygon meshes.
            props = _properties(buf, entry)
            if len(props) < 3 or props[2] != 'Mesh':
                continue
            vertices = indices = None
            for part in _headers(buf, entry.children_start, entry.end, wide):
                if part.name == 'Vertices':
                    values = _properties(buf, part)
                    vertices = values[0] if values else None
                elif part.name == 'PolygonVertexIndex':
                    values = _properties(buf, part)
                    indices = values[0] if values else None
            if isinstance(vertices, list) and isinstance(indices, list):
                meshes.append((vertices, indices))
            if len(meshes) >= 128:
                break
    return meshes


def _find_block(text: str, start: int) -> str:
    # Find balanced braces while accounting for quoted FBX strings.
    pos = text.find('{', start)
    if pos < 0: return ''
    level, quoted, escape = 1, False, False
    for i in range(pos + 1, len(text)):
        c = text[i]
        if escape:
            escape = False
        elif c == '\\' and quoted:
            escape = True
        elif c == '"':
            quoted = not quoted
        elif not quoted and c == '{':
            level += 1
        elif not quoted and c == '}':
            level -= 1
            if level == 0: return text[pos + 1:i]
    return ''


def _ascii_meshes(data: bytes) -> list[tuple[list[float], list[int]]]:
    text = data.decode('utf-8-sig', 'replace')
    meshes = []
    for match in re.finditer(r'Geometry\s*:\s*[^\n{}]+?"Mesh"\s*\{', text):
        block = _find_block(text, match.end() - 1)
        if not block: continue
        arrays = []
        for key in ('Vertices', 'PolygonVertexIndex'):
            m = re.search(r'\b' + key + r'\s*:\s*(?:\*\s*\d+\s*)?\{', block)
            if not m:
                arrays = []; break
            field = _find_block(block, m.end() - 1)
            am = re.search(r'\ba\s*:\s*([\s\S]*)', field)
            if not am:
                arrays = []; break
            nums = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', am.group(1))
            if len(nums) > MAX_ARRAY_ITEMS: raise FBXPreviewError('ASCII FBX numeric array too large')
            arrays.append([float(n) for n in nums] if key == 'Vertices' else [int(n) for n in nums])
        if len(arrays) == 2:
            meshes.append((arrays[0], arrays[1]))
        if len(meshes) >= 128: break
    return meshes


def parse_fbx_geometry(data: bytes) -> dict:
    """Return a normalized model for static shaded 3D previews.

    Mesh geometry only; textures, skeletal skinning and keyframe animation are not
    reconstructed. Limitations are deliberately explicit rather than mis-rendering.
    """
    if len(data) > MAX_FBX_BYTES:
        raise FBXPreviewError('FBX is too large for preview (96 MB limit)')
    meshes = _binary_meshes(data) if data.startswith(FBX_MAGIC) else _ascii_meshes(data)
    if not meshes:
        raise FBXPreviewError('No supported mesh geometry found in FBX')
    points: list[float] = []
    triangles: list[int] = []
    clipped = False
    for vertices, indices in meshes:
        n = len(vertices) // 3
        if n < 3: continue
        if len(points) // 3 + n > MAX_VERTICES:
            clipped = True; break
        offset = len(points) // 3
        points.extend(vertices[:n * 3])
        face: list[int] = []
        for token in indices:
            raw = int(token)
            finished = raw < 0
            v = -raw - 1 if finished else raw
            if v < 0 or v >= n:
                face.clear()
                continue
            face.append(v + offset)
            if len(face) > 500:
                face.clear()
                continue
            if finished:
                for j in range(1, len(face) - 1):
                    if len(triangles) // 3 >= MAX_TRIANGLES:
                        clipped = True; break
                    triangles.extend((face[0], face[j], face[j + 1]))
                face.clear()
            if clipped: break
        if clipped: break
    if not points or not triangles:
        raise FBXPreviewError('FBX contains no renderable polygons')
    if not all(math.isfinite(v) for v in points):
        raise FBXPreviewError('FBX has invalid mesh coordinates')
    mins = [min(points[c::3]) for c in range(3)]
    maxs = [max(points[c::3]) for c in range(3)]
    longest = max((hi - lo for lo, hi in zip(mins, maxs)), default=0)
    if longest <= 1e-10: raise FBXPreviewError('Degenerate FBX geometry')
    centers = [(lo + hi) / 2 for lo, hi in zip(mins, maxs)]
    scale = 1.7 / longest
    coords = [round((v - centers[i % 3]) * scale, 5) for i, v in enumerate(points)]
    return {'vertices': coords, 'triangles': triangles, 'meshes': len(meshes),
            'truncated': clipped, 'note': 'Static mesh preview: no textures, rigs or animation'}


def thumbnail_svg(mesh: dict, size: int = 256) -> bytes:
    """Return safe numeric-only SVG preview; no third-party code or user text."""
    pts = mesh['vertices']; faces = mesh['triangles']
    import html  # SVG text is completely static; geometry is numeric only.
    # Isometric projected wireframe polygons. Limit to 900 paths for thumbnail cost.
    cos_y, sin_y, cos_x, sin_x = .78, .63, .90, -.44
    transformed = []
    for i in range(0, len(pts), 3):
        x, y, z = pts[i:i+3]
        xp, zp = x*cos_y + z*sin_y, -x*sin_y + z*cos_y
        yp, zp = y*cos_x - zp*sin_x, y*sin_x + zp*cos_x
        transformed.append((xp, yp, zp))
    selected = list(range(0, len(faces), max(3, (len(faces)//3//900)*3)))[:900]
    polys = []
    for ix in selected:
        if ix+2 >= len(faces): break
        a, b, c = [transformed[faces[ix+k]] for k in range(3)]
        ax, ay = a[0]*105+size/2, -a[1]*105+size/2
        bx, by = b[0]*105+size/2, -b[1]*105+size/2
        cx, cy = c[0]*105+size/2, -c[1]*105+size/2
        cross = (bx-ax)*(cy-ay) - (by-ay)*(cx-ax)
        intensity = min(.85, max(.16, .48 + .2 * (1 if cross > 0 else -1)))
        fill = f'rgb({int(115*intensity)},{int(157*intensity)},{int(219*intensity)})'
        polys.append(((a[2]+b[2]+c[2])/3, f'<path d="M{ax:.1f},{ay:.1f}L{bx:.1f},{by:.1f}L{cx:.1f},{cy:.1f}Z" fill="{fill}" stroke="#dd94d9" stroke-opacity=".35" stroke-width=".6"/>'))
    polys.sort(key=lambda t: t[0])
    body = ''.join(p[1] for p in polys)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}"><rect width="100%" height="100%" fill="#171e2d"/>{body}</svg>').encode('ascii')
