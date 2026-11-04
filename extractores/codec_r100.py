"""
codec_r100.py: la PRIMERA LLAMADA DE RADIO a Hunnigan (la pantalla del codec) de Resident Evil 4 (GameCube USA) en
Whisk3D. La usa make_r100_w3d.py. Datos (re4_extract_codec.py / re4_extract_texto.py / re4_extract_intro_r100.py):

  out/codec/codec.json            linea de tiempo (relojes g / c / s), rectangulos de las ventanas, camaras, luces
  out/codec/leon_codec.glb        Leon de la terminal (clips "espera" y "llamada", cabeza con 10 shape keys)
  out/codec/hunnigan_codec.glb    Hunnigan (clips "espera" y "llamada", cabeza con 9 shape keys)
  out/codec/caras.json            pesos de las caras por frame del clip "llamada"
  out/codec/ui/ui.json + tex_*    las unidades 2D del IDSystem (fondo / frente) con sus pistas por frame
  out/codec/audio/*.wav           voz (str1_140), tono de la radio (str1_003), SE de abrir / cerrar
  out/texto/mensajes_en.json      los subtitulos (codec_op01, op 0) ; out/texto/whisk3d/fuente_re4_codec_x125.*
  out/r100_intro/radio.glb        la radio en la mano izquierda de Leon (vertices en el espacio de hueso_016)

Uso (desde make_r100_w3d.py):

    lineas += codec_r100.lineas_importar()          # importa los dos personajes del codec y los fondos de las ventanas
    ...
    codec_r100.aplicar(proy, datos, extra)          # DESPUES de hud_r100.agregar; el Recorte queda ultimo

LO QUE AGREGA:
  * Empty "Codec" con scripts/codec.lua (lua/codec.lua + las tablas que genera este modulo en la marca --@@DATOS@@)
    y las dos luces direccionales del codec (ocultas: codec.lua las prende y apaga las del mundo durante la llamada).
  * Recorte "Codec_pantalla" (pantalla completa, fondo, oculto): va ULTIMO en el arbol 3D -> tapa el mundo. Adentro:
      Recorte "Codec_ventana_hunnigan"  camara Codec_cam_hunnigan (+ el plano del fondo de la ventana) + Hunnigan
      Recorte "Codec_ventana_leon"      camara Codec_cam_leon     (+ el plano del fondo)               + LeonCodec
    Los personajes estan en el "espacio del codec" (origen ORIGEN, debajo del mapa: la camara del juego nunca los ve).
    Cada ventana usa la camara simetrica girada hacia el centro de la ventana (codec.json: aprox_simetrica).
  * Leon_radio: la radio (Child Of hueso_016 de Leon, oculta) - la busca por nombre donde este (la importa quien
    arme a Leon; lineas_importar(radio=True) la importa sola).
  * Animacion de escena "codec": las curvas de las caras (p 15) de LeonCodec_cabeza y Hunnigan_cabeza.
  * La capa 2D "frente" del juego (marco, tintes, estatica, destellos, lineas) y el subtitulo con la fuente del codec:
    un contenedor "codec_ui_raiz" (oculto) que se mete ADENTRO de escenas/hud.w3dui, justo antes de "hud_fundido"
    (Whisk3D trata cada nodo UI de la raiz como una escena UI EXCLUSIVA: un .w3dui propio apagaba al HUD). Por eso
    aplicar() va DESPUES de hud_r100.agregar (si no hay HUD, agrega escenas/codec.w3dui propio).
  * Sonidos: sonidos/codec_voz.wav, codec_tono.wav, codec_abrir.wav, codec_cerrar.wav.

PANTALLA: el juego es letterbox (640x480 virtuales, se ven las filas 60..420) = nuestro marco de camara (1.7725).
Una fraccion "centro" de codec.json (alto = 480) pasa a la del marco con y * 480/360, alto * 480/360.

APROXIMACIONES (limitaciones de la UI de Whisk3D, ver el informe):
  * las unidades con efecto de pantalla (trans_type 2/3 = copia de la pantalla corrida por una textura indirecta:
    la distorsion / nieve de las ventanas, ids 1B 02 03 0A 37 12 15 28 2B) no se dibujan (identidad). La suma de
    02/03 (+18% de la pantalla sobre las ventanas) se pasa a las luces del codec (x1.18).
  * blend 3 (GX DSTCLR, ONE = dst * (1 + src)) no existe: se usa aditiva ponderada con el color x 0.3 (fondo supuesto).
  * la capa "fondo" (se dibuja ANTES que los modelos) se hornea en un plano texturado detras de cada personaje.
"""
import json
import math
import os
import struct
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
CODEC = os.path.join(OUT, 'codec')
CODEC_JSON = os.path.join(CODEC, 'codec.json')
UI_JSON = os.path.join(CODEC, 'ui', 'ui.json')
CARAS = os.path.join(CODEC, 'caras.json')
GLB_LEON = os.path.join(CODEC, 'leon_codec.glb')
GLB_HUNNIGAN = os.path.join(CODEC, 'hunnigan_codec.glb')
GLB_RADIO = os.path.join(OUT, 'r100_intro', 'radio.glb')
MENSAJES = os.path.join(OUT, 'texto', 'mensajes_en.json')
FUENTE = os.path.join(OUT, 'texto', 'whisk3d', 'fuente_re4_codec_x125')
LUA = os.path.join(HERE, 'lua', 'codec.lua')

