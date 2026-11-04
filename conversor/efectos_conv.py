"""LOS EFECTOS para el N95 (tablas.bin): cada emisor de particulas de la demo como 'fx.<i>' y cada grupo (lo que se
emite junto: el fogonazo, la sangre, el polvo, los vidrios...) como 'fxg.<nombre>' = pares (emisor, cuantas).

  fx.<i> = textura, mezcla, cantidad por segundo, vida, tam, color r g b a, pos x y z (en su grupo), velLocal xyz,
           velAzar xyz, posAzar xyz, aceleracion xyz, arrastre, crecimiento, freno, alphaDecae, alphaMuerte,
           rotInicial, rotAzar, velRotacion, velRotAzar, giroSignoAzar, flipCuadros, flipCols, flipFilas, flipFps,
           flipUnaVez, desvanecer, aparecer, fundeCerca0, fundeCerca1, radioEmision, linea
"""
import io

from PIL import Image

import fuentes

SANGRE_TAM = 3.0


def grilla(im, n, cols, filas):
    """un flipbook en tira (30 x 1) a una grilla casi cuadrada: achicado a 256 de ancho, cada cuadro de la tira quedaba
    de 8 pixeles"""
    if n <= 1 or (cols > 1 and filas > 1):
        return im, cols, filas
    w, h = im.size[0] // cols, im.size[1] // filas
    nc = 1
    while nc * nc < n:
        nc += 1
    nf = (n + nc - 1) // nc
    o = Image.new(im.mode, (nc * w, nf * h))
    for k in range(n):
        x, y = (k % cols) * w, (k // cols) * h
        o.paste(im.crop((x, y, x + w, y + h)), ((k % nc) * w, (k // nc) * h))
    return o, nc, nf


def emisor(proy, o, tex):
    t = 0xFFFFFFFF
    g = lambda k, d: o.get(k, d)
    cols, filas = g('flipCols', 1), g('flipFilas', 1)
    ruta = o.get('textura', '')
    if ruta:
        try:
            datos = proy.leer(ruta)
        except KeyError:
            datos = None
        if datos:
            im = Image.open(io.BytesIO(datos))
            if g('flipCuadros', 0) > 1:
                im.load()
                im, cols, filas = grilla(im.convert('RGBA'), int(g('flipCuadros', 0)), int(cols), int(filas))
            t = tex.agregar('x_' + ruta.rsplit('/', 1)[1][:-4], im, repetir=False, tope=256)
    v = [t, g('mezcla', 1), g('cantidad', 0), g('vida', 1), g('tam', 0.1)] + list(g('color', [1, 1, 1, 1]))
    v += list(g('pos', [0, 0, 0])) + list(g('velLocal', [0, 0, 0])) + list(g('velAzar', [0, 0, 0]))
    v += list(g('posAzar', [0, 0, 0])) + list(g('aceleracion', [0, 0, 0]))
    v += [g('arrastre', 1), g('crecimiento', 0), g('frenoCrecimiento', 1), g('alphaDecae', 1), g('alphaMuerte', 0),
          g('rotInicial', 0), g('rotAzar', 0), g('velRotacion', 0), g('velRotAzar', 0),
          1 if g('giroSignoAzar', False) else 0, g('flipCuadros', 0), cols, filas,
          g('flipFps', 0), 1 if g('flipUnaVez', False) else 0, 1 if g('desvanecer', False) else 0, g('aparecer', 0)]
    v += list(g('fundeCerca', [0, 0])) + [g('radioEmision', 0), 1 if g('forma', '') == 'linea' else 0]
    return v


def armar(nivel, pers, tex, tablas, log=print):
    emisores = []
    grupos = {}

    def agregar(proy, nombre):
        o = proy.objetos[nombre]
        emisores.append(emisor(proy, o, tex))
        return len(emisores) - 1

    fxl = fuentes.tablas_locales(pers.script('leon.lua'), ['FX', 'FXC'])
    grupos['fogonazo'] = [(agregar(pers, n), c) for n, c in fxl['FX']]
    for g, lista in fxl['FXC'].items():
        grupos[g] = [(agregar(nivel, n), c) for n, c in lista if n in nivel.objetos]
    grupos['punto'] = [(agregar(nivel, 'Leon_laser_punto'), 1)]
    # el ambiente: la chimenea (cada una con su particula eterna) y la neblina de la casa; el clima (en la camara)
    grupos['chimenea'] = [(agregar(nivel, 'fx_chimenea_%s' % k), 1) for k in ('02', '03', '04', '10', '11', '12')]
    grupos['chimenea_fuego'] = [(agregar(nivel, 'fx_chimenea_%s' % k), 0) for k in ('00', '01')]
    grupos['neblina'] = [(agregar(nivel, 'fx_neblina_casa_00'), 0)]
    grupos['clima'] = [(agregar(nivel, 'fx_clima'), 0)]
    # (la sangre del juego es de gotas de 2 a 8 cm: a 320 x 180, a unos metros, menos de un pixel; en el N95, mas grande)
    for g in ('fx_sangre', 'fx_sangre_leon', 'fx_cuchillo'):
        for e in {e for e, _ in grupos.get(g, [])}:
            emisores[e][4] *= SANGRE_TAM
    for i, v in enumerate(emisores):
        tablas.poner('fx.%d' % i, v)
    for g, l in grupos.items():
        tablas.poner('fxg.' + g, [x for par in l for x in par])
    log('efectos: %d emisores en %d grupos' % (len(emisores), len(grupos)))
