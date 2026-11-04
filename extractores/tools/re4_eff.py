#!/usr/bin/env python3
"""RE4 (GameCube) effect data ("EFF", version 0xB) dumper and texture exporter.

Layout reversed from the decomp (re4/src/game/eff_sys.cpp EspDataLoad, include/esp.h, espgen.h):

  EffData header (big endian u32, byte offsets from the EFF start)
    0x00 version == 0xB
    0x04 ofsTexId   EffIdTbl {u32 num; {u16 id; u16; u32;}[num]}   texture ids (0..0xFF, global table)
    0x08 ofsEstList SstList  {u32 num; {u16 no; u16 type; u32 flg}[num]}  est ids (EstSet(owner, id))
    0x0C ofsSstList SstList  (room effects, same shape)
    0x10 ofsPathList
    0x14 ofsEfmId   EffIdTbl effect-model ids
    0x18 ofsTpl     EffOfsTbl {u32 num; u32 ofs[num]} ofs relative to the table -> TPL
    0x1C ofsAnm     EffOfsTbl -> EspAnmData (u16 W, H; s16 Cx, Cy; u16 Frames; u8 Xn, Loop, Data_num;
                    pad[3]; u8 Frame_cnt[Frames] ; u8 time[Frames] when Data_num != 0)
    0x20 ofsEstData SstData  {u32 num; u32 ofs[num]} ofs relative to SstData -> EspSeqData
    0x24 ofsSstData 0x28 ofsPathData 0x2C ofsEfm (EffOfsTbl of EffEfmEnt)

  EspSeqData: 0x30 header {u16 num; ...; u16 flags@8; u8 parts@0xA; Vec pos@0xC; Vec rot@0x18 (deg);
              u8 Ver_no@0x24; u16 Core_flg@0x26} then num EspGenWork records of 0x12C bytes (fields: see Eff._rec).

Semantics (esp_sub.cpp EspSeqSet / cEsp::CommonMove / ColorUpdate / AnmMove / EspCommonTrans, 30 fps,
units = mm, angles in degrees in the file, converted with 3.14/180):
  per frame:  pos += speed; speed += Speed_plus; speed *= D_speed          (after Pos_start_cnt)
              size_mul += Size_plus; Size_plus *= D_size_plus; die if size_mul <= 0 (after Size_start_cnt)
              ang += Ang_plus
              colour: t <= Col_max_cnt: alpha = a0 * t / Col_max_cnt (fade-in, only if Col_max_cnt != 0)
                      t >= Col_max_cnt + Col_start_cnt: rgba *= Col_d_* ; die when alpha < 4
              die when Life_max != 0 and t >= Life_max
  drawn size (full quad width / height) = Size_base_{x,y} * size_mul, quad centred unless Anm Cx/Cy.
  Blend_type -> GXSetBlendMode(BLEND, src, dst): 0 alpha, 1 additive (src*a + dst), 2 add (one,one),
              3 src*dst + dst, 4 multiply (dst*src, rgb pre-scaled by alpha), 5 src*a + dst*(1-srccol)
  Tool_flg bit0 = oriented in parent space (not a camera billboard); bit1/2 flip s/t, bit3/4 random
              flip; 0x20 = only position from the part (world); 0x40 lit; 0x80000 = y-axis billboard.
  Parts_no 0..0xF7 = parts of the model given to EstSet (released to world after Release_time frames,
  0 = on the first move), 0xFE free / world, 0xFF world through the sequence matrix, 0xF8..0xFD screen.

Usage:
  re4_eff.py FILE [--entry N] [--est ID ...] [--png DIR] [--core core.das] [--all-tex] [--json FILE]
  FILE: .drs/.das archive (every EFF entry, or --entry N) or a raw .eff file.
"""
import argparse
import json
import math
import os
import struct
import sys
import zlib

RE4_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 're4', 'tools')

# ---------------------------------------------------------------------------------------------------
# GX texture decoding (TPL)

TF_NAMES = {0: 'I4', 1: 'I8', 2: 'IA4', 3: 'IA8', 4: 'RGB565', 5: 'RGB5A3', 6: 'RGBA8', 8: 'CI4', 9: 'CI8',
            10: 'CI14X2', 14: 'CMPR'}