ENTRADA_UI = 'escenas/codec.w3dui'
ENTRADA_LUA = 'scripts/codec.lua'
TEX = 'texturas/codec/'
SON = 'sonidos/codec_'

ORIGEN = (0.0, -300.0, 0.0)       # el espacio del codec: lejos debajo del mapa
ARM_LEON, ARM_HUNNIGAN = 'LeonCodec', 'Hunnigan'
HUESO_RADIO = 'hueso_016'          # mano izquierda de Leon (parentSet(pl, 0x10, ...))
FILAS = 360.0                      # filas virtuales visibles (60..420)
FONDO_DIST = 2.6                   # m: el plano del fondo de cada ventana, detras del personaje
FONDO_MARGEN = 6.0                 # px virtuales de mas alrededor de la ventana (el marco tapa el borde)
BRILLO_DISTORSION = 1.18           # las unidades 02/03 SUMAN 45/255 de la pantalla corrida sobre las ventanas
# blend de las unidades del juego -> w3dEngine::Mezcla (1 alpha, 2 add, 3 add ponderada por alpha, 4 multiplicar)
MEZCLA = {0: 1, 1: 3, 2: 2, 3: 3, 4: 4}
BLEND3_ESCALA = 0.3                # blend 3 (dst * (1 + src)): aditiva con el color x el fondo supuesto
SUBTITULO_Y = 320.0                # MesSet(y = (240 + 80) * 0.8) en 512x384 -> 320 en 640x480 (tope de la 1ra linea)
_TMP = {}


def _salida():
    """carpeta temporal (una por proceso) para lo generado: el glb de los fondos, sus texturas, el .w3dui y la lua"""
    if 'dir' not in _TMP:
        _TMP['dir'] = tempfile.mkdtemp(prefix='codec_r100_')
    return _TMP['dir']


def _doc_glb(ruta):
    g = open(ruta, 'rb').read()
    jl = struct.unpack('<I', g[12:16])[0]
    return json.loads(g[20:20 + jl])


def _mallas(ruta):
    return [n.get('name', '') for n in _doc_glb(ruta)['nodes'] if 'mesh' in n]


def _codec():
    return json.load(open(CODEC_JSON))


# ---------------------------------------------------------------------------------------------------------------
#  geometria de la pantalla
# ---------------------------------------------------------------------------------------------------------------
def _rect_marco(fc):
    """frac_centro de codec.json (alto 480, +y arriba) -> (x, y, ancho, alto) del Recorte en el marco (alto 360)"""
    k = 480.0 / FILAS
    return round(fc['cx'], 6), round(fc['cy'] * k, 6), round(fc['w'], 6), round(fc['h'] * k, 6)


