"""
pvs_interior.py: que se VE desde adentro de la casa (r100), calculado una vez con rayos. RE4 no tiene oclusion (dibuja
lo que cae en el frustum de los bloques cargados); estando adentro eso incluye todo el pasto y los arboles de afuera,
tapados por las paredes. Aca: puntos de muestra adentro de la casa, rayos a puntos de cada chunk, contra los triangulos
OPACOS de la casa (paredes, techo, postigos: los rayos pasan por la puerta y por las rendijas). Un chunk es visible si
algun rayo llega sin chocar. r100.lua usa la lista cuando la camara esta adentro (o durante la cinematica).
"""
import json
import struct
import numpy as np

CASA = dict(x0=-85.8, x1=-71.1, z0=-42.5, z1=-29.9, y0=0.2, y1=5.0)   # AEV 9 (el interior)


def _glb(ruta):
    g = open(ruta, 'rb').read()
    jl = struct.unpack('<I', g[12:16])[0]
    doc = json.loads(g[20:20 + jl])
    bl = g[20 + jl + 8:]

    def acc(i):
        a = doc['accessors'][i]
        bv = doc['bufferViews'][a['bufferView']]
        o = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[a['componentType']]
        v = np.frombuffer(bl, dt, a['count'] * n, o)
        return v.reshape(-1, n) if n > 1 else v
    return doc, acc


def calcular(glb, piezas, margen=1.0):
    doc, acc = _glb(glb)
    # AABB de cada chunk (union de sus niveles) y triangulos opacos L0 cerca de la casa (los oclusores)
    cajas, oclus = {}, []
    c = CASA
    for n, p in zip(doc['nodes'], piezas):
        if p['grupo'] in ('colision', 'cielo') or 'mesh' not in n:
            continue
        T = np.array(n.get('translation', [0, 0, 0]), np.float32)
        m = doc['meshes'][n['mesh']]
        lo = np.min([doc['accessors'][q['attributes']['POSITION']]['min'] for q in m['primitives']], 0) + T
        hi = np.max([doc['accessors'][q['attributes']['POSITION']]['max'] for q in m['primitives']], 0) + T
        ch = p.get('chunk', p['nombre'])
        if ch in cajas:
            cajas[ch] = (np.minimum(cajas[ch][0], lo), np.maximum(cajas[ch][1], hi))
        else:
            cajas[ch] = (lo, hi)
        cerca = hi[0] > c['x0'] - 2 and lo[0] < c['x1'] + 2 and hi[2] > c['z0'] - 2 and lo[2] < c['z1'] + 2
        if p['capa'] == 'opaco' and p.get('lod', 0) == 0 and cerca:
            for q in m['primitives']:
                P = acc(q['attributes']['POSITION']).astype(np.float32) + T
                I = acc(q['indices']).reshape(-1, 3)
                oclus.append(P[I])
    O = np.concatenate(oclus) if oclus else np.zeros((0, 3, 3), np.float32)
    # solo los triangulos que tocan la caja de la casa: las paredes / techo / piso (no el terreno de afuera)
    tlo, thi = O.min(1), O.max(1)
    dentro = (thi[:, 0] > c['x0'] - 0.5) & (tlo[:, 0] < c['x1'] + 0.5) & (thi[:, 2] > c['z0'] - 0.5) & \
             (tlo[:, 2] < c['z1'] + 0.5) & (thi[:, 1] > c['y0'] - 0.5)
    O = O[dentro]
    A, E1, E2 = O[:, 0], O[:, 1] - O[:, 0], O[:, 2] - O[:, 0]
    # muestras adentro (grilla, 1 m adentro de las paredes) a dos alturas: la de los ojos y la de una camara alta
    xs = np.linspace(c['x0'] + margen, c['x1'] - margen, 14)
    zs = np.linspace(c['z0'] + margen, c['z1'] - margen, 10)
    ys = [1.4, 2.4]
    S = np.array([(x, y, z) for x in xs for z in zs for y in ys], np.float32)

    def choca(o, d, lmax):
        """cada rayo (o[i], d[i]) choca con algun oclusor antes de lmax?"""
        res = np.zeros(len(o), bool)
        for i0 in range(0, len(o), 256):
            dd, oo = d[i0:i0 + 256, None, :], o[i0:i0 + 256, None, :]
            p = np.cross(dd, E2[None]); det = np.einsum('rtk,tk->rt', p, E1)
            ok = np.abs(det) > 1e-9; inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
            s_ = oo - A[None]; u = np.einsum('rtk,rtk->rt', s_, p) * inv
            q = np.cross(s_, E1[None]); v = np.einsum('rk,rtk->rt', dd[:, 0], q) * inv
            t = np.einsum('tk,rtk->rt', E2, q) * inv
            res[i0:i0 + 256] = (ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0.02) & (t < lmax)).any(1)
        return res
    # ENCERRADAS: solo las muestras de adentro de verdad (arriba y las 4 direcciones chocan con la casa a < 8 m);
    # el area AEV es mas grande que el interior (el porche) y desde ahi se ve todo
    dirs = np.array([(0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)], np.float32)
    oo = np.repeat(S, len(dirs), 0)
    dd = np.tile(dirs, (len(S), 1))
    enc = choca(oo, dd, 8.0).reshape(len(S), len(dirs)).all(1)
    S = S[enc]
    if len(S) == 0:
        return set(cajas), len(cajas), len(O)
    visibles = set()
    for ch, (lo, hi) in cajas.items():
        # el chunk que toca la casa: visible siempre (es la casa o algo pegado a ella)
        if hi[0] > c['x0'] and lo[0] < c['x1'] and hi[2] > c['z0'] and lo[2] < c['z1']:
            visibles.add(ch)
            continue
        ctr = (lo + hi) / 2
        pts = [ctr] + [np.array([x, y, z]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        pts += [np.array([ctr[0], hi[1], ctr[2]]), np.array([lo[0], ctr[1], ctr[2]]), np.array([hi[0], ctr[1], ctr[2]]),
                np.array([ctr[0], ctr[1], lo[2]]), np.array([ctr[0], ctr[1], hi[2]])]
        Tg = np.array(pts, np.float32)
        Oo = np.repeat(S, len(Tg), 0)
        D = np.tile(Tg, (len(S), 1)) - Oo
        L = np.linalg.norm(D, axis=1)
        D = D / L[:, None]
        libre = np.ones(len(D), bool)
        for i0 in range(0, len(D), 256):          # Moller-Trumbore: rayos x triangulos, por tandas
            d, o, l = D[i0:i0 + 256, None, :], Oo[i0:i0 + 256, None, :], L[i0:i0 + 256, None]
            p = np.cross(d, E2[None])
            det = np.einsum('rtk,tk->rt', p, E1)
            ok = np.abs(det) > 1e-9
            inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
            s = o - A[None]
            u = np.einsum('rtk,rtk->rt', s, p) * inv
            q = np.cross(s, E1[None])
            v = np.einsum('rk,rtk->rt', d[:, 0], q) * inv
            t = np.einsum('tk,rtk->rt', E2, q) * inv
            golpe = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0.05) & (t < l - 0.05)
            libre[i0:i0 + 256] = ~golpe.any(1)
        if libre.any():
            visibles.add(ch)
    return visibles, len(cajas), len(O)
