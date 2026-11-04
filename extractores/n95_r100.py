#!/usr/bin/env python3
"""
n95_r100.py: el PERFIL N95 de la demo r100 (un N95 8GB: 128 MB de RAM, la app con un heap de 96 MB como mucho, la
pantalla de 320 x 240). Pedido del dueno: TODAS las texturas a la mitad de su definicion original y el audio igual.
Se aplica al .w3d ya armado (y a su libreria de personajes) mirando la version ORIGINAL (la de PC: --full / la
libreria completa) para no achicar dos veces lo que el armado del N95 ya trae a la mitad (el mapa, los "_mitad"):

  texturas   cada una a la mitad del ancho y el alto de la original, y ninguna de mas de 512 px de lado (las UV
             van de 0 a 1: el dibujo no cambia, solo el detalle). El alfa de un bit sigue de un bit. Salvo las
             fuentes bitmap (sus glifos estan en pixeles del PNG). Y en el proyecto "texturas16" (el motor sube en
             16 bits lo opaco y lo de alfa de un bit) y "mallasSoloGPU" (las mallas del mundo, que solo dibujan
             rutinas, sueltan su RAM al subir el VBO)
  sonidos    mono, a la mitad de la frecuencia del original (un filtro pasabajos antes). Los puntos de loop (chunk
             'smpl') se escalan con el cambio

  python3 n95_r100.py ENTRADA.w3d SALIDA.w3d [--original ORIGINAL.w3d ...] [--proyecto]
"""
import io
import json
import os
import re
import struct
import sys
import zipfile

import numpy as np
from PIL import Image

FRACCION = 0.5     # la definicion de la original que queda
TOPE = 512         # y ningun lado de mas de 512 px: decodificar uno de 1024 x 512 en el telefono pide ~7 MB de golpe


def original_de(nombre, originales):
    """el tamano / frecuencia de la ORIGINAL (la del .w3d de PC); los "_mitad" del armado del N95 son la misma imagen"""
    if nombre in originales:
        return originales[nombre]
    sin = nombre.replace('_mitad', '')
    return originales.get(sin)


def tamano_n95(nombre, w, h, originales=None):
    """el tamano para el telefono (None = queda como esta)"""
    if 'fuente' in nombre.split('/')[-1]:
        return None
    ref = original_de(nombre, originales or {}) or (w, h)
    nw, nh = max(1, int(round(ref[0] * FRACCION))), max(1, int(round(ref[1] * FRACCION)))
    if max(nw, nh) > TOPE:
        k = TOPE / float(max(nw, nh))
        nw, nh = max(1, int(round(nw * k))), max(1, int(round(nh * k)))
    if nw >= w and nh >= h:
        return None
    return (min(nw, w), min(nh, h))


def achicar_png(nombre, datos, originales=None):
    im = Image.open(io.BytesIO(datos))
    t = tamano_n95(nombre, im.width, im.height, originales)
    if not t:
        return datos, None
    modo = 'RGBA' if im.mode in ('RGBA', 'LA', 'P') else 'RGB'
    im = im.convert(modo)
    if modo == 'RGBA':
        a = np.asarray(im)[:, :, 3]
        binario = bool(np.all((a == 0) | (a == 255)))
        # el COLOR pesado por el alfa (un texel transparente no oscurece el borde) y, si el alfa era de un bit,
        # sigue de un bit (asi entra en 16 bits)
        px = np.asarray(im).astype(np.float32)
        pre = px[:, :, :3] * (px[:, :, 3:4] / 255.0)
        rgb_pre = np.asarray(Image.fromarray(np.clip(pre, 0, 255).astype(np.uint8), 'RGB').resize(t, Image.LANCZOS)).astype(np.float32)
        ra = np.asarray(Image.fromarray(px[:, :, 3].astype(np.uint8), 'L').resize(t, Image.LANCZOS)).astype(np.float32)
        rgb = np.where(ra[:, :, None] > 0, rgb_pre * 255.0 / np.maximum(ra[:, :, None], 1), rgb_pre)
        a2 = np.where(ra >= 128, 255, 0) if binario else ra
        out = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.clip(a2, 0, 255)]).astype(np.uint8), 'RGBA')
    else:
        out = im.resize(t, Image.LANCZOS)
    b = io.BytesIO()
    out.save(b, 'PNG', optimize=True)
    return b.getvalue(), (im.size, t)


# ------------------------------------------------------------------------------------------------- audio
def _chunks(d):
    out, o = [], 12
    while o + 8 <= len(d):
        cid, n = d[o:o + 4], struct.unpack_from('<I', d, o + 4)[0]
        out.append((cid, d[o + 8:o + 8 + n]))
        o += 8 + n + (n & 1)
    return out


def remuestrear(x, sr, hz):
    """x: float (n,) mono; filtro pasabajos (sinc con ventana) y remuestreo lineal sobre la senal filtrada"""
    if sr == hz:
        return x
    if hz < sr:
        fc = 0.5 * hz / sr * 0.95
        n = 63
        k = np.arange(n) - (n - 1) / 2
        h = 2 * fc * np.sinc(2 * fc * k) * np.blackman(n)
        h /= h.sum()
        x = np.convolve(x, h, mode='same')
    m = int(round(len(x) * hz / float(sr)))
    t = np.arange(m) * (sr / float(hz))
    return np.interp(t, np.arange(len(x)), x)