def _euler_xyz(eye, tgt, up):
    """rot euler XYZ (grados, Whisk3D: Qx*Qy*Qz) de una camara que mira de eye a tgt (-Z local, +Y arriba)"""
    f = [t - e for t, e in zip(tgt, eye)]
    n = math.sqrt(sum(c * c for c in f)) or 1.0
    f = [c / n for c in f]
    r = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]]
    n = math.sqrt(sum(c * c for c in r)) or 1.0
    r = [c / n for c in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    z = [-c for c in f]
    R = [[r[0], u[0], z[0]], [r[1], u[1], z[1]], [r[2], u[2], z[2]]]
    b = math.asin(max(-1.0, min(1.0, R[0][2])))
    a = math.atan2(-R[1][2], R[2][2])
    c = math.atan2(-R[0][1], R[0][0])
    return [round(math.degrees(a), 5), round(math.degrees(b), 5), round(math.degrees(c), 5)]


def _rot_desde_y(s):
    """rot euler (grados) de una lampara direccional cuya luz VIENE de la direccion s (Whisk3D: +Y local rotado)"""
    n = math.sqrt(sum(c * c for c in s)) or 1.0
    x, y, z = (c / n for c in s)
    rz = math.asin(max(-1.0, min(1.0, -x)))
    rx = math.atan2(z, y)
    return [round(math.degrees(rx), 4), 0.0, round(math.degrees(rz), 4)]


def _ventanas(cj):
    """[(clave, rect_px, frac_centro, camara)] de las dos ventanas del marco"""
    lay = cj['layout']
    return [(clave, lay['ventana_' + clave]['px_640x480'], lay['ventana_' + clave]['frac_centro'],
             lay['ventana_' + clave]['camara']) for clave in ('hunnigan', 'leon')]


# ---------------------------------------------------------------------------------------------------------------
#  la capa "fondo" horneada (gris + dos brillos): se dibuja ANTES que los modelos -> un plano detras de cada uno
# ---------------------------------------------------------------------------------------------------------------
def _rgba01(ruta):
    return np.asarray(Image.open(ruta).convert('RGBA'), np.float32) / 255.0


def _capa_fondo(ui, esc=4):
    """la capa fondo del juego (unidades fondo_*, blend 0) sobre negro, a esc x 640x480 (RGB 0..1)"""
    H, W = 480 * esc, 640 * esc
    img = np.zeros((H, W, 3), np.float32)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    xs, ys = (xs + 0.5) / esc, (ys + 0.5) / esc
    for nombre, u in ui['unidades'].items():
        if u['capa'] != 'fondo':
            continue
        t = [p for p in ui['pistas'][nombre] if p[1]][0]
        (x0, y0), _, (x1, y1), _ = t[3]
        col = np.array(t[4], np.float32) / 255.0
        tex = _rgba01(os.path.join(CODEC, u['archivo']))
        th, tw = tex.shape[:2]
        du, dv = (xs - x0) / (x1 - x0), (ys - y0) / (y1 - y0)
        dentro = (du >= 0) & (du < 1) & (dv >= 0) & (dv < 1)
        s = tex[np.clip((dv * th).astype(int), 0, th - 1), np.clip((du * tw).astype(int), 0, tw - 1)]
        rgb, a = s[..., :3] * col[:3], (s[..., 3] * col[3])[..., None]
        img = np.where(dentro[..., None], rgb * a + img * (1 - a), img)
    return img


def _glb_fondos(dir_salida):
    """codec_fondo.glb: un quad por ventana (en el espacio LOCAL de su camara: z = -FONDO_DIST, del tamano del
    frustum + margen) con la capa fondo recortada a esa ventana. Devuelve (ruta, {clave: color medio})"""
    cj, ui = _codec(), json.load(open(UI_JSON))
    esc = 4
    capa = _capa_fondo(ui, esc)
    bin_ = bytearray()
    acc, vistas, mallas, mats, texs, imgs, nodos = [], [], [], [], [], [], []
    medios = {}

    def vista(datos, destino=None):
        while len(bin_) % 4:
            bin_.append(0)
        off = len(bin_)
        bin_.extend(datos)
        vistas.append({'buffer': 0, 'byteOffset': off, 'byteLength': len(datos)} |
                      ({'target': destino} if destino else {}))
        return len(vistas) - 1

    for k, (clave, px, _, cam) in enumerate(_ventanas(cj)):
        m = FONDO_MARGEN
        x0, y0, x1, y1 = px['x'] - m, px['y'] - m, px['x'] + px['w'] + m, px['y'] + px['h'] + m
        rec = capa[int(y0 * esc):int(y1 * esc), int(x0 * esc):int(x1 * esc)]
        medios[clave] = [round(float(v), 4) for v in capa[px['y'] * esc:(px['y'] + px['h']) * esc,
                                                         px['x'] * esc:(px['x'] + px['w']) * esc].mean((0, 1))]
        nombre_png = 'codec_fondo_%s.png' % clave
        Image.fromarray((np.clip(rec, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB').convert('RGBA').save(
            os.path.join(dir_salida, nombre_png))
        # el frustum simetrico de la ventana (fov vertical, aspecto de la ventana) a FONDO_DIST
        hh = FONDO_DIST * math.tan(math.radians(cam['aprox_simetrica']['fov_vertical_grados']) / 2)
        hw = hh * px['w'] / px['h']
        hh *= (px['h'] + 2 * m) / px['h']
        hw *= (px['w'] + 2 * m) / px['w']
        z = -FONDO_DIST
        pos = np.array([[-hw, -hh, z], [hw, -hh, z], [hw, hh, z], [-hw, hh, z]], np.float32)
        nor = np.array([[0, 0, 1]] * 4, np.float32)
        uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
        ind = np.array([0, 1, 2, 0, 2, 3], np.uint16)
        a0 = len(acc)
        acc.append({'bufferView': vista(pos.tobytes(), 34962), 'componentType': 5126, 'count': 4, 'type': 'VEC3',
                    'min': pos.min(0).tolist(), 'max': pos.max(0).tolist()})
        acc.append({'bufferView': vista(nor.tobytes(), 34962), 'componentType': 5126, 'count': 4, 'type': 'VEC3'})
        acc.append({'bufferView': vista(uv.tobytes(), 34962), 'componentType': 5126, 'count': 4, 'type': 'VEC2'})
        acc.append({'bufferView': vista(ind.tobytes(), 34963), 'componentType': 5123, 'count': 6, 'type': 'SCALAR'})
        imgs.append({'uri': nombre_png})
        texs.append({'source': k})
        mats.append({'name': 'Codec_fondo_%s' % clave, 'pbrMetallicRoughness': {
            'baseColorTexture': {'index': k}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0},
            'extras': {'w3d_transparent': False}})
        mallas.append({'name': 'Codec_fondo_%s' % clave, 'primitives': [{
            'attributes': {'POSITION': a0, 'NORMAL': a0 + 1, 'TEXCOORD_0': a0 + 2}, 'indices': a0 + 3,
            'material': k}]})
        nodos.append({'name': 'Codec_fondo_%s' % clave, 'mesh': k})
    doc = {'asset': {'version': '2.0', 'generator': 'codec_r100.py'}, 'scene': 0,
           'scenes': [{'nodes': list(range(len(nodos)))}], 'nodes': nodos, 'meshes': mallas, 'materials': mats,
           'textures': texs, 'images': imgs, 'accessors': acc, 'bufferViews': vistas,
           'buffers': [{'byteLength': len(bin_)}]}
    js = json.dumps(doc).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    ruta = os.path.join(dir_salida, 'codec_fondo.glb')
    with open(ruta, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A) + js)
        f.write(struct.pack('<II', len(bin_), 0x004E4942) + bytes(bin_))
    return ruta, medios


# ---------------------------------------------------------------------------------------------------------------
#  import (whisk3d --script)
# ---------------------------------------------------------------------------------------------------------------
def lineas_importar(radio=False):
    """importa LeonCodec y Hunnigan (armature + mallas con el nombre del glb) y los fondos de las ventanas
    (Codec_fondo_hunnigan / _leon). radio=True importa tambien la radio como Leon_radio (si el glb de Leon no la
    trae)."""
    import combate_r100
    out = []
    for glb, arm in ((GLB_LEON, ARM_LEON), (GLB_HUNNIGAN, ARM_HUNNIGAN)):
        base = os.path.splitext(os.path.basename(glb))[0]
        out += ['importgltf ' + glb, 'activename %s_rig' % base, 'objname ' + arm]
        noms = _mallas(glb)
        for k, m in enumerate(noms):
            out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + m]
        out += combate_r100.lineas_unir(noms, combate_r100.sueltas_de(noms))   # (menos dibujos: ver lineas_unir)
    ruta, _ = _glb_fondos(_salida())
    out += ['importgltf ' + ruta]
    for k, m in enumerate(_mallas(ruta)):
        out += ['activename ' + ('codec_fondo' if k == 0 else 'codec_fondo.%03d' % k), 'objname ' + m]
    if radio:
        out += ['importgltf ' + GLB_RADIO, 'activename radio', 'objname Leon_radio']
    return out


# ---------------------------------------------------------------------------------------------------------------
#  caras -> animacion de escena "codec"
# ---------------------------------------------------------------------------------------------------------------
def _reducir(keys, tol):
    """Ramer-Douglas-Peucker sobre (frame, valor)"""
    if len(keys) <= 2:
        return keys
    f0, v0 = keys[0]
    f1, v1 = keys[-1]
    peor, ip = -1.0, -1
    for i in range(1, len(keys) - 1):
        f, v = keys[i]
        d = abs(v - (v0 + (v1 - v0) * (f - f0) / float(f1 - f0)))
        if d > peor:
            peor, ip = d, i
    if peor <= tol:
        return [keys[0], keys[-1]]
    return _reducir(keys[:ip + 1], tol)[:-1] + _reducir(keys[ip:], tol)


def escena_caras():
    """animacion de escena "codec": frame 1 = frame 0 del clip "llamada" (codec.lua la lleva con animEscenaFrame)"""
    c = json.load(open(CARAS))
    objs, fin = [], 1
    for clave in ('leon', 'hunnigan'):
        pesos = c[clave]['pesos']
        fin = max(fin, len(pesos))
        curvas = []
        for k in range(len(c[clave]['shapes'])):
            keys = [(f + 1, float(pesos[f][k])) for f in range(len(pesos))]
            if max(abs(v) for _, v in keys) < 1e-4:
                continue
            keys = _reducir(keys, 0.002)
            curvas.append({'p': 15, 'c': k, 'k': [[f, round(v, 4), 1, 3, 0, 0, 0, 0] for f, v in keys]})
        if curvas:
            objs.append({'objeto': c[clave]['malla'], 'curvas': curvas})
    return {'nombre': 'codec', 'inicio': 1, 'fin': fin, 'fps': 30, 'objetos': objs}


# ---------------------------------------------------------------------------------------------------------------
#  la UI (capa "frente") + subtitulos
# ---------------------------------------------------------------------------------------------------------------
# las unidades de DISTORSION (trans_type 2/3: copia de la pantalla corrida por una textura indirecta) que se notan:
# la de la ventana de Hunnigan al abrir (37, hasta c 160) y las rafagas de las dos ventanas en c 33-47 (12, 28).
# Whisk3D no puede copiar la pantalla: se aproximan con un rect del color MEDIO de la ventana (la distorsion fuerte
# "borra" los rasgos), con el alfa de la unidad x un factor, dibujado ANTES que el resto de la capa frente.
DISTORSION = {'frente_37': ('hunnigan', 0.9), 'frente_12': ('hunnigan', 0.6), 'frente_28': ('leon', 0.4)}
COLOR_MEDIO = {'hunnigan': (0.247, 0.225, 0.215), 'leon': (0.185, 0.169, 0.156)}   # medido en la captura (c 237)


def _unidades_ui(ui):
    """las unidades de la capa frente que se dibujan (quad texturado con alfa > 0 alguna vez) en orden de dibujo, y
    delante las aproximaciones de DISTORSION. [(nombre, unidad, pista)]"""
    out = []
    for nombre, u in ui['unidades'].items():
        if u['capa'] != 'frente' or u['trans_type'] != 0:
            continue
        pista = ui['pistas'].get(nombre, [])
        if not any(p[1] and p[4][3] > 0 for p in pista):
            continue
        out.append((nombre, u, pista))

    def orden(e):
        p = [q for q in e[2] if q[1] and q[0] <= 40]
        return p[-1][2] if p else 999
    out.sort(key=orden)
    aprox = []
    ventanas = dict((v['nombre'], v['px_640x480']) for v in ui['ventanas_del_marco'])
    for nombre, (clave, factor) in DISTORSION.items():
        u = dict(ui['unidades'][nombre], textura='0A', archivo='ui/tex_0A.png', blend=0, trans_type=0)
        r = ventanas[clave]
        esq = [[r['x'], r['y']], [r['x'] + r['w'], r['y']], [r['x'] + r['w'], r['y'] + r['h']], [r['x'], r['y'] + r['h']]]
        col = [min(255, int(round(c * 255 * 255 / 206.0))) for c in COLOR_MEDIO[clave]]
        pista = [[p[0], p[1], p[2], esq, col + [int(round(p[4][3] * factor))], 0] if p[1] else p
                 for p in ui['pistas'][nombre]]
        aprox.append((nombre + '_aprox', u, pista))
    return aprox + out


def _ruido(u, pista):
    """True si la unidad alterna los dos cuadros de la estatica (tex 0x00) cada frame: cuadro = c % 2"""
    return u['textura'] == '00' and all(p[5] == p[0] % 2 for p in pista if p[1])


def _rect(esq):
    xs, ys = [p[0] for p in esq], [p[1] for p in esq]
    return min(xs), min(ys), max(xs), max(ys)


def _pos_tam(x0, y0, x1, y1):
    """rect en px virtuales 640x480 -> (pos relativa al centro del marco (+y abajo), ancho, alto en fraccion)"""
    return ([round(((x0 + x1) / 2 - 320.0) / 640.0, 6), round(((y0 + y1) / 2 - 240.0) / FILAS, 6), 0],
            round((x1 - x0) / 640.0, 6), round((y1 - y0) / FILAS, 6))


def _textura_ui(u):
    return TEX + ('ruido_0.png' if u['textura'] == '00' else os.path.basename(u['archivo']))


def _tinte(u, rgba):
    c = [v / 255.0 for v in rgba]
    if u['blend'] == 3:        # dst * (1 + src) ~ dst + src * fondo supuesto
        c = [v * BLEND3_ESCALA for v in c[:3]] + [c[3]]
    return [round(v, 4) for v in c]


def _fuente():
    return json.load(open(FUENTE + '.json'))


def _texto_w3d(t):
    return t.replace('\u2019', "'").replace('\u201d', '"').replace('\u201c', '\u00ab')


def _ancho_juego(fnt, linea):
    """ancho de la linea en unidades de la pantalla de mensajes del juego (512x384): suma de los avances del layout
    OPERATOR (la fuente _x125 los trae x1.25 redondeados)"""
    g = fnt['glifos']
    return sum(int(round(g[ch]['avance'] / 1.25)) if ch in g else 0 for ch in _texto_w3d(linea))


def subtitulos():
    """[(c_desde, c_hasta, texto con \\n, color rgba, x virtual del bloque)]: bloque centrado (sin attr 0x20000 /
    0x80000: todas las lineas arrancan en (512 - ancho_max) >> 1, alineadas a la izquierda)"""
    cj = _codec()
    fnt = _fuente()
    col = {'Leon': [0x87 / 255.0, 0xCF / 255.0, 0xA5 / 255.0, 1.0],
           'Hunnigan': [0xCD / 255.0, 0x7D / 255.0, 0x5F / 255.0, 1.0]}
    msj = json.load(open(MENSAJES))['tablas']['codec_op01']['llamadas'][0]['subtitulos']
    disparo = json.load(open(UI_JSON))['disparo_c']
    out = []
    for s in msj:
        lineas = [_texto_w3d(l) for l in s['lineas']]
        ancho = max(_ancho_juego(fnt, l) for l in s['lineas'])
        x = ((512 - ancho) >> 1) * 1.25
        out.append((disparo + int(round(s['desde'] * 30)), disparo + int(round(s['hasta'] * 30)),
                    '\n'.join(lineas), col[s['habla']], x))
    return out


def escena_ui(ui):
    """el .w3dui: raiz (todo el marco, oculta) con las unidades en orden de dibujo + el subtitulo"""
    hijos = []
    for nombre, u, pista in _unidades_ui(ui):
        p0 = next(p for p in pista if p[1])
        pos, w, h = _pos_tam(*_rect(p0[3]))
        e = {'tipo': 'imagen', 'nombre': 'codec_ui_' + nombre[7:], 'visible': False, 'pos': pos, 'ancla': 0,
             'rotacion': 0.0, 'opacidad': 1.0, 'ancho': w, 'alto': h, 'tamPx': False, 'tamModo': 0,
             'textura': _textura_ui(u), 'modo': 0, 'tinte': _tinte(u, p0[4]), 'usarAlpha': True, 'filtrado': True,
             'palTinte': -1, 'hijos': []}
        if MEZCLA[u['blend']] != 1:
            e['mezcla'] = MEZCLA[u['blend']]
        hijos.append(e)
    fnt = _fuente()
    hijos.append({'tipo': 'texto', 'nombre': 'codec_ui_subtitulo', 'visible': False,
                  'pos': [0.3, round((SUBTITULO_Y - 60.0) / FILAS, 6), 0], 'ancla': 5, 'texto': '',
                  # alto del renglon del juego: 25 (512x384) = 31.25 virtuales -> x alto/360; tamModo 2 mide x alto/480
                  'tam': round(25 * 1.25 * 480.0 / FILAS, 4),
                  'tamModo': 2, 'alignX': 0, 'alignY': 0, 'color': [1, 1, 1, 1], 'fuente': '',
                  'fuenteBitmap': TEX + 'fuente_codec.png', 'hijos': []})
    raiz = {'tipo': 'contenedor', 'nombre': 'codec_ui_raiz', 'visible': False, 'pos': [0, 0, 0], 'ancla': 0,
            'rotacion': 0.0, 'opacidad': 1.0, 'ancho': 1.0, 'alto': 1.0, 'tamPx': False, 'tamModo': 0,
            'hijos': hijos}
    return {'version': 1, 'nombre': 'Codec',
            'ventana': {'igualQueRender': True, 'ancho': 640, 'alto': 480, 'escalaGlobal': 1,
                        'escalaIgualEditor': False, 'color': [0, 0, 0, 0]},
            'padUni': True, 'padIzq': 0, 'padDer': 0, 'padArr': 0, 'padAba': 0,
            'layoutHijos': 0, 'layoutAjuste': 0, 'layoutAlign': 0, 'distribucion': 0, 'gap': 0, 'padGapPx': True,
            'overflowX': False, 'overflowY': False, 'scroll': False, 'scrollX': 0, 'scrollY': 0,
            'hijos': [raiz]}


def texturas_ui(ui, dir_salida):
    """{entrada del zip: archivo local} de las texturas de la UI (la estatica en dos imagenes) y la fuente"""
    out = {}
    usadas = set(os.path.basename(u['archivo']) for _, u, _ in _unidades_ui(ui) if u['textura'] != '00')
    for n in sorted(usadas):
        out[TEX + n] = os.path.join(CODEC, 'ui', n)
    out[TEX + 'ruido_0.png'] = os.path.join(CODEC, 'ui', 'tex_00.png')
    out[TEX + 'ruido_1.png'] = os.path.join(CODEC, 'ui', 'tex_00_f1.png')
    out[TEX + 'fuente_codec.png'] = FUENTE + '.png'
    out[TEX + 'fuente_codec.json'] = FUENTE + '.json'
    return out


# ---------------------------------------------------------------------------------------------------------------
#  tablas para codec.lua
# ---------------------------------------------------------------------------------------------------------------
def _lua_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def tablas_lua(ui, luces_mundo, ocultar=()):
    cj = _codec()
    lin = []
    lin.append('-- (generado por codec_r100.py: no editar a mano)')
    # pistas de la UI: {c, visible, r, g, b, a, pos x, pos y, ancho, alto} solo cuando algo cambia
    lin.append('local UNIDADES = {')
    for nombre, u, pista in _unidades_ui(ui):
        ruido = _ruido(u, pista)
        keys, prev = [], None
        for p in pista:
            if p[1]:
                pos, w, h = _pos_tam(*_rect(p[3]))
                est = (1,) + tuple(round(v, 4) for v in _tinte(u, p[4])) + (pos[0], pos[1], w, h)
            else:
                est = (0,)
            if est != prev:
                keys.append((p[0],) + est)
                prev = est
        ks = ', '.join('{' + ', '.join('%g' % v for v in k) + '}' for k in keys)
        lin.append('    {nombre = "codec_ui_%s", ruido = %s, k = {%s}},' % (nombre[7:], 'true' if ruido else 'false',
                                                                         ks))
    lin.append('}')
    lin.append('local SUBTITULOS = {')
    for c0, c1, txt, col, x in subtitulos():
        lin.append('    {desde = %d, hasta = %d, x = %g, color = {%s}, texto = %s},'
                   % (c0, c1, round(x / 640.0, 6), ', '.join('%g' % round(v, 4) for v in col), _lua_str(txt)))
    lin.append('}')
    lin.append('local LUCES_MUNDO = {%s}' % ', '.join('"%s"' % n for n in luces_mundo))
    # lo que la pantalla del codec TAPA (el mapa, los personajes, los efectos): mientras dura la llamada no se dibuja
    lin.append('local OCULTAR_MUNDO = {%s}' % ', '.join('"%s"' % n for n in ocultar))
    tg = cj['timeline_global']
    lin.append('local G_CODEC = %d        -- frame global del primer frame del codec (c = 0)' % (tg['codec_g'][0]))
    fin = [e for e in cj['transiciones']['cerrar']]
    lin.append('local C_CIERRE = %d      -- TermSeq -1: para la voz, borra el mensaje, SE de cerrar' % fin[0]['c'])
    return '\n'.join(lin) + '\n'


def lua(ui, luces_mundo, ocultar=()):
    txt = open(LUA, encoding='utf-8').read()
    assert '--@@DATOS@@' in txt, LUA
    return txt.replace('--@@DATOS@@', tablas_lua(ui, luces_mundo, ocultar))


# ---------------------------------------------------------------------------------------------------------------
#  el proyecto
# ---------------------------------------------------------------------------------------------------------------
def _todos(lista, padre=None):
    for o in lista:
        yield o, lista
        yield from _todos(o.get('hijos', []), o)


def _sacar(raiz, nombre):
    """saca del arbol el objeto 'nombre' (donde este: raiz = lista de objetos de la escena) y lo devuelve (None si
    no esta). Lo importado cae en la Coleccion (proyecto nuevo) o en la raiz de la escena (proyecto abierto)."""
    for o, lista in list(_todos(raiz)):
        if o.get('nombre') == nombre:
            lista.remove(o)
            return o
    return None


def _child_of(arm, hueso):
    return {'tipo': 'childOf', 'nombre': 'Child Of', 'influencia': 100, 'fuente': 'objeto', 'objeto': arm,
            'ejes': [True, True, True], 'hueso': hueso, 'hereda': [True, True, True],
            'inversa': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}


def radio_prop(proy, geometria=None):
    """la radio: hija de Leon, Child Of hueso_016 (sin inversa: los vertices ya estan en el espacio del hueso),
    oculta. Si ya existe un 'Leon_radio' en el arbol se reusa (su geometria); si no, con 'geometria'."""
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    o = _sacar(proy['escena']['objetos'], 'Leon_radio') or {'tipo': 'malla', 'nombre': 'Leon_radio', 'geometria': geometria}
    o.update({'visible': False, 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
              'constraints': [_child_of('Leon', HUESO_RADIO)]})
    o.pop('modArmature', None)
    leon = next((x for x, _ in _todos(col['hijos']) if x.get('nombre') == 'Leon' and x.get('tipo') == 'armature'),
                None)
    if leon is None:
        raise SystemExit('codec_r100: no esta el armature Leon')
    leon.setdefault('hijos', []).append(o)
    return o


def _camara(nombre, cam):
    eye = [o + e for o, e in zip(ORIGEN, cam['ojo_m'])]
    d = cam['aprox_simetrica']['direccion']
    tgt = [e + v for e, v in zip(eye, d)]
    return {'tipo': 'camara', 'nombre': nombre, 'pos': [round(v, 5) for v in eye],
            'rot': _euler_xyz(eye, tgt, [0, 1, 0]), 'escala': [1, 1, 1],
            'fov': round(cam['aprox_simetrica']['fov_vertical_grados'], 4), 'orto': False, 'near': 0.05, 'far': 20,
            'aspecto': round(cam['aspecto'], 5)}


def _luces_codec(cj):
    """las luces del codec (LIT de ss_cmmn): direccionales, color x intensidad x tev_mult (x la suma de 02/03)"""
    out = []
    lit = cj['espacio_3d']['luces']
    mult = lit['tev_mult'][0]
    for l in lit['luces']:
        if not l['encendida']:
            continue
        col = [round(min(2.0, c / 255.0 * l['intensidad'] * mult * BRILLO_DISTORSION), 4) for c in l['color_255']]
        out.append({'tipo': 'luz', 'nombre': 'Codec_luz_%d' % l['n'], 'visible': False,
                    'pos': [ORIGEN[0], ORIGEN[1] + 3, ORIGEN[2]], 'rot': _rot_desde_y(l['hacia_la_luz']),
                    'escala': [1, 1, 1], 'color': col, 'direccional': True})
    return out


HUD_UI = 'escenas/hud.w3dui'


def _ui_en_hud(proy, datos, extra, ui_codec, salida):
    """la raiz 2D del codec va ADENTRO del .w3dui del HUD, justo antes de "hud_fundido" (el fundido a negro la tapa;
    el grano y el medidor quedan debajo). Whisk3D trata cada nodo UI de la raiz de la escena como una ESCENA UI
    exclusiva (W3dEscenaArrancar -> MostrarSolo): con dos, solo se ve y corre UNA (la de nombre menor o la inicial),
    asi que un .w3dui propio apagaba al HUD (y a hud.lua con su fundido). Si no hay HUD se agrega el propio.
    -> {entrada: archivo local}"""
    raiz = ui_codec['hijos'][0]
    if HUD_UI in extra:
        hud = json.load(open(extra[HUD_UI], encoding='utf-8'))
    elif HUD_UI in datos:
        hud = json.loads(datos[HUD_UI].decode('utf-8'))
    else:
        hud = None
    if hud is None:
        ruta = os.path.join(salida, 'codec.w3dui')
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(ui_codec, f, ensure_ascii=False, indent=1)
        objs = proy['escena']['objetos']
        objs[:] = [o for o in objs if not (o.get('tipo') == 'ui' and o.get('archivo') == ENTRADA_UI)]
        objs.append({'tipo': 'ui', 'archivo': ENTRADA_UI})
        return {ENTRADA_UI: ruta}
    hijos = [h for h in hud['hijos'] if h.get('nombre') != raiz['nombre']]
    k = next((i for i, h in enumerate(hijos) if h.get('nombre') == 'hud_fundido'), len(hijos))
    hud['hijos'] = hijos[:k] + [raiz] + hijos[k:]
    ruta = os.path.join(salida, 'hud_con_codec.w3dui')
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(hud, f, ensure_ascii=False, indent=1)
    return {HUD_UI: ruta}


def aplicar(proy, datos, extra, salida=None, libreria=None):
    """agrega el codec al proyecto (ver el encabezado). Hay que llamarla DESPUES de armar el arbol 3D (el Recorte
    tiene que quedar ULTIMO en la Coleccion: nada que se agregue despues) y DESPUES de hud_r100.agregar (la UI del
    codec va adentro del .w3dui del HUD). Devuelve 'extra' actualizado.
    libreria: Leon es un proxy de la libreria de personajes (libreria_r100.py) y la radio ya viene en su prefab
    (make_personajes_w3d.py): codec.lua la encuentra por nombre igual (buscar entra a los proxies)."""
    cj, ui = _codec(), json.load(open(UI_JSON))
    salida = salida or _salida()
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')

    # --- lo importado ---
    arms = {}
    for arm in (ARM_LEON, ARM_HUNNIGAN):
        o = _sacar(proy['escena']['objetos'], arm)
        if o is None:
            raise SystemExit('codec_r100: falta el armature %s (lineas_importar)' % arm)
        o['pos'] = list(ORIGEN)       # los clips ya traen la posicion del personaje en el espacio del codec
        o['rot'] = [0, 0, 0]
        o['visible'] = True
        arms[arm] = o
    fondos = {}
    for clave in ('hunnigan', 'leon'):
        o = _sacar(proy['escena']['objetos'], 'Codec_fondo_' + clave)
        if o is None:
            raise SystemExit('codec_r100: falta Codec_fondo_%s (lineas_importar)' % clave)
        o.update({'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1]})
        fondos[clave] = o
    for m in proy.get('materiales', []):
        if m.get('nombre', '').startswith('Codec_fondo_'):       # el fondo: sin luz ni niebla de las luces
            m.setdefault('flags', {})['luz'] = False
    if not libreria:
        radio_prop(proy)

    # --- las ventanas y la pantalla ---
    _, medios = _glb_fondos(salida)
    ventanas = []
    for clave, px, fc, cam in _ventanas(cj):
        x, y, w, h = _rect_marco(fc)
        c = _camara('Codec_cam_' + clave, cam)
        c['hijos'] = [fondos[clave]]
        arm = arms[ARM_HUNNIGAN if clave == 'hunnigan' else ARM_LEON]
        ventanas.append({'tipo': 'recorte', 'nombre': 'Codec_ventana_' + clave, 'pos': [0, 0, 0], 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'activo': True, 'x': x, 'y': y, 'ancho': w, 'alto': h,
                         'camara': c['nombre'], 'limpiarZ': True, 'fondo': True,
                         'color': medios[clave] + [1.0], 'hijos': [c, arm]})
    gris = [round(v / 255.0 * 206 / 255.0, 4) for v in (30, 30, 30)]
    pantalla = {'tipo': 'recorte', 'nombre': 'Codec_pantalla', 'visible': False, 'pos': [0, 0, 0],
                'rot': [0, 0, 0], 'escala': [1, 1, 1], 'activo': True, 'x': 0.0, 'y': 0.0, 'ancho': 1.0, 'alto': 1.0,
                'limpiarZ': True, 'fondo': True, 'color': gris + [1.0], 'hijos': ventanas}
    luces_mundo = [o['nombre'] for o, _ in _todos(col['hijos']) if o.get('tipo') == 'luz']
    # lo que la pantalla de la llamada TAPA entero (se oculta mientras dura): lo que dibuja algo y no lleva scripts que
    # tengan que seguir corriendo (r100.lua, los eventos, colocar.lua); los proxies de los personajes si (sus scripts
    # estan en cinematica). Las rutinas del mundo las agrega el modo avanzado despues (avanzado_r100.py)
    ocultar = [o['nombre'] for o in col['hijos']
               if o.get('tipo') in ('culling', 'armature', 'proxy', 'malla', 'particulas', 'objeto', 'rutina', 'lod')
               and not o.get('scripts') and o.get('nombre') not in ('Codec', 'Codec_pantalla')]
    ocultar += ['r100_MundoOpaco', 'r100_MundoTranslucido']
    vacio = {'tipo': 'objeto', 'nombre': 'Codec', 'pos': list(ORIGEN), 'rot': [0, 0, 0], 'escala': [1, 1, 1],
             'scripts': [{'archivo': ENTRADA_LUA}], 'hijos': _luces_codec(cj)}
    col['hijos'] = [o for o in col['hijos'] if o.get('nombre') not in ('Codec', 'Codec_pantalla')]
    col['hijos'].append(vacio)
    col['hijos'].append(pantalla)          # ULTIMO: tapa el mundo mientras dura la llamada

    # --- la animacion de las caras ---
    anim = proy.get('animaciones') or {'activa': 0, 'escenas': []}
    anim['escenas'] = [e for e in anim['escenas'] if e.get('nombre') != 'codec'] + [escena_caras()]
    proy['animaciones'] = anim

    # --- la UI: ADENTRO de la escena del HUD (ver _ui_en_hud) ---
    nuevos = {}
    nuevos.update(_ui_en_hud(proy, datos, extra, escena_ui(ui), salida))

    # --- archivos ---
    ruta_lua = os.path.join(salida, 'codec.lua')
    with open(ruta_lua, 'w', encoding='utf-8') as f:
        f.write(lua(ui, luces_mundo, ocultar))
    nuevos[ENTRADA_LUA] = ruta_lua
    nuevos.update(texturas_ui(ui, salida))
    a = cj['audio']
    for n, clave in (('voz', 'voz'), ('tono', 'tono_radio'), ('abrir', 'se_abrir'), ('cerrar', 'se_cerrar')):
        nuevos[SON + n + '.wav'] = os.path.join(CODEC, a[clave]['wav'])
    extra.update(nuevos)
    # si el proyecto ya traia estas entradas, el escritor usa 'datos' para las existentes: se pisan
    for k, ruta in nuevos.items():
        if k in datos:
            datos[k] = open(ruta, 'rb').read()
    return extra


if __name__ == '__main__':
    print('\n'.join(lineas_importar(radio=True)))
    u = json.load(open(UI_JSON))
    print(tablas_lua(u, ['r100_luz_00'])[:3000])
    for s in subtitulos():
        print(s)
