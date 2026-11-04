"""
meshopt.py — lo minimo de meshoptimizer (zeux/meshoptimizer, MIT, ver LICENSE.md) por ctypes, para los LOD del
escenario (re4_extract_r100.py). La libreria se compila sola la primera vez:

    g++ -O2 -shared -fPIC src/*.cpp -o libmeshopt.so   (en Windows: -static ... -o meshopt.dll)
"""
import ctypes
import os
import subprocess

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(AQUI, 'meshopt.dll' if os.name == 'nt' else 'libmeshopt.so')

LOCK_BORDER = 1 << 0
PRUNE = 1 << 3
PERMISSIVE = 1 << 5   # colapsa a traves de las costuras de UV/color (para LOD lejanos, con niebla no se nota)

_lib = None


def _cargar():
    global _lib
    if _lib is None:
        if not os.path.isfile(LIB):
            fuentes = [os.path.join(AQUI, 'src', f) for f in sorted(os.listdir(os.path.join(AQUI, 'src')))
                       if f.endswith('.cpp')]
            subprocess.check_call(['g++', '-O2', '-shared'] + (['-static'] if os.name == 'nt' else ['-fPIC']) + fuentes +
                                  ['-o', LIB])
        _lib = ctypes.CDLL(LIB)
        p = ctypes.c_void_p
        _lib.meshopt_simplifyWithAttributes.restype = ctypes.c_size_t
        _lib.meshopt_simplifyWithAttributes.argtypes = [p, p, ctypes.c_size_t, p, ctypes.c_size_t, ctypes.c_size_t,
                                                        p, ctypes.c_size_t, p, ctypes.c_size_t, p, ctypes.c_size_t,
                                                        ctypes.c_float, ctypes.c_uint, p]
        _lib.meshopt_optimizeVertexCache.restype = None
        _lib.meshopt_optimizeVertexCache.argtypes = [p, p, ctypes.c_size_t, ctypes.c_size_t]
    return _lib


def _p(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def simplificar(idx, pos, attrs, pesos, proporcion, error, opciones=0, bloqueados=None):
    """indices (n*3) simplificados a ~proporcion de los triangulos sin pasar 'error' (relativo al tamanio de la
    malla). attrs: (nv, k) float32 (uv, color...) con 'pesos' (k). bloqueados: (nv,) bool, los vertices que no se
    mueven ni se colapsan (p.ej. los que deforman las shape keys). Devuelve (indices, error logrado)."""
    lib = _cargar()
    idx = np.ascontiguousarray(idx, np.uint32)
    pos = np.ascontiguousarray(pos, np.float32)
    attrs = np.ascontiguousarray(attrs, np.float32)
    pesos = np.ascontiguousarray(pesos, np.float32)
    bloq = None if bloqueados is None else np.ascontiguousarray(bloqueados, np.uint8)
    dest = np.zeros(len(idx), np.uint32)
    objetivo = max(3, int(len(idx) * proporcion) // 3 * 3)
    err = ctypes.c_float(0.0)
    n = lib.meshopt_simplifyWithAttributes(_p(dest), _p(idx), len(idx), _p(pos), len(pos), 12, _p(attrs),
                                           attrs.shape[1] * 4, _p(pesos), attrs.shape[1],
                                           None if bloq is None else _p(bloq), objetivo,
                                           ctypes.c_float(error), ctypes.c_uint(opciones), ctypes.byref(err))
    return dest[:n].copy(), err.value


def orden_cache(idx, nv):
    """reordena los triangulos para el cache de vertices del GPU (el N95 no lo hace al cargar)."""
    lib = _cargar()
    idx = np.ascontiguousarray(idx, np.uint32)
    dest = np.zeros(len(idx), np.uint32)
    lib.meshopt_optimizeVertexCache(_p(dest), _p(idx), len(idx), nv)
    return dest
