"""LOS ITEMS de r100 para el N95 (de re3_w3d/out/items: re4_extract_items.py):

  item_XX.mdl         el modelo de cada item (XX = su id en hexa), de un hueso, centrado en su origen
  item_brillo.mdl     la columna de luz de lo que sueltan los enemigos
  tablas.bin:
    item.<k>          los del piso desde el arranque: id, cantidad, x y z, giro x, giro y (radianes), radio
    itemdef.<id>      tipo, cantidad por defecto, maximo, giro del examen x y z (grados), escala del examen
    itemnom.<id>      el nombre en pantalla (los codigos de sus letras)
    itemui            la textura de la pantalla de recoger (640 x 480 con alfa: el juego se ve detras)
"""
import json
import os

import numpy as np
from PIL import Image

import glb
import modelos


class _Malla:
    """lo que Modelo.agregar_malla lee de una malla, armado desde un .glb"""

    def __init__(self, g):
        P, N, U, I, partes = [], [], [], [], []
        base = 0
        for mi, m in enumerate(g.json['meshes']):
            for prim in m['primitives']:
                pos = g.accessor(prim['attributes']['POSITION']).astype(np.float64)
                nrm = g.accessor(prim['attributes']['NORMAL']).astype(np.float64)
                uv = g.accessor(prim['attributes']['TEXCOORD_0']).astype(np.float64)
                idx = g.accessor(prim['indices']).astype(np.int64).reshape(-1) + base
                partes.append(('p%d' % len(partes), prim.get('material', 0), sum(len(i) for i in I), len(idx)))
                P.append(pos)
                N.append(nrm)
                U.append(uv)
                I.append(idx)
                base += len(pos)
        self.pos = np.concatenate(P)
        self.nrm = np.concatenate(N)
        self.uv = np.concatenate(U)
        self.idx = np.concatenate(I)
        self.nv = len(self.pos)
        self.partes = partes
        self.formas = []


def _modelo(ruta_glb, archivo, tex, datos, nombre_tex, repetir=True):
    g = glb.Glb(ruta_glb)
    malla = _Malla(g)
    carpeta = os.path.dirname(ruta_glb)
    imgs = g.json.get('images', [])
    texs = g.json.get('textures', [])
    materiales = {}
    for k, m in enumerate(g.json.get('materials', [])):
        t = m.get('pbrMetallicRoughness', {}).get('baseColorTexture', {}).get('index')
        uri = imgs[texs[t]['source']].get('uri') if t is not None else None
        materiales[k] = {'flags': {'transparente': m.get('alphaMode') == 'BLEND', 'culling': not m.get('doubleSided')},
                         'png': os.path.join(carpeta, uri) if uri else None}

    def tex_de(mj):
        if not mj.get('png'):
            return 0xFFFFFFFF
        return tex.agregar(nombre_tex + '_' + os.path.basename(mj['png'])[:-4], mj['png'], repetir=repetir, tope=128)

    arm = {'bones': [{'nombre': 'raiz', 'padre': -1, 'restT': [0, 0, 0], 'restR': [0, 0, 0], 'restS': [1, 1, 1],
                      'invBind': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
    M = modelos.Modelo(archivo, arm, ([], []), tex)
    M.agregar_malla(malla, materiales, tex_de, 1.0, rigida_en='raiz')
    return M.guardar(os.path.join(datos, archivo))


def _codigos(s):
    return [float(ord(c)) for c in s]


def armar(re3, tex, tablas, datos, log=print):
    raiz = os.path.join(re3, 'out', 'items')
    J = json.load(open(os.path.join(raiz, 'items_r100.json'), encoding='utf-8'))
    cat = J['catalogo_itm']
    for hx, c in sorted(cat.items()):
        iid = int(hx, 16)
        _modelo(os.path.join(raiz, c['modelo']['glb']), 'item_%02X.mdl' % iid, tex, datos, 'i%02X' % iid)
        ex = c.get('examen', {})
        rot = ex.get('rot_deg', [0, 0, 0])
        tablas.poner('itemdef.%d' % iid, [c['tipo_item'], c.get('defNum') or 0, c.get('maxNum') or 0] + list(rot) +
                     [ex.get('escala', 1.0)])
        tablas.poner('itemnom.%d' % iid, _codigos(c['nombre']))
    n = 0
    for p in J['colocaciones']:
        if not p.get('origen', {}).get('tipo', '').startswith('colocado en el piso'):
            continue
        iid = int(p['id'], 16)
        if iid >= 0x1000:
            continue
        rx, ry = (p['rot_rad'][0], p['rot_rad'][1]) if p.get('rot_aplicada') else (0.0, 0.0)
        tablas.poner('item.%d' % n, [iid, p.get('num') or 0] + list(p['pos_m']) + [rx, ry, p.get('radio_recoger_m', 3.0)])
        n += 1
    # la columna de luz que gira sobre lo que sueltan los enemigos (EFM 0x25 de core.das)
    _modelo(os.path.join(raiz, 'fx', 'efm25_pilar_brillo.glb'), 'item_brillo.mdl', tex, datos, 'ibrillo', repetir=False)
    img = Image.open(os.path.join(raiz, 'ui', 'examine_rgba_640x480.png'))
    tablas.poner('itemui', [tex.agregar('u_examinar', img, repetir=False, tope=512)])
    log('items: %d modelos, %d en el piso' % (len(cat), n))
