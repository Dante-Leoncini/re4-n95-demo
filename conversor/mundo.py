"""EL ESCENARIO de r100 (el camino, la casa, el puente) para el N95: mundo.bin.

La fuente es lo que extrajo re3_w3d (out/r100_n95: el mapa del juego ya simplificado para el telefono, cada chunk con
sus tres niveles de detalle L0 / L1 / L2, la luz horneada en el color de vertice) y el streaming de bloques del juego
(r100.json: las areas del BLK y que bloques se ven desde cada una; pvs_interior.json: lo que se ve desde ADENTRO de la
casa).

Cada nivel de cada chunk es una PIEZA con su caja. Las piezas se juntan en MALLAS (hasta 60000 vertices: indices de 16
bits) por cercania; adentro de cada malla los triangulos van ordenados por pasada, material y pieza: lo visible de un
material queda en tramos seguidos y sale en pocas llamadas. Posiciones y UV en enteros de 16 bits (la escala va en las
matrices), color RGBA en bytes.

    'MUN1'
    u32 nmallas; por malla: u32 nv, ni; f32 origen[3], escala, escala_uv; i16 pos[nv*3]; i16 uv[nv*2]; u8 col[nv*4];
                            u16 idx[ni]
    u32 nmateriales; por material: u32 textura, banderas (1 mezcla, 2 caras de atras afuera, 4 no escribe z, 8 recorte)
    u32 npiezas; por pieza: u16 chunk, u8 lod, u8 clase (0 chunk, 1 fondo, 2 cielo), f32 min[3], max[3]; u32 bloque
                            (0xFF siempre), u8 adentro,
                            u8 puente (0 no, 1 sano, 2 roto), u16 0
    u32 nchunks; por chunk: u16 primera pieza, u16 cuantas
    u32 ndibujos; por dibujo: u16 malla, u16 material, u8 pasada (0 opaco, 1 recorte, 2 mezcla), u8 0, u16 nrangos; por rango: u16 pieza, u16 0,
                            u32 desde, u32 cantidad (en indices)
    u32 nareas; por area: f32 piso, alto, pts[8]; u32 visibles (un bit por bloque), prioridad
"""
import json
import math
import os
import struct

import numpy as np

import sys

import binario
import glb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'meshopt'))

# cuanto se aclara el interior de la casa (los colores de vertice)
CASA_LUZ = 1.0
import meshopt  # noqa: E402

MAX_VERTS = 60000
CELDA = 24.0
CLASES = {'opaco': 0, 'alfa': 1}
MEZCLA, CULL, SIN_Z, RECORTE = 1, 2, 4, 8


