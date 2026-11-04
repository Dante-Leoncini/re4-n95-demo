#!/usr/bin/env python3
"""
Texto de Resident Evil 4 (GameCube, disco USA): la FUENTE de los mensajes y las TABLAS DE MENSAJES, a PNG + JSON, y
una fuente bitmap compatible con Whisk3D (formato/fuente-bitmap.md del motor) para subtitulos y menues.

  out/texto/fuente_re4.png            el atlas tal cual esta en el disco (1024x192, 32x6 celdas de 32x32), RGBA
  out/texto/fuente_re4.json           metricas de cada glifo (celda, L/R, ancho), codigo -> unicode, paleta, reglas
                                      de layout (tamanos por LAYOUT_TYPE, espacio, separacion, alineacion), colores,
                                      codigos de control
  out/texto/mensajes_en.json          todas las tablas de mensajes del disco que tocan a la demo, en ingles
  out/texto/mensajes_es.json          traduccion PROPIA al espanol (el disco USA NO trae espanol), codificada con la
                                      misma tabla de glifos (sirve para probar la fuente con acentos / enie / ¿ ¡)
  out/texto/whisk3d/fuente_re4_<layout>[_x125].png/.json
                                      fuente bitmap de Whisk3D horneada con el tamano de cada layout del juego
                                      (subtitulo = LAYOUT_CAPTION, boton = LAYOUT_ACT_BTN, codec = LAYOUT_OPERATOR)
  out/texto/muestra_{512,640}_{juego,whisk3d}.png, comparacion_{512,640}.png, comparacion.json
                                      la misma escena dibujada con las reglas del juego (mes.cpp) y con Texto2D de
                                      Whisk3D (harness --script + uishot, escena en out/texto/whisk3d/prueba/)
  (out/texto/LEEME.md resume la codificacion; esta escrito a mano, el script no lo toca)

De donde sale cada cosa (decomp ../re4, solo lectura):
  src/game/mes.cpp   MessageFont::create/getSize (ancho = R - L de la tabla de anchos; el glifo 0 = espacio),
                     draw() (quad de w x h en la ortho 512x384 de messageCamera, UV = celda + L, ancho R-L),
                     getCharCode (glifo = palabra - 0x80), isCtrlCode (< 0x80), CommandArg (argumentos),
                     code00..code12, WidthCk (centrado), QueSet (avance = (s16)(ancho*escala) + separacion),
                     setLayout (layout_tbl[idioma][tipo] = ancho, alto, ?, separacion, ?, interlineado),
                     loadCommonFont (fuera del japones: Font/common_p.fnt, celdas 32x32), mes_col_tbl,
                     MessageData::getAddr (MDT: u32 n_idiomas; u32 ofs[n]; bloque {u32 ?, u32 cuenta, u32 ofs[]}),
                     setLanguage (1 = ingles).
  src/game/main.cpp  setLanguage(): "Fixed language 1 / region 1 for this build" (USA = solo ingles).
  src/game/read.cpp  ReadAreaData: el MDT del cuarto (stX/rNNN.das, etiqueta MDT) = tipo 1.
  src/game/mes.cpp   gameInit: tipo 0/1/2 = etc/core.das entrada 6 (ofs_28), tipo 3 = entrada 17 (ofs_54, objetos).
  src/game/act_btn.cpp  disp(): mensaje core (kind + 0x16), LAYOUT_ACT_BTN, x/y del IDSystem (clase 0x20 id 1).
  src/game/sce_com.cpp  SceMesSet: los mensajes del cuarto (attr 0x1002), y = 0x150 - interlineado - alto - 1.
  src/Sscrn/ss_term.cpp la llamada por radio (codec): op/opNN.das (+0x400): MDT 0..12 + SEQ 13..25, stream
                     0x8C + op, LAYOUT_OPERATOR, MesSet(.., 0x03000054) (tipo 2).
  src/st1/r100.cpp   que mensajes del cuarto usa r100 (SceMesSet 0xB 0xC 0xD 0xE 0xF 0x28, MesSet 0x33).

Uso:  python3 re4_extract_texto.py [--disc RUTA.rvz] [--sin-muestra] [--sin-whisk3d]
"""
import argparse
import json
import os
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
from motion import archive  # noqa: E402

DEFAULT_DISC = os.path.join(HERE, '..', 'Resident Evil 4 (USA) (Disc 1)', 'Resident Evil 4 (USA) (Disc 1).rvz')
DTK = os.path.join(HERE, 'tools', 'dtk')
EXTR = os.path.join(HERE, 'extracted')
OUT = os.path.join(HERE, 'out', 'texto')
OUT_W3D = os.path.join(OUT, 'whisk3d')

# ---------------------------------------------------------------------------------------------------------------
#  la tabla de glifos de Font/common_p.fnt (la fuente de TODOS los idiomas que no son japones)
#  indice = palabra - 0x80 (getCharCode). Leido a ojo del atlas y verificado con la tabla de anchos (L/R).
# ---------------------------------------------------------------------------------------------------------------
GLIFOS = {0x00: ' ', 0x01: '▶', 0x02: '▼'}
for _i in range(10):
    GLIFOS[0x03 + _i] = str(_i)
for _i, _c in enumerate(':%&+−/=,.・…()!?“”~☆—<>[]①②'):
    GLIFOS[0x0D + _i] = _c
for _i in range(26):
    GLIFOS[0x27 + _i] = chr(ord('A') + _i)
    GLIFOS[0x41 + _i] = chr(ord('a') + _i)
for _i, _c in enumerate('âêîôûÂÊÎÔÛàèìòùÀÈÌÒÙáéíóúýÁÉÍÓÚÝäëïöüÿÄËÏÖÜŸãõÃÕñÑåÅçÇøØþÞšŠßÐƒµðæœÆŒ°¡¿’™;#@→←↑↓₧'):
    GLIFOS[0x5B + _i] = _c
N_GLIFOS = 0xAD            # 0xAD..0xBF: celdas vacias (ancho 0-32 en la tabla)
NOMBRES = {0x01: 'cursor de opcion (code07)', 0x02: 'cursor de pagina siguiente (code08)', 0x11: 'menos largo',
           0x16: 'punto medio', 0x17: 'puntos suspensivos', 0x20: 'raya', 0x25: '1 en circulo', 0x26: '2 en circulo',
           0xA3: 'apostrofo (el unico: no hay comilla recta)', 0xAC: 'PTAS (pesetas; code0a lo usa como "%" '
           'fuera del japones con attr 0x10000000)'}
# para escribir texto: variantes ASCII que caen en el glifo del juego
ALIAS_ENTRADA = {"'": '’', '"': '”', '-': '−', '«': '“', '»': '”', '·': '・', '₧': '₧'}

# codigos de control (mes.cpp CommandExec / CommandArg), nombre del tag en el texto decodificado
ARGS = [0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1]
TAGS = {0x00: 'inicio', 0x01: 'fin', 0x02: 'llamar', 0x03: 'linea', 0x04: 'pagina', 0x05: 'vel', 0x06: 'color',
        0x07: 'opcion', 0x08: 'boton', 0x09: 'espera', 0x0A: 'numero', 0x0B: 'x', 0x0C: 'y', 0x0D: 'evento',
        0x0E: 'volver', 0x0F: 'llamar_core', 0x10: 'objeto', 0x11: 'llamar_objeto', 0x12: 'habla'}
TAG_COD = {v: k for k, v in TAGS.items()}
CONTROL_DOC = {
    'inicio': '00 comienzo de pagina: vacia la cola de glifos, mide la pagina (WidthCk) y vuelve el lapiz al '
              'principio de la linea 0',
    'fin': '01 fin del mensaje (libera el slot salvo attr 0x01000000; devuelve Stop_flg)',
    'llamar': '02 n: inserta el mensaje n del MISMO archivo (0xFFFF = siguiente de la tabla de saltos) y vuelve '
              'con {volver}',
    'linea': '03 salto de linea: y += interlineado, x = inicio de la linea siguiente (centrado precalculado)',
    'pagina': '04 pagina nueva (code00 otra vez); espera un frame',
    'vel': '05 n: velocidad del tipeo = un glifo cada n+1 frames (default 1 = cada 2 frames; attr 0x40 = '
           'instantaneo; A/B completa la pagina)',
    'color': '06 n: color = mes_col_tbl[n] para los glifos SIGUIENTES (multiplica el glifo blanco; el borde negro '
             'queda negro)',
    'opcion': '07 una opcion elegible: guarda el lugar del cursor ▶ (glifo 1) y encola un espacio del ancho del '
              'cursor; texto instantaneo',
    'boton': '08 espera un boton (A/B); con opciones, arriba/abajo mueven el cursor y A elige (m_sel = opcion+1)',
    'espera': '09 n: espera n frames (0xFFFF = hasta WaitEnd, el codec lo usa)',
    'numero': '0A inserta el numero de setNumber() con los glifos 3..12 (digitos)',
    'x': '0B n: lapiz x = n (px de la pantalla 512x384)',
    'y': '0C n: lapiz y = n',
    'evento': '0D n: m_evt_no = n (lo lee el codigo que abrio el mensaje)',
    'volver': '0E vuelve de un {llamar}/{llamar_core}/{objeto}/{llamar_objeto}',
    'llamar_core': '0F n: inserta el mensaje n de core (tipo 0) con la fuente comun',
    'objeto': '10 inserta el nombre del objeto m_item_no (tabla de objetos, tipo 3)',
    'llamar_objeto': '11 n: inserta el nombre de objeto n (tipo 3)',
    'habla': '12 n: m_who = n (quien habla; el codec lo usa antes de cada linea)',
}

