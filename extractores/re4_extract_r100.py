#!/usr/bin/env python3
"""
Extrae el escenario r100 de RE4 (GameCube): el camino del bosque y la casa del primer ganado, para Whisk3D.

  out/r100/r100.glb       las piezas del mapa (un nodo por "work" de SMD, en el orden de r100.json) + la colision
  out/r100/tex/*.png      las texturas del TPL comun (a la mitad, N95), sueltas: los mapas REPITEN el UV (sin atlas)
  out/r100/r100.json      bloques (streaming), areas de bloque, piezas, disparadores AEV, puerta, spawn, eventos

COMO ARMA EL JUEGO EL MAPA (src/game/scroll.cpp, block.cpp; ver el informe en el README de la carpeta):
  * SMD #0 del .das (13 works): siempre residente (SmdSetup(-1)).
  * r100_0N.dat: los 5 BLOQUES (BlockCreate). Cada uno trae su SMD con works y bins propios.
  * SMD #1 del .das = el COMUN: bins compartidos (work flag 0x10 = bin del comun) y EL UNICO TPL con texturas
    (69): todos los tex_id de todos los bins indexan ese TPL (addTplAddr). Sus 18 works NO se instancian.
  * transform de un work: M = T(pos) Rz Ry Rx S(escala) (cCoord::matUpdate), radianes, milimetros, Y arriba.
  * SMX: registro por id de work: CullMode (0 = GX_CULL_FRONT, 1 = BACK, 2 = NONE), color (tinte; su alpha es
    el blend mode), UV scroll.
  * VISIBILIDAD: no hay PVS ni portales. BLK = areas (prismas XZ) -> bloque; se dibuja el bloque del area donde
    esta Leon + sus vecinos por link (block.cpp cBlock::check). Adentro de eso: frustum por esfera y la niebla.
  * COLISION: SAT archivo 0: triangulos ordenados pisos, rampas, paredes (atari.cpp).

Uso:  python3 re4_extract_r100.py [--full]   (--full: texturas a tamanio original)
"""
import argparse
import json
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 're4', 'tools'))
from motion import archive, meshbin, gxtex, gltf  # noqa: E402

meshbin._zero_pad = lambda *a: None   # los bins de mapa traen 1 registro de peso que no cumple el padding estricto

EXT = os.path.join(HERE, 'extracted')
DAS = os.path.join(EXT, 'St1', 'r100.das')
BLOQUES = [os.path.join(EXT, 'St1', 'r100_%02d.dat' % i) for i in range(5)]
ESCALA = 0.001        # mm -> m
FLAG_BIN_COMUN = 0x10

# ---- RGBA8 (formato GX 6): falta en gxtex (una sola textura del mapa lo usa) ----
FMT_RGBA8 = 6
_base_size = gxtex.base_size
_decode = gxtex.decode