def achicar_wav(d, rate_original=None):
    if d[:4] != b'RIFF' or d[8:12] != b'WAVE':
        return d, None
    ch = dict((cid, body) for cid, body in _chunks(d))
    fmt = ch.get(b'fmt ')
    if not fmt or b'data' not in ch:
        return d, None
    tag, canales, sr, _, _, bits = struct.unpack_from('<HHIIHH', fmt, 0)
    nsr = int(round((rate_original or sr) * FRACCION))
    if tag != 1 or bits != 16 or (nsr >= sr and canales == 1):
        return d, None
    nsr = min(nsr, sr)
    x = np.frombuffer(ch[b'data'], '<i2').astype(np.float32)
    x = x.reshape(-1, canales).mean(1)
    y = remuestrear(x, sr, nsr)
    data = np.clip(np.round(y), -32768, 32767).astype('<i2').tobytes()
    partes = []
    for cid, body in _chunks(d):
        if cid == b'fmt ':
            body = struct.pack('<HHIIHH', 1, 1, nsr, nsr * 2, 2, 16) + body[16:]
        elif cid == b'data':
            body = data
        elif cid == b'smpl' and len(body) >= 36:
            # el periodo de muestra y los loops (inicio / fin en muestras) al nuevo sr
            b2 = bytearray(body)
            struct.pack_into('<I', b2, 8, int(round(1e9 / nsr)))
            nl = struct.unpack_from('<I', b2, 28)[0]
            for i in range(nl):
                o = 36 + 24 * i
                if o + 24 <= len(b2):
                    for c in (8, 12):
                        v = struct.unpack_from('<I', b2, o + c)[0]
                        struct.pack_into('<I', b2, o + c, int(round(v * nsr / float(sr))))
            body = bytes(b2)
        partes.append(cid + struct.pack('<I', len(body)) + body + (b'\0' if len(body) & 1 else b''))
    cuerpo = b'WAVE' + b''.join(partes)
    return b'RIFF' + struct.pack('<I', len(cuerpo)) + cuerpo, ((sr, canales), (nsr, 1))


def leer_originales(rutas):
    """{entrada: (w, h)} de las texturas y {entrada: Hz} de los sonidos de los .w3d originales (los de PC)"""
    tex, son = {}, {}
    for r in rutas or []:
        if not r or not os.path.isfile(r):
            continue
        with zipfile.ZipFile(r) as z:
            for n in z.namelist():
                if n.startswith('texturas/') and n.endswith('.png'):
                    with z.open(n) as f:
                        tex.setdefault(n, Image.open(f).size)
                elif n.endswith('.wav'):
                    with z.open(n) as f:
                        cab = f.read(64)
                    if cab[:4] == b'RIFF':
                        o = 12
                        while o + 8 <= len(cab):
                            if cab[o:o + 4] == b'fmt ':
                                son.setdefault(n, struct.unpack_from('<I', cab, o + 12)[0])
                                break
                            o += 8 + struct.unpack_from('<I', cab, o + 4)[0]
    return tex, son


def convertir(entrada, salida, proyecto=False, originales=None, log=print):
    tex_o, son_o = leer_originales(originales)
    with zipfile.ZipFile(entrada) as z:
        infos = z.infolist()
        datos = dict((i.filename, z.read(i.filename)) for i in infos)
    antes_t = antes_s = despues_t = despues_s = 0
    nt = ns = 0
    for n in list(datos):
        if n.endswith('.png') and n.startswith('texturas/'):
            antes_t += len(datos[n])
            datos[n], cambio = achicar_png(n, datos[n], tex_o)
            despues_t += len(datos[n])
            nt += bool(cambio)
        elif n.endswith('.wav'):
            antes_s += len(datos[n])
            datos[n], cambio = achicar_wav(datos[n], son_o.get(n))
            despues_s += len(datos[n])
            ns += bool(cambio)
    if proyecto:
        pj = json.loads(datos['proyecto.json'])
        pj['texturas16'] = True
        # las mallas que solo dibujan las rutinas (el mundo horneado) sueltan su RAM al subir el VBO (en el N95 el
        # VBO del driver es la misma RAM: si no, estaban dos veces)
        pj['mallasSoloGPU'] = True
        datos['proyecto.json'] = json.dumps(pj, ensure_ascii=False).encode('utf-8')
    tmp = salida + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        for i in infos:
            zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            zi.compress_type = i.compress_type
            zi.external_attr = i.external_attr
            z.writestr(zi, datos[i.filename])
    os.replace(tmp, salida)
    log('   n95: %d texturas a la mitad de la original (%.1f -> %.1f MB de PNG), %d sonidos mono a la mitad de su '
        'frecuencia (%.1f -> %.1f MB)%s' % (nt, antes_t / 1e6, despues_t / 1e6, ns, antes_s / 1e6, despues_s / 1e6,
                                            ', texturas16 y mallasSoloGPU' if proyecto else ''))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('entrada'); ap.add_argument('salida')
    ap.add_argument('--original', action='append', default=[])
    ap.add_argument('--proyecto', action='store_true')
    a = ap.parse_args()
    convertir(a.entrada, a.salida, proyecto=a.proyecto, originales=a.original)
