"""LA INTERFAZ (el HUD y la pantalla del codec) para el N95: las texturas (al registro) y sus numeros (a tablas.bin):

  hud.<nombre>      la imagen del HUD (escenas/hud.w3dui del proyecto): textura, centro x y (fraccion de la pantalla
                    desde la esquina de abajo a la derecha), ancho alto (pixeles de una pantalla de 1280 de alto),
                    giro, tinte r g b a, uv u0 v0 u1 v1
  codec.u<i>        cada unidad de la pantalla del codec (codec.lua): textura, ruido (0/1), n claves y por clave
                    cuadro visible r g b a x y ancho alto (centro corrido desde el medio, fraccion de la pantalla)
  codec.ruido       las dos texturas de la estatica
  codec.s<i>        cada subtitulo: desde hasta x r g b a y los codigos de sus letras (10 = renglon nuevo)
  fuente.<nombre>   una letra bitmap del juego: textura, alto del renglon, ancho y alto de la textura y por glifo
                    codigo x y w h xoff yoff avance
"""
import io
import json

import numpy as np
from PIL import Image


def _pad(img):
    """al lado potencia de dos SIN escalar (las coordenadas de los glifos siguen valiendo)"""
    w, h = img.size
    W, H = 1, 1
    while W < w:
        W *= 2
    while H < h:
        H *= 2
    if (W, H) == (w, h):
        return img
    o = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    o.paste(img, (0, 0))
    return o


def _img(proy, ruta):
    return Image.open(io.BytesIO(proy.leer(ruta))).convert('RGBA')


def fuente(proy, ruta_json, nombre, tex, tablas):
    j = json.loads(proy.leer(ruta_json))
    carpeta = ruta_json.rsplit('/', 1)[0]
    img = _img(proy, carpeta + '/' + ruta_json.rsplit('/', 1)[1].replace('.json', '.png'))
    w, h = img.size
    t = tex.agregar('f_' + nombre, _pad(img), repetir=False, tope=1024)
    W, H = _pad(img).size
    v = [t, j['alto_linea'], W, H]
    for c, g in j['glifos'].items():
        if len(c) != 1:
            continue
        v += [ord(c), g['x'], g['y'], g['w'], g['h'], g['xoff'], g['yoff'], g['avance']]
    tablas.poner('fuente.' + nombre, v)


def armar(nivel, tex, tablas, log=print):
    ui = json.loads(nivel.leer('escenas/hud.w3dui'))
    nodos = {}

    def recorrer(o):
        nodos[o.get('nombre')] = o
        for h in o.get('hijos', []):
            recorrer(h)
    for h in ui['hijos']:
        recorrer(h)

    def textura(ruta, repetir=False):
        if not ruta:
            return 0xFFFFFFFF
        n = 'u_' + ruta.rsplit('/', 1)[1][:-4]
        return tex.agregar(n, _img(nivel, ruta), repetir=repetir, tope=512)

    # EL HUD: las imagenes de hud_raiz y del cartel de accion. Cada una: textura, centro cx cy (fraccion de la
    # pantalla desde la esquina de su raiz), corrimiento ox oy (pixeles de referencia, girado con su contenedor), ancho,
    # alto, giro propio, giro del contenedor, tinte, uv
    n = 0
    for raiz in ('hud_raiz', 'hud_accion'):
        for o in nodos[raiz].get('hijos', []):
            hijos = [(o, None)] if o['tipo'] != 'contenedor' else [(h, o) for h in o.get('hijos', [])]
            for x, cont in hijos:
                if cont is None:
                    c, off, rc = x.get('pos', [0, 0, 0]), [0, 0], 0
                else:
                    c = cont.get('pos', [0, 0, 0])
                    hp = x.get('pos', [0, 0, 0])
                    off = [hp[0] * cont['ancho'], hp[1] * cont['alto']]
                    rc = cont.get('rotacion', 0)
                if x['tipo'] == 'imagen':
                    v = [textura(x.get('textura', '')), c[0], c[1], off[0], off[1], x['ancho'], x['alto'],
                         x.get('rotacion', 0), rc] + list(x.get('tinte', [1, 1, 1, 1]))
                    v += [x.get('uvU0', 0), x.get('uvV0', 0), x.get('uvU1', 1), x.get('uvV1', 1)]
                    tablas.poner('hud.' + x['nombre'][4:31], v)
                    n += 1
                elif x['tipo'] == 'texto':
                    tablas.poner('hud.' + x['nombre'][4:31], [0, c[0], c[1], 0, 0, x['ancho'], x['alto'], 0, 0] +
                                 list(x.get('color', [1, 1, 1, 1])) + [x.get('tam', 40), 0, 0, 0])
    grano = nodos['hud_grano']
    tablas.poner('hud.grano', [textura(grano['textura'], True)] + list(grano['tinte']))
    fuente(nivel, 'texturas/hud/fuente_boton.json', 'boton', tex, tablas)
    fuente(nivel, 'texturas/codec/fuente_codec.json', 'codec', tex, tablas)

    # EL CODEC
    from fuentes import tablas_locales
    t = tablas_locales(nivel.script('codec.lua'), ['UNIDADES', 'SUBTITULOS'])
    for i, u in enumerate(t['UNIDADES']):
        x = nodos[u['nombre']]
        v = [textura(x.get('textura', '')), 1 if u['ruido'] else 0, len(u['k'])]
        for k in u['k']:
            v += [k[0], k[1]] + list(k[2:10])
        tablas.poner('codec.u%d' % i, v)
    tablas.poner('codec.ruido', [textura('texturas/codec/ruido_0.png', True), textura('texturas/codec/ruido_1.png', True)])
    for i, s in enumerate(t['SUBTITULOS']):
        tablas.poner('codec.s%d' % i, [s['desde'], s['hasta'], s['x']] + list(s['color']) +
                     [ord(c) for c in s['texto'].replace(chr(92) + 'n', chr(10))])
    # los dos recortes (las caras): centro x y, ancho alto (fraccion, y hacia arriba) y el color del fondo
    for nom in ('Codec_ventana_hunnigan', 'Codec_ventana_leon', 'Codec_pantalla'):
        o = nivel.objetos[nom]
        tablas.poner('codec.' + nom.split('_')[-1], [o['x'], o['y'], o['ancho'], o['alto']] + list(o['color']))
    for nom in ('Codec_cam_hunnigan', 'Codec_cam_leon'):
        o = nivel.objetos[nom]
        tablas.poner('codec.' + nom.lower()[6:], list(o['pos']) + list(o['rot']) + [o['fov']])
    log('interfaz: %d imagenes del HUD, %d unidades del codec, %d subtitulos' % (n, len(t['UNIDADES']),
                                                                             len(t['SUBTITULOS'])))