def _base_size6(fmt, w, h):
    if fmt == FMT_RGBA8:
        return ((w + 3) // 4) * ((h + 3) // 4) * 64
    return _base_size(fmt, w, h)


def _decode6(fmt, w, h, data, crop=True):
    if fmt != FMT_RGBA8:
        return _decode(fmt, w, h, data, crop)
    tw, th = (w + 3) // 4, (h + 3) // 4
    img = np.zeros((th * 4, tw * 4, 4), np.uint8)
    p = 0
    for ty in range(th):
        for tx in range(tw):
            ar = np.frombuffer(data, np.uint8, 32, p).reshape(4, 4, 2)          # A R por pixel
            gb = np.frombuffer(data, np.uint8, 32, p + 32).reshape(4, 4, 2)     # G B por pixel
            blk = img[ty * 4:ty * 4 + 4, tx * 4:tx * 4 + 4]
            blk[..., 0] = ar[..., 1]
            blk[..., 1] = gb[..., 0]
            blk[..., 2] = gb[..., 1]
            blk[..., 3] = ar[..., 0]
            p += 64
    return img[:h, :w] if crop else img


gxtex.base_size = _base_size6
gxtex.decode = _decode6


# ---------------------------------------------------------------------------
#  SMD / SMX
# ---------------------------------------------------------------------------
def tabla(d, t):
    """offsets (relativos a la tabla) de una tabla de bins/tpls: se cuentan los no-cero (la primera / 4 sobra)."""
    n = struct.unpack('>I', d[t:t + 4])[0] // 4
    o = list(struct.unpack('>%dI' % n, d[t:t + 4 * n]))
    while o and o[-1] == 0:
        o.pop()
    return o


class Smd:
    def __init__(self, d, nombre):
        self.d, self.nombre = d, nombre
        ver, flag, n, bt, tt, mt = struct.unpack('>BBHIII', d[:16])
        w0 = 0x10
        if flag & 1:
            ng, = struct.unpack('>I', d[16:20])
            w0 = 0x14 + ng * 4
        self.bt, self.tt, self.mt = bt, tt, mt
        self.bins = tabla(d, bt)
        self.tpls = tabla(d, tt)
        self.works = []
        for i in range(n):
            w = d[w0 + 0x48 * i:w0 + 0x48 * (i + 1)]
            self.works.append(dict(pos=struct.unpack('>3f', w[0:12]), rot=struct.unpack('>3f', w[12:24]),
                                   sc=struct.unpack('>3f', w[24:36]), bin=w[0x24], tpl=w[0x25], id=w[0x27],
                                   flags=struct.unpack('>I', w[0x44:0x48])[0]))
        self._mallas = {}

    def malla(self, i):
        if i not in self._mallas:
            a = self.bt + self.bins[i]
            e = self.bt + self.bins[i + 1] if i + 1 < len(self.bins) else self.tt
            self._mallas[i] = meshbin.parse(self.d[a:e])
        return self._mallas[i]

    def texturas(self, i=0):
        a = self.tt + self.tpls[i]
        e = self.tt + self.tpls[i + 1] if i + 1 < len(self.tpls) else self.mt
        return gxtex.parse_tpl(self.d[a:e])


def smd_de(path):
    a = archive.Archive(path)
    return [Smd(e.data, '%s:%d' % (a.name, e.index)) for e in a.entries() if e.tag == 'SMD']


def smx(d):
    n = d[1]
    out = {}
    for i in range(n):
        r = d[0x10 + 0x90 * i:0x10 + 0x90 * (i + 1)]
        out[r[0]] = dict(tipo=r[1], ot=r[2], cull=r[3], flags=struct.unpack('>I', r[8:12])[0],
                         mascara=struct.unpack('>I', r[4:8])[0],   # SelectMask: bit i = la luz i NO lo ilumina
                         color=struct.unpack('>I', r[12:16])[0], scroll=struct.unpack('>2f', r[0x88:0x90]))
    return out


# ---------------------------------------------------------------------------
#  BLK / AEV / ETS / SAT
# ---------------------------------------------------------------------------
def area_data(b):
    """AreaData (0x30): u8 be_flag, u8 type, u16, cuerpo: floor, height, radius, 4 puntos XZ (tipo 1 = XZ4) o
    x,z (tipo 2 = cilindro). En metros. 'alto' = cuanto sube desde el piso."""
    tipo = b[1]
    piso, alto, radio = struct.unpack('>fff', b[4:16])
    a = dict(tipo=tipo, piso=round(piso * ESCALA, 4), alto=round(alto * ESCALA, 4))
    if tipo == 2:
        x, z = struct.unpack('>ff', b[16:24])
        a.update(centro=[round(x * ESCALA, 4), round(z * ESCALA, 4)], radio=round(radio * ESCALA, 4))
    else:
        pts = [struct.unpack('>ff', b[16 + 8 * k:24 + 8 * k]) for k in range(4)]
        a['pts'] = [[round(x * ESCALA, 4), round(z * ESCALA, 4)] for x, z in pts]
    return a


def blk(d):
    """BLK -> links, areas y, por area, el conjunto VISIBLE ya resuelto (cBlock::checkBlockConnect: el bloque del
    area + sus vecinos por link en los dos sentidos = MRAM; lo demas va a ARAM o se borra: setTrans(0), no se ve)."""
    assert d[:3] == b'BLK', d[:4]
    nb = d[7]
    na, nc = struct.unpack('>HH', d[8:12])
    o_link, o_area, o_con = struct.unpack('>III', d[12:24])
    links = []
    for i in range(nb):
        r = d[o_link + 0xC * i:o_link + 0xC * (i + 1)]
        links.append(dict(existe=bool(r[0] & 1), link=[x for x in struct.unpack('>8b', r[4:12]) if x >= 0]))

    def vecinos(bl):
        out = set(links[bl]['link'])
        out |= {i for i, l in enumerate(links) if bl in l['link']}
        return out
    conexiones = []
    for i in range(nc):
        r = d[o_con + 0x14 * i:o_con + 0x14 * (i + 1)]
        if not r[0] & 1:
            conexiones.append(None)
            continue
        visibles = {r[1]} | vecinos(r[1])
        conexiones.append(dict(bloque=r[1], visibles=sorted(b for b in visibles if links[b]['existe'])))
    areas = []
    for i in range(na):
        r = d[o_area + 0x38 * i:o_area + 0x38 * (i + 1)]
        a = area_data(r[4:0x34])
        a.update(activa=bool(r[0x34] & 1), area=struct.unpack('>b', r[0x36:0x37])[0], prioridad=r[0x37])
        c = conexiones[a['area']] if 0 <= a['area'] < len(conexiones) else None
        a['visibles'] = c['visibles'] if c else []
        areas.append(a)
    return dict(links=links, areas=areas, conexiones=conexiones)


def aev(d):
    assert d[:3] == b'AEV', d[:4]
    n, = struct.unpack('>H', d[6:8])
    out = []
    for i in range(n):
        r = d[0x10 + 0x9C * i:0x10 + 0x9C * (i + 1)]
        a = area_data(r[4:0x34])
        a.update(tipo_evento=r[0x35], no=r[0x36])
        out.append(a)
    return out


def ets(d):
    n, = struct.unpack('>H', d[:2])
    out = []
    for i in range(n):
        r = d[0x10 + 0x28 * i:0x10 + 0x28 * (i + 1)]
        idn, no = struct.unpack('>HH', r[:4])
        out.append(dict(id=idn, no=no, sc=struct.unpack('>3f', r[4:16]), rot=struct.unpack('>3f', r[16:28]),
                        pos=struct.unpack('>3f', r[28:40])))
    return out


def sat(d):
    """cSatFile 0 -> (vertices en m, [(a, b, c, attr, clase)]) con clase 0 piso / 1 rampa / 2 pared."""
    o, = struct.unpack('>I', d[4:8])
    v, _, nv, nn, ne, _, npol, nf, ns, nw, _ = struct.unpack('>BBHHHHHHHHH', d[o:o + 0x14])
    vt = o + 0x14
    V = [tuple(c * ESCALA for c in struct.unpack_from('>3f', d, vt + 12 * i)) for i in range(nv)]
    pp = vt + 12 * (nv + nn + ne)
    tris = []
    for i in range(npol):
        a, b, c = struct.unpack_from('>3H', d, pp + 0x14 * i)
        attr, = struct.unpack_from('>I', d, pp + 0x14 * i + 0x10)
        clase = 0 if i < nf else (1 if i < nf + ns else 2)
        tris.append((a, b, c, attr, clase))
    return V, tris


def lit(d, corte=0):
    """cLit: un corte de luces (cLightEnv 0x104 + nLight x cLightWork 0x12C). Colores GX 0..255; el juego multiplica
    la salida del TEV por 2^tev_scale. xD = tipo de luz (5 = paralela/direccional; 2/3 puntual; 6 spot)."""
    cn, = struct.unpack('>H', d[:2])
    offs = struct.unpack('>%dI' % cn, d[4:4 + 4 * cn])
    o = offs[corte]
    col = lambda b: [round(c / 255.0, 4) for c in b[:3]]
    nl, = struct.unpack('>I', d[o + 4:o + 8])
    ft, fs, fe = struct.unpack('>iff', d[o + 8:o + 20])
    env = dict(ambiente=col(d[o:o + 4]), ambienteEm=col(d[o + 0xFC:o + 0x100]),
               niebla=dict(tipo=ft, inicio=round(fs * ESCALA, 3), fin=round(fe * ESCALA, 3), color=col(d[o + 20:o + 24])),
               far_play_ratio=round(struct.unpack('>f', d[o + 0x44:o + 0x48])[0], 3),
               tev_scale=list(d[o + 0x40:o + 0x42]), luces=[])
    for k in range(nl):
        w = d[o + 0x104 + 0x12C * k:o + 0x104 + 0x12C * (k + 1)]
        if not (w[0] & 2):             # be_flag bit1: encendida (5 = definida pero apagada)
            continue
        sp = w[0x2C:0x6C]
        env['luces'].append(dict(
            n=k, tipo=w[1], clase=w[2], xf=w[3], pos=[round(c * ESCALA, 4) for c in struct.unpack('>3f', w[4:16])],
            radio=round(struct.unpack('>f', w[16:20])[0] * ESCALA, 3), color=col(w[20:24]),
            intensidad=round(struct.unpack('>f', w[24:28])[0], 3),
            dir=[round(c, 4) for c in struct.unpack('>3f', sp[0:12])],
            a=[round(struct.unpack('>f', sp[0x0C + 4 * i:0x10 + 4 * i])[0], 5) for i in range(3)],   # A0 corte del cono
            k=[struct.unpack('>f', sp[0x18 + 4 * i:0x1C + 4 * i])[0] for i in range(3)],
            padre=w[0x1C]))                  # ParentType: != 0 = colgada de un personaje (no ilumina el mapa)
    return env


# ---------------------------------------------------------------------------
def quat_zyx(rx, ry, rz):
    """q = qz * qy * qx (M = Rz Ry Rx), glTF (x, y, z, w)."""
    def q(ax, ang):
        s = math.sin(ang / 2)
        return [ax[0] * s, ax[1] * s, ax[2] * s, math.cos(ang / 2)]

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]
    return mul(mul(q((0, 0, 1), rz), q((0, 1, 0), ry)), q((1, 0, 0), rx))