def leer(dir_mapa, texturas, log=print, l0=0.45):
    g = glb.Glb(os.path.join(dir_mapa, 'r100.glb'))
    J = g.json
    info = json.load(open(os.path.join(dir_mapa, 'r100.json')))
    pvs = set(json.load(open(os.path.join(dir_mapa, 'pvs_interior.json')))['visibles'])

    # los materiales: textura (del registro) + banderas
    mats = []
    for m in J['materials']:
        ex = m.get('extras', {})
        tex = m['pbrMetallicRoughness'].get('baseColorTexture')
        ti = 0xFFFFFFFF
        if tex is not None:
            src = J['textures'][tex['index']]['source']
            uri = J['images'][src]['uri']
            ti = texturas.agregar('m_' + os.path.basename(uri)[:-4], os.path.join(dir_mapa, uri),
                                  repetir=ex.get('w3d_repeat', True))
        b = 0
        if ex.get('w3d_transparent') or m.get('alphaMode') == 'BLEND':
            # (el alfa de un bit -las plantas, los arboles- se RECORTA y escribe z: no hace falta ordenarlo)
            b |= RECORTE if texturas.formato(ti) == 'recorte' else (MEZCLA | SIN_Z)
        if ex.get('w3d_culling', True):
            b |= CULL
        mats.append((ti, b))

    # las piezas (nodo = chunk_Ln): sus triangulos por material, en mundo
    por_nombre = {p['nombre']: p for p in info['piezas']}
    piezas = []
    for k, nodo in enumerate(J['nodes']):
        if 'mesh' not in nodo:
            continue
        nombre = nodo['name']
        p = por_nombre.get(nombre)
        # (la puerta de la casa va aparte, abierta: props.cpp; en el mapa esta cerrada)
        if not p or p['grupo'] == 'colision' or nombre == 'r100_puerta':
            continue
        t = np.array(nodo.get('translation', [0, 0, 0]), np.float64)
        partes = []
        for prim in J['meshes'][nodo['mesh']]['primitives']:
            pos = g.accessor(prim['attributes']['POSITION']).astype(np.float64) + t
            uv = g.accessor(prim['attributes']['TEXCOORD_0']).astype(np.float64)
            col = g.accessor(prim['attributes']['COLOR_0'])
            if col.dtype != np.uint8:
                col = np.clip(col * 255 + 0.5, 0, 255).astype(np.uint8)
            if col.shape[1] == 3:
                col = np.c_[col, np.full(len(col), 255, np.uint8)]
            idx = g.accessor(prim['indices']).astype(np.int64).reshape(-1, 3)
            casa = p['grupo'] == 'b1'
            if casa:
                # (adentro de la casa, mas claro: en la pantalla del N95 el cuarto con la luz del fuego quedaba negro)
                den = ((pos[:, 0] > -85.5) & (pos[:, 0] < -71.4) & (pos[:, 2] > -42.2) & (pos[:, 2] < -30.2) &
                       (pos[:, 1] < 4.5))
                col = col.copy()
                col[den, :3] = np.clip(col[den, :3].astype(np.float32) * CASA_LUZ + 0.5, 0, 255).astype(np.uint8)
            # (la casa no: sus escalones, el marco de la puerta y la persiana se ven de cerca y se rompian)
            if p['lod'] == 0 and p['grupo'][:1] == 'b' and not casa and len(idx) > 120 and l0 < 0.999:
                # (el L0 del N95 todavia mas liviano: los bordes quietos, que no se abran rendijas entre chunks)
                at = np.c_[uv, col[:, :3] / 255.0].astype(np.float32)
                # (la casa se ve de cerca en las cinematicas: menos y con los bordes quietos)
                s, _ = meshopt.simplificar(idx.reshape(-1), pos, at, np.array([1, 1, 0.5, 0.5, 0.5], np.float32),
                                           0.45 if casa else l0, 0.02 if casa else 0.06,
                                           meshopt.LOCK_BORDER if casa else 0)
                if len(s) >= 3:
                    idx = s.astype(np.int64).reshape(-1, 3)
            partes.append((prim['material'], pos, uv, col, idx))
        if not partes:
            continue
        todo = np.concatenate([q[1] for q in partes])
        chunk = p.get('chunk', nombre.rsplit('_L', 1)[0])
        grupo = p['grupo']
        bloque = int(grupo[1:]) if grupo[:1] == 'b' and grupo[1:].isdigit() else 0xFF
        puente = 1 if grupo == 'puente_sano' else 2 if grupo == 'puente_roto' else 0
        clase = 2 if grupo == 'cielo' else 1 if grupo == 'fondo' else 0
        piezas.append({'nombre': nombre, 'chunk': chunk, 'lod': p['lod'], 'clase': clase,
                       'grupo': grupo, 'bloque': bloque, 'puente': puente,
                       'adentro': 1 if (chunk in pvs or chunk.split('_c')[0] in pvs) else 0,
                       'min': todo.min(0), 'max': todo.max(0), 'partes': partes})
    # (cada chunk con sus niveles juntos, L0 primero)
    piezas.sort(key=lambda p: (p['chunk'], p['lod']))
    chunks = []
    for i, p in enumerate(piezas):
        if not chunks or chunks[-1][0] != p['chunk']:
            chunks.append([p['chunk'], i, 0])
        chunks[-1][2] += 1
        p['ichunk'] = len(chunks) - 1
    log('mundo: %d piezas en %d chunks, %d materiales' % (len(piezas), len(chunks), len(mats)))
    return piezas, chunks, mats, info