# mes.cpp mes_col_tbl (RGBA)
COLORES = [0xE5D9CFF0, 0x87CFA5FF, 0xCD7D5FFF, 0x87AFFFFF, 0xA55FFFFF,
           0x707070FF, 0x707070FF, 0x52DF73FF, 0x00000000, 0x00000000]

# mes.cpp setLayout: layout_tbl[idioma][tipo] = {ancho, alto, ?, separacion, ?, interlineado}; el idioma 1 (ingles,
# el unico del disco USA) usa la fila 1. La celda de la fuente es 32x32 -> escala = ancho/32, alto/32.
LAYOUT_TIPOS = ['CAPTION', 'ACT_BTN', 'SUBSCRN', 'MEMCARD', 'OPERATOR', 'SYSTEM', 'SHOP_LIST', 'FILE', 'MANUAL']
LAYOUT_TBL = [
    [(0x19, 0x1B, 0, 1, 0, 0x1B), (0x1A, 0x1C, 0, 1, 0, 0x16), (0x16, 0x18, 0, 1, 0, 0x18), (0x16, 0x16, 0, 0, 0, 0x16),
     (0x18, 0x15, 0, 0, 0, 0x19), (0x17, 0x17, 0, 0, 0, 0x1C), (0x11, 0x13, 0, 0, 0, 0x00), (0x16, 0x17, 0, 1, 0, 0x16),
     (0x16, 0x15, 0, 1, 0, 0x13)],
    [(0x16, 0x20, -1, -1, 0, 0x19), (0x17, 0x20, 0, 0, 0, 0x19), (0x12, 0x18, -1, -1, 0, 0x13), (0x15, 0x19, 0, 0, 0, 0x14),
     (0x15, 0x1C, 0, 0, 0, 0x19), (0x17, 0x17, 0, 0, 0, 0x1C), (0x10, 0x15, -1, -1, 0, 0x00), (0x14, 0x19, -1, -1, 0, 0x15),
     (0x14, 0x19, -1, -1, 0, 0x15)],
]
CELDA = 32          # loadCommonFont: loadFont(0x20, 0x20, "Font/common_p.fnt", 0)
ESPACIO = 8         # MessageData::getSpaceWidth(): 8 px fuera del japones (13 en japones)
PANT_W, PANT_H = 512, 384   # messageCamera: C_MTXOrtho(0, 384, 0, 512)
SALIDA_W, SALIDA_H = 640, 480

# fuentes Whisk3D a hornear: nombre -> layout del juego
FUENTES_W3D = {'subtitulo': 'CAPTION', 'boton': 'ACT_BTN', 'codec': 'OPERATOR'}


def layout(tipo, idioma=1):
    a, h, _, sep, _, inter = LAYOUT_TBL[idioma][LAYOUT_TIPOS.index(tipo)]
    return dict(tipo=tipo, ancho=a, alto=h, separacion=sep, interlineado=inter,
                escala_x=a / CELDA, escala_y=h / CELDA)


# ---------------------------------------------------------------------------------------------------------------
#  disco
# ---------------------------------------------------------------------------------------------------------------
def del_disco(disc, ruta_disco, local):
    """extracted/<local>; si falta lo copia del disco con dtk."""
    dst = os.path.join(EXTR, local)
    if not os.path.isfile(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        subprocess.check_call([DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/{ruta_disco}', dst],
                              stdout=subprocess.DEVNULL)
    return dst


# ---------------------------------------------------------------------------------------------------------------
#  fuente (.fnt = u32 ofs_tpl, u32 ofs_anchos; TPL con UNA textura C4 + TLUT RGB5A3 de 16 colores)
# ---------------------------------------------------------------------------------------------------------------
def rgb5a3(v):
    if v & 0x8000:
        r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
        return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2), 255)
    a, r, g, b = (v >> 12) & 7, (v >> 8) & 15, (v >> 4) & 15, v & 15
    return (r * 17, g * 17, b * 17, (a << 5) | (a << 2) | (a >> 1))