# ---------------------------------------------------------------------------
#  ILUMINACION HORNEADA: la cuenta de GX (trans_lit.cpp) por vertice, con las luces del corte 0 del LIT
# ---------------------------------------------------------------------------
TEV_EN_EL_JUEGO = False


class Luces:
    """canal de color de GX: amb + suma(color * atenuacion * max(N.L, 0)), clampeado a [0, 1]; despues el TEV lo
    multiplica por la textura y por 2^tev_scale. El brillo 'br' de cada luz se decide POR OBJETO (obj_pos /
    obj_size = centro y radio de la pieza), como lightSet*; N.L y la atenuacion por distancia, por vertice."""

    def __init__(self, lit):
        # el MAPA usa AmbientScr (lit['ambiente']; casi negro), no AmbientEm (ese es de personajes). Y solo lo tocan
        # las luces con xF & 0x10 (EnableMask de SMD, scroll.cpp): las demas son para personajes.
        self.amb = np.array(lit['ambiente'], np.float32)
        self.escala = 2.0 ** (lit['tev_scale'][0] if lit['tev_scale'] else 0)
        self.luces = [l for l in lit['luces'] if l.get('padre', 0) == 0 and (l.get('xf', 0x10) & 0x10)]

    def color(self, P, N, centro, radio, mascara, amb=None, tinte=None):
        """P, N: (k, 3) en metros / normalizadas, mundo. -> (k, 3) en [0, 1] (ya escalado por el TEV).
        mascara = SelectMask: bit i PRENDIDO = la luz i SI ilumina (light.cpp). amb: ambiente por vertice (modelos
        self-lit: el color de vertice del modelo) o None (el AmbientScr del corte)."""
        acc = np.tile(self.amb, (len(P), 1)) if amb is None else np.array(amb, np.float32)
        for l in self.luces:
            if not (mascara & (1 << l['n'])):
                continue
            col = np.array(l['color'], np.float32)
            I, r = l['intensidad'], l['radio']
            lp = np.array(l['pos'], np.float32)
            d_obj = float(np.linalg.norm(lp - centro))
            rango = r + radio
            t = l['tipo']
            if t == 5:                                          # PARALELA: desde la direccion 'dir'
                L = np.array(l['dir'], np.float32)
                L /= (np.linalg.norm(L) or 1.0)
                br = I if (r == 0 or d_obj < rango) else 0.001
                ndl = np.clip(N @ L, 0, None)
                acc += col * br * ndl[:, None]
                continue
            v = lp - P
            dist = np.linalg.norm(v, axis=1)
            L = v / np.maximum(dist, 1e-6)[:, None]
            ndl = np.clip(np.sum(N * L, axis=1), 0, None)
            dmm = dist * 1000.0
            if t == 0:                                          # constante hasta el radio
                att = np.full(len(P), I if (r == 0 or d_obj < rango) else 0.0)
            elif t == 1:                                        # lineal hasta 0 en el radio
                att = np.full(len(P), I * max(0.0, (r - d_obj) / r) if r else I)
            elif t in (2, 6):                                   # cuadratica: 0.1 en el radio
                br = I if (r == 0 or d_obj < rango) else 0.001
                k2 = (I - 0.1) / 0.1 / ((r * 1000.0) ** 2) if r else 0.0
                att = br / (1.0 + k2 * dmm * dmm)
                if t == 6:
                    att = att * self._cono(l, L)
            elif t == 3:                                        # spot: cono A0 + GX_DA_MEDIUM a 5000 mm
                br = I if (r == 0 or d_obj < rango) else 0.001
                if 0 < br < 1:
                    k1 = 0.5 * (1 - br) / (br * 5000.0)
                    k2 = 0.5 * (1 - br) / (br * 5000.0 ** 2)
                    att = 1.0 / (1.0 + k1 * dmm + k2 * dmm * dmm)
                else:
                    att = np.ones(len(P))
                att = att * self._cono(l, L)
            else:                                               # 4 (custom) / otras: sin atenuacion conocida
                att = np.full(len(P), I)
            acc += col * (att * ndl)[:, None]
        # canal de GX: clamp(material * (ambiente + luces)), material = tinte SMX; despues el TEV x2
        if tinte is not None:
            acc = acc * np.asarray(tinte, np.float32)
        if TEV_EN_EL_JUEGO:
            # (el juego multiplica por 2 al dibujar, como el TEV: el color va a la mitad y no se recorta lo que pasa de 1)
            return np.clip(np.clip(acc, 0, 1) * self.escala * 0.5, 0, 1)
        return np.clip(np.clip(acc, 0, 1) * self.escala, 0, 1)

    @staticmethod
    def _cono(l, L):
        """GX_SP_COS: a0 + a1 cos(angulo), con el corte A0 (grados) sobre la direccion del spot."""
        corte = l['a'][0] if l.get('a') else 90.0
        if not 0 < corte <= 90:
            return 1.0
        cr = math.cos(math.radians(corte))
        D = np.array(l['dir'], np.float32)
        D /= (np.linalg.norm(D) or 1.0)
        cosang = -(L @ D)                                   # L apunta del vertice a la luz
        return np.clip(-cr / (1 - cr) + cosang / (1 - cr), 0, 1)


