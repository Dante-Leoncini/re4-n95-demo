#!/usr/bin/env python3
"""
simplificar_glb.py: un .glb con menos triangulos (meshoptimizer), para el N95 a 30 fps. Cada primitiva de triangulos
con indices se simplifica a una PROPORCION de sus triangulos:

  * sin cruzar costuras de UV ni el BORDE de la malla (la cara y el cuerpo van en mallas aparte: un borde movido
    abre una rendija en el cuello). --permisivo y --sin-borde los sueltan (mucha mas reduccion: los personajes de
    RE4 son piezas sueltas, una por hueso, y casi todo es borde o costura);
  * las SHAPE KEYS se cuidan: sus deltas entran al simplificador como atributos (sus componentes principales), asi
    lo que arma las expresiones (boca, parpados) es lo ultimo que se colapsa;
  * los vertices que quedan se compactan con TODOS sus atributos (normales, UV, color, huesos y pesos) y los deltas
    de las shape keys; el orden de los triangulos se optimiza para el cache de vertices.

El resto del archivo (nodos, esqueleto, animaciones, materiales, imagenes) queda igual. Los datos viejos de las
primitivas tocadas quedan en el BIN sin referencias (el importador no los lee).

  python3 simplificar_glb.py ENTRADA.glb SALIDA.glb PROPORCION [--error 0.02] [--minimo 200]
"""
import argparse
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools', 'meshopt'))
import meshopt  # noqa: E402

PCA_SHAPE_KEYS = 8     # componentes principales de los deltas de las shape keys que cuida el simplificador
PESO_SHAPE_KEYS = 2.0
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def leer_glb(ruta):
    d = open(ruta, 'rb').read()
    if d[:4] != b'glTF':
        raise ValueError('%s no es un glb' % ruta)
    jl = struct.unpack_from('<I', d, 12)[0]
    J = json.loads(d[20:20 + jl])
    o = 20 + jl
    B = bytearray()
    if o + 8 <= len(d):
        bl = struct.unpack_from('<I', d, o)[0]
        B = bytearray(d[o + 8:o + 8 + bl])
    return J, B


def escribir_glb(ruta, J, B):
    B = bytes(B) + b'\0' * ((4 - len(B) % 4) % 4)
    J['buffers'][0]['byteLength'] = len(B)
    js = json.dumps(J, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(B)
    with open(ruta, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(js), 0x4E4F534A) + js)
        f.write(struct.pack('<II', len(B), 0x004E4942) + B)