def leer_fuente(ruta):
    d = open(ruta, 'rb').read()
    ofs_tpl, ofs_anchos = struct.unpack_from('>II', d, 0)
    t = ofs_tpl
    ver, n, ofs_desc = struct.unpack_from('>III', d, t)
    assert ver == 0x0020AF30 and n == 1, (hex(ver), n)
    ofs_th, ofs_clut = struct.unpack_from('>II', d, t + ofs_desc)
    h, w, fmt, ofs_dat = struct.unpack_from('>HHII', d, t + ofs_th)
    assert fmt == 8, fmt                                   # GX_TF_C4
    n_col, _, _, fmt_clut, ofs_col = struct.unpack_from('>HBBII', d, t + ofs_clut)
    assert fmt_clut == 2, fmt_clut                         # GX_TL_RGB5A3
    paleta = [rgb5a3(struct.unpack_from('>H', d, t + ofs_col + 2 * i)[0]) for i in range(n_col)]
    b = np.frombuffer(d, np.uint8, w * h // 2, t + ofs_dat)
    idx = np.stack([b >> 4, b & 15], -1).reshape(-1)      # nibble alto = texel izquierdo
    idx = idx.reshape(h // 8, w // 8, 8, 8).transpose(0, 2, 1, 3).reshape(h, w)   # tiles de 8x8
    rgba = np.array(paleta, np.uint8)[idx]
    n_anch = (len(d) - ofs_anchos) // 2
    anchos = [(d[ofs_anchos + 2 * i], d[ofs_anchos + 2 * i + 1]) for i in range(n_anch)]
    return dict(rgba=rgba, w=w, h=h, paleta=paleta, anchos=anchos, ofs_tpl=ofs_tpl, ofs_anchos=ofs_anchos,
                n_col=n_col)


def lr(fnt, i):
    """MessageFont::getSize: el glifo 0 usa la entrada 1 (idx = 2)."""
    return fnt['anchos'][1 if i == 0 else i]


# ---------------------------------------------------------------------------------------------------------------
#  mensajes (MDT) y codificacion
# ---------------------------------------------------------------------------------------------------------------
def leer_mdt(d):
    """[(x0, [palabras de cada mensaje])] por bloque de idioma (MessageData::getAddr)."""
    n = struct.unpack_from('>I', d, 0)[0]
    out = []
    for L in range(n):
        bo = struct.unpack_from('>I', d, 4 + 4 * L)[0]
        x0, cnt = struct.unpack_from('>II', d, bo)
        msgs = []
        for k in range(cnt):
            o = bo + struct.unpack_from('>I', d, bo + 8 + 4 * k)[0]
            w = []
            while o + 2 <= len(d):
                v = struct.unpack_from('>H', d, o)[0]
                o += 2
                w.append(v)
                if v < 0x80 and v < len(ARGS):
                    for _ in range(ARGS[v]):
                        w.append(struct.unpack_from('>H', d, o)[0])
                        o += 2
                if v == 1:
                    break
            msgs.append(w)
        out.append((x0, msgs))
    return out


def decodificar(w):
    """palabras -> (texto con {tags}, [paginas [lineas]] en unicode sin tags, tiene_glifos_fuera_de_la_fuente)."""
    tx, paginas, linea, pagina = [], [], [], []
    fuera = False
    i = 0
    while i < len(w):
        c = w[i]
        if c < 0x80:
            if c >= len(ARGS):
                tx.append('{?%02x}' % c)
                i += 1
                continue
            a = w[i + 1:i + 1 + ARGS[c]]
            tx.append('{%s%s}' % (TAGS[c], ''.join(':%d' % (v if v != 0xFFFF else -1) for v in a)))
            if c == 3:
                pagina.append(''.join(linea))
                linea = []
            elif c in (1, 4):
                if linea or pagina:
                    pagina.append(''.join(linea))
                    paginas.append(pagina)
                linea, pagina = [], []
            elif c == 7:
                linea.append('▶')
            elif c == 0x0A:
                linea.append('#')
            i += 1 + ARGS[c]
            if c == 1:
                break
        else:
            g = c - 0x80
            ch = GLIFOS.get(g)
            if ch is None:
                ch = '{g%x}' % g
                fuera = True
            tx.append(ch)
            linea.append(ch)
            i += 1
    paginas = [[l.rstrip() for l in p] for p in paginas]
    paginas = [p for p in paginas if any(p)]
    return ''.join(tx), paginas, fuera


UNI_A_GLIFO = {v: k for k, v in GLIFOS.items()}
for _k, _v in ALIAS_ENTRADA.items():
    UNI_A_GLIFO.setdefault(_k, UNI_A_GLIFO[_v])


def codificar(texto):
    """texto con {tags} (los de decodificar) -> palabras u16. Sin {inicio}/{fin} explicitos los agrega."""
    w = []
    i = 0
    while i < len(texto):
        c = texto[i]
        if c == '{':
            j = texto.index('}', i)
            partes = texto[i + 1:j].split(':')
            cod = TAG_COD[partes[0]]
            w.append(cod)
            for p in partes[1:]:
                v = int(p)
                w.append(0xFFFF if v < 0 else v)
            i = j + 1
            continue
        if c == '\n':
            w.append(3)
        elif c not in UNI_A_GLIFO:
            raise ValueError(f'caracter sin glifo en la fuente del juego: {c!r} en {texto!r}')
        else:
            w.append(0x80 + UNI_A_GLIFO[c])
        i += 1
    if not w or w[0] != 0:
        w.insert(0, 0)
    if w[-1] != 1:
        w.append(1)
    return w


# ---------------------------------------------------------------------------------------------------------------
#  layout del juego (mes.cpp): medicion, posiciones de cada glifo
# ---------------------------------------------------------------------------------------------------------------
def avance(fnt, g, lay):
    """QueSet: (s16)((R-L) * escala_w) + separacion; el espacio (glifo 0): (s16)(8 * escala_w), sin separacion."""
    if g == 0:
        return int(ESPACIO * lay['escala_x'])
    L, R = lr(fnt, g)
    return int((R - L) * lay['escala_x']) + lay['separacion']


def maquetar(fnt, palabras, lay, x0=None, y0=None, attr=0, color=0):
    """Ejecuta WidthCk + move para la PRIMERA pagina (sin tipeo): [(x, y, glifo, w, h, rgba)] en la ortho 512x384.
    attr 0x20000 = alineado a la izquierda en x0; 0x80000 = cada linea centrada; sino todas las lineas arrancan en
    (512 - ancho_max) / 2 (el bloque centrado, las lineas alineadas a la izquierda dentro del bloque)."""
    # WidthCk: ancho de cada linea de la pagina
    anchos = [0]
    i = 1 if palabras and palabras[0] == 0 else 0
    while i < len(palabras):
        c = palabras[i]
        if c < 0x80:
            if c == 3:
                anchos.append(0)
            elif c in (1, 4):
                break
            i += 1 + ARGS[c]
            continue
        anchos[-1] += avance(fnt, c - 0x80, lay)
        i += 1
    ancho_max = max(anchos)
    if attr & 0x20000:
        xs = [x0] * len(anchos)
    elif attr & 0x80000:
        xs = [(PANT_W - a) >> 1 for a in anchos]
    else:
        xs = [(PANT_W - ancho_max) >> 1] * len(anchos)
    y = y0
    glifos = []
    lin = 0
    x = xs[0]
    col = COLORES[color]
    i = 1 if palabras and palabras[0] == 0 else 0
    while i < len(palabras):
        c = palabras[i]
        if c < 0x80:
            a = palabras[i + 1:i + 1 + ARGS[c]]
            if c == 3:
                y += lay['interlineado']
                lin += 1
                x = xs[lin]
            elif c in (1, 4):
                break
            elif c == 6:
                col = COLORES[a[0]]
            elif c == 0x0B:
                x = a[0]
            elif c == 0x0C:
                y = a[0]
            elif c == 7:
                # code07: QueSet(0) reserva el lugar del cursor (ancho del glifo 1 via getSize(0)); putSelCursol
                # pone el glifo 1 (▶) en la opcion actual (m_cur = 0 al abrir). WidthCk NO lo cuenta en el ancho.
                L, R = lr(fnt, 0)
                w = int((R - L) * lay['escala_x'])
                if not any(q[2] == 1 for q in glifos):
                    glifos.append((x, y, 1, w, int(CELDA * lay['escala_y']), col))
                x += w + lay['separacion']
            i += 1 + ARGS[c]
            continue
        g = c - 0x80
        if g == 0:
            x += int(ESPACIO * lay['escala_x'])
        else:
            L, R = lr(fnt, g)
            w = int((R - L) * lay['escala_x'])
            h = int(CELDA * lay['escala_y'])
            glifos.append((x, y, g, w, h, col))
            x += w + lay['separacion']
        i += 1
    return glifos, anchos


def muestrear(atlas01, u, v):
    """bilineal de GX (centros de texel, CLAMP): atlas (H, W, 4) float premultiplicado; u, v en texeles."""
    H, W = atlas01.shape[:2]
    u = u - 0.5
    v = v - 0.5
    u0 = np.floor(u).astype(int)
    v0 = np.floor(v).astype(int)
    fu = (u - u0)[..., None]
    fv = (v - v0)[..., None]
    u1, v1 = np.clip(u0 + 1, 0, W - 1), np.clip(v0 + 1, 0, H - 1)
    u0, v0 = np.clip(u0, 0, W - 1), np.clip(v0, 0, H - 1)
    return ((atlas01[v0, u0] * (1 - fu) + atlas01[v0, u1] * fu) * (1 - fv)
            + (atlas01[v1, u0] * (1 - fu) + atlas01[v1, u1] * fu) * fv)


def premult(rgba_u8):
    a = rgba_u8.astype(np.float32) / 255.0
    a[..., :3] *= a[..., 3:4]
    return a


def dibujar_quad(lienzo, atlas_pm, fnt, g, x, y, w, h, col, esc):
    """messageTrans/draw: quad (x, y)-(x+w, y+h) de la ortho 512x384 escalado por `esc` a la salida, UV de la celda
    (u + L .. u + R, v .. v + 32), color de vertice MODULATE, mezcla SRC_ALPHA / INV_SRC_ALPHA. Rasteriza por centros
    de pixel como el GX (sin MSAA)."""
    L, R = lr(fnt, g)
    cols = fnt['w'] // CELDA
    u0 = (g % cols) * CELDA + L
    v0 = (g // cols) * CELDA
    X0, Y0, X1, Y1 = x * esc, y * esc, (x + w) * esc, (y + h) * esc
    px0, px1 = int(np.ceil(X0 - 0.5)), int(np.ceil(X1 - 0.5))
    py0, py1 = int(np.ceil(Y0 - 0.5)), int(np.ceil(Y1 - 0.5))
    px0, py0 = max(px0, 0), max(py0, 0)
    px1, py1 = min(px1, lienzo.shape[1]), min(py1, lienzo.shape[0])
    if px1 <= px0 or py1 <= py0:
        return
    cx = np.arange(px0, px1) + 0.5
    cy = np.arange(py0, py1) + 0.5
    U = u0 + (cx - X0) / (X1 - X0) * (R - L)
    V = v0 + (cy - Y0) / (Y1 - Y0) * CELDA
    UU, VV = np.meshgrid(U, V)
    s = muestrear(atlas_pm, UU, VV)                        # premultiplicado
    c = np.array([(col >> 24) & 255, (col >> 16) & 255, (col >> 8) & 255, col & 255], np.float32) / 255.0
    src = s * c[None, None, :]                             # MODULATE (premult * color; alpha * alpha_color)
    dst = lienzo[py0:py1, px0:px1]
    lienzo[py0:py1, px0:px1] = src + dst * (1.0 - src[..., 3:4])


# ---------------------------------------------------------------------------------------------------------------
#  fuente Whisk3D
# ---------------------------------------------------------------------------------------------------------------
def unicode_whisk3d(ch):
    """la clave del .json de Whisk3D: W3dTextAtlas::NextCp solo decodifica UTF-8 de 1 y 2 bytes (<= U+07FF); un
    caracter de 3 bytes (’ “ ” … — ™ flechas) devuelve su PRIMER byte (0xE2 = 'â') y pisaria ese glifo. Devuelve la
    clave a usar o None si no hay un equivalente de 1-2 bytes."""
    sust = {'’': "'", '”': '"', '“': '«', '−': '-', '・': '·'}
    ch = sust.get(ch, ch)
    return ch if ord(ch) <= 0x7FF else None


def hornear_whisk3d(fnt, nombre, tipo_layout, esc=1.0, sufijo=''):
    """Atlas + json de Whisk3D con cada glifo YA escalado al tamano del layout (ancho (s16)((R-L)*escala_x) x alto
    32*escala_y, muestreado bilineal como el GX), a `esc` pixeles de salida por pixel de la ortho 512x384 del juego
    (1.0 = unidades del juego exactas; 1.25 = pantalla 640x480, con los avances redondeados)."""
    lay = layout(tipo_layout)
    atlas_pm = premult(fnt['rgba'])
    h = int(round(CELDA * lay['escala_y'] * esc))
    alto_linea = int(round(lay['interlineado'] * esc))
    pad = 2
    glifos, no_mapeables, recortes = {}, [], []
    for g in range(1, N_GLIFOS):
        ch = GLIFOS[g]
        clave = unicode_whisk3d(ch)
        if clave is None:
            no_mapeables.append(dict(indice=g, palabra='0x%04X' % (0x80 + g), unicode=ch, nombre=NOMBRES.get(g, '')))
            continue
        L, R = lr(fnt, g)
        w_juego = int((R - L) * lay['escala_x'])
        w = max(1, int(round(w_juego * esc)))
        adv = int(round((w_juego + lay['separacion']) * esc))
        cols = fnt['w'] // CELDA
        u0, v0 = (g % cols) * CELDA + L, (g // cols) * CELDA
        U = u0 + (np.arange(w) + 0.5) / w * (R - L)
        V = v0 + (np.arange(h) + 0.5) / h * CELDA
        UU, VV = np.meshgrid(U, V)
        img = muestrear(atlas_pm, UU, VV)
        recortes.append((clave, g, img, adv))
    # empaquetado en filas (ancho 512)
    ANCHO = 512
    x, y, fila_h = pad, pad, h
    pos = []
    for clave, g, img, adv in recortes:
        wi = img.shape[1]
        if x + wi + pad > ANCHO:
            x, y = pad, y + fila_h + pad
        pos.append((x, y))
        x += wi + pad
    alto = y + fila_h + pad
    lienzo = np.zeros((alto, ANCHO, 4), np.float32)
    for (clave, g, img, adv), (px, py) in zip(recortes, pos):
        lienzo[py:py + h, px:px + img.shape[1]] = img
        glifos[clave] = dict(x=px, y=py, w=int(img.shape[1]), h=h, xoff=0, yoff=0, avance=adv)
    # espacio (el atlas no lo trae: w/h 0, solo avance)
    glifos[' '] = dict(x=0, y=0, w=0, h=0, xoff=0, yoff=0, avance=int(round(int(ESPACIO * lay['escala_x']) * esc)))
    # des-premultiplicar para el PNG (el motor premultiplica al cargar)
    a = lienzo[..., 3:4]
    rgb = np.where(a > 0, lienzo[..., :3] / np.maximum(a, 1e-6), 0)
    png = np.clip(np.rint(np.concatenate([rgb, a], -1) * 255), 0, 255).astype(np.uint8)
    base = f'fuente_re4_{nombre}{sufijo}'
    os.makedirs(OUT_W3D, exist_ok=True)
    Image.fromarray(png, 'RGBA').save(os.path.join(OUT_W3D, base + '.png'))
    raiz = {
        'textura': base + '.png',
        'alto_linea': alto_linea,
        'origen': 'Resident Evil 4 (GameCube USA) Font/common_p.fnt, horneada por re4_extract_texto.py',
        'nota': (f'layout {tipo_layout} del juego: celda 32x32 dibujada a {lay["ancho"]}x{lay["alto"]} '
                 f'(escala {lay["escala_x"]:.4f} x {lay["escala_y"]:.4f}), separacion {lay["separacion"]}, '
                 f'interlineado {lay["interlineado"]} en la ortho 512x384; esta version x{esc:g} '
                 f'({PANT_W * esc:g}x{PANT_H * esc:g}). Cada glifo ocupa la celda entera de alto (h = {h}) y cuelga '
                 f'del tope del renglon (yoff 0), como el quad del juego: el renglon ({alto_linea}) es mas corto '
                 f'que el glifo, las lineas se solapan como en el juego. Blanco con borde negro: el color del '
                 f'Texto2D tine solo el relleno (MODULATE).'),
        'layout_juego': lay,
        'escala_salida': esc,
        'no_mapeables': no_mapeables,
        'glifos': glifos,
    }
    with open(os.path.join(OUT_W3D, base + '.json'), 'w', encoding='utf-8') as f:
        json.dump(raiz, f, ensure_ascii=False, indent=1)
    return base, raiz


# ---------------------------------------------------------------------------------------------------------------
#  traduccion propia al espanol (el disco USA no la trae): id -> texto con tags
# ---------------------------------------------------------------------------------------------------------------
ES = {
    # r100 (cuarto): SceMesSet / AEV de r100
    'r100:11': '¡No se mueve!{boton}{pagina}Deben estar empujando desde{linea}el otro lado.{boton}',
    'r100:12': 'Esta vieja camioneta bloquea{linea}el camino.{boton}{pagina}Quizás sea de alguno de{linea}'
               'los aldeanos de por aquí.{boton}',
    'r100:13': 'No es un zombi...{boton}',
    'r100:14': 'El puente está roto.{linea}No puedo volver por aquí.{boton}',
    'r100:17': 'Hay varios objetos pequeños{linea}en el estante.{boton}{pagina}Nada fuera de lo común.{boton}',
    'r100:18': 'Hay unos libros viejos.{boton}{pagina}Pero ninguno está escrito{linea}en inglés.{boton}',
    'r100:19': 'Hay algo podrido pegado{linea}en la mesa.{boton}{pagina}Parece que alguien comía aquí{linea}'
               'hasta hace muy poco.{boton}',
    'r100:20': 'Algo se quema en el fuego.{boton}{pagina}Pero no sé qué es...{boton}',
    'r100:21': 'Hay una vieja máquina de escribir.{boton}{pagina}No puedo guardar mi progreso{linea}'
               'en esta versión.{boton}',
    'r100:40': '¿Dónde están los policías?{linea}Ojalá hayan salido a tiempo.{boton}',
    'r100:47': 'Parece que han matado a mucha{linea}gente.{boton}{pagina}Espero que Ashley esté bien.{boton}',
    'r100:48': 'Parece algún tipo de advertencia.{boton}{pagina}Esto me da mala espina.{boton}',
    'r100:49': 'Parece que aquí no discriminan{linea}por sexo.{boton}{pagina}¡Tengo que encontrarla rápido!{boton}',
    'r100:50': 'El cartel dice «Pueblo».{boton}',
    # core: acciones del boton (act_btn.cpp: mensaje kind + 0x16)
    'core:22': 'HABLAR', 'core:23': 'EXAMINAR', 'core:24': 'SALTAR AFUERA', 'core:25': 'SALTAR ADENTRO',
    'core:26': 'SALTAR ABAJO', 'core:27': 'SALTAR', 'core:28': 'EMPUJAR', 'core:29': 'PATEAR',
    'core:30': 'SUBIR', 'core:31': 'BAJAR', 'core:32': 'DERRIBAR', 'core:33': 'LEVANTAR', 'core:34': 'SALTAR',
    'core:35': 'MIRAR', 'core:36': 'MIRAR ABAJO', 'core:37': 'ESPALDA A LA PARED', 'core:38': 'ABRIR',
    'core:39': 'NADAR', 'core:40': 'SALTAR', 'core:41': 'AGACHARSE', 'core:42': 'ACCIONAR', 'core:43': 'AYUDAR',
    'core:45': 'LANZAR', 'core:46': 'CORRER', 'core:47': 'TREPAR', 'core:48': 'SALTAR', 'core:50': 'ATRAPAR',
    'core:52': 'ESPERAR', 'core:53': 'ATRÁS', 'core:54': 'ESCONDERSE', 'core:55': 'SÍGUEME',
    'core:62': 'TOMAR', 'core:63': 'CORTAR', 'core:65': 'SACUDIRSE', 'core:69': 'GUARDAR', 'core:76': 'RESPONDER',
    # core: mensajes generales
    'core:2': '{x:200}{opcion}Sí {opcion}No {boton}',
    'core:3': 'Es una caja de madera.{linea}Parece que se puede romper.{boton}',
    'core:4': 'Hay un barril aquí.{linea}Parece que se puede romper.{boton}',
    'core:6': 'Hay una vieja máquina de escribir.{boton}{pagina}¿Guardar?{linea}{opcion}Sí {opcion}No {boton}',
    'core:7': 'Guardado.{boton}',
    'core:8': 'Está cerrada con llave.{boton}',
    'core:9': 'La abriste.{boton}',
    'core:10': '¡No se mueve!{boton}{pagina}Debe estar cerrada del otro lado.{boton}',
    'core:17': '¿Tomar {objeto}?{linea}{opcion}Sí {opcion}No {boton}',
    'core:21': 'Obtuviste {objeto}.{boton}',
    'core:115': 'Han pasado 6 años desde el incidente{linea}de Raccoon City...{boton}',
    'core:116': 'Alguien secuestró a la hija del{linea}Presidente, Ashley Graham.{boton}',
    'core:117': 'Por orden directa del Presidente,{linea}Leon debe averiguar su paradero y{linea}'
                'traerla sana y salva.{boton}',
    'core:143': '¿Guardar?{linea}{opcion}Sí {opcion}No {boton}',
    'core:162': '¿Seguro que quieres salir del juego?{linea}{opcion}Sí {opcion}No {boton}',
    'core:166': '¡Tengo que salvar a Ashley!{boton}',
    # objetos (tabla tipo 3)
    'objeto:4': 'Munición de pistola{volver}', 'objeto:5': 'Spray de primeros auxilios{volver}',
    'objeto:6': 'Hierba verde{volver}', 'objeto:25': 'Hierba roja{volver}', 'objeto:35': 'Pistola{volver}',
    'objeto:56': 'Cuchillo de combate{volver}', 'objeto:1': 'Granada de mano{volver}',
    'objeto:14': 'Granada cegadora{volver}', 'objeto:2': 'Granada incendiaria{volver}',
    # codec (op/op01.das): llamada 0 (la primera, en r100) y 1 (despues del primer ganado)
    'codec_op00:0': '{habla:1}{color:2}Leon, espero que me escuches.{espera:-1}{boton}{pagina}Soy Ingrid Hunnigan.'
                    '{linea}Seré tu apoyo en esta misión.',
    'codec_op00:1': '{habla:0}{color:1}Fuerte y claro.{linea}Creí que serías un poco mayor.{espera:-1}{boton}{pagina}'
                    'Entonces la chica se llama{linea}Ashley Graham, ¿no?',
    'codec_op00:2': '{habla:1}{color:2}Así es.{espera:-1}{boton}{pagina}Es la hija del Presidente.{linea}'
                    'Así que pórtate bien, ¿de acuerdo?',
    'codec_op00:3': '{habla:0}{color:1}Sea quien sea este grupo, eligió{linea}a la chica equivocada.',
    'codec_op00:4': '{habla:1}{color:2}Yo también buscaré más{linea}información sobre ellos.',
    'codec_op00:5': '{habla:0}{color:1}Bien. Hablamos luego.{linea}Cambio y fuera.',
    'codec_op01:0': '{habla:1}{color:2}¿Está todo bien?',
    'codec_op01:1': '{habla:0}{color:1}Había un lugareño hostil.{linea}No tuve más remedio que neutralizarlo.'
                    '{espera:-1}{boton}{pagina}Todavía hay otros rodeando{linea}la zona.',
    'codec_op01:2': '{habla:1}{color:2}Sal de ahí y dirígete{linea}hacia la aldea.{espera:-1}{boton}{pagina}'
                    'Toma todas las medidas necesarias{linea}para rescatar a la chica.',
    'codec_op01:3': '{habla:0}{color:1}Entendido.',
    # eventos: nombres de los policias (debug del evento: "POLICE A/B")
    'evento_r100s41:0': 'POLICÍA A', 'evento_r100s43:0': 'POLICÍA B',
    'evento_r100s44:0': 'POLICÍA A', 'evento_r100s44:1': 'POLICÍA B',
}

# que mensaje usa cada cosa de la demo (verificado contra el decomp)
USOS = {
    'r100:11': 'st1/r100.cpp r100_MesDoor (area 0xB): la puerta trabada, con el golpe SE 0x29',
    'r100:12': 'st1/r100.cpp r100_MesTruck (area 0xC): la camioneta que bloquea el camino',
    'r100:13': 'st1/r100.cpp r100_MesGanado: primer ganado, camara LookDownEm (attr 0x20 = no para el juego)',
    'r100:14': 'st1/r100.cpp r100_MesBrige (area 0x18) despues del evento del barranco, corte de camara 8',
    'r100:15': 'st1/r100.cpp r100_MesBrige antes de la muerte de los policias (placeholder "aaa" en ingles)',
    'r100:40': 'st1/r100.cpp SceMesSet(0x28) tras el evento del barranco (corte 9)',
    'r100:51': 'st1/r100.cpp MesSet(0x33, .., 0x52): el policia "habla" (solo {espera:90}: la voz sin texto)',
    'core:22': 'act_btn.cpp: kind 0 = HABLAR (con los policias); x = (-34 + 320) * 0.8, y = (240 + 153) * 0.8 - 16',
    'core:29': 'act_btn.cpp: kind 7 = PATEAR', 'core:38': 'act_btn.cpp: kind 16 = ABRIR (puertas: color 7 verde)',
    'core:34': 'act_btn.cpp: kind 12 = SALTAR', 'core:27': 'act_btn.cpp: kind 5 = SALTAR POR ENCIMA (ventana)',
}


# ---------------------------------------------------------------------------------------------------------------
def tabla_json(nombre, fuente, mdt, lang=1, extra=None):
    x0, msgs = mdt[lang]
    out = []
    for n, w in enumerate(msgs):
        texto, paginas, fuera = decodificar(w)
        vacio = not any(any(l for l in p) for p in paginas)
        e = dict(id=f'{nombre}:{n}', n=n, texto=texto, paginas=paginas,
                 plano='\n\n'.join('\n'.join(p) for p in paginas),
                 crudo=' '.join('%04X' % v for v in w))
        if vacio:
            e['vacio'] = True
        if fuera:
            e['glifos_fuera_de_common_p'] = True
        if e['id'] in USOS:
            e['uso'] = USOS[e['id']]
        if extra and n in extra:
            e.update(extra[n])
        out.append(e)
    return dict(fuente=fuente, idiomas_en_el_bloque=len(mdt), mensajes=out)


def linea_de_tiempo_codec(seq, msgs):
    """la SEQ del codec -> [{desde, hasta (s), mensaje, pagina, habla, color, lineas}] (una entrada por pagina)."""
    HABLA = {0: 'Leon', 1: 'Hunnigan'}
    out, act = [], None
    for s in seq:
        t = s['frame'] / 30.0
        if act is not None and s['accion'] in ('mostrar', 'esperar_fin', 'fin'):
            act['hasta'] = round(t, 3)
            out.append(act)
        if s['accion'] == 'fin':
            break
        if s['accion'] == 'mostrar':
            n, pag = s['mensaje'], 0
        else:
            n, pag = act['mensaje'], act['pagina'] + 1
        w = msgs[n]
        _, paginas, _ = decodificar(w)
        habla = next((w[i + 1] for i in range(len(w) - 1) if w[i] == 0x12), None)
        color = next((w[i + 1] for i in range(len(w) - 1) if w[i] == 0x06), 0)
        act = dict(desde=round(t, 3), hasta=None, mensaje=n, pagina=pag, habla=HABLA.get(habla, habla),
                   color='#%08X' % COLORES[color], lineas=paginas[pag] if pag < len(paginas) else [])
    return out


def idiomas_resumen(mdt):
    """por bloque: cuantos mensajes, si es igual al 0 / 1, si decodifica como latino."""
    res = []
    for L, (x0, msgs) in enumerate(mdt):
        ws = [c for m in msgs for c in m if c >= 0x80]
        latin = sum(1 for c in ws if 0x80 + 0x27 <= c <= 0x80 + 0x5A) / max(1, len(ws))
        fuera = sum(1 for c in ws if c - 0x80 >= N_GLIFOS) / max(1, len(ws))
        res.append(dict(bloque=L, mensajes=len(msgs), igual_al_bloque_0=msgs == mdt[0][1],
                        igual_al_bloque_1=msgs == mdt[1][1], proporcion_letras_latinas=round(latin, 2),
                        proporcion_codigos_fuera_de_common_p=round(fuera, 2)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--disc', default=DEFAULT_DISC)
    ap.add_argument('--sin-muestra', action='store_true')
    ap.add_argument('--sin-whisk3d', action='store_true', help='no correr el harness de Whisk3D para la comparacion')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    # ---------------- fuente ----------------
    fnt = leer_fuente(del_disco(a.disc, 'font/common_p.fnt', 'font/common_p.fnt'))
    Image.fromarray(fnt['rgba'], 'RGBA').save(os.path.join(OUT, 'fuente_re4.png'))
    cols = fnt['w'] // CELDA
    glifos = []
    for g in range(fnt['w'] // CELDA * (fnt['h'] // CELDA)):
        L, R = lr(fnt, g) if g < len(fnt['anchos']) else (0, 32)
        e = dict(indice=g, palabra='0x%04X' % (0x80 + g), celda=[(g % cols) * CELDA, (g // cols) * CELDA],
                 L=L, R=R, ancho=R - L, recorte=[(g % cols) * CELDA + L, (g // cols) * CELDA, R - L, CELDA])
        if g < N_GLIFOS:
            e['unicode'] = GLIFOS[g]
            e['clave_whisk3d'] = unicode_whisk3d(GLIFOS[g]) if g else ' '
            if g in NOMBRES:
                e['nombre'] = NOMBRES[g]
        else:
            e['vacio'] = True
        glifos.append(e)
    fuente_json = {
        'origen': 'Resident Evil 4 (GameCube USA) files/font/common_p.fnt (mes.cpp loadCommonFont: la fuente de '
                  'todos los idiomas salvo el japones; el disco trae ademas stage/event/sscrn_p.fnt de 1024x1024 con '
                  'el mismo mapa de glifos en otro trazo, que el codigo no-japones del decomp NO carga)',
        'textura': 'fuente_re4.png',
        'archivo': {'ofs_tpl': fnt['ofs_tpl'], 'ofs_anchos': fnt['ofs_anchos'],
                    'formato': 'TPL, 1 textura GX_TF_C4 (4 bits) + TLUT GX_TL_RGB5A3 de 16 colores; tabla de anchos '
                               '= pares u8 (L, R) por glifo'},
        'atlas': {'ancho': fnt['w'], 'alto': fnt['h'], 'celda': [CELDA, CELDA], 'columnas': cols,
                  'filas': fnt['h'] // CELDA, 'glifos_usados': N_GLIFOS},
        'paleta': [list(c) for c in fnt['paleta']],
        'aspecto': 'relleno blanco con borde/sombra negra (indices 1..8 negro con alpha creciente, 9..15 grises '
                   'hasta blanco); el color del texto MULTIPLICA (TEV MODULATE) -> tine el relleno, el borde queda '
                   'negro. Filtro bilineal (GXInitTexObj), mezcla SRC_ALPHA / INV_SRC_ALPHA, sin z',
        'codificacion': {
            'palabra': 'u16 big-endian; < 0x80 = codigo de control, >= 0x80 = glifo (palabra - 0x80)',
            'espacio': 'glifo 0 (palabra 0x0080): no dibuja, avanza (s16)(8 * escala_x) (getSpaceWidth = 8; 13 en '
                       'japones); la tabla de anchos del glifo 0 es (32, 0) y getSize usa la entrada 1 en su lugar',
            'glifo': 'celda (i % 32, i / 32) de 32x32; se dibuja la franja [L, R) de la celda, todo el alto',
            'ancho_dibujado': '(s16)((R - L) * escala_x) x (s16)(32 * escala_y), escala = tamano del layout / 32',
            'avance': 'ancho_dibujado + separacion (layout); sin kerning por pares',
            'control': {TAGS[c]: dict(codigo='0x%02X' % c, argumentos=ARGS[c], que_hace=CONTROL_DOC[TAGS[c]])
                        for c in range(len(ARGS))},
            'tags_en_mensajes_json': 'cada codigo de control aparece como {nombre} o {nombre:arg}; 0xFFFF = -1',
        },
        'pantalla': {'ortho': [PANT_W, PANT_H], 'salida': [SALIDA_W, SALIDA_H],
                     'nota': 'messageCamera: C_MTXOrtho 512x384 sobre el EFB 640x480 (x1.25); las posiciones de '
                             'los mensajes son s16 de la ortho'},
        'layouts_ingles': {t: layout(t) for t in LAYOUT_TIPOS},
        'layouts_japones': {t: layout(t, 0) for t in LAYOUT_TIPOS},
        'alineacion': {
            'por_defecto': 'bloque centrado: TODAS las lineas arrancan en (512 - ancho_de_la_linea_mas_larga) >> 1 '
                           '(lineas alineadas a la izquierda dentro del bloque)',
            'attr_0x80000': 'cada linea centrada por separado',
            'attr_0x20000': 'a la izquierda en la x pedida (boton de accion)',
            'attr_0x40000': 'a la derecha',
            'attr_0x10000': 'centrado vertical: y = (384 - lineas * interlineado) >> 1',
            'ancho_de_linea': 'suma de avances (incluye el espacio final que los mensajes traen antes de {boton})',
        },
        'posiciones': {
            'mensaje_de_cuarto': 'SceMesSet: x ignorada (centrado), y de la 1ra linea = 0x150 - interlineado - '
                                 'alto - 1 = 278 con CAPTION; cada {linea} baja el interlineado (25)',
            'boton_de_accion': 'act_btn.cpp: MesSet(kind + 0x16, x, y, 0x200F1, slot 1, color 0 o 7 en puertas); '
                               'x = (X + 320) * 0.8, y = (240 - Y) * 0.8 - alto/2 con (X, Y) = unidad 1 de la tabla '
                               'IDC_ACT_BUTTON (core.das 28) = (-34, -153) -> (228, 298)',
            'codec': 'ss_term.cpp OpeMesSet: MesSet(n, x, y, 0x03000054, 0, 0, 4): x centrado (sin 0x20000), '
                     'y = (240 - Y) * 0.8 de la unidad 0xFE de ss_term; LAYOUT_OPERATOR',
        },
        'colores_mes_col_tbl': ['#%08X' % c for c in COLORES],
        'tipeo': 'Message::move: un glifo cada (vel + 1) frames (vel 1 por defecto = 15 glifos/s a 30 fps); '
                 'A/B completa la pagina; attr 0x40/0x80 = instantaneo',
        'glifos': glifos,
    }
    with open(os.path.join(OUT, 'fuente_re4.json'), 'w', encoding='utf-8') as f:
        json.dump(fuente_json, f, ensure_ascii=False, indent=1)

    # ---------------- mensajes ----------------
    core = archive.Archive(del_disco(a.disc, 'etc/core.das', 'etc/core.das'))
    r100 = archive.Archive(del_disco(a.disc, 'St1/r100.das', 'St1/r100.das'))
    op01 = open(del_disco(a.disc, 'op/op01.das', 'op/op01.das'), 'rb').read()
    mdt_core = leer_mdt(core.entry(6).data)
    mdt_obj = leer_mdt(core.entry(17).data)
    mdt_sys = leer_mdt(core.entry(23).data)
    mdt_prog = leer_mdt(core.entry(24).data)
    mdt_r100 = leer_mdt([e for e in r100.entries() if e.tag == 'MDT'][0].data)
    tablas = {
        'core': tabla_json('core', 'etc/core.das entrada 6 (pCore->ofs_28; MesData tipo 0/1/2 fuera de un cuarto)',
                           mdt_core),
        'objeto': tabla_json('objeto', 'etc/core.das entrada 17 (pCore->ofs_54; tipo 3 = nombres de objetos, '
                             '{objeto} / {llamar_objeto})', mdt_obj),
        'sistema': tabla_json('sistema', 'etc/core.das entrada 23 (errores de disco)', mdt_sys),
        'progresivo': tabla_json('progresivo', 'etc/core.das entrada 24 (barrido progresivo)', mdt_prog),
        'r100': tabla_json('r100', 'St1/r100.das etiqueta MDT (pG->RoomMes, tipo 1 = attr 2)', mdt_r100),
    }
    resumen_idiomas = {'core': idiomas_resumen(mdt_core), 'r100': idiomas_resumen(mdt_r100)}
    # eventos de r100 (MDT dentro del .evd): en ingles solo etiquetas de depuracion / ids de las voces
    for ev in ['r100s03', 'r100s40', 'r100s41', 'r100s43', 'r100s44']:
        p = os.path.join(EXTR, 'Evd', ev + '.evd')
        if not os.path.isfile(p):
            p = del_disco(a.disc, f'Evd/{ev}.evd', f'Evd/{ev}.evd')
        arc = archive.Archive(p)
        m = [e for e in arc.entries() if e.tag == 'MDT']
        if m:
            tablas['evento_' + ev] = tabla_json('evento_' + ev, f'Evd/{ev}.evd {m[0].label} (Event::MesSet: el '
                                                'juego NO lo muestra con language 1)', leer_mdt(m[0].data))
    # codec: op/op01.das (+0x400), 13 llamadas: MDT 0..12, SEQ 13..25
    ents = archive.parse_body(op01[0x400:])
    llamadas = []
    for op in range(13):
        mdt = leer_mdt(ents[op][1])
        seq_d = ents[13 + op][1]
        seq = []
        for i in range(len(seq_d) // 16):
            x0, x2, t, no, arg = struct.unpack_from('>Hhiii', seq_d, 16 * i)
            seq.append(dict(indice=x2, frame=t, segundos=round(t / 30.0, 3),
                            accion=('fin' if arg == -1 else ('esperar_fin' if no == -1 else 'mostrar')),
                            mensaje=no, tiempo_visible=arg))
            if arg == -1:
                break
        t = tabla_json(f'codec_op{op:02d}', f'op/op01.das +0x400 entrada {op} (MDT) / {13 + op} (SEQ)', mdt)
        llamadas.append(dict(op=op, stream=f'bio4evt str {0x8C + op} (SndStrReq(1, 0x8C + op))',
                             secuencia=seq, subtitulos=linea_de_tiempo_codec(seq, mdt[1][1]),
                             mensajes=t['mensajes']))
    tablas['codec_op01'] = dict(
        fuente='op/op01.das (ss_term.cpp OpeMesTblInit: MDT = entradas 4..16, SEQ = 17..29 de la tabla SS_ARC)',
        tiempo='SEQ.frame en frames de 30 fps (la op 0 termina en 810 = 27.0 s; su stream 0x8C = str1_140.wav '
               'dura 26.1 s)',
        mostrar='OpeMesSet: MesSet(n, x, y, 0x03000054): attr 0x04 = tipo 2 (este MDT), 0x10 no para el juego, 0x40 '
                'sin tipeo (instantaneo), 0x01000000 queda en pantalla al terminar, 0x02000000 = {boton} no espera. '
                'Cada mensaje es {habla:n}{color:c} + paginas separadas por {espera:-1}{boton}{pagina}: la pagina '
                'siguiente sale cuando la SEQ trae "esperar_fin" (OpeMesSet(-1) -> WaitEnd). tiempo_visible 0 = no '
                'se oculta: lo reemplaza el mensaje siguiente. Centrado (sin 0x20000), LAYOUT_OPERATOR',
        habla={'0': 'Leon (color 1 = #87CFA5 verde)', '1': 'Hunnigan (color 2 = #CD7D5F naranja)'},
        uso_r100='st1/r100.cpp: OpeSetOpenTerm(0) = llamada op 0 (despues del evento s40, la primera llamada a '
                 'Hunnigan); OpeSetOpenTerm(1, ..) = op 1 (despues de matar al primer ganado)',
        llamadas=llamadas)
    demo = {
        'acciones_boton': {k: f'core:{0x16 + v}' for k, v in
                           dict(HABLAR=0, EXAMINAR=1, PATEAR=7, ABRIR=16, SALTAR=12, SALTAR_POR_ENCIMA=5,
                                EMPUJAR=6, SUBIR=8, BAJAR=9).items()},
        'r100_examinar': ['r100:17', 'r100:18', 'r100:19', 'r100:20', 'r100:21'],
        'r100_scripts': ['r100:11', 'r100:12', 'r100:13', 'r100:14', 'r100:40', 'r100:51'],
        'r100_carteles': ['r100:47', 'r100:48', 'r100:49', 'r100:50'],
        'codec_hunnigan': ['codec_op01 op 0', 'codec_op01 op 1'],
        'menu': ['core:2', 'core:6', 'core:7', 'core:8', 'core:143', 'core:162'],
        'objetos_iniciales': ['objeto:35', 'objeto:4', 'objeto:56', 'objeto:5', 'objeto:6'],
        'policias_hablar': 'eventos r100s41/s43/s44 (sus MDT en ingles solo dicen POLICE A / POLICE B: voz sin texto)',
    }
    idiomas = {
        'disco': 'USA: files/ss/Eng y files/etc/Eng son las UNICAS carpetas de idioma; main.cpp setLanguage() fija '
                 'language 1 (ingles). No hay frances, aleman, espanol ni italiano en este disco',
        'bloques_mdt': 'cada MDT trae 6 bloques (mes.h: 0 JP, 1 EN, 2..5 = DE/FR/ES/IT en la version PAL); en el '
                       'disco USA el bloque 0 es japones (fuente common_j), el 1 ingles y los 2..5 son copias '
                       '(japones con la fuente del escenario / codec, o el ingles repetido)',
        'resumen': resumen_idiomas,
    }
    with open(os.path.join(OUT, 'mensajes_en.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(idioma='en', origen='Resident Evil 4 (GameCube USA), bloque de idioma 1 de cada MDT',
                       idiomas=idiomas, demo=demo, tablas=tablas), f, ensure_ascii=False, indent=1)

    # ---------------- espanol (traduccion propia) ----------------
    es_tablas = {}
    en_idx = {m['id']: m for t in tablas.values() if 'mensajes' in t for m in t['mensajes']}
    for ll in llamadas:
        en_idx.update({m['id']: m for m in ll['mensajes']})
    avisos = []
    es_palabras = {}
    for mid, txt in ES.items():
        tabla, n = mid.split(':')
        tipo = 'OPERATOR' if tabla.startswith('codec') else (
            'ACT_BTN' if tabla == 'core' and 22 <= int(n) <= 88 else 'CAPTION')
        lay = layout(tipo)
        w = codificar(txt)
        es_palabras[mid] = w
        texto, paginas, _ = decodificar(w)
        # ancho de la linea mas larga de cada pagina, con el layout donde se muestra
        ancho = max(max(maquetar(fnt, codificar(p), lay, y0=0)[1]) for p in txt.split('{pagina}'))
        if ancho > 480:
            avisos.append(f'{mid}: una linea mide {ancho} px con {tipo} (> 480 de 512)')
        e = dict(id=mid, texto=texto, paginas=paginas, plano='\n\n'.join('\n'.join(p) for p in paginas),
                 crudo=' '.join('%04X' % v for v in w), layout=tipo, ancho_max_px=ancho)
        if mid in en_idx:
            e['ingles'] = en_idx[mid]['plano']
        if mid in USOS:
            e['uso'] = USOS[mid]
        es_tablas.setdefault(tabla, []).append(e)
    codec_es = {}
    for ll in llamadas:
        op = ll['op']
        msgs = [es_palabras.get(f'codec_op{op:02d}:{k}') for k in range(len(ll['mensajes']))]
        if all(msgs):
            codec_es[f'op{op:02d}'] = linea_de_tiempo_codec(ll['secuencia'], msgs)
    with open(os.path.join(OUT, 'mensajes_es.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(idioma='es', origen='TRADUCCION PROPIA (re4_extract_texto.py ES). El disco USA no trae '
                       'espanol: estos textos NO son del juego. "crudo" = las palabras u16 con la tabla de '
                       'glifos de common_p.fnt (todas las letras del espanol existen: á é í ó ú ü ñ Ñ ¿ ¡)',
                       avisos=avisos, codec_subtitulos=codec_es, tablas=es_tablas), f, ensure_ascii=False, indent=1)

    # ---------------- Whisk3D ----------------
    hechas = []
    for nombre, tipo in FUENTES_W3D.items():
        for esc, suf in ((1.0, ''), (1.25, '_x125')):
            base, _ = hornear_whisk3d(fnt, nombre, tipo, esc, suf)
            hechas.append(base)

    # ---------------- muestra con las reglas del juego ----------------
    if not a.sin_muestra:
        muestra_juego(fnt, en_idx, es_tablas, not a.sin_whisk3d)
    print('fuente:', os.path.join(OUT, 'fuente_re4.png'), f'{fnt["w"]}x{fnt["h"]}', N_GLIFOS, 'glifos')
    print('tablas en:', ', '.join(f'{k} ({len(v.get("mensajes", v.get("llamadas", [])))})' for k, v in tablas.items()))
    print('espanol:', len(ES), 'mensajes;', 'avisos:', avisos or 'ninguno')
    print('whisk3d:', ', '.join(hechas))


def pagina_palabras(w, n=0):
    """las palabras de la pagina n (desde un {inicio}/{pagina} hasta {pagina}/{fin}), respetando los argumentos;
    el ultimo {color} de las paginas anteriores se arrastra (m_col sigue vigente)."""
    paginas, act, color = [], [], None
    i = 0
    while i < len(w):
        c = w[i]
        k = 1 + (ARGS[c] if c < len(ARGS) else 0)
        act += w[i:i + k]
        if c == 6:
            color = w[i + 1]
        if c in (1, 4):
            paginas.append(act)
            act = [0] + ([6, color] if color is not None else [])
        i += k
    return paginas[min(n, len(paginas) - 1)]


FONDO = (70, 70, 76)   # gris de fondo de las muestras


def render_juego(fnt, items, esc, fondo=FONDO):
    """lienzo (512x384 * esc) con cada (palabras, layout, x, y, attr, color) maquetado con las reglas del juego."""
    W, H = int(PANT_W * esc), int(PANT_H * esc)
    lienzo = np.zeros((H, W, 4), np.float32)
    lienzo[..., :3] = np.array(fondo, np.float32) / 255.0
    lienzo[..., 3] = 1.0
    atlas_pm = premult(fnt['rgba'])
    for w, tipo, x0, y0, attr, color in items:
        gl, _ = maquetar(fnt, w, layout(tipo), x0, y0, attr, color)
        for (x, y, g, gw, gh, col) in gl:
            dibujar_quad(lienzo, atlas_pm, fnt, g, x, y, gw, gh, col, esc)
    return np.clip(np.rint(lienzo[..., :3] * 255), 0, 255).astype(np.uint8)


def escena_muestra(en_idx, es_tablas):
    """la muestra: subtitulos (EN y ES) + botones de accion, en coordenadas del juego (512x384)."""
    es_idx = {m['id']: m for t in es_tablas.values() for m in t}

    def palabras(mid, idioma, pag=0):
        crudo = (en_idx if idioma == 'en' else es_idx)[mid]['crudo']
        return pagina_palabras([int(v, 16) for v in crudo.split()], pag)
    return [   # (palabras, layout, x, y, attr, color)
        (palabras('r100:11', 'en', 1), 'CAPTION', 0, 14, 0, 0),
        (palabras('r100:11', 'es', 1), 'CAPTION', 0, 68, 0, 0),
        (palabras('r100:49', 'es', 1), 'CAPTION', 0, 122, 0, 0),
        (palabras('core:22', 'es'), 'ACT_BTN', 228, 158, 0x20000, 0),
        (palabras('core:38', 'en'), 'ACT_BTN', 228, 190, 0x20000, 7),    # puerta: color 7
        (palabras('codec_op00:0', 'en', 1), 'OPERATOR', 0, 232, 0, 0),   # {color:2} viene en el texto
        (palabras('codec_op00:1', 'es', 0), 'OPERATOR', 0, 290, 0, 0),
    ]


def lineas_muestra(fnt, items):
    """cada linea de la muestra ya ubicada por las reglas del juego: [(texto unicode, layout, x, y, color)]. Es lo
    que un Texto2D por linea necesita (Whisk3D centra cada linea por separado y no parte en \\n)."""
    out = []
    for w, tipo, x0, y0, attr, color in items:
        gl, _ = maquetar(fnt, w, layout(tipo), x0, y0, attr, color)
        _, paginas, _ = decodificar(w + [1])
        ys = sorted(set(g[1] for g in gl))
        for texto, yy in zip(paginas[0], ys):
            gl_lin = sorted((g for g in gl if g[1] == yy), key=lambda g: g[0])
            # Texto2D tiene UN color: el del primer glifo de la linea (un {color} a mitad de linea se pierde)
            out.append((texto, tipo, gl_lin[0][0], yy, gl_lin[0][5]))
    return out


W3D_BIN = os.path.normpath(os.path.join(HERE, '..', '..', 'Whisk3D', 'platform', 'linux', 'build', 'whisk3d'))
PRUEBA = os.path.join(OUT_W3D, 'prueba')
FUENTE_DE_LAYOUT = {'CAPTION': 'subtitulo', 'ACT_BTN': 'boton', 'OPERATOR': 'codec'}


def texto_whisk3d(t):
    return ''.join(unicode_whisk3d(c) or '' for c in t)


def escribir_prueba(lineas, esc, nombre):
    """escena de texto de Whisk3D (.w3d) + UI (.w3dui): UI "igual que el render" (en modo juego el lienzo ES el
    viewport, escala 1), un rect de 512x384 * esc px arriba-izquierda con el gris de fondo y adentro un Texto2D por
    linea (ancla arriba-izquierda, alineado a la izquierda/arriba) en la posicion del juego * esc (fraccion del
    rect del padre)."""
    suf = '' if esc == 1.0 else '_x125'
    W, H = int(PANT_W * esc), int(PANT_H * esc)
    hijos = []
    for k, (texto, tipo, x, y, col) in enumerate(lineas):
        f = f'../fuente_re4_{FUENTE_DE_LAYOUT[tipo]}{suf}.png'
        alto = json.load(open(os.path.join(OUT_W3D, f[3:-4] + '.json')))['alto_linea']
        hijos.append({'tipo': 'texto', 'nombre': 'L%02d' % k,
                      'pos': [round(x * esc) / W, round(y * esc) / H, 0], 'ancla': 5,
                      'texto': texto_whisk3d(texto), 'tam': alto, 'alignX': 0, 'alignY': 0,
                      'color': [((col >> s) & 255) / 255.0 for s in (24, 16, 8, 0)],
                      'fuente': '', 'fuenteBitmap': f, 'hijos': []})
    pantalla = {'tipo': 'rect', 'nombre': 'Pantalla', 'pos': [0, 0, 0], 'ancla': 0, 'ancho': W, 'alto': H,
                'tamModo': 1, 'color': [c / 255.0 for c in FONDO] + [1], 'hijos': hijos}
    ui = {'version': 1, 'nombre': 'Subtitulos',
          'ventana': {'igualQueRender': True, 'ancho': 640, 'alto': 480, 'escalaGlobal': 1, 'color': [0, 0, 0, 0]},
          'paleta': '', 'paletas': [], 'hijos': [pantalla]}
    with open(os.path.join(PRUEBA, nombre + '.w3dui'), 'w', encoding='utf-8') as fh:
        json.dump(ui, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(PRUEBA, nombre + '.w3d'), 'w') as fh:
        fh.write('Whisk3D {\n    version: 20251127\n    Escena {\n        background: "0.0, 0.0, 0.0, 1.0"\n'
                 '        Camera {\n            name: "Camara"\n            y: -8.0\n            z: 2.0\n        }\n'
                 '        UI {\n            archivo: "%s.w3dui"\n        }\n    }\n}\n' % nombre)


def correr_whisk3d(nombre):
    guion = os.path.join(PRUEBA, nombre + '_guion.txt')
    with open(guion, 'w') as fh:
        fh.write(f'abrirw3d {nombre}.w3d\nuifuente\nventana 1024 768\njuego on\nsimplay 2\n'
                 f'uishot {nombre}_captura.png\njuego off\n')
    r = subprocess.run([W3D_BIN, '--script', guion], cwd=PRUEBA, capture_output=True, text=True, timeout=600)
    if 'TEST OK' not in r.stdout:
        raise RuntimeError('whisk3d --script fallo:\n' + r.stdout[-3000:] + r.stderr[-2000:])
    return np.asarray(Image.open(os.path.join(PRUEBA, nombre + '_captura.png')).convert('RGB'))


def prueba_whisk3d(fnt, items):
    """dibuja la muestra con Texto2D de Whisk3D (harness --script en modo juego, captura uishot) a escala 1
    (512x384, fuente x1) y 1.25 (640x480, fuente _x125) y la compara pixel a pixel con las reglas del juego."""
    os.makedirs(PRUEBA, exist_ok=True)
    lineas = lineas_muestra(fnt, items)
    res = {}
    for esc in (1.0, 1.25):
        nombre = 'muestra_512' if esc == 1.0 else 'muestra_640'
        escribir_prueba(lineas, esc, nombre)
        cap = correr_whisk3d(nombre)
        x0, y0, x1, y1 = rect_lienzo(cap)
        W, H = int(PANT_W * esc), int(PANT_H * esc)
        if (x1 - x0, y1 - y0) != (W, H):
            print(f'aviso: el rect de {nombre} mide {x1 - x0}x{y1 - y0}, se esperaba {W}x{H}')
        w3d = cap[y0:y0 + H, x0:x0 + W]
        juego = render_juego(fnt, items, esc)
        dif = np.abs(w3d.astype(int) - juego.astype(int)).max(-1)
        dif[:, x1 - x0:] = 0      # el rect cae en medio pixel (centrado en el viewport): la ultima columna es de afuera
        dif[y1 - y0:, :] = 0
        res[nombre] = dict(rect_en_captura=[int(x0), int(y0), int(x1 - x0), int(y1 - y0)], pixeles=W * H,
                           iguales_tol2=int((dif <= 2).sum()), dif_max=int(dif.max()),
                           dif_media=round(float(dif.mean()), 3), px_con_dif_mayor_a_16=int((dif > 16).sum()))
        Image.fromarray(w3d).save(os.path.join(OUT, f'{nombre}_whisk3d.png'))
        Image.fromarray(juego).save(os.path.join(OUT, f'{nombre}_juego.png'))
        mapa = np.clip(dif * 4, 0, 255).astype(np.uint8)
        blanco = np.full((H, 8, 3), 255, np.uint8)
        lado = np.concatenate([juego, blanco, w3d, blanco, np.stack([mapa] * 3, -1)], 1)
        Image.fromarray(lado).save(os.path.join(OUT, f'comparacion_{nombre[8:]}.png'))
    with open(os.path.join(OUT, 'comparacion.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    return res


def rect_lienzo(cap):
    m = np.abs(cap.astype(int) - np.array(FONDO)).sum(-1) <= 3
    ys, xs = np.nonzero(m)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def muestra_juego(fnt, en_idx, es_tablas, whisk3d=True):
    items = escena_muestra(en_idx, es_tablas)
    Image.fromarray(render_juego(fnt, items, 1.25)).save(os.path.join(OUT, 'muestra_640_juego.png'))
    if whisk3d and os.path.isfile(W3D_BIN):
        print('comparacion con Whisk3D:', prueba_whisk3d(fnt, items))


if __name__ == '__main__':
    main()
