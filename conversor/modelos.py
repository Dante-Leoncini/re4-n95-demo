"""LOS PERSONAJES (y lo que se mueve con un esqueleto: los vehiculos, la utileria de las cinematicas) para el N95: un
archivo .mdl por modelo con su esqueleto, su malla (las piezas de un armature juntas) y sus clips muestreados.

En el telefono el skinning es por CPU (el MBX no lo hace): cada vertice con UNO o DOS huesos (el tercero, si lo hay, se
reparte), ordenados en TRAMOS por su par de huesos (la matriz se toma una vez por tramo). La luz tambien la pone la CPU:
la normal del vertice contra la luz llevada al espacio de su hueso. Las shape keys (las caras de las cinematicas) se
suman antes del skinning.

    'MDL1'
    u32 nh; por hueso: char nombre[16], i16 padre, u16 0, f32 t[3], q[4] (x y z w), s[3], inv[12] (invBind 3x4 por
            columnas)
    u32 nv, ni, npartes, ntramos, nformas, nclips; f32 centro[3], radio
    f32 pos[nv*3]; i8 nrm[nv*4]; f32 uv[nv*2]; u16 idx[ni]
    por parte: u32 desde, cantidad (indices), textura, banderas (1 mezcla, 2 caras de atras afuera, 4 sin luz, 8 no escribe z)
    por tramo: u16 h0, h1 (0xFFFF: un solo hueso), u32 desde, cantidad (vertices)
    f32 peso[nv] (el de h0; h1 lleva 1 - peso)
    u32 hay_color; u8 color[nv*4] (el difuso del material: multiplica la luz y pone el alfa)
    por forma: char nombre[16], u32 n, u16 idx[n], i16 d[n*3] (1/8192 m)
    por clip: char nombre[32], u32 nf, u16 nr, u16 nt, u8 lazo, 3 x u8 0, u16 hr[nr], u16 ht[nt],
              i16 q[nf*nr*4] (/32767), f32 t[nf*nt*3]
"""
import sys
import os

import numpy as np

import binario
import esqueleto as esq

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'meshopt'))
import meshopt  # noqa: E402

MEZCLA, CULL, SIN_LUZ, SIN_Z = 1, 2, 4, 8
ESCALA_FORMA = 8192.0


def pesos_dos(malla, nombres, nh):
    """por render-vert: (h0, h1, w0) con los dos huesos de mas peso (h1 = -1 si es uno solo)"""
    nv = malla.nv
    W = np.zeros((nv, max(nh, 2)))
    for nom, (idx, val) in malla.grupos.items():
        if nom in nombres:
            W[idx, nombres.index(nom)] += val
    orden = np.argsort(-W, 1)
    h0 = orden[:, 0]
    h1 = orden[:, 1]
    w0 = W[np.arange(nv), h0]
    w1 = W[np.arange(nv), h1]
    tot = w0 + w1
    sin = tot <= 1e-6
    tot[sin] = 1
    w0n = w0 / tot
    h1 = np.where((w1 / tot) < 0.02, -1, h1)
    w0n = np.where(h1 < 0, 1.0, w0n)
    h0 = np.where(sin, 0, h0)
    return h0, h1, w0n, sin


def simplificar_partes(pos, uv, nrm, idx, partes, proporcion, error=0.02, bloq=None, permisivo=False):
    """los indices de cada parte simplificados a ~proporcion (sin tocar las que son chicas)"""
    if proporcion >= 0.999:
        return idx, partes
    attrs = np.c_[uv * 1.0, nrm.astype(np.float64) / 127.0 * 0.5].astype(np.float32)
    pesos = np.array([1, 1, 0.5, 0.5, 0.5], np.float32)
    nuevo, np_ = [], []
    desde = 0
    for (ini, cnt, mat) in partes:
        t = idx[ini:ini + cnt]
        # (lo mezclado -los vidrios- nunca permisivo: se deshace)
        opciones = meshopt.PERMISSIVE if permisivo and not (mat[1] & MEZCLA) else 0
        if cnt >= 3 * 60:
            s, _ = meshopt.simplificar(t, pos, attrs, pesos, proporcion, error, opciones, bloq)
            if len(s) >= 3:
                t = s.astype(np.int64)
        t = meshopt.orden_cache(t, len(pos)).astype(np.int64)
        nuevo.append(t)
        np_.append((desde, len(t), mat))
        desde += len(t)
    return (np.concatenate(nuevo) if nuevo else idx[:0]), np_