def armar(piezas, chunks, mats, info, ruta, log=print):
    # LAS MALLAS: los chunks (con todos sus niveles) por celdas de CELDA m recorridas en zigzag, hasta MAX_VERTS
    def centro(c):
        ps = piezas[c[1]:c[1] + c[2]]
        mn = np.min([p['min'] for p in ps], 0)
        mx = np.max([p['max'] for p in ps], 0)
        return (mn + mx) / 2, mx - mn
    orden = []
    for ci, c in enumerate(chunks):
        cen, tam = centro(c)
        grande = float(max(tam[0], tam[2])) > 60
        cx = int(cen[0] // CELDA)
        orden.append(((grande, cx, int(cen[2] // CELDA) * (1 if cx % 2 == 0 else -1), float(cen[0])), ci))
    orden.sort()
    uniones, actual, nv = [], [], 0
    for _, ci in orden:
        c = chunks[ci]
        v = sum(len(q[1]) for p in piezas[c[1]:c[1] + c[2]] for q in p['partes'])
        if actual and nv + v > MAX_VERTS:
            uniones.append(actual)
            actual, nv = [], 0
        actual.append(ci)
        nv += v
    if actual:
        uniones.append(actual)

    w = binario.Escritor().b(b'MUN1').s('I', len(uniones))
    dibujos = []
    total_v = total_t = 0
    for u, cis in enumerate(uniones):
        # los triangulos de la malla: (pasada, material, pieza) -> sus triangulos. Los VERTICES van en el mismo orden
        # que los triangulos (cada dibujo toca un rango corto: el driver del N95 transforma todo el rango de cada
        # glDrawElements) y numerados por su primer uso, con los triangulos ordenados para el cache de vertices
        tramos = {}   # (pasada, mat) -> [(pieza, pos, uv, col, tris)]
        for ci in cis:
            c = chunks[ci]
            for pi in range(c[1], c[1] + c[2]):
                p = piezas[pi]
                for mat, pos, uv, col, idx in p['partes']:
                    clave = np.concatenate([np.round(pos, 4), np.round(uv, 5), col.astype(np.float64)], 1)
                    _, primero, inv = np.unique(clave, axis=0, return_index=True, return_inverse=True)
                    t = inv.reshape(-1)[idx].reshape(-1)
                    t = meshopt.orden_cache(t, len(primero)).astype(np.int64)
                    _, pv = np.unique(t, return_index=True)
                    uso = t[np.sort(pv)]
                    nuevo = np.empty(len(primero), np.int64)
                    nuevo[uso] = np.arange(len(uso))
                    src = primero[uso]
                    pasada = 2 if mats[mat][1] & MEZCLA else 1 if mats[mat][1] & RECORTE else 0
                    tramos.setdefault((pasada, mat), []).append((pi, pos[src], uv[src], col[src], nuevo[t]))
        pos_l, uv_l, col_l, idx_l = [], [], [], []
        base = desde = 0
        for (pasada, mat) in sorted(tramos):
            rangos = []
            for pi, pp, uu, cc, t in tramos[(pasada, mat)]:
                pos_l.append(pp); uv_l.append(uu); col_l.append(cc)
                idx_l.append(t + base)
                rangos.append((pi, desde, t.size))
                base += len(pp)
                desde += t.size
            dibujos.append((u, mat, pasada, rangos))
        pos = np.concatenate(pos_l)
        uv = np.concatenate(uv_l)
        col = np.concatenate(col_l)
        # enteros: la posicion relativa al origen de la malla con su escala; las UV con la suya
        mn, mx = pos.min(0), pos.max(0)
        origen = (mn + mx) / 2
        escala = float(max(mx - mn)) / 2 / 32000.0 or 1e-4
        pos16 = np.round((pos - origen) / escala).astype(np.int16)
        umax = float(np.abs(uv).max()) or 1.0
        escala_uv = 2.0 ** math.ceil(math.log2(umax / 32000.0))
        uv16 = np.round(uv / escala_uv).astype(np.int16)
        idx = np.concatenate(idx_l).astype(np.uint16)
        assert len(pos) < 65536
        w.s('II', len(pos), len(idx)).s('5f', origen[0], origen[1], origen[2], escala, escala_uv)
        w.b(pos16.tobytes()).alinear().b(uv16.tobytes()).alinear().b(np.ascontiguousarray(col, np.uint8).tobytes())
        w.alinear().b(idx.tobytes()).alinear()
        total_v += len(pos)
        total_t += len(idx) // 3
    w.s('I', len(mats))
    for ti, b in mats:
        w.s('II', ti, b)
    w.s('I', len(piezas))
    for p in piezas:
        w.s('HBB', p['ichunk'], p['lod'], p['clase']).s('6f', *p['min'], *p['max'])
        w.s('IBBH', p['bloque'], p['adentro'], p['puente'], 0)
    w.s('I', len(chunks))
    for c in chunks:
        w.s('HH', c[1], c[2])
    # opaco primero (por material: menos cambios de textura), despues lo mezclado
    dibujos.sort(key=lambda d: (d[2], d[1], d[0]))
    w.s('I', len(dibujos))
    for u, mat, pasada, rangos in dibujos:
        w.s('HHBBH', u, mat, pasada, 0, len(rangos))
        for pi, desde, n in rangos:
            w.s('HHII', pi, 0, desde, n)
    areas = info['bloques']['areas']
    w.s('I', len(areas))
    for a in areas:
        pts = [c for p in a['pts'] for c in p]
        vis = 0
        for b in a['visibles']:
            vis |= 1 << b
        w.s('10f', a['piso'], a['alto'], *pts).s('Ii', vis, a.get('prioridad', 0))
    n = w.guardar(ruta)
    log('mundo.bin: %d mallas, %d vertices, %d triangulos, %d dibujos (%d KB)' % (
        len(uniones), total_v, total_t, len(dibujos), n // 1024))