def teselar(P, UV, C, idx, maximo):
    """parte los triangulos con algun lado > maximo (metros) por el lado mas largo, hasta que ninguno lo pase.
    POR QUE: la niebla de GL fijo (y la del N95) se calcula POR VERTICE. Un triangulo de piso de 50 m tiene el
    vertice lejano 100 %% en niebla y ese color se arrastra hasta el pie de la camara: se ven 'agujeros' del color
    de la niebla. En GX la niebla es por pixel y no pasa. Con lados cortos la interpolacion ya no se nota."""
    P, UV, C = [list(P), list(UV), list(C)]
    tris = [tuple(t) for t in np.asarray(idx).reshape(-1, 3)]
    L2 = maximo * maximo
    medio = {}

    def mid(a, b):
        k = (a, b) if a < b else (b, a)
        if k not in medio:
            medio[k] = len(P)
            P.append((np.asarray(P[a]) + np.asarray(P[b])) / 2)
            UV.append((np.asarray(UV[a]) + np.asarray(UV[b])) / 2)
            C.append((np.asarray(C[a]) + np.asarray(C[b])) / 2)
        return medio[k]
    out, pila = [], tris[::-1]
    while pila:
        a, b, c = pila.pop()
        pa, pb, pc = np.asarray(P[a]), np.asarray(P[b]), np.asarray(P[c])
        l = [((pa - pb) ** 2).sum(), ((pb - pc) ** 2).sum(), ((pc - pa) ** 2).sum()]
        k = int(np.argmax(l))
        if l[k] <= L2:
            out.append((a, b, c))
            continue
        if k == 0:
            m = mid(a, b); pila += [(a, m, c), (m, b, c)]
        elif k == 1:
            m = mid(b, c); pila += [(a, b, m), (a, m, c)]
        else:
            m = mid(c, a); pila += [(a, b, m), (m, b, c)]
    return np.array(P), np.array(UV), np.array(C), np.array(out, np.uint32).reshape(-1)


def matriz_pieza(w):
    """M = T Rz Ry Rx S en metros: (R*S 3x3, T)."""
    rx, ry, rz = w['rot']
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    return R @ np.diag(w['sc']), R, np.array(w['pos']) * ESCALA