TL_NAMES = {0: 'IA8', 1: 'RGB565', 2: 'RGB5A3'}
BLOCK = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16), 6: (4, 4, 32),
         8: (8, 8, 4), 9: (8, 4, 8), 10: (4, 4, 16), 14: (8, 8, 4)}


def _565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2), 255)


def _5a3(v):
    if v & 0x8000:
        r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
        return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2), 255)
    a, r, g, b = (v >> 12) & 7, (v >> 8) & 15, (v >> 4) & 15, v & 15
    return (r * 17, g * 17, b * 17, (a << 5) | (a << 2) | (a >> 1))


def _ia8(v):
    i, a = v & 0xFF, v >> 8
    return (i, i, i, a)


def decode_palette(data, fmt, n):
    f = {0: _ia8, 1: _565, 2: _5a3}[fmt]
    return [f(struct.unpack_from('>H', data, 2 * i)[0]) for i in range(n)]


def decode_tex(fmt, w, h, data, pal=None):
    """-> list of rows of RGBA tuples."""
    bw, bh, bpp = BLOCK[fmt]
    img = [[(0, 0, 0, 0)] * w for _ in range(h)]
    bx_n = (w + bw - 1) // bw
    by_n = (h + bh - 1) // bh
    pos = 0
    for by in range(by_n):
        for bx in range(bx_n):
            if fmt == 14:     # CMPR: 2x2 DXT1 sub-blocks
                for sb in range(4):
                    c0, c1 = struct.unpack_from('>HH', data, pos)
                    idx = data[pos + 4:pos + 8]
                    pos += 8
                    p0, p1 = _565(c0), _565(c1)
                    if c0 > c1:
                        p2 = tuple((5 * p0[k] + 3 * p1[k]) // 8 for k in range(3)) + (255,)
                        p3 = tuple((3 * p0[k] + 5 * p1[k]) // 8 for k in range(3)) + (255,)
                    else:
                        p2 = tuple((p0[k] + p1[k]) // 2 for k in range(3)) + (255,)
                        p3 = tuple((p0[k] + p1[k]) // 2 for k in range(3)) + (0,)
                    cols = (p0, p1, p2, p3)
                    ox = bx * 8 + (sb & 1) * 4
                    oy = by * 8 + (sb >> 1) * 4
                    for y in range(4):
                        for x in range(4):
                            c = cols[(idx[y] >> (6 - 2 * x)) & 3]
                            if oy + y < h and ox + x < w:
                                img[oy + y][ox + x] = c
                continue
            if fmt == 6:      # RGBA8: AR block then GB block
                ar = data[pos:pos + 32]
                gb = data[pos + 32:pos + 64]
                pos += 64
                for i in range(16):
                    x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                    if y < h and x < w:
                        img[y][x] = (ar[2 * i + 1], gb[2 * i], gb[2 * i + 1], ar[2 * i])
                continue
            for y in range(bh):
                for x in range(bw):
                    if fmt in (0, 8):
                        b = data[pos + (y * bw + x) // 2]
                        v = (b >> 4) if x % 2 == 0 else (b & 15)
                    elif fmt in (1, 9):
                        v = data[pos + y * bw + x]
                    elif fmt == 2:
                        v = data[pos + y * bw + x]
                    else:
                        v = struct.unpack_from('>H', data, pos + 2 * (y * bw + x))[0]
                    if fmt == 0:
                        c = (v * 17,) * 4
                    elif fmt == 1:
                        c = (v,) * 4
                    elif fmt == 2:
                        i = (v & 15) * 17
                        c = (i, i, i, (v >> 4) * 17)
                    elif fmt == 3:
                        c = _ia8(v)
                    elif fmt == 4:
                        c = _565(v)
                    elif fmt == 5:
                        c = _5a3(v)
                    elif fmt in (8, 9, 10):
                        c = pal[v & 0x3FFF] if pal and (v & 0x3FFF) < len(pal) else (255, 0, 255, 255)
                    X, Y = bx * bw + x, by * bh + y
                    if Y < h and X < w:
                        img[Y][X] = c
            pos += 32
    return img


def png_bytes(img):
    h = len(img)
    w = len(img[0])
    raw = b''.join(b'\0' + bytes(v for px in row for v in px) for row in img)

    def chunk(tag, body):
        c = tag + body
        return struct.pack('>I', len(body)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def parse_tpl(d, base):
    ver, n, dofs = struct.unpack_from('>III', d, base)
    if ver != 0x0020AF30:
        raise ValueError('bad TPL at %#x' % base)
    out = []
    for i in range(n):
        th, cl = struct.unpack_from('>II', d, base + dofs + 8 * i)
        h, w, fmt, dat, ws, wt, minf, magf = struct.unpack_from('>HHIIIIII', d, base + th)
        pal = None
        palfmt = None
        if cl:
            ne, _unp, _pad, palfmt, pdat = struct.unpack_from('>HBBII', d, base + cl)
            pal = decode_palette(d[base + pdat:base + pdat + 2 * ne], palfmt, ne)
        bw, bh, bpp = BLOCK[fmt]
        size = ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * (64 if fmt == 6 else 32)
        out.append(dict(w=w, h=h, fmt=fmt, wrap=(ws, wt), filt=(minf, magf), palfmt=palfmt, pal=pal,
                        data=d[base + dat:base + dat + size]))
    return out


# ---------------------------------------------------------------------------------------------------
# EFF container

ESP_NAMES = {
    0x00: 'sprite (billboard quad)', 0x01: 'motion-trail strip', 0x02: 'ribbon beam (quad along -X, camera-facing)',
    0x03: 'line trail (GX lines, no texture)', 0x04: 'screen tiled overlay', 0x05: 'flutter sprite',
    0x06: 'path sprite', 0x07: 'bouncing particle', 0x08: 'scrolling tiled sprite', 0x09: 'position trail',
    0x0A: 'motion-trail sprites', 0x0B: 'jitter sprite', 0x0C: 'est spawner', 0x0D: 'attracted sprite',
    0x0E: 'lens-flare glow', 0x0F: 'refraction sprite', 0x10: 'ground decal', 0x11: 'dynamic point light',
    0x12: 'textured ribbon trail', 0x14: 'light shaft', 0x15: 'weather particle', 0x16: 'rope',
    0x17: 'view-space sprite', 0x18: 'heat shimmer', 0x19: '3D line (laser)', 0x1A: 'axis jitter sprite',
    0x1B: 'spline ribbon', 0x42: 'sprite, explicit blend', 0x45: 'bloom glow', 0x4B: 'frozen-pattern sprite',
    0xFC: 'effect model', 0xFD: 'effect model', 0xFE: 'effect model', 0xFF: 'effect model',
}
BLEND = {0: 'ALPHA   src*a + dst*(1-a)', 1: 'ADDITIVE src*a + dst', 2: 'ADD      src + dst',
         3: 'MOD2X    src*dst + dst', 4: 'MULTIPLY dst*src (rgb pre-multiplied by a)',
         5: 'SCREEN   src*a + dst*(1-src)'}
NO_TEX_IDS = {0x03, 0x0C, 0x11, 0x19, 0x44, 0x46, 0x4A, 0x4C, 0x4D}   # draw no texture (Tex_id unused)
TOOL_BITS = {0: 'oriented(not billboard)', 1: 'flipS', 2: 'flipT', 3: 'randFlipS', 4: 'randFlipT',
             5: 'posOnlyFromPart(world)', 6: 'lit', 7: 'tevScaleColor', 13: 'nega', 14: 'maskTex',
             15: 'alphaUpdate', 17: 'maskAlphaScale', 19: 'yBillboard', 20: 'alphaTest0x80', 21: 'noZ?/dstAlpha',
             23: 'alphaUpdate2'}



def u32(d, o):
    return struct.unpack_from('>I', d, o)[0]


class Eff:
    def __init__(self, d, name='eff'):
        self.d = d
        self.name = name
        h = struct.unpack_from('>12I', d, 0)
        if h[0] != 0xB:
            raise ValueError('not an EFF v0xB (version %#x)' % h[0])
        self.h = h
        # textures
        ids, tpl, anm = h[1], h[6], h[7]
        self.tex = {}
        for i in range(u32(d, ids)):
            tid = struct.unpack_from('>H', d, ids + 4 + 8 * i)[0]
            to = tpl + u32(d, tpl + 4 + 4 * i)
            ao = anm + u32(d, anm + 4 + 4 * i)
            W, H, cx, cy, fr, xn, lp, dn = struct.unpack_from('>HHhhHBBB', d, ao)
            times = list(d[ao + 0x10 + fr:ao + 0x10 + 2 * fr]) if dn else None
            self.tex[tid] = dict(id=tid, anm=dict(W=W, H=H, Cx=cx, Cy=cy, Frames=fr, Xn=xn, Loop=lp & 3,
                                                   Data_num=dn, times=times), frames=parse_tpl(d, to))
        # est tables
        self.est = self._seq_tables(h[2], h[8])
        self.sst = self._seq_tables(h[3], h[9])

    def _seq_tables(self, lst, data):
        d = self.d
        out = {}
        if not lst or not data:
            return out
        n = u32(d, lst)
        for i in range(n):
            no, typ, flg = struct.unpack_from('>HHI', d, lst + 4 + 8 * i)
            seq = data + u32(d, data + 4 + 4 * i)
            out[no] = self._seq(seq)
        return out

    def _seq(self, o):
        d = self.d
        num, = struct.unpack_from('>H', d, o)
        flags, parts = struct.unpack_from('>HB', d, o + 8)
        pos = struct.unpack_from('>3f', d, o + 0xC)
        rot = struct.unpack_from('>3f', d, o + 0x18)
        ver, core = d[o + 0x24], struct.unpack_from('>H', d, o + 0x26)[0]
        recs = [self._rec(o + 0x30 + 0x12C * i) for i in range(num)]
        return dict(offset=o, flags=flags, parts=parts, pos=pos, rot_deg=rot, ver=ver, core_flg=core, records=recs)

    def _rec(self, o):
        d = self.d
        r = {}
        (r['Be_flg'], r['Id'], r['Tex_id'], r['Type'], r['Set_time'], r['Parent_no'], r['Parts_no'],
         r['Tool_flg']) = struct.unpack_from('>BBBBHBBI', d, o)
        f = struct.unpack_from('>3f3f3ff3f3f3f3f3f3f3f', d, o + 0xC)
        r['Pos'], r['R_pos'], r['Speed'] = f[0:3], f[3:6], f[6:9]
        r['D_speed'] = f[9]
        r['R_speed'], r['Speed_plus'], r['R_speed_plus'] = f[10:13], f[13:16], f[16:19]
        r['Ang'], r['R_ang'], r['Ang_plus'], r['R_ang_plus'] = f[19:22], f[22:25], f[25:28], f[28:31]
        (r['Size_base_x'], r['Size_base_y'], r['R_size_base'], r['Size_plus'],
         r['D_size_plus']) = struct.unpack_from('>5f', d, o + 0x88)
        r['Col_start'] = list(d[o + 0x9C:o + 0xA0])
        r['Col_d'] = struct.unpack_from('>4f', d, o + 0xA0)
        (r['Col_max_cnt'], r['Col_start_cnt'], r['Pos_start_cnt'], r['Size_start_cnt'], r['Life_max'],
         r['Life_time']) = struct.unpack_from('>6H', d, o + 0xB0)
        r['Ptn_no'], r['Anm_rate'] = d[o + 0xBC], struct.unpack_from('>b', d, o + 0xBD)[0]
        r['Anm_cnt'], = struct.unpack_from('>H', d, o + 0xBE)
        (r['Release_time'], r['Groupe_no'], r['Blend_type'], r['Shimmer_type'], r['Shimmer_pow'],
         r['MaskTex_id'], r['Del_far'], r['Del_near']) = d[o + 0xC0:o + 0xC8]
        r['Work8'] = list(d[o + 0xC8:o + 0xCC])
        r['Work32'] = list(struct.unpack_from('>3I', d, o + 0xCC))
        r['Vec0'] = struct.unpack_from('>3f', d, o + 0xD8)
        r['Vec1'] = struct.unpack_from('>3f', d, o + 0xE4)
        r['Vec2'] = struct.unpack_from('>3f', d, o + 0xF0)
        r['WorkSp8'] = list(d[o + 0xFC:o + 0x100])
        r['Espgen_work8_4'] = list(d[o + 0x104:o + 0x108])
        r['Kind'], r['Espgen_id'], r['Espgen_type'], r['Espgen_flg'] = d[o + 0x108:o + 0x10C]
        r['Espgen_work8'] = list(struct.unpack_from('>4b', d, o + 0x10C))
        r['Espgen_work16'] = list(struct.unpack_from('>4h', d, o + 0x110))
        r['Espgen_vec0'] = struct.unpack_from('>3f', d, o + 0x118)
        r['Espgen_work8_2'] = list(struct.unpack_from('>4b', d, o + 0x124))
        r['Espgen_work8_3'] = list(d[o + 0x128:o + 0x12C])
        return r


# ---------------------------------------------------------------------------------------------------
# simulation helpers (derived values)

def simulate(r, max_frames=120):
    """Frame-by-frame size_mul / alpha / distance like cEsp::CommonMove + ColorUpdate (no anim)."""
    sm, sp = 1.0, r['Size_plus']
    a = float(r['Col_start'][3])
    spd = list(r['Speed'])
    pos = [0.0, 0.0, 0.0]
    out = []
    life = r['Life_max']
    cmax, cst = r['Col_max_cnt'], r['Col_start_cnt']
    for t in range(max_frames):
        # move at life_time t
        if r['Pos_start_cnt'] == 0 or r['Pos_start_cnt'] <= t:
            pos = [pos[k] + spd[k] for k in range(3)]
            spd = [(spd[k] + r['Speed_plus'][k]) * r['D_speed'] for k in range(3)]
        if r['Size_start_cnt'] == 0 or r['Size_start_cnt'] <= t:
            sm += sp
            sp *= r['D_size_plus']
            if sm <= 0:
                out.append((t, 'dies: size<=0'))
                break
        if cmax < t:
            if cmax + cst <= t:
                a *= r['Col_d'][3]
                a = min(a, 255.0)
                if a < 4:
                    out.append((t, 'dies: alpha<4'))
                    break
        elif cmax != 0:
            a = r['Col_start'][3] * t / cmax
        if life != 0 and life <= t:
            out.append((t, 'dies: Life_max'))
            break
        out.append((t, sm, a, tuple(pos)))
    return out


def anim_life(r, tex):
    """Frames until AnmMove ends a non-looping animation (esp00/02 die then)."""
    if tex is None:
        return None
    anm = tex['anm']
    if anm['Loop'] != 0:
        return None
    rate = (r['Anm_rate'] + 0x20) & 0xFF
    if rate == 0:
        return None
    cnt, ptn, t = r['Anm_cnt'], r['Ptn_no'], 0
    while t < 1000:
        t += 1
        time = 1 if anm['Data_num'] == 0 else anm['times'][ptn]
        cnt += rate
        while (cnt >> 5) > time:
            ptn += 1
            cnt -= time << 5
            if ptn >= anm['Frames']:
                return t
            time = 1 if anm['Data_num'] == 0 else anm['times'][ptn]
    return None


def fmt_v(v):
    return '(' + ', '.join('%g' % round(x, 4) for x in v) + ')'


def tool_str(f):
    return ','.join(n for b, n in TOOL_BITS.items() if f & (1 << b)) or '-'


def describe_record(i, r, texlookup):
    L = []
    kind = 'espgen%02X emitter' % r['Espgen_id'] if r['Kind'] == 1 else ESP_NAMES.get(r['Id'], 'esp%02X' % r['Id'])
    L.append('  rec %d  t=%d  Kind %d  Id 0x%02X [%s]  Tex 0x%02X  Parts %d  Tool_flg %#x (%s)' % (
        i, r['Set_time'], r['Kind'], r['Id'], kind, r['Tex_id'], r['Parts_no'], r['Tool_flg'], tool_str(r['Tool_flg'])))
    if r['Kind'] == 1:
        w8, w16 = r['Espgen_work8'], r['Espgen_work16']
        L.append('     EMITTER: life %d frames, wait %d, burst %d particles/emission, D-curves(scale,spd,col,wait)=%s, '
                 'flg %#x (bit0: spread burst over 360deg about Y), waitRnd %d' % (
                     w16[0], w8[0], w8[1] + 1, r['Espgen_work8_2'], r['Espgen_flg'], r['Espgen_work8_3'][0]))
        L.append('     emitted particle = esp 0x%02X (%s) with the fields below:' % (r['Id'], ESP_NAMES.get(r['Id'], '?')))
    L.append('     pos %s +-%s   speed %s +-%s  (mm/frame, part-local)  D_speed %g' % (
        fmt_v(r['Pos']), fmt_v(r['R_pos']), fmt_v(r['Speed']), fmt_v(r['R_speed']), r['D_speed']))
    L.append('     accel %s +-%s   ang(deg) %s +-%s   angVel(deg/f) %s +-%s' % (
        fmt_v(r['Speed_plus']), fmt_v(r['R_speed_plus']), fmt_v(r['Ang']), fmt_v(r['R_ang']),
        fmt_v(r['Ang_plus']), fmt_v(r['R_ang_plus'])))
    L.append('     size %g x %g +-%g (mm, full quad)  Size_plus %g/frame  D_size_plus %g' % (
        r['Size_base_x'], r['Size_base_y'], r['R_size_base'], r['Size_plus'], r['D_size_plus']))
    L.append('     colour RGBA %s  per-frame mul %s  fadeIn(Col_max_cnt) %d  hold(Col_start_cnt) %d' % (
        r['Col_start'], fmt_v(r['Col_d']), r['Col_max_cnt'], r['Col_start_cnt']))
    L.append('     Life_max %d  start frame %d  Pos_start %d  Size_start %d  Release_time %d  anim ptn %d rate %d(/32 per frame)' % (
        r['Life_max'], r['Life_time'], r['Pos_start_cnt'], r['Size_start_cnt'], r['Release_time'], r['Ptn_no'],
        (r['Anm_rate'] + 0x20) & 0xFF))
    L.append('     blend %d = %s   shimmer %d/%d  mask 0x%02X  del far/near %d/%d  Work8 %s  WorkSp8 %s  Vec0 %s Vec1 %s' % (
        r['Blend_type'], BLEND.get(r['Blend_type'], '?'), r['Shimmer_type'], r['Shimmer_pow'], r['MaskTex_id'],
        r['Del_far'], r['Del_near'], r['Work8'], r['WorkSp8'], fmt_v(r['Vec0']), fmt_v(r['Vec1'])))
    if r['Id'] == 0x11:
        k, cut, no, typ = r['Work8']
        if k == 2:
            k, cut, no, typ = 0, 8, 0, 1
        L.append('     LIGHT: cLightMgr.create(lit %s, cut %d, light %d), type %d (%s); radius = size*size_mul*10 = %g mm' % (
            'core' if k == 0 else 'room', cut, no, typ, 'follows sprite pos/colour' if typ == 1 else 'static',
            r['Size_base_x'] * 10))
    if r['Id'] == 0x03:
        n = r['Work8'][0]
        mp = 10 if n == 10 else max(2, min(6, 4 - n))
        L.append('     LINE: %s, GX line width = int(size*size_mul/33.33) = %d (1/6 px units), wall stop %d' % (
            'camera diamond quad' if mp == 10 else '%d-point line strip (last positions)' % mp,
            int(r['Size_base_x'] / (100.0 / 3.0)), r['Work8'][1]))
    tex = texlookup(r['Tex_id'])
    if r['Kind'] == 0 and r['Id'] not in NO_TEX_IDS:
        al = anim_life(r, tex)
        if tex:
            a = tex['anm']
            L.append('     texture 0x%02X: %d frame(s) %s, loop %d%s' % (
                r['Tex_id'], a['Frames'], TF_NAMES.get(tex['frames'][0]['fmt']), a['Loop'],
                ('  -> non-looping anim: killed on move #%d, i.e. visible %d frame(s) showing patterns 0..%d'
                 % (al, al - 1, al - 2)) if al else ''))
        else:
            L.append('     texture 0x%02X: not in this file (core EFF)' % r['Tex_id'])
    sim = simulate(r)
    end = sim[-1]
    keys = [s for s in sim if len(s) == 4]
    if keys:
        sample = [keys[k] for k in sorted(set([0, 1, 2, 4, 8, 12, 16, 24, len(keys) - 1])) if k < len(keys)]
        L.append('     sim: ' + '  '.join('t%d size*%.2f a%.0f' % (s[0], s[1], s[2]) for s in sample) +
                 ('   [%s at t=%d]' % (end[1], end[0]) if len(end) == 2 else ''))
    return L


def dump(eff, core=None, only=None, out=sys.stdout):
    def texlookup(tid):
        if tid in eff.tex:
            return eff.tex[tid]
        if core and tid in core.tex:
            return core.tex[tid]
        return None
    p = lambda s='': print(s, file=out)
    p('== %s: EFF v0xB, %d textures, %d est, %d sst' % (eff.name, len(eff.tex), len(eff.est), len(eff.sst)))
    for tid, t in sorted(eff.tex.items()):
        a = t['anm']
        fr = t['frames'][0]
        p('  tex 0x%02X: %d frame(s) %dx%d %s%s  anm W%d H%d Cx%d Cy%d Loop%d Data_num%d' % (
            tid, len(t['frames']), fr['w'], fr['h'], TF_NAMES.get(fr['fmt'], fr['fmt']),
            ('/pal ' + TL_NAMES.get(fr['palfmt'], '?')) if fr['pal'] else '', a['W'], a['H'], a['Cx'], a['Cy'],
            a['Loop'], a['Data_num']))
    for no, s in sorted(eff.est.items()):
        if only is not None and no not in only:
            continue
        p()
        p('  est 0x%02X: %d records, head parts 0x%02X pos %s rot %s flags %#x core_flg %#x ver %#x' % (
            no, len(s['records']), s['parts'], fmt_v(s['pos']), fmt_v(s['rot_deg']), s['flags'], s['core_flg'], s['ver']))
        for i, r in enumerate(s['records']):
            for line in describe_record(i, r, texlookup):
                p(line)


def export_pngs(eff, outdir, prefix, ids=None):
    os.makedirs(outdir, exist_ok=True)
    written = []
    for tid, t in sorted(eff.tex.items()):
        if ids is not None and tid not in ids:
            continue
        for k, fr in enumerate(t['frames']):
            img = decode_tex(fr['fmt'], fr['w'], fr['h'], fr['data'], fr['pal'])
            path = os.path.join(outdir, '%s_tex%02X_f%d.png' % (prefix, tid, k))
            with open(path, 'wb') as fh:
                fh.write(png_bytes(img))
            written.append(path)
    return written


def load_effs(path, entry=None):
    with open(path, 'rb') as fh:
        head = fh.read(4)
    if head == b'\0\0\0\x0b':
        return [Eff(open(path, 'rb').read(), os.path.basename(path))]
    sys.path.insert(0, RE4_TOOLS)
    from motion import archive
    a = archive.Archive(path)
    out = []
    i = 0
    while True:
        try:
            e = a.entry(i)
        except Exception:
            break
        if (entry is None and e.tag == 'EFF') or entry == i:
            out.append(Eff(e.data, '%s#%d' % (os.path.basename(path), i)))
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file')
    ap.add_argument('--entry', type=int)
    ap.add_argument('--est', type=lambda s: int(s, 0), nargs='*', help='only these est ids')
    ap.add_argument('--png', help='export textures as PNG into this directory')
    ap.add_argument('--core', help='core.das (resolves core textures referenced by the records)')
    ap.add_argument('--all-tex', action='store_true', help='export every texture, not only referenced ones')
    ap.add_argument('--json', help='write the decoded est tables as JSON')
    args = ap.parse_args()

    core = None
    if args.core:
        core = load_effs(args.core, 1)[0]
    effs = load_effs(args.file, args.entry)
    for eff in effs:
        dump(eff, core, set(args.est) if args.est else None)
        if args.png:
            prefix = os.path.splitext(eff.name.replace('#', '_e'))[0].replace('.', '_')
            used = set()
            for no, s in eff.est.items():
                if args.est and no not in args.est:
                    continue
                for r in s['records']:
                    if r['Id'] not in NO_TEX_IDS:
                        used.add(r['Tex_id'])
                    if r['Tool_flg'] & 0x4000:
                        used.add(r['MaskTex_id'])
            local = None if args.all_tex else used
            w = export_pngs(eff, args.png, prefix, local)
            if core is not None and core is not eff:
                miss = {t for t in used if t not in eff.tex and t in core.tex}
                w += export_pngs(core, args.png, 'core', miss)
            print('\n  exported %d PNG(s) to %s' % (len(w), args.png))
            for p in w:
                print('    ' + p)
        if args.json:
            js = {'name': eff.name,
                  'textures': {('0x%02X' % k): v['anm'] for k, v in eff.tex.items()},
                  'est': {('0x%02X' % k): v for k, v in eff.est.items() if not args.est or k in args.est}}
            path = args.json if len(effs) == 1 else args.json.replace('.json', '_%s.json' % eff.name.replace('#', '_'))
            with open(path, 'w') as fh:
                json.dump(js, fh, indent=1, default=list)
            print('  json -> ' + path)


if __name__ == '__main__':
    main()