def leer_accessor(J, B, i):
    a = J['accessors'][i]
    if 'sparse' in a:
        raise ValueError('accessor %d disperso: no soportado' % i)
    dt = np.dtype(COMP[a['componentType']])
    nc = NCOMP[a['type']]
    if 'bufferView' not in a:
        return np.zeros((a['count'], nc), dt)
    bv = J['bufferViews'][a['bufferView']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    tam = dt.itemsize * nc
    paso = bv.get('byteStride', 0) or tam
    filas = [np.frombuffer(B, dt, nc, off + k * paso) for k in range(a['count'])] if paso != tam else None
    if filas is not None:
        return np.array(filas, dt).reshape(a['count'], nc)
    return np.frombuffer(B, dt, a['count'] * nc, off).reshape(a['count'], nc).copy()


def agregar_accessor(J, B, arr, modelo, destino):
    """arr (n, nc) con el tipo del accessor 'modelo' (sus campos: tipo, normalizado...). Devuelve el indice nuevo."""
    while len(B) % 4:
        B.append(0)
    datos = np.ascontiguousarray(arr).tobytes()
    J['bufferViews'].append({'buffer': 0, 'byteOffset': len(B), 'byteLength': len(datos), 'target': destino})
    B.extend(datos)
    a = {k: v for k, v in modelo.items() if k not in ('bufferView', 'byteOffset', 'count', 'min', 'max', 'sparse')}
    a['bufferView'] = len(J['bufferViews']) - 1
    a['count'] = int(arr.shape[0])
    if 'min' in modelo or 'max' in modelo:
        a['min'] = [float(x) for x in arr.min(0)] if len(arr) else modelo.get('min')
        a['max'] = [float(x) for x in arr.max(0)] if len(arr) else modelo.get('max')
    J['accessors'].append(a)
    return len(J['accessors']) - 1


def simplificar_primitiva(J, B, pr, proporcion, error, minimo, opciones=meshopt.LOCK_BORDER):
    if pr.get('mode', 4) != 4 or 'indices' not in pr or 'POSITION' not in pr['attributes']:
        return None
    idx = leer_accessor(J, B, pr['indices']).reshape(-1).astype(np.uint32)
    if len(idx) // 3 <= minimo:
        return None
    attrs = pr['attributes']
    pos = leer_accessor(J, B, attrs['POSITION']).astype(np.float32)
    # lo que el simplificador cuida ademas de la forma: UV (pesa mucho: el atlas) y normales
    cols, pesos = [], []
    if 'TEXCOORD_0' in attrs:
        uv = leer_accessor(J, B, attrs['TEXCOORD_0']).astype(np.float32)
        cols.append(uv); pesos += [1.0, 1.0]
    if 'NORMAL' in attrs:
        nr = leer_accessor(J, B, attrs['NORMAL']).astype(np.float32)
        cols.append(nr); pesos += [0.3, 0.3, 0.3]
    if not cols:
        cols.append(np.zeros((len(pos), 1), np.float32)); pesos.append(0.0)
    attr = np.concatenate(cols, 1).astype(np.float32)
    # las SHAPE KEYS: sus deltas (3 por shape key: no entran como atributos, el tope es 32) resumidos en sus
    # COMPONENTES PRINCIPALES (8 explican ~95 %), en unidades del tamanio de la malla: el simplificador colapsa
    # primero lo que deforman parecido y conserva los vertices que arman las expresiones (fijarlos no servia: las
    # expresiones mueven casi toda la cara)
    targets = pr.get('targets') or []
    deltas = [leer_accessor(J, B, t['POSITION']).astype(np.float32) for t in targets if 'POSITION' in t]
    if deltas:
        D = np.concatenate(deltas, 1)
        if np.abs(D).max() > 0:
            U, sv, _ = np.linalg.svd(D, full_matrices=False)
            k = min(PCA_SHAPE_KEYS, len(sv))
            ext = float(np.ptp(pos, 0).max()) or 1.0
            attr = np.concatenate([attr, (U[:, :k] * sv[:k]) / ext], 1).astype(np.float32)
            pesos = pesos + [PESO_SHAPE_KEYS] * k
    nuevo, err = meshopt.simplificar(idx, pos, attr, pesos, proporcion, error, opciones)
    if len(nuevo) == 0 or len(nuevo) >= len(idx):
        return None
    usados, remap = np.unique(nuevo, return_inverse=True)
    idx2 = meshopt.orden_cache(remap.astype(np.uint32), len(usados))
    # los atributos y los deltas de las shape keys, solo de los vertices que quedan
    for nombre, ai in list(attrs.items()):
        arr = leer_accessor(J, B, ai)[usados]
        attrs[nombre] = agregar_accessor(J, B, arr, J['accessors'][ai], 34962)
    for t in targets:
        for nombre, ai in list(t.items()):
            arr = leer_accessor(J, B, ai)[usados]
            t[nombre] = agregar_accessor(J, B, arr, J['accessors'][ai], 34962)
    modelo = dict(J['accessors'][pr['indices']])
    tipo = 5123 if len(usados) < 65536 else 5125
    modelo['componentType'] = tipo
    pr['indices'] = agregar_accessor(J, B, idx2.astype(COMP[tipo]).reshape(-1, 1), modelo, 34963)
    return len(idx) // 3, len(idx2) // 3


def simplificar(entrada, salida, proporcion, error=0.02, minimo=200, permisivo=False, borde=True, log=print):
    opciones = (meshopt.PERMISSIVE if permisivo else 0) | (meshopt.LOCK_BORDER if borde else 0)
    J, B = leer_glb(entrada)
    antes = despues = 0
    for m in J.get('meshes', []):
        for pr in m['primitives']:
            r = simplificar_primitiva(J, B, pr, proporcion, error, minimo, opciones)
            if r:
                antes += r[0]
                despues += r[1]
    escribir_glb(salida, J, B)
    log('   %s: %d -> %d triangulos' % (os.path.basename(entrada), antes, despues))
    return antes, despues


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('entrada')
    ap.add_argument('salida')
    ap.add_argument('proporcion', type=float)
    ap.add_argument('--error', type=float, default=0.02, help='error maximo (relativo al tamanio de la malla)')
    ap.add_argument('--minimo', type=int, default=200, help='las primitivas de hasta tantos triangulos quedan enteras')
    ap.add_argument('--permisivo', action='store_true', help='colapsa a traves de las costuras de UV (mas reduccion)')
    ap.add_argument('--sin-borde', action='store_true', help='el borde de la malla tambien se simplifica')
    a = ap.parse_args()
    simplificar(a.entrada, a.salida, a.proporcion, a.error, a.minimo, a.permisivo, not a.sin_borde)
