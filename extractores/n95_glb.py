#!/usr/bin/env python3
"""
n95_glb.py: los modelos del N95 con menos triangulos (para 30 fps: ~6.000 triangulos por cuadro en total). Recibe las
lineas del harness de un armado y cambia cada "importgltf X.glb" por una copia simplificada de X
(tools_r100/simplificar_glb.py), segun REGLAS (nombre del archivo -> proporcion de triangulos que queda).

La copia va a out/n95_glb/<carpeta de X>/<el MISMO nombre>.glb: el armado busca los objetos importados por el nombre
del archivo ("activename leon_combate_radio_rig"). Se rehace solo si X cambio o cambio su regla.
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools_r100'))
import simplificar_glb  # noqa: E402

CARPETA = os.path.join(HERE, 'out', 'n95_glb')

# (patron del nombre del archivo, proporcion, permisivo). La primera que coincide. Lo que no coincide queda entero (la
# utileria chica, la pistola, la radio, las ventanas). Las CARAS cuidan sus shape keys (simplificar_glb).
# Lo que se DEFORMA (personajes) es lo caro en el N95: skinning por CPU y luces por vertice en cada cuadro -> mas
# reduccion, cruzando costuras de UV (permisivo). Lo ESTATICO (los vehiculos: su esqueleto solo mueve piezas enteras
# cuando hay una animacion) cuesta poco por triangulo -> menos reduccion y sin cruzar costuras (al 12 % la camioneta
# quedaba destruida).
REGLAS = [
    (r'^leon_combate', 0.2, True),            # Leon de juego (ya simplificado por re4_extract_leon): ~1.150
    (r'^ganado_(juego|e\d+)', 0.18, True),    # los aldeanos de juego: ~600 cada uno
    (r'^leon_evento', 0.2, True),             # los personajes de las cinematicas
    (r'^ganado_evento', 0.25, True),
    (r'^policia(_a)?_evento', 0.2, True),
    (r'^policia(_a)?_juego', 0.15, True),
    (r'^(leon|hunnigan)_codec', 0.3, True),   # los retratos de la radio (de cerca)
    (r'^(coche|camion)_', 0.4, False),        # los vehiculos
    (r'^obm(1a00|2d00)$', 0.4, False),        # la camioneta de la intro y el camion del puente
]
ERROR = 0.05


def regla(ruta):
    """(proporcion, permisivo) o None"""
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    for patron, prop, permisivo in REGLAS:
        if re.search(patron, nombre):
            return prop, permisivo
    return None


def copia(ruta, log=print):
    r = regla(ruta)
    if r is None:
        return ruta
    prop, permisivo = r
    rel = os.path.relpath(os.path.dirname(os.path.abspath(ruta)), HERE)
    if rel.startswith('..'):
        rel = 'externos'
    dest = os.path.join(CARPETA, rel, os.path.basename(ruta))
    sello = dest + '.json'
    firma = {'origen': os.path.abspath(ruta), 'mtime': os.path.getmtime(ruta), 'tam': os.path.getsize(ruta),
             'prop': prop, 'error': ERROR, 'permisivo': permisivo}
    if os.path.isfile(dest) and os.path.isfile(sello):
        try:
            if json.load(open(sello)) == firma:
                imagenes(ruta, dest)
                return dest
        except ValueError:
            pass
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    simplificar_glb.simplificar(ruta, dest, prop, ERROR, permisivo=permisivo, log=log)
    json.dump(firma, open(sello, 'w'))
    imagenes(ruta, dest)
    return dest


def imagenes(ruta, dest):
    """las imagenes que el glb referencia por archivo (no adentro): al lado de la copia, con la misma ruta relativa"""
    J, _ = simplificar_glb.leer_glb(ruta)
    for im in J.get('images', []):
        uri = im.get('uri')
        if not uri or uri.startswith('data:') or os.path.isabs(uri):
            continue
        a = os.path.join(os.path.dirname(os.path.abspath(ruta)), uri)
        b = os.path.join(os.path.dirname(dest), uri)
        if os.path.isfile(a) and (not os.path.isfile(b) or os.path.getmtime(b) < os.path.getmtime(a)):
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(a, b)


def simplificadas(lineas, log=print):
    """las lineas del harness con cada importgltf apuntando a su copia del N95"""
    out = []
    for l in lineas:
        if l.startswith('importgltf '):
            l = 'importgltf ' + copia(l[len('importgltf '):].strip(), log)
        out.append(l)
    return out
