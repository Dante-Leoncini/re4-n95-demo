"""LOS OBJETOS DEL CUARTO para el N95 (de re3_w3d/out/objetos_r100: re4_extract_objetos_r100.py).

  tablas.bin:
    exa.<k>       un area para EXAMINAR: cuando (0 siempre, 1 antes del barranco, 2 en la emboscada, 3 despues del
                  barranco), cartel (0 ninguno -la tecla de accion sola-, 1 CHECK, 2 OPEN), piso, alto, los 4 puntos
                  del poligono (x z), la mirada (yaw y rango en radianes; rango 0 = cualquiera), si hay camara y sus
                  dos claves (ojo xyz, objetivo xyz, fov) en los cuadros 0 y 30
    exatxt.<k>    el texto (los codigos de sus letras; "/" separa las paginas)
"""
import json
import os

CUANDO = {'0x0B': 2, '0x0C': 1, '0x18': 3}


def _codigos(s):
    return [float(ord(c)) for c in s]


def armar_examinar(J, tablas, log):
    n = 0
    for a in J['examinar']['areas']:
        if a['tipo'] == 'SAVE':
            continue
        texto = a['texto']
        if isinstance(texto, list):
            texto = texto[-1]
        pol = a['poligono_xz_m']
        if len(pol) != 4:
            continue
        cartel = 0
        if a.get('cartel'):
            cartel = 2 if a['cartel']['nombre'] == 'OPEN' else 1
        mir = a.get('mirada') or {}
        v = [CUANDO.get(a['area'], 0), cartel, a['piso_m'], a['alto_m']] + [c for p in pol for c in p]
        v += [mir.get('yaw_rad', 0.0), mir.get('rango_rad', 0.0)]
        cam = a.get('camara')
        if cam and len(cam.get('ojo_m', [])) >= 2:
            v += [1]
            for k in (0, -1):
                v += list(cam['ojo_m'][k]) + list(cam['objetivo_m'][k]) + [cam['fovy_grados'][k]]
        else:
            v += [0] + [0] * 14
        tablas.poner('exa.%d' % n, v)
        # (las paginas del juego van separadas por " / ")
        tablas.poner('exatxt.%d' % n, _codigos(texto.replace(' / ', '/').replace('  ', ' ')))
        n += 1
    log('examinar: %d areas' % n)


def armar(re3, tex, tablas, datos, log=print):
    raiz = os.path.join(re3, 'out', 'objetos_r100')
    J = json.load(open(os.path.join(raiz, 'objetos_r100.json'), encoding='utf-8'))
    armar_examinar(J, tablas, log)
