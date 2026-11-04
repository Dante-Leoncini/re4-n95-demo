#!/usr/bin/env python3
"""
claves_r100.py: saca las claves REDUNDANTES de las animaciones de escena (las camaras y los objetos de las
cinematicas). Vienen horneadas: una clave por frame, todas lineales. Una clave que cae sobre la recta entre sus
vecinas (dentro de una tolerancia que no se ve) no aporta nada: la curva lineal entre las que quedan pasa por el
mismo lugar. Las de interpolacion constante que repiten el valor anterior tampoco.

Por que: el proyecto.json se parsea ENTERO al abrir (cada clave es un nodo en memoria hasta terminar de abrir) y
despues cada clave queda como un keyframe de 32 B. En el N95 la carga se quedaba sin memoria; esto saca dos
tercios de las claves (34.761 -> ~12.000) en las dos versiones.

  tolerancias   posicion 1 mm, rotacion 0.02 grados, escala 0.0005, campo de vision 0.01 grados,
                shape keys 0.002 (los pesos van de 0 a 1)

  python3 claves_r100.py NIVEL.w3d
"""
import json
import os
import sys
import zipfile

# por canal (AnimProperty::tipo): AnimPosition, AnimRotation, AnimScale, AnimFov y los pesos de shape keys
TOLERANCIA = {0: 0.001, 1: 0.02, 2: 0.0005, 6: 0.01, 15: 0.002}
LINEAL, CONSTANTE = 1, 0


def reducir_lineal(k, tol):
    """k: claves [frame, valor, interp, tipoH, inDF, inDV, outDF, outDV] lineales. Se queda con la primera, la
    ultima y las que la recta entre las que quedan no reproduce dentro de tol (en TODOS los frames del medio)"""
    if len(k) <= 2:
        return k
    out = [k[0]]
    i = 0
    while i < len(k) - 1:
        j = i + 1
        while j + 1 < len(k):
            a, b = k[i], k[j + 1]
            df = float(b[0] - a[0])
            if df <= 0:
                break
            bien = True
            for m in range(i + 1, j + 1):
                t = (k[m][0] - a[0]) / df
                if abs(a[1] + (b[1] - a[1]) * t - k[m][1]) > tol:
                    bien = False
                    break
            if not bien:
                break
            j += 1
        out.append(k[j])
        i = j
    return out


def reducir_constante(k):
    """escalones: sobra la que repite el valor de la anterior (la ultima queda: marca el final del rango)"""
    return [x for i, x in enumerate(k) if i == 0 or i == len(k) - 1 or x[1] != k[i - 1][1]]


def reducir_curva(c):
    k = c.get('k') or []
    if len(k) <= 2 or any(len(x) < 8 for x in k):
        return k
    sin_handles = all(not any(x[4:8]) for x in k)
    if sin_handles and all(x[2] == LINEAL for x in k) and c.get('p') in TOLERANCIA:
        return reducir_lineal(k, TOLERANCIA[c['p']])
    if all(x[2] == CONSTANTE for x in k):
        return reducir_constante(k)
    return k        # bezier (los handles automaticos dependen de las vecinas) u otra mezcla: queda como esta


def reducir_proyecto(pj):
    antes = despues = 0
    for e in ((pj.get('animaciones') or {}).get('escenas') or []):
        for o in e.get('objetos') or []:
            for c in o.get('curvas') or []:
                antes += len(c.get('k') or [])
                c['k'] = reducir_curva(c)
                despues += len(c['k'])
    return antes, despues


def reducir(w3d, log=print):
    with zipfile.ZipFile(w3d) as z:
        infos = z.infolist()
        datos = dict((i.filename, z.read(i.filename)) for i in infos)
    pj = json.loads(datos['proyecto.json'])
    antes, despues = reducir_proyecto(pj)
    datos['proyecto.json'] = json.dumps(pj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    tmp = w3d + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        for i in infos:
            zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            zi.compress_type = i.compress_type
            zi.external_attr = i.external_attr
            z.writestr(zi, datos[i.filename])
    os.replace(tmp, w3d)
    log('   claves de las animaciones de escena: %d -> %d (las que caen sobre la recta de sus vecinas)'
        % (antes, despues))


if __name__ == '__main__':
    for ruta in sys.argv[1:]:
        reducir(ruta)