class Modelo:
    """junta las mallas de un armature y escribe su .mdl"""

    def __init__(self, nombre, arm_json, animset, texturas, log=print):
        self.nombre = nombre
        self.E = esq.Esqueleto(arm_json, animset)
        self.tex = texturas
        self.log = log
        self.mallas = []    # (pos, nrm, uv, h0, h1, w0, idx, partes [(ini, cnt, (tex, banderas))], formas)
        self.crudas = []    # lo mismo sin simplificar (para el nivel bajo)
        self.clips = []     # (nombre, k, lazo)

    def agregar_malla(self, malla, materiales, tex_de_material, proporcion=1.0, error=0.02, permisivo=False,
                      sin_formas=False, rigida_en=None, forma_min=0.0):
        """materiales: nombre -> json del material; tex_de_material(mat_json) -> indice de textura. rigida_en: el hueso
        al que va pegada una malla sin grupos (Child Of)"""
        nh = len(self.E.huesos)
        pos, uv, nrm = malla.pos.copy(), malla.uv.copy(), malla.nrm.copy()
        if rigida_en is not None:
            hb = self.E.nombres.index(rigida_en)
            mundo = self.E.reposo()
            M = mundo[hb]
            pos = (np.c_[pos, np.ones(len(pos))] @ M.T)[:, :3]
            n3 = nrm.astype(np.float64) @ M[:3, :3].T
            n3 /= np.maximum(np.linalg.norm(n3, axis=1, keepdims=True), 1e-9)
            nrm = np.round(n3 * 127).astype(np.int8)
            h0 = np.full(malla.nv, hb)
            h1 = np.full(malla.nv, -1)
            w0 = np.ones(malla.nv)
        else:
            h0, h1, w0, sin = pesos_dos(malla, self.E.nombres, nh)
            if sin.any():
                self.log('  %s: %d vertices sin hueso (van al 0)' % (self.nombre, int(sin.sum())))
        partes = []
        for nom, mat, ini, cnt in malla.partes:
            if cnt <= 0:
                continue
            mj = materiales.get(mat, {})
            fl = mj.get('flags', {})
            b = 0
            if fl.get('transparente'):
                b |= MEZCLA
            if fl.get('culling', True):
                b |= CULL
            if not fl.get('luz', True):
                b |= SIN_LUZ
            if not fl.get('escribeProfundidad', True):
                b |= SIN_Z
            dif = mj.get('difuso', [1, 1, 1, 1])
            col = tuple(int(round(max(0, min(1, c)) * 255)) for c in dif)
            partes.append((ini, cnt, (tex_de_material(mj), b, col)))
        idx = malla.idx
        formas = [] if sin_formas else malla.formas
        bloq = None
        if formas and proporcion < 0.999:
            # (lo que mueven las expresiones no se colapsa)
            bloq = np.zeros(malla.nv, bool)
            # (forma_min: solo lo que se mueve mas que esa fraccion del mayor desplazamiento de la forma)
            for _, fi, fd in formas:
                d = np.abs(fd).max(1)
                bloq[fi[d > max(1e-4, forma_min * (d.max() if len(d) else 0))]] = True
        self.crudas.append((pos, nrm, uv, h0, h1, w0, idx, partes))
        idx, partes = simplificar_partes(pos, uv, nrm, idx, partes, proporcion, error, bloq, permisivo)
        self.mallas.append((pos, nrm, uv, h0, h1, w0, idx, partes, formas))

    def guardar_bajo(self, ruta, proporcion):
        """el NIVEL BAJO (de lejos): el mismo esqueleto, la malla mucho mas simplificada, sin clips ni caras (el juego
        lo posa con los huesos del modelo de siempre)"""
        b = Modelo(self.nombre + '_b', {'bones': self.E.huesos}, ([], []), self.tex, self.log)
        b.E = self.E
        for pos, nrm, uv, h0, h1, w0, idx, partes in self.crudas:
            i2, p2 = simplificar_partes(pos, uv, nrm, idx, partes, proporcion, 0.08, None, True)
            b.mallas.append((pos, nrm, uv, h0, h1, w0, i2, p2, []))
        return b.guardar(ruta)

    def agregar_clip(self, nombre, k, lazo):
        self.clips.append((nombre, k, lazo))

    def guardar(self, ruta, cuadros_max=None):
        E = self.E
        # una sola malla: los vertices usados de cada pieza, ordenados por (h0, h1)
        P, N, U, H0, H1, W0, PARTES, FORMAS = [], [], [], [], [], [], [], []
        base = 0
        idx_all = []
        for pos, nrm, uv, h0, h1, w0, idx, partes, formas in self.mallas:
            usados = np.unique(idx)
            remap = -np.ones(len(pos), np.int64)
            remap[usados] = np.arange(len(usados)) + base
            P.append(pos[usados]); N.append(nrm[usados]); U.append(uv[usados])
            H0.append(h0[usados]); H1.append(h1[usados]); W0.append(w0[usados])
            for ini, cnt, mat in partes:
                PARTES.append((remap[idx[ini:ini + cnt]], mat))
            for nom, fi, fd in formas:
                m = remap[fi]
                ok = (m >= 0) & (np.abs(fd).max(1) > 1e-5)
                FORMAS.append((nom, m[ok], fd[ok]))
            base += len(usados)
        pos = np.concatenate(P); nrm = np.concatenate(N); uv = np.concatenate(U)
        h0 = np.concatenate(H0); h1 = np.concatenate(H1); w0 = np.concatenate(W0)
        # orden por pasada (lo opaco, lo mezclado: cada dibujo toca un rango corto de vertices) y por tramo
        pas = np.zeros(len(pos), np.int64)
        for t, mat in PARTES:
            if mat[1] & MEZCLA:
                pas[t.reshape(-1)] = 1
        clave = pas * 10 ** 7 + h0 * 1000 + np.where(h1 < 0, 999, h1)
        orden = np.argsort(clave, kind='stable')
        inv = np.empty_like(orden)
        inv[orden] = np.arange(len(orden))
        pos, nrm, uv, h0, h1, w0 = pos[orden], nrm[orden], uv[orden], h0[orden], h1[orden], w0[orden]
        tramos = []
        for i in range(len(pos)):
            par = (int(h0[i]), int(h1[i]))
            if tramos and tramos[-1][0] == par:
                tramos[-1][2] += 1
            else:
                tramos.append([par, i, 1])
        # las partes: por (pasada, textura) juntas (opaco antes que lo mezclado)
        juntas = {}
        mcol = np.full((len(pos), 4), 255, np.uint8)
        for t, mat in PARTES:
            juntas.setdefault(mat, []).append(inv[t])
            if mat[2] != (255, 255, 255, 255):
                mcol[inv[t].reshape(-1)] = mat[2]
        partes, idx_l, desde = [], [], 0
        for mat in sorted(juntas, key=lambda m: (m[1] & MEZCLA, m[0], m[1])):
            t = np.concatenate(juntas[mat])
            partes.append((desde, len(t), mat[0], mat[1]))
            idx_l.append(t)
            desde += len(t)
        idx = np.concatenate(idx_l)
        assert len(pos) < 65536, '%s: %d vertices' % (self.nombre, len(pos))
        mn, mx = pos.min(0), pos.max(0)
        centro = (mn + mx) / 2
        radio = float(np.linalg.norm(mx - mn) / 2)

        w = binario.Escritor().b(b'MDL1').s('I', len(E.huesos))
        for i, b in enumerate(E.huesos):
            inv_b = E.inv_bind[i]
            w.nombre(b['nombre'], 16).s('hH', b['padre'], 0).s('3f', *E.rest_t[i]).s('4f', *E.rest_q[i])
            w.s('3f', *E.rest_s[i]).s('12f', *inv_b[:3, :].T.reshape(-1))
        w.s('6I', len(pos), len(idx), len(partes), len(tramos), len(FORMAS), len(self.clips))
        w.s('4f', centro[0], centro[1], centro[2], radio)
        w.b(pos.astype(np.float32).tobytes())
        w.b(np.c_[nrm, np.zeros(len(nrm), np.int8)].astype(np.int8).tobytes())
        w.b(uv.astype(np.float32).tobytes())
        w.b(idx.astype(np.uint16).tobytes()).alinear()
        for p in partes:
            w.s('4I', *p)
        for (a, b), d, n in tramos:
            w.s('HHII', a, 0xFFFF if b < 0 else b, d, n)
        w.b(w0.astype(np.float32).tobytes())
        hay = bool((mcol != 255).any())
        w.s('I', 1 if hay else 0)
        if hay:
            w.b(mcol.tobytes())
        for nom, fi, fd in FORMAS:
            fi2 = inv[fi]
            w.nombre(nom, 16).s('I', len(fi2)).b(fi2.astype(np.uint16).tobytes()).alinear()
            w.b(np.clip(np.round(fd * ESCALA_FORMA), -32767, 32767).astype(np.int16).tobytes()).alinear()
        kb_clips = 0
        for nombre, k, lazo in self.clips:
            frames, T, Q, ar, at = E.muestrear(k)
            if cuadros_max and len(frames) > cuadros_max:
                frames, T, Q = frames[:cuadros_max], T[:cuadros_max], Q[:cuadros_max]
            nf = len(frames)
            w.nombre(nombre, 32).s('IHHBBBB', nf, len(ar), len(at), 1 if lazo else 0, 0, 0, 0)
            w.b(np.array(ar, np.uint16).tobytes()).alinear()
            w.b(np.array(at, np.uint16).tobytes()).alinear()
            q16 = np.round(Q[:, ar, :] * 32767).astype(np.int16) if ar else np.zeros((nf, 0, 4), np.int16)
            w.b(q16.tobytes()).alinear()
            w.b(T[:, at, :].astype(np.float32).tobytes())
            kb_clips += (q16.nbytes + nf * len(at) * 12) // 1024
        n = w.guardar(ruta)
        tris = len(idx) // 3
        self.log('%s: %d huesos, %d vertices, %d triangulos, %d partes, %d tramos, %d formas, %d clips (%d KB, '
                 'clips %d KB)' % (os.path.basename(ruta), len(E.huesos), len(pos), tris, len(partes), len(tramos),
                                   len(FORMAS), len(self.clips), n // 1024, kb_clips))
        return tris