def main():
    sys.path.insert(0, os.path.join(HERE, 'tools', 'meshopt'))
    import meshopt
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--out', default=os.path.join(HERE, 'out', 'r100'))
    ap.add_argument('--full', action='store_true', help='texturas a tamanio original (default: a la mitad)')
    ap.add_argument('--celda', type=float, default=8.0, help='lado (m) de las celdas en que se agrupan las piezas')
    ap.add_argument('--lod', default='0.35,0.12', help='proporcion de triangulos de cada LOD ("" = sin LOD)')
    ap.add_argument('--lod-alfa', default=None,
                    help='la proporcion de los LOD de lo TRANSLUCIDO (follaje: tarjetas sueltas que el LOD poda; '
                         'default: la misma que --lod)')
    ap.add_argument('--lod-error', default='0.02,0.06', help='error maximo de cada LOD (relativo al chunk)')
    ap.add_argument('--lod-error-opaco', type=float, default=None,
                    help='tope del error de los LOD en lo opaco (0 = el mismo que el resto; por defecto 0.025 con '
                         '--full y 0 sin)')
    ap.add_argument('--lado', default='3,5,9',
                    help='lado maximo (m) de los triangulos de cada LOD: la niebla por vertice necesita lados cortos')
    ap.add_argument('--l0', type=float, default=0.003,
                    help='error de la PRE-simplificacion del nivel 0 (respeta costuras; 0 = el original del juego)')
    ap.add_argument('--fondo-prop', type=float, default=0,
                    help='el FONDO (cerros, siluetas, terreno base) tambien simplificado a esta proporcion, sin cruzar '
                         'costuras ni bordes (asi no se abren agujeros en el piso); 0 = entero. Para el N95')
    ap.add_argument('--fondo-celda', type=float, default=0,
                    help='el FONDO partido en celdas de este lado (m), por el centro de cada triangulo: asi la distancia '
                         'y el frustum descartan lo lejano y lo de atras (una pieza entera es una caja gigante que '
                         'siempre contiene a la camara); 0 = una pieza, un chunk. Para el N95')
    ap.add_argument('--fondo-lado', type=float, default=6.0,
                    help='lado maximo (m) de los triangulos del fondo (la niebla por vertice)')
    ap.add_argument('--l0-costuras', action='store_true',
                    help='con --l0-prop, el nivel cercano sin cruzar las costuras de UV/color (las texturas no se '
                         'corren; reduce menos)')
    ap.add_argument('--l0-prop', type=float, default=0,
                    help='el nivel 0 TAMBIEN simplificado por proporcion (como los LOD: permisivo, error --lod-error[0]); '
                         '0 = el del juego apenas simplificado (--l0). Para el N95 a 30 fps')
    ap.add_argument('--l0-prop-casa', type=float, default=0,
                    help='con --l0-prop, la proporcion del nivel cercano de la CASA (bloque b1): se ve de cerca')
    ap.add_argument('--tev-juego', action='store_true',
                    help='el color de vertice a la MITAD, sin recortar el x2 del TEV: el juego lo multiplica por 2 al '
                         'dibujar (GL_COMBINE con RGB_SCALE 2). Para el N95: asi la luz es la del original')
    args = ap.parse_args()
    global TEV_EN_EL_JUEGO
    TEV_EN_EL_JUEGO = args.tev_juego
    out = args.out
    os.makedirs(os.path.join(out, 'tex'), exist_ok=True)
    for f in os.listdir(os.path.join(out, 'tex')):
        os.remove(os.path.join(out, 'tex', f))
    from PIL import Image
    props = [float(x) for x in args.lod.split(',') if x.strip()]
    props_alfa = [float(x) for x in args.lod_alfa.split(',') if x.strip()] if args.lod_alfa else props
    errores = [float(x) for x in args.lod_error.split(',') if x.strip()]
    lados = [float(x) for x in args.lado.split(',') if x.strip()]

    das = archive.Archive(DAS)
    ent = {e.index: e for e in das.entries()}
    smds_das = [Smd(ent[i].data, 'r100.das:%d' % i) for i in sorted(ent) if ent[i].tag == 'SMD']
    raiz, comun = smds_das[0], smds_das[1]
    smx_tab = smx([e for e in ent.values() if e.tag == 'SMX'][0].data)
    bloques = [smd_de(p)[0] for p in BLOQUES]
    lit_d = [e for e in ent.values() if e.tag == 'LIT'][0].data
    lit0 = lit(lit_d, 0)
    # EL CORTE DE LUZ POR ZONA: el juego elige el corte del LIT por el AREA DE CAMARA donde esta Leon (cam_ctrl.cpp
    # switchCamera -> LightMgr.update): la casa es el area 4 (corte 4: la chimenea y las luces de adentro). Horneado:
    # cada pieza con el corte del area donde esta su centro (fuera de toda area: corte 0).
    look = json.load(open(os.path.join(HERE, 'out', 'r100_look', 'look.json')))
    areas_cam = [a for a in look['areas_luz']['areas_camara'] if a.get('habilitada') and not (a.get('attr', 0) & 4)]
    luces_de = {}

    def luces_corte(c):
        if c not in luces_de:
            luces_de[c] = Luces(lit(lit_d, c))
        return luces_de[c]

    def corte_en(x, y, z):
        for a in sorted(areas_cam, key=lambda a: 0 if a.get('attr', 0) & 0x20 else 1):
            if not (a['piso_m'] <= y + 0.1 < a['piso_m'] + a['alto_m']):
                continue
            pts = a['poligono_xz']; dentro = False; j = len(pts) - 1
            for i in range(len(pts)):
                xi, zi = pts[i]; xj, zj = pts[j]
                if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
                    dentro = not dentro
                j = i
            if dentro:
                return a['corte_lit']
        return 0
    luces = luces_corte(0)

    # ---- texturas: el TPL del comun (+ las compuestas color/alfa) ----
    texs = comun.texturas(0)
    decod = [t.decode() for t in texs]
    tex_info = []

    def guardar_png(img, nombre):
        h, w = img.shape[:2]
        if not args.full and w >= 16 and h >= 16:
            img = np.asarray(Image.fromarray(img, 'RGBA').resize((w // 2, h // 2), Image.BOX))
        with open(os.path.join(out, 'tex', nombre), 'wb') as f:
            f.write(gxtex.png(np.ascontiguousarray(img)))
        return img
    for t, img in zip(texs, decod):
        img2 = guardar_png(img, 'r100_t%02d.png' % t.index)
        tex_info.append(dict(archivo='r100_t%02d.png' % t.index, w=img2.shape[1], h=img2.shape[0],
                             alfa=bool((img2[..., 3] < 250).any()), fmt=t.fmt))
    compuestas = {}

    def textura_alfa(tex_id, alfa_id):
        """alphaSetup: el ALFA sale de OTRA textura (ModelPart.alphaTex) sobre el mismo UV -> PNG compuesta."""
        if (tex_id, alfa_id) not in compuestas:
            img = decod[tex_id].copy()
            a = decod[alfa_id][..., 3]
            h, w = img.shape[:2]
            img[..., 3] = a[((np.arange(h) * a.shape[0]) // h)[:, None], ((np.arange(w) * a.shape[1]) // w)[None, :]]
            nombre = 'r100_t%02d_a%02d.png' % (tex_id, alfa_id)
            img2 = guardar_png(img, nombre)
            tex_info.append(dict(archivo=nombre, w=img2.shape[1], h=img2.shape[0], alfa=True, fmt=-1))
            compuestas[(tex_id, alfa_id)] = len(tex_info) - 1
        return compuestas[(tex_id, alfa_id)]

    # ---- materiales: SIN luz de GL (la iluminacion va horneada en el vertex color) ----
    materiales, mat_de = [], {}

    def material(tex_id, alfa_test, cutoff, cull, blend, alfa_id=None, luz=False):
        if alfa_test and alfa_id is not None and 0 <= tex_id < len(decod) and 0 <= alfa_id < len(decod) \
                and alfa_id != tex_id:
            tex_id = textura_alfa(tex_id, alfa_id)
            # alphaTex con alphaRef 0 (todas las del mapa): el juego MEZCLA (tabla translucida), no recorta
            if cutoff <= 1.5 / 255.0:
                blend = blend or 1
        clave = (tex_id, alfa_test, round(cutoff, 3), cull, blend, luz)
        if clave in mat_de:
            return mat_de[clave]
        pbr = {'baseColorFactor': [1.0, 1.0, 1.0, 1.0], 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
        if 0 <= tex_id < len(tex_info):
            pbr['baseColorTexture'] = {'index': tex_id}
        m = {'name': 'r100_m%03d_t%02d%s%s' % (len(materiales), tex_id,
                                               '_b' if blend else ('_a' if alfa_test else ''),
                                               '' if cull == 0 else '_c%d' % cull),
             'pbrMetallicRoughness': pbr,
             'extras': {'w3d_transparent': bool(alfa_test or blend), 'w3d_culling': cull != 2, 'w3d_repeat': True,
                        'w3d_vertexColor': True, 'w3d_lighting': bool(luz)}}
        if blend:
            m['alphaMode'] = 'BLEND'
        elif alfa_test:
            m['alphaMode'] = 'MASK'
            m['alphaCutoff'] = cutoff
        if cull == 2:
            m['doubleSided'] = True
        mat_de[clave] = len(materiales)
        materiales.append(m)
        return mat_de[clave]

    # ---- 1. cada pieza a MUNDO, con su luz horneada, repartida en chunks (bloque, capa, celda) ----
    #  grupo: 'b0'..'b4' (bloques), 'raiz' (siempre cargado), 'fondo' (siluetas lejanas, escala 10) y 'cielo'
    PUENTES = {0x23: 'puente_sano', 0x44: 'puente_sano', 0x37: 'puente_roto', 0x38: 'puente_roto'}
    chunks = {}          # (grupo, capa, cx, cz) -> {material: [P, UV, C]}
    n_piezas = 0
    for bi, s in [(-1, raiz)] + list(enumerate(bloques)):
        for wi, w in enumerate(s.works):
            if w['bin'] == 0xFF:
                continue
            src = comun if (w['flags'] & FLAG_BIN_COMUN) else s
            if w['bin'] >= len(src.bins):
                continue
            rec = smx_tab.get(w['id'])
            cull = rec['cull'] if rec else 0
            mascara = rec['mascara'] if rec else 0xFFFFFFFF   # sin registro SMX: todas las luces
            blend = (rec['color'] & 0xFF) if rec else 0
            tinte = np.ones(3)
            if rec and rec['color'] & ~0xFF:
                c = rec['color']
                tinte = np.array([(c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255]) / 255.0
            m = src.malla(w['bin'])
            MS, R, T = matriz_pieza(w)
            Nmat = np.linalg.inv(MS).T
            grande = max(w['sc']) >= 5.0
            # corners de todas las partes, a mundo
            partes = []
            for part in m.parts:
                tris = [t for t in part.triangles() if len({v[0] for v in t}) == 3]
                if not tris:
                    continue
                if cull == 1:   # GX: frente = horario; CULL_FRONT (0) es lo normal, BACK (1) muestra la otra cara
                    tris = [(t[0], t[2], t[1]) for t in tris]
                cs = [v for t in tris for v in t]
                P = np.array([m.position(v[0]) for v in cs]) * ESCALA @ MS.T + T
                N = np.array([m.normal(v[1]) for v in cs]) @ Nmat.T
                N /= np.maximum(np.linalg.norm(N, axis=1), 1e-9)[:, None]
                if cull == 1:
                    N = -N
                UV = np.array([m.texcoord(v[3]) for v in cs])
                AMB = (np.array([m.colour(v[2])[:3] for v in cs], np.float32) / 255.0) \
                    if (bool(m.flags & 0x40000000) and m.clr) else None
                alfa_test = bool(part.flags & 4)
                cutoff = (part.alpha_ref + 1) / 255.0 if alfa_test else 0.5
                if not alfa_test and 0 <= part.tex_id < len(tex_info) and tex_info[part.tex_id]['alfa']:
                    alfa_test, cutoff = True, 0.5
                mi = material(part.tex_id, alfa_test, cutoff, cull, blend, part.alpha_tex)
                partes.append((mi, P, N, UV, AMB))
            if not partes:
                continue
            todo = np.concatenate([p[1] for p in partes])
            partes = [(p[0], p[1], p[2], p[3], p[4]) for p in partes]
            lo, hi = todo.min(0), todo.max(0)
            centro, radio = (lo + hi) / 2, float(np.linalg.norm(hi - lo) / 2)
            luces = luces_corte(corte_en(float(centro[0]), float(lo[1]) + 0.5, float(centro[2])))
            # modelos SELF-LIT (flag 0x40000000 del bin): el ambiente es el color de vertice del modelo
            self_lit = bool(m.flags & 0x40000000) and bool(m.clr)
            cielo = grande and any(p[0] is not None and materiales[p[0]]['name'].split('_t')[1][:2] == '08'
                                   for p in partes)
            grupo = 'cielo' if cielo else ('fondo' if grande else ('raiz' if bi < 0 else 'b%d' % bi))
            # los PUENTES del SMD residente: el sano (0x23 + la marca de la camioneta 0x44) y el roto (0x38 + las
            # huellas del arrastre 0x37) van en grupos propios: el juego prende uno u otro (be_flag) segun r100s20
            puente = PUENTES.get(w['id']) if bi < 0 else None
            if puente:
                grupo = puente
            for mi, P, N, UV, AMB in partes:
                if cielo:
                    # el cielo: self-lit, tex * 0.941 * 2 (TEV x2) -> con vertex color a lo sumo 1: blanco
                    C = np.full((len(P), 3), 0.941 if TEV_EN_EL_JUEGO else 1.0)
                else:
                    C = luces.color(P, N, centro, radio, mascara, AMB, tinte)
                capa = 'alfa' if materiales[mi]['extras']['w3d_transparent'] else 'opaco'
                if grande and not cielo and not puente and args.fondo_celda > 0:
                    # (el N95) el gigante partido en celdas: cada triangulo a la de su centro
                    cen = P.reshape(-1, 3, 3).mean(1)
                    ca = np.floor(cen[:, 0] / args.fondo_celda).astype(int)
                    cb = np.floor(cen[:, 2] / args.fondo_celda).astype(int)
                    for a, b in sorted(set(zip(ca.tolist(), cb.tolist()))):
                        sel = np.repeat((ca == a) & (cb == b), 3)
                        d = chunks.setdefault((grupo, capa, (wi, a, b), 0), {}).setdefault(mi, [[], [], []])
                        d[0].append(P[sel])
                        d[1].append(UV[sel])
                        d[2].append(C[sel])
                    continue
                if puente:
                    clave = (grupo, capa, 0, 0)
                elif grande:
                    clave = (grupo, capa, wi, 0)             # los gigantes: un chunk cada uno
                else:
                    clave = (grupo, capa, int(math.floor(centro[0] / args.celda)),
                             int(math.floor(centro[2] / args.celda)))
                d = chunks.setdefault(clave, {}).setdefault(mi, [[], [], []])
                d[0].append(P)
                d[1].append(UV)
                d[2].append(C)
            n_piezas += 1

    # ---- 2. cada chunk: una malla por nivel de detalle ----
    b = gltf.Builder()
    meshes, nodos, lista = [], [], []
    stats = {}

    def primitiva(P, UV, C, idx, mi):
        chico = len(P) < 65536
        return {'attributes': {
            'POSITION': b.accessor('3f', gltf.FLOAT, 'VEC3', [tuple(x) for x in P], gltf.ARRAY_BUFFER, minmax=True),
            'TEXCOORD_0': b.accessor('2f', gltf.FLOAT, 'VEC2', [tuple(x) for x in UV], gltf.ARRAY_BUFFER),
            'COLOR_0': b.accessor('4f', gltf.FLOAT, 'VEC4', [(c[0], c[1], c[2], 1.0) for c in C], gltf.ARRAY_BUFFER)},
            'indices': b.accessor('H' if chico else 'I', gltf.U16 if chico else gltf.U32, 'SCALAR',
                                  [int(x) for x in idx], gltf.ELEMENT_ARRAY_BUFFER),
            'mode': 4, 'material': mi, 'extras': {'w3d_part': materiales[mi]['name']}}

    for (grupo, capa, cx, cz), por_mat in sorted(chunks.items(), key=lambda kv: str(kv[0])):
        # vertices unicos por material (posicion + uv + color), en coordenadas del CENTRO del chunk
        geo = {}
        todos = []
        for mi, (Ps, UVs, Cs) in por_mat.items():
            P = np.concatenate(Ps)
            UV = np.concatenate(UVs)
            C = np.concatenate(Cs)
            clave = np.concatenate([np.round(P, 4), np.round(UV, 4), np.round(C, 3)], axis=1)
            uniq, inv = np.unique(clave, axis=0, return_inverse=True)
            geo[mi] = (uniq[:, 0:3], uniq[:, 3:5], uniq[:, 5:8], inv.reshape(-1).astype(np.uint32))
            todos.append(uniq[:, 0:3])
        todo = np.concatenate(todos)
        centro = (todo.min(0) + todo.max(0)) / 2
        # el FONDO (piezas a escala 10: cerros, siluetas y el TERRENO BASE debajo de zonas grandes del camino) NO se
        # simplifica: es el piso de abajo de otras piezas y simplificarlo abria agujeros en el suelo. Un solo nivel.
        # nivel 0: el del juego apenas simplificado (error ~0.3 % del chunk, sin cruzar costuras de UV/color)
        l0 = args.l0_prop if args.l0_prop > 0 else (0.5 if args.l0 > 0 else 1.0)
        niveles = [l0] + (props_alfa if capa == 'alfa' else props) if grupo not in ('cielo', 'fondo') else \
            ([args.fondo_prop] if grupo == 'fondo' and args.fondo_prop > 0 else [1.0])
        if grupo == 'b1' and args.l0_prop_casa > 0:
            niveles[0] = args.l0_prop_casa     # (la casa se ve de cerca: los escalones, el marco de la puerta)
        if isinstance(cx, tuple):          # una celda de un gigante (--fondo-celda): pieza y celda
            nom = 'r100_%s_%s_%d_c%d_%d' % ((grupo, capa) + cx)
        else:
            nom = 'r100_%s_%s' % (grupo, capa) + ('_%d' % cx if grupo in ('cielo', 'fondo') else '_%d_%d' % (cx, cz))
        for k, prop in enumerate(niveles):
            prims = []
            n_tri = 0
            for mi in sorted(geo):
                P, UV, C, idx = geo[mi]
                if prop < 1.0:
                    # PERMISSIVE: cruza costuras de UV/color (a 12+ m no se nota); el ultimo nivel ademas PODA las
                    # partes chicas sueltas (matas de pasto, ramitas): es lo que mas triangulos saca en el follaje
                    opc = meshopt.PERMISSIVE | (meshopt.PRUNE if k == len(niveles) - 1 else 0)
                    err = errores[min(max(k - 1, 0), len(errores) - 1)] if grupo != 'fondo' else 0.05
                    # lo OPACO (casas, cercas) con menos error en el nivel lejano: con el 6 % del chunk se hundian
                    # los huecos de las ventanas de la casa (la buhardilla de lejos quedaba como un agujero)
                    tope = args.lod_error_opaco if args.lod_error_opaco is not None else (0.025 if args.full else 0)
                    if capa == 'opaco' and tope > 0:
                        err = min(err, tope)
                    if grupo == 'fondo':          # (el N95: --fondo-prop) sin cruzar costuras ni el borde
                        opc, err = meshopt.LOCK_BORDER, errores[0]
                    elif k == 0:
                        if args.l0_prop > 0:      # el N95: el cercano tambien por proporcion, sin podar
                            opc, err = (0 if args.l0_costuras else meshopt.PERMISSIVE), errores[0]
                        else:
                            opc, err = 0, args.l0
                    attrs = np.concatenate([UV, C], axis=1).astype(np.float32)
                    idx, _ = meshopt.simplificar(idx, P - centro, attrs, [0.5, 0.5, 0.3, 0.3, 0.3], prop,
                                                 err, opc)
                    if len(idx) == 0:
                        continue
                # compactar + partir los triangulos largos (niebla por vertice) + orden de cache
                usados, nuevo = np.unique(idx, return_inverse=True)
                Pk, UVk, Ck, idxk = P[usados], UV[usados], C[usados], nuevo.astype(np.uint32)
                if grupo == 'fondo':        # triangulos de hasta 100 m: la niebla por vertice los pintaba enteros
                    Pk, UVk, Ck, idxk = teselar(Pk, UVk, Ck, idxk, args.fondo_lado)
                elif grupo != 'cielo':
                    Pk, UVk, Ck, idxk = teselar(Pk, UVk, Ck, idxk, lados[min(k, len(lados) - 1)])
                idx2 = meshopt.orden_cache(idxk.astype(np.uint32), len(Pk))
                prims.append(primitiva(Pk - centro, UVk, Ck, idx2, mi))
                n_tri += len(idx2) // 3
            if not prims:
                continue
            meshes.append({'name': '%s_L%d' % (nom, k), 'primitives': prims})
            nodos.append({'name': '%s_L%d' % (nom, k), 'mesh': len(meshes) - 1, 'translation': list(centro)})
            lista.append(dict(nombre='%s_L%d' % (nom, k), chunk=nom, grupo=grupo, capa=capa, lod=k, tris=n_tri,
                              centro=[round(x, 3) for x in centro]))
            stats.setdefault((grupo, k), 0)
            stats[(grupo, k)] += n_tri
    print('piezas: %d -> %d chunks (celda %g m), %d mallas, %d materiales' %
          (n_piezas, len(chunks), args.celda, len(meshes), len(materiales)))
    for g in sorted({g for g, _ in stats}):
        print('  %-5s ' % g + '  '.join('L%d %6d' % (k, stats[(g, k)]) for k in range(3) if (g, k) in stats))

    # ---- colision (SAT 0): piso (pisos + rampas) y paredes, dos mallas en MUNDO ----
    satd = [e for e in ent.values() if e.tag == 'SAT'][0].data
    V, tris = sat(satd)
    col_mat = len(materiales)
    materiales.append({'name': 'r100_colision', 'pbrMetallicRoughness': {'baseColorFactor': [0.2, 0.8, 0.3, 1.0],
                                                                         'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                       'doubleSided': True, 'extras': {'w3d_culling': False, 'w3d_textureOn': False}})
    attrs_col = {}
    # el CAMION viejo que tapa el camino (W->carSub en (-60.821, -17.23)): sus paredes van en una malla APARTE,
    # r100_col_camion, porque despues del evento r100s20 se va al barranco y el camino queda libre
    CAMION, R_CAMION = (-60.821, -17.23), 3.5

    def del_camion(a, bb, c):
        cx = (V[a][0] + V[bb][0] + V[c][0]) / 3.0
        cz = (V[a][2] + V[bb][2] + V[c][2]) / 3.0
        return (cx - CAMION[0]) ** 2 + (cz - CAMION[1]) ** 2 < R_CAMION ** 2
    for nombre, clases in (('r100_col_suelo', (0, 1)), ('r100_col_pared', (2,)), ('r100_col_camion', (2,))):
        index, pos, idx = {}, [], []
        for a, bb, c, attr, clase in tris:
            if clase not in clases:
                continue
            if clase == 2 and (nombre == 'r100_col_camion') != del_camion(a, bb, c):
                continue
            attrs_col[attr] = attrs_col.get(attr, 0) + 1
            for v in (a, bb, c):
                if v not in index:
                    index[v] = len(pos)
                    pos.append(V[v])
                idx.append(index[v])
        meshes.append({'name': nombre, 'primitives': [{
            'attributes': {'POSITION': b.accessor('3f', gltf.FLOAT, 'VEC3', pos, gltf.ARRAY_BUFFER, minmax=True)},
            'indices': b.accessor('H', gltf.U16, 'SCALAR', idx, gltf.ELEMENT_ARRAY_BUFFER),
            'mode': 4, 'material': col_mat, 'extras': {'w3d_part': 'colision'}}]})
        nodos.append({'name': nombre, 'mesh': len(meshes) - 1})
        lista.append(dict(nombre=nombre, grupo='colision', capa='-', lod=0, tris=len(idx) // 3))
        print('colision %s: %d triangulos' % (nombre, len(idx) // 3))

    # ---- la puerta de la casa (ETS no 2, id 0x0D, modelo ETM et0d00): objeto propio (se mueve), luz horneada ----
    etm = dict(archive.parse_etm([e for e in ent.values() if e.tag == 'ETM'][0].data))
    etc = ets([e for e in ent.values() if e.tag == 'ETS'][0].data)
    puerta = [r for r in etc if r['id'] == 0x0D]
    info_puerta = None
    if puerta and 'et0d00.bin' in etm:
        r = puerta[0]
        pm = meshbin.parse(etm['et0d00.bin'])
        ptex = gxtex.parse_tpl(etm['et0d00.tpl']) if 'et0d00.tpl' in etm else []
        base_tex = len(tex_info)
        for t in ptex:
            nombre = 'r100_puerta_t%02d.png' % t.index
            img2 = guardar_png(t.decode(), nombre)
            tex_info.append(dict(archivo=nombre, w=img2.shape[1], h=img2.shape[0], alfa=False, fmt=t.fmt))
        rot = [math.radians(c) if abs(c) > 6.3 else c for c in r['rot']]
        wpu = dict(pos=r['pos'], rot=rot, sc=r['sc'])
        MS, R, T = matriz_pieza(wpu)
        prims = []
        for part in pm.parts:
            tris = [t for t in part.triangles() if len({v[0] for v in t}) == 3]
            cs = [v for t in tris for v in t]
            Pl = np.array([pm.position(v[0]) for v in cs]) * ESCALA
            N = np.array([pm.normal(v[1]) for v in cs]) @ R.T
            N /= np.maximum(np.linalg.norm(N, axis=1), 1e-9)[:, None]
            # sin record SMX: todas las luces (mascara 0 = NINGUNA luz desde que la mascara se lee bien: salia negra)
            C = luces_corte(0).color(Pl @ MS.T + T, N, T, 1.0, 0xFFFFFFFF)
            UV = np.array([pm.texcoord(v[3]) for v in cs])
            clave = np.concatenate([np.round(Pl, 4), np.round(UV, 4), np.round(C, 3)], axis=1)
            uniq, inv = np.unique(clave, axis=0, return_inverse=True)
            mi = material(base_tex + part.tex_id, bool(part.flags & 4), (part.alpha_ref + 1) / 255.0, 0, 0)
            prims.append(primitiva(uniq[:, 0:3], uniq[:, 3:5], uniq[:, 5:8], inv.reshape(-1), mi))
        meshes.append({'name': 'r100_puerta', 'primitives': prims})
        nodos.append({'name': 'r100_puerta', 'mesh': len(meshes) - 1,
                      'translation': [c * ESCALA for c in r['pos']], 'rotation': quat_zyx(*rot), 'scale': list(r['sc'])})
        lista.append(dict(nombre='r100_puerta', grupo='b1', capa='opaco', lod=0, tris=0))
        info_puerta = dict(pos=[round(c * ESCALA, 4) for c in r['pos']], rot=r['rot'], escala=r['sc'])

    # ---- glb ----
    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_r100.py'},
        'scene': 0,
        'scenes': [{'name': 'r100', 'nodes': list(range(len(nodos)))}],
        'nodes': nodos,
        'meshes': meshes,
        'materials': materiales,
        'images': [{'uri': 'tex/' + t['archivo']} for t in tex_info],
        'samplers': [{'magFilter': 9729, 'minFilter': 9987, 'wrapS': 10497, 'wrapT': 10497}],
        'textures': [{'source': i, 'sampler': 0} for i in range(len(tex_info))],
        'accessors': b.accessors,
        'bufferViews': b.buffer_views,
    }
    glb = os.path.join(out, 'r100.glb')
    gltf.write(doc, bytes(b.blob), glb)

    # ---- datos del mapa ----
    niebla = lit0['niebla']
    info = dict(
        escala=ESCALA,
        piezas=lista,
        texturas=tex_info,
        bloques=blk([e for e in ent.values() if e.tag == 'BLK'][0].data),
        aev=aev([e for e in ent.values() if e.tag == 'AEV'][0].data),
        ets=[dict(r, pos=[round(c * ESCALA, 4) for c in r['pos']]) for r in etc],
        puerta=info_puerta,
        luz=lit0,
        # el FAR del juego con niebla (light.cpp): fog.End * (1 - far_play_ratio) + 1 (en metros)
        lejos=round(niebla['fin'] * (1 - lit0['far_play_ratio']) + 0.001, 3),
        colision_attrs={hex(k): v for k, v in sorted(attrs_col.items())},
        leon_post_evento=[-82.910, 0.860, -38.480],
        eventos={'casa': 'r100s03.evd', 'apertura': 'r100s40.evd', 'puente': 'r100s20.evd'},
    )
    with open(os.path.join(out, 'r100.json'), 'w') as f:
        json.dump(info, f, indent=1)
    print('-> %s (%d nodos, %.1f MB), r100.json' % (glb, len(nodos), os.path.getsize(glb) / 1e6))


if __name__ == '__main__':
    main()
