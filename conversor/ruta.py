"""LA RUTA DE LAS PRUEBAS ('ruta.demo' en tablas.bin): los puntos por donde el piloto de las pruebas lleva a Leon
(juego.cpp: Leon anda solo) desde el arranque, por la escena de la ventana, a la casa, de vuelta afuera y hasta la
salida del cuarto. Un A* sobre una grilla de 0,5 m con el piso de la colision del juego y lejos de sus paredes."""
import heapq
import math

import numpy as np

CELDA = 0.5


def _piso(tris, xs, zs):
    """la altura del piso (el triangulo mas alto) en cada celda; nan si no hay"""
    alto = np.full((len(zs), len(xs)), np.nan)
    for a, b, c in tris:
        mn = np.minimum(np.minimum(a, b), c)
        mx = np.maximum(np.maximum(a, b), c)
        i0, i1 = np.searchsorted(xs, mn[0]), np.searchsorted(xs, mx[0], 'right')
        j0, j1 = np.searchsorted(zs, mn[2]), np.searchsorted(zs, mx[2], 'right')
        if i0 >= i1 or j0 >= j1:
            continue
        X, Z = np.meshgrid(xs[i0:i1], zs[j0:j1])
        v0, v1 = b - a, c - a
        den = v0[0] * v1[2] - v1[0] * v0[2]
        if abs(den) < 1e-9:
            continue
        px, pz = X - a[0], Z - a[2]
        u = (px * v1[2] - v1[0] * pz) / den
        v = (v0[0] * pz - px * v0[2]) / den
        ok = (u >= -1e-4) & (v >= -1e-4) & (u + v <= 1 + 1e-4)
        y = a[1] + v0[1] * u + v1[1] * v
        sub = alto[j0:j1, i0:i1]
        mejor = np.where(ok & (np.isnan(sub) | (y > sub)), y, sub)
        alto[j0:j1, i0:i1] = mejor
    return alto


def _paredes(tris, xs, zs, alto, radio=0.28):
    """celdas con una pared cerca (a la altura del cuerpo)"""
    bloq = np.zeros(alto.shape, bool)
    for a, b, c in tris:
        mn = np.minimum(np.minimum(a, b), c) - radio
        mx = np.maximum(np.maximum(a, b), c) + radio
        i0, i1 = np.searchsorted(xs, mn[0]), np.searchsorted(xs, mx[0], 'right')
        j0, j1 = np.searchsorted(zs, mn[2]), np.searchsorted(zs, mx[2], 'right')
        if i0 >= i1 or j0 >= j1:
            continue
        sub = alto[j0:j1, i0:i1]
        # (solo si la pared llega a la altura del cuerpo en esa celda)
        tapa = (mn[1] < sub + 1.6) & (mx[1] > sub + 0.3)
        bloq[j0:j1, i0:i1] |= tapa
    return bloq


def camino(tris_piso, tris_pared, puntos):
    tp = [np.array(t, float).reshape(3, 3) for t in tris_piso]
    tw = [np.array(t, float).reshape(3, 3) for t in tris_pared]
    todos = np.concatenate([np.array(t).reshape(-1, 3) for t in (tris_piso,)]).reshape(-1, 3)
    mn, mx = todos.min(0), todos.max(0)
    xs = np.arange(mn[0], mx[0], CELDA)
    zs = np.arange(mn[2], mx[2], CELDA)
    alto = _piso(tp, xs, zs)
    bloq = _paredes(tw, xs, zs, np.nan_to_num(alto, nan=-99))
    libre = ~np.isnan(alto) & ~bloq

    def celda(p):
        return int(round((p[2] - zs[0]) / CELDA)), int(round((p[0] - xs[0]) / CELDA))

    def cercana(c):
        j, i = c
        for r in range(0, 20):
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    jj, ii = j + dj, i + di
                    if 0 <= jj < libre.shape[0] and 0 <= ii < libre.shape[1] and libre[jj, ii]:
                        return jj, ii
        return c

    ruta = []
    for a, b in zip(puntos, puntos[1:]):
        s, g = cercana(celda(a)), cercana(celda(b))
        prev = {s: None}
        cost = {s: 0}
        q = [(0, s)]
        while q:
            _, c = heapq.heappop(q)
            if c == g:
                break
            for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nj, ni = c[0] + dj, c[1] + di
                if not (0 <= nj < libre.shape[0] and 0 <= ni < libre.shape[1]) or not libre[nj, ni]:
                    continue
                if abs(alto[nj, ni] - alto[c]) > 0.45:
                    continue
                nc = cost[c] + math.hypot(dj, di)
                if (nj, ni) not in cost or nc < cost[(nj, ni)]:
                    cost[(nj, ni)] = nc
                    prev[(nj, ni)] = c
                    h = math.hypot(g[0] - nj, g[1] - ni)
                    heapq.heappush(q, (nc + h, (nj, ni)))
        if g not in prev:
            raise ValueError('no hay camino de %s a %s' % (a, b))
        tramo = []
        c = g
        while c is not None:
            tramo.append(c)
            c = prev[c]
        tramo.reverse()
        # de a 1 m (el piloto va de punto en punto en linea recta: mas lejos cortaria las esquinas de las puertas)
        for k, (j, i) in enumerate(tramo):
            if k % 2 == 0 or k == len(tramo) - 1:
                ruta.append((float(xs[i]), float(alto[j, i]), float(zs[j])))
    return ruta
