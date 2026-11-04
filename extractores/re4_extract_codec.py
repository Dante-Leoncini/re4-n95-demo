#!/usr/bin/env python3
"""
LA PRIMERA LLAMADA DE RADIO CON HUNNIGAN (RE4 GameCube USA, despues de la intro r100s40) -> Whisk3D.

  out/codec/leon_codec.glb       Leon del codec (pl00 cuerpo + chaqueta + ojos, cabeza ss_term:8 con 10 shapes, mano con
                                 la radio ss_term:6), clips "espera" (60 f, loop) y "llamada" (815 f), raiz en el
                                 ESPACIO DEL CODEC (ver codec.json "espacio_3d")
  out/codec/hunnigan_codec.glb   Hunnigan (ss_oc101 5+1 piezas, cabeza con 9 shapes), clips "espera" (60 f) y "llamada" (814 f)
  out/codec/*_atlas.png          atlas a resolucion completa
  out/codec/caras.json           pesos de los shapes por frame de "llamada" (tambien van como canal glTF "weights")
  out/codec/ui/                  texturas 2D (frame del codec, fondos, lineas) + ui.json (unidades ID simuladas) +
                                 capas renderizadas (fondo = detras de los modelos, frente = delante)
  out/codec/audio/               str1_140.wav (la voz de la llamada, bio4evt #140), se_core_14/15.wav (abrir/cerrar)
  out/codec/codec.json           secuencia completa, layout, camara, luces, timeline de subtitulos

De donde sale cada cosa (decomp ../re4/src):
  game/sscrn.cpp      OpeSetOpenTerm (radio en la mano, tono bio4evt #3, motion pl00 0x79, SubScreenOpen(SS_OPEN_TERM)),
                      SubScreenExec (fundido a negro 3 f, pantalla 640x448), SubScreenExit (fundido desde negro 3 f),
                      OpeSetOpenTermEnd (fundido desde negro 10 f).
  Sscrn/ss_term.cpp   SsTermInit (lee SS/eng/ss_term.dat, op/op01.das, SS/cmn/ss_oc101.dat; fundido desde negro 5 f),
                      SsTermMain::init (ID 2D: ss_term SS8 -> IDC_SSCRN_0 ot 0xC, SS9 -> IDC_SSCRN_NEAR_0 ot 0xF;
                      camara (0,0,2000) fov 50; Hunnigan en (0,-1600,950), Leon en (435,-1580,850) mirando a la camara),
                      OpeMesMove / OpeSeqMove / OpeMesSet (la tabla TermSeq de op01 SS17, mensajes MDT SS4, stream
                      bio4evt #0x8C), termMotionSet (hokan 10) / termMotionCancel (loop).
  Sscrn/ss_model.cpp  tel00ModelInit / hunniganModelInit (las piezas).

Uso:  python3 re4_extract_codec.py [--disc RUTA.rvz] [--solo modelos|ui|audio|json]
"""
import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf  # noqa: E402
import re4_extract_leon as L  # noqa: E402
import re4_extract_personajes_evento as P  # noqa: E402
import re4_extract_hud as HUD  # noqa: E402
import re4_eff  # noqa: E402

DEFAULT_DISC = L.DEFAULT_DISC
DTK = L.DTK
OUT = os.path.join(HERE, 'out', 'codec')
OUT_UI = os.path.join(OUT, 'ui')
EXT = os.path.join(HERE, 'extracted')
SCALE = 0.001
FPS = 30.0

ARCHIVOS = ['ss/Eng/ss_term.dat', 'ss/Eng/ss_cmmn.dat', 'ss/Cmn/ss_oc101.dat', 'op/op01.das', 'em/pl00.drs',
            'etc/core.das']

# ---- lo fijo del decomp (ss_term.cpp) ----
CAM_POS = (0.0, 0.0, 2000.0)            # terminalCameraInit
CAM_FOVY = 50.0
TERM_PL_POS = (0.0, -1600.0, 950.0)     # term_pl_pos -> Hunnigan (MapMgr work 2)
TERM_CAM_POS = (435.0, -1580.0, 850.0)  # term_cam_pos -> Leon (MapMgr work 0), ang.y = atan2(cam - pos)
LEON_ANG_Y = math.atan2(CAM_POS[0] - TERM_CAM_POS[0], CAM_POS[2] - TERM_CAM_POS[2])
OPE_WAIT = 0x1E                         # SsTermMain::init ope.wait
MDT_NO = 0x8C                           # term_ope_tbl[0].mdtNo -> SndStrReq(1, 0x8C) = bio4evt #140
HOKAN_LLAMADA = 10                      # termMotionSet(pTelDat, 10)
SHAPE_X_HUNNIGAN = 1.37                 # ShapeSet(.., 0xA): bit 3 -> CalculateShape_new multiplica por 1.37


def asegurar(disc):
    for f in ARCHIVOS:
        p = os.path.join(EXT, f)
        if not os.path.isfile(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            subprocess.check_call([DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/{f}', p])


def arc(f):
    return archive.Archive(os.path.join(EXT, f))


def ss(a, n):
    """SS_ARC_PTR(arc, n): entrada n - 4 del cuerpo (ofs[0..3] = cabecera count,0,0,0)."""
    return a.entry(n - 4).data


def pl(n):
    """PL_ARC(n) de pl00: entrada n - 4."""
    return arc('em/pl00.drs').entry(n - 4).data


def mat_modelo(pos, ang_y):
    """RotMatrix(Rz*Ry*Rx) con solo Y + TransMatrix: matriz 3x4 del juego (mm)."""
    c, s = math.cos(ang_y), math.sin(ang_y)
    return (c, 0.0, s, pos[0], 0.0, 1.0, 0.0, pos[1], -s, 0.0, c, pos[2])


# ---------------------------------------------------------------------------------------------------
#  PERSONAJES
# ---------------------------------------------------------------------------------------------------
def personajes():
    term, oc = arc('ss/Eng/ss_term.dat'), arc('ss/Cmn/ss_oc101.dat')
    return {
        'leon': dict(
            pref='LeonCodec', raiz='leon_codec', pos=TERM_CAM_POS, ang=LEON_ANG_Y,
            # tel00ModelInit: modelInit(PL_ARC 4, 5) + PL 10 / 5 + SS10/11 + SS12/13 + PL 9 / 7. La cabeza (SS12 =
            # ss_term:8, 10 shapes) usa texturas 0/1/2: el unico TPL que calza es ss_oc101:12 (SS16, la cara de Leon
            # 256x256 + pelo 64x64 + alfa); ss_term SS13 es un FCV (ver caveats en codec.json)
            piezas=[('cuerpo', pl(4), pl(5), 'pl00:0 / pl00:1'),
                    ('chaqueta', pl(10), pl(5), 'pl00:6 / pl00:1'),
                    ('mano_radio', ss(term, 10), ss(term, 11), 'ss_term:6 / ss_term:7'),
                    ('cabeza', ss(term, 12), ss(oc, 16), 'ss_term:8 / ss_oc101:12'),
                    ('ojos', pl(9), pl(7), 'pl00:5 / pl00:3')],
            cara='cabeza', shape_x=1.0,
            espera=(ss(term, 13), 'ss_term:9 (termMotionCancel usa SS14 de pTermDat; el FCV de 60 f del archivo es SS13)'),
            llamada=(ss(oc, 12), 'ss_oc101:8 (SS12, termMotionSet)'),
            shape=(ss(oc, 13), 'ss_oc101:9 (SS13)')),
        'hunnigan': dict(
            pref='Hunnigan', raiz='hunnigan_codec', pos=TERM_PL_POS, ang=0.0,
            piezas=[('cuerpo', ss(oc, 6), ss(oc, 5), 'ss_oc101:2 / ss_oc101:1')] +
                   [(n, ss(oc, k), ss(oc, 5), f'ss_oc101:{k - 4} / ss_oc101:1')
                    for n, k in (('pieza1', 7), ('pieza2', 8), ('cabeza', 9), ('pieza4', 10), ('pieza5', 11))],
            cara='cabeza', shape_x=SHAPE_X_HUNNIGAN,
            espera=(ss(oc, 4), 'ss_oc101:0 (SS4, termMotionCancel)'),
            llamada=(ss(oc, 14), 'ss_oc101:10 (SS14, termMotionSet)'),
            shape=(ss(oc, 15), 'ss_oc101:11 (SS15)')),
    }


def pesos_cara(sd_bytes, n_shapes, n_frames, mult):
    """ShapeSet(frame 0, flags 2|..) + ShapeMove por frame: rate = shape_frame; sube hasta nFrame-2 y se sostiene."""
    sd = fcv.parse(sd_bytes)
    sd.n_frame = struct.unpack('>H', sd_bytes[:2])[0]
    out, sf = [], 0
    for _ in range(n_frames):
        w = P.pesos_shape(sd, sf, n_shapes)
        out.append([round(x * mult, 5) for x in w])
        sf += 1
        if sf >= sd.n_frame - 1:
            sf -= 1
    return out, sd.n_frame


def exportar_personaje(clave, cfg):
    skel = modelbin.parse(cfg['piezas'][0][1])
    skel.check_tree()
    n = skel.n_parts
    rest = L.rest_world(skel)
    fuentes = []
    for nombre, b_d, t_d, desc in cfg['piezas']:
        m = meshbin.parse(b_d)
        fuentes.append((nombre, m, gxtex.parse_tpl(t_d), desc))
    imagenes = {}

    def clave_de(tex, tp, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (tp, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for nombre, m, tex, desc in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, desc.split(' / ')[1], part)
    atlas, rects = P.armar_atlas_completo(imagenes)
    H, W = atlas.shape[:2]
    png = f'{cfg["raiz"]}_atlas.png'
    with open(os.path.join(OUT, png), 'wb') as f:
        f.write(gxtex.png(atlas))

    b = gltf.Builder()
    nodes = [{'name': cfg['raiz'], 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * SCALE for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * SCALE, -r[1] * SCALE, -r[2] * SCALE, 1] for r in rest]
    skin = {'name': f'{cfg["raiz"]}_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    materials = [{'name': f'{cfg["pref"]}_opaco', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                                         'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                  'extras': {'w3d_transparent': False}}]
    meshes, mesh_nodes, resumen, nodo_cara, n_sh_cara = [], [], [], None, 0
    for nombre, m, tex, desc in fuentes:
        malla = f'{cfg["pref"]}_{nombre}'
        prims, nv, nt, cutoff, _ = P.malla_pieza(b, m, tex, desc.split(' / ')[1], clave_de, rects, W, H, SCALE, 0, None)
        for pr in prims:
            if pr['material'] is None:
                nm = f'{cfg["pref"]}_transparente_{int(round(cutoff * 255)) - 1}'
                idx = next((i for i, mt in enumerate(materials) if mt['name'] == nm), None)
                if idx is None:
                    idx = len(materials)
                    materials.append({'name': nm, 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                                           'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                                      'alphaMode': 'MASK', 'alphaCutoff': cutoff, 'extras': {'w3d_transparent': True}})
                pr['material'] = idx
        mesh = {'name': malla, 'primitives': prims, 'extras': {'re4': desc}}
        n_sh = len(m.shapes or [])
        if n_sh:
            mesh['weights'] = [0.0] * n_sh
            mesh['extras']['targetNames'] = [f'shape_{k:02d}' for k in range(n_sh)]
        if nombre == cfg['cara']:
            nodo_cara, n_sh_cara = len(nodes), n_sh
        mesh_nodes.append(len(nodes))
        nodes.append({'name': malla, 'mesh': len(meshes), 'skin': 0})
        meshes.append(mesh)
        resumen.append(dict(malla=malla, fuente=desc, vertices=nv, triangulos=nt, shapes=n_sh, partes=n))
        print(f'  {malla:26s} {desc:28s} {nv:5d} v {nt:5d} tri' + (f'  {n_sh} shapes' if n_sh else ''))

    raiz = mat_modelo(cfg['pos'], cfg['ang'])
    animations, clips = [], {}
    from motion import evalhost
    for nombre_clip, (datos, desc) in (('espera', cfg['espera']), ('llamada', cfg['llamada'])):
        mot = fcv.parse(datos)
        player = evalhost.Player(skel, mot, ik=False)
        poses = [player.frame(f) for f in range(mot.n_frames)]
        a = L.clip_esqueleto(b, nodes, n, poses, nombre_clip, FPS, SCALE, [raiz] * len(poses), skel.roots())
        clips[nombre_clip] = dict(frames=mot.n_frames, segundos=round(mot.n_frames / FPS, 3), fuente=desc)
        if nombre_clip == 'llamada':
            pesos, nf_shape = pesos_cara(cfg['shape'][0], n_sh_cara, mot.n_frames, cfg['shape_x'])
            clips['llamada']['cara'] = dict(fuente=cfg['shape'][1], frames_shape=nf_shape, multiplicador=cfg['shape_x'])
            a['samplers'].append({'input': b.accessor('f', gltf.FLOAT, 'SCALAR', [f / FPS for f in range(len(pesos))],
                                                      minmax=True),
                                  'output': b.accessor('f', gltf.FLOAT, 'SCALAR', [w for fr in pesos for w in fr]),
                                  'interpolation': 'LINEAR'})
            a['channels'].append({'sampler': len(a['samplers']) - 1, 'target': {'node': nodo_cara, 'path': 'weights'}})
            caras = dict(malla=nodes[nodo_cara]['name'], shapes=[f'shape_{k:02d}' for k in range(n_sh_cara)],
                         pesos=pesos)
        animations.append(a)
    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_codec.py'},
        'scene': 0, 'scenes': [{'name': cfg['raiz'], 'nodes': [0] + mesh_nodes}],
        'nodes': nodes, 'skins': [skin], 'meshes': meshes,
        'images': [{'uri': png}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
        'textures': [{'source': 0, 'sampler': 0}], 'materials': materials, 'animations': animations,
        'extras': {'raiz': 'hueso_000 en el ESPACIO DEL CODEC (m): camara en (0, 0, 2) mirando a -Z, fov 50 vertical, '
                           '4:3; la armadura va en el origen',
                   'clips': clips},
    }
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    salida = os.path.join(OUT, f'{cfg["raiz"]}.glb')
    gltf.write(doc, bytes(b.blob), salida)
    print(f'  -> {salida}  atlas {W}x{H}, clips {", ".join(f"{k} {v["frames"]} f" for k, v in clips.items())}')
    return dict(glb=os.path.relpath(salida, OUT), atlas=png, atlas_px=[W, H], mallas=resumen, clips=clips,
                huesos=n), caras


def modelos():
    info, caras = {}, {}
    for clave, cfg in personajes().items():
        print(clave)
        info[clave], caras[clave] = exportar_personaje(clave, cfg)
    with open(os.path.join(OUT, 'caras.json'), 'w') as f:
        json.dump(dict(nota='pesos por frame del clip "llamada" (0 = primer frame); ShapeMove: la cara arranca con la '
                            'motion (termMotionSet) y sostiene el ultimo rate. Hunnigan x1.37 (ShapeSet flags 0xA) ya '
                            'aplicado. Tambien estan como canal "weights" del clip en el glb.', **caras), f)
    return info


# ---------------------------------------------------------------------------------------------------
#  UI 2D: el ID system del codec (IdSub), re-ejecutado con la logica de ss_term.cpp
# ---------------------------------------------------------------------------------------------------
IDC_SSCRN_NEAR_0, IDC_SSCRN_0 = 16, 20
CAPACIDAD, OCUPADAS = 0x80, 13 + 46 + 13 + 4
CAPA = {IDC_SSCRN_0: dict(nombre='fondo', ot=0xC, prio=5, nota='OT 0xC: se dibuja ANTES que los modelos (OT 0xD)'),
        IDC_SSCRN_NEAR_0: dict(nombre='frente', ot=0xF, prio=2, nota='OT 0xF: se dibuja DESPUES de los modelos')}


def texturas_ui():
    """Todas las texturas ID vivas en el codec: core.das #25 (HUD, TEX_OWNER_ID_COCKPIT, sigue cargada), ss_cmmn SS6
    (TEX_OWNER_ID_SHARE, sscrn.cpp SubScreenExec) y ss_term SS5 (TEX_OWNER_ID_SSCRN, SsTermMain::init)."""
    tex = {}
    fuente = {}
    for nombre, d in (('core.das#25', arc('etc/core.das').entry(25).data),
                      ('ss_cmmn SS6', ss(arc('ss/Eng/ss_cmmn.dat'), 6)),
                      ('ss_term SS5', ss(arc('ss/Eng/ss_term.dat'), 5))):
        e = re4_eff.Eff(d, nombre)
        for k, v in e.tex.items():
            tex[k] = v
            fuente[k] = nombre
    return tex, fuente


class IdSub(HUD.IdSys):
    def set_time(self, u, t):
        """IDSystem::setTime: el sub-arbol completo a t."""
        for c in self.vivas():
            if c.padre is u:
                self.set_time(c, t)
        u.timer = [t, t, t, t]

    def ptr(self, ident, clase):
        return HUD.IdSys.ptr(self, ident, clase)


def simular_ui(n_frames, disparo):
    """frame 0 = SsTermMain::init (primer frame de la pantalla del codec). `disparo` = frame en que el stream de voz
    esta listo (OpeMesMove: 0x13 / 0x14 setTime(0), visibles, rev &= 0xF0). -> (ids, [frames: [(u, estado)]])."""
    tex, _ = texturas_ui()
    term = arc('ss/Eng/ss_term.dat')
    ids = IdSub(tex)
    t8, t9 = HUD.leer_tabla(ss(term, 8)), HUD.leer_tabla(ss(term, 9))
    # CAPACIDAD: IdSub.gameInit(0x80) (sscrn.cpp, open_flag 0x20) = 128 unidades; siguen vivas las de ss_cmmn que
    # IdSubErase NO mata (PESETA SS7 13 + MAIN_MENU SS0xB 46 + ETC SS0x11 13 + BACK_GROUND SS9 4 = 76). SS8 pone 5 y de
    # SS9 solo entran las primeras 128 - 81 = 47 filas: IDSystem::set salta el resto ("work full"). Sin esas filas
    # (el televisor gris de los grupos 0x16/0x17) Hunnigan queda tapada todo el tiempo.
    t9_creadas = t9[:max(0, CAPACIDAD - OCUPADAS - len(t8))]
    ids.set(t8, 0xFF, IDC_SSCRN_0)
    ids.set(t9_creadas, 0xFF, IDC_SSCRN_NEAR_0)
    ids.filas_perdidas = ['%02X' % r['no'] for r in t9[len(t9_creadas):]]
    for m in (0x12, 0x13, 0x14):
        u = ids.ptr(m, IDC_SSCRN_NEAR_0)
        u.be_flag &= ~8
        u.rev |= 0xF
    cuadros = []
    for f in range(n_frames):
        if f == disparo:
            for m in (0x13, 0x14):
                u = ids.ptr(m, IDC_SSCRN_NEAR_0)
                ids.set_time(u, 0)
                u.be_flag |= 8
                u.rev &= 0xF0
        ids.mover()
        cuadros.append([(u, dict(col=list(u.col), mat=u.mat.copy(), ver=None if u.ver is None else u.ver.copy(),
                                 tex_no=u.tex_no)) for u in ids.orden_dibujo()])
    return ids, cuadros, tex


class Foto:
    def __init__(self, u, st):
        self.__dict__.update(u.__dict__)
        self.col, self.mat, self.ver, self.tex_no = st['col'], st['mat'], st['ver'], st['tex_no']


def render_capa(cuadro, clase, cache, escala=1, fondo=None):
    """PIL RGBA (640x480 * escala) de una capa; fondo None = transparente."""
    dib = [Foto(u, st) for u, st in cuadro if u.clase == clase]
    img = HUD.render(dib, cache, escala=escala, fondo=(0, 0, 0))
    if fondo is not None:
        return img
    # render() dibuja sobre negro: se reconstruye alfa renderizando sobre blanco tambien
    img_b = HUD.render(dib, cache, escala=escala, fondo=(255, 255, 255))
    a = np.asarray(img, np.float32) / 255.0
    b = np.asarray(img_b, np.float32) / 255.0
    alfa = np.clip(1.0 - (b - a).mean(axis=2), 0, 1)
    rgb = np.where(alfa[..., None] > 1e-4, a / np.maximum(alfa[..., None], 1e-4), 0)
    out = np.concatenate([np.clip(rgb, 0, 1), alfa[..., None]], axis=2)
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), 'RGBA')


def elemento(u, st, orden):
    esq = [[round(c, 2) for c in HUD.a_pantalla(st['mat'], v)] for v in st['ver']]
    xs, ys = [p[0] for p in esq], [p[1] for p in esq]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    return dict(orden=orden, capa=CAPA[u.clase]['nombre'], id='%02X' % u.mark, no='%02X' % u.no,
                padre=('%02X' % u.padre.no) if u.padre is not None else None,
                textura='%02X' % u.tex, archivo='ui/tex_%02X.png' % u.tex,
                rect_px_640x480=[round(min(xs), 2), round(min(ys), 2), round(w, 2), round(h, 2)],
                rect_frac_centro=dict(cx=round((cx - 320) / 640, 5), cy=round((240 - cy) / 480, 5),
                                      w=round(w / 640, 5), h=round(h / 480, 5)),
                esquinas_px=esq, color_rgba=[int(c) for c in st['col']], blend=u.rec['blend'],
                blend_gl=HUD.BLEND[u.rec['blend']]['gl'],
                rot_z_grados=round(math.degrees(math.atan2(st['mat'][1, 0], st['mat'][0, 0])), 3))


def componer(cuadro, img3d, cache, fondo=(0, 0, 0)):
    """Imagen de control 640x480: capa 'fondo' (OT 0xC) -> modelos 3D (RGBA, OT 0xD) -> capa 'frente' (OT 0xF), cada
    unidad con su trans_type (id_sys.cpp IdGeneralTrans):
      0 IdCommonTrans: quad texturado x color de la unidad, blend de la tabla.
      1 IdNegativeTrans: copia de la pantalla; color = col_unidad * (1 - pantalla * 2^pow); alfa = col.a * tex.a.
      2/3 IdShimmerTrans: copia de la pantalla corrida por la textura (indirecta, 3 = con signo); color = pantalla *
          col_unidad; alfa = col.a. Fuerza = col.a/255 * 0.04 * 1000/1500 * (1 + pow/32) (APROXIMADO: el
          desplazamiento en pixeles se estima como valor(0..255) * fuerza * 2 texeles de la copia a media resolucion)."""
    dst = np.zeros((480, 640, 3), np.float32)
    dst[:] = np.array(fondo, np.float32) / 255.0
    capa3d = np.asarray(img3d.convert('RGBA'), np.float32) / 255.0 if img3d is not None else None
    dib = [Foto(u, st) for u, st in cuadro]
    for clase in (IDC_SSCRN_0, None, IDC_SSCRN_NEAR_0):
        if clase is None:
            if capa3d is not None:
                a = capa3d[..., 3:4]
                dst = capa3d[..., :3] * a + dst * (1 - a)
            continue
        for u in dib:
            if u.clase == clase:
                _dibujar_unidad(dst, u, cache)
    return Image.fromarray((np.clip(dst, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')


def _dibujar_unidad(dst, u, cache):
    H, W = dst.shape[:2]
    esq = np.array([HUD.a_pantalla(u.mat, v) for v in u.ver])
    o, ex, ey = esq[0], esq[1] - esq[0], esq[3] - esq[0]
    x0, y0 = np.floor(esq.min(0)).astype(int)
    x1, y1 = np.ceil(esq.max(0)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1] + 0.5
    M = np.array([[ex[0], ey[0]], [ex[1], ey[1]]])
    if abs(np.linalg.det(M)) < 1e-9:
        return
    inv = np.linalg.inv(M)
    du = inv[0, 0] * (xs - o[0]) + inv[0, 1] * (ys - o[1])
    dv = inv[1, 0] * (xs - o[0]) + inv[1, 1] * (ys - o[1])
    dentro = (du >= 0) & (du < 1) & (dv >= 0) & (dv < 1)
    tex = cache(u.tex, u.tex_no)
    th, tw = tex.shape[:2]
    t = tex[np.clip((dv * th).astype(int), 0, th - 1), np.clip((du * tw).astype(int), 0, tw - 1)].astype(np.float32) / 255
    col = np.array(u.col, np.float32) / 255.0
    region = dst[y0:y1, x0:x1]
    modo = u.rec['trans']
    if modo == 1:
        pw = min(u.rec['pow'], 2)
        rgb = col[:3] * (1.0 - np.clip(region * (2 ** pw), 0, 1))
        a = t[..., 3] * col[3]
    elif modo in (2, 3):
        fuerza = col[3] * 0.04 * 1000.0 / 1500.0 * (u.rec['pow'] / 32.0 + 1.0)
        ind = t[..., :2] * 255.0 - (128.0 if modo == 3 else 0.0)
        off = ind * fuerza * 2.0 * 2.0                      # texeles de la copia a media resolucion -> px
        sx = np.clip((xs + off[..., 0]).astype(int), 0, W - 1)
        sy = np.clip((ys + off[..., 1]).astype(int), 0, H - 1)
        rgb = dst[sy, sx] * col[:3]
        a = np.full(du.shape, col[3], np.float32)
    else:
        rgb = t[..., :3] * col[:3]
        a = t[..., 3] * col[3]
    ok = dentro & (a * 255.0 > 1.0)
    a3 = a[..., None]
    b = u.rec['blend']
    if b == 0:
        nuevo = rgb * a3 + region * (1 - a3)
    elif b == 1:
        nuevo = region + rgb * a3
    elif b == 2:
        nuevo = region + rgb
    elif b == 3:
        nuevo = region * rgb + region
    else:
        nuevo = region * rgb
    region[ok] = np.clip(nuevo, 0, 1)[ok]


# ---------------------------------------------------------------------------------------------------
#  AUDIO
# ---------------------------------------------------------------------------------------------------
def audio(disc):
    import re4_extract_evento as EV
    import re4_sonidos as R
    os.makedirs(os.path.join(OUT, 'audio'), exist_ok=True)
    disco = EV.Disco(disc)
    st = EV.Streams(disco)
    res = {}
    h, rit = st.shd(1, MDT_NO), st.rit(1, MDT_NO)
    ruta = os.path.join(OUT, 'audio', 'str1_140.wav')
    if not os.path.isfile(ruta):
        canales, rate, _ = st.decodificar(1, MDT_NO)
        EV.escribir_wav(ruta, canales, rate)
    disco.limpiar()
    res['voz'] = dict(wav='audio/str1_140.wav', archivo_disco='bgm/bio4evt.sbb', bloque=1, numero=MDT_NO,
                      rate=h['rate'], muestras=h['samples'], canales=2 if (h['flag'] & 1) else 1,
                      duracion_s=round(h['samples'] / h['rate'], 4),
                      duracion_frames=round(h['samples'] / h['rate'] * FPS, 2), loop=bool(h['flag'] & 4),
                      volumen_rit=rit['vol'], pedido='SndStrReq(1, 0x8C, 1 = precargar); cuando SndStrStatusCk(.., 2) '
                                                     '-> SndStrReq(id, 2) = arrancar (ss_term.cpp OpeMesMove)')
    tono = os.path.join(HERE, 'out', 'r100_intro', 'audio', 'str1_003.wav')
    if os.path.isfile(tono):
        shutil.copyfile(tono, os.path.join(OUT, 'audio', 'str1_003.wav'))
    h3 = st.shd(1, 3)
    res['tono_radio'] = dict(wav='audio/str1_003.wav', bloque=1, numero=3, rate=h3['rate'], muestras=h3['samples'],
                             duracion_s=round(h3['samples'] / h3['rate'], 4),
                             pedido='SndStrPlayBlock(1, strTbl[0] = 3) (sscrn.cpp OpeSetOpenTerm); lo corta '
                                    'SndStrStopBlock(sndId) al pedir la voz (OpeMesMove)')
    banco = R.load_bank('etc/core.das', 0)
    for no, nombre, nota in ((0x14, 'abrir', 'SndCall(0, 0x14) en SsTermMain::init'),
                             (0x15, 'cerrar', 'SndCall(0, 0x15) en SsTermMain::quit')):
        fr = R.render_se(banco, no)
        fn = f'audio/se_codec_{nombre}.wav'
        R.write_wav_stereo(os.path.join(OUT, fn), fr, 32000)
        res[f'se_{nombre}'] = dict(wav=fn, banco='CORE (etc/core.das, bloque 0)', se=no,
                                   duracion_s=round(len(fr) / 32000, 4), nota=nota)
    for f in ('se_core_14.wav', 'se_core_15.wav'):
        p = os.path.join(OUT, 'audio', f)
        if os.path.isfile(p):
            os.remove(p)
    return res


def envolvente_voz(ruta, umbral=300.0, hueco=8):
    import wave
    with wave.open(ruta) as w:
        n, r, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), '<i2').reshape(-1, ch).astype(np.float64).mean(1)
    spf = r / FPS
    nf = int(len(x) / spf)
    e = np.array([np.sqrt((x[int(i * spf):int((i + 1) * spf)] ** 2).mean()) for i in range(nf)])
    segs, s = [], None
    for i, a in enumerate(e > umbral):
        if a and s is None:
            s = i
        if not a and s is not None:
            if i - s > 3:
                segs.append([s, i])
            s = None
    if s is not None:
        segs.append([s, nf])
    out = []
    for a, b in segs:
        if out and a - out[-1][1] < hueco:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


# ---------------------------------------------------------------------------------------------------
#  SECUENCIA (op/op01.das)
# ---------------------------------------------------------------------------------------------------
def secuencia():
    op = arc('op/op01.das')
    d = op.entry(17 - 4).data          # term_ope_tbl[0].seq = OP_ARC_PTR(17)
    out = []
    for i in range(0, len(d), 16):
        x0, x2, t, mes, arg = struct.unpack('>Hhiii', d[i:i + 16])
        out.append(dict(x0=x0, x2=x2, frame=t, mensaje=mes, arg=arg))
        if arg == -1:
            break
    return out


def textos():
    """out/texto/mensajes_en.json (lo genera el otro extractor): codec_op01 -> llamadas[0].mensajes."""
    p = os.path.join(HERE, 'out', 'texto', 'mensajes_en.json')
    if not os.path.isfile(p):
        return None
    try:
        t = json.load(open(p))['tablas']['codec_op01']['llamadas'][0]['mensajes']
    except (KeyError, IndexError, ValueError):
        return None
    return {m['n']: m for m in t}


# ---------------------------------------------------------------------------------------------------
#  TIEMPOS (frames de 30 fps)
# ---------------------------------------------------------------------------------------------------
LATENCIA_STREAM = 1          # frames entre el pedido del stream (OpeMesMove, c = OPE_WAIT + 1) y "listo": SUPUESTO
DISPARO = OPE_WAIT + 1 + LATENCIA_STREAM     # c en que arranca la voz (0x13 / 0x14 se abren, motions de la llamada)
FIN_SEQ = 810


def huecos_marco(tex):
    """Las ventanas transparentes de la textura 0xFE (el marco del codec, 640x360 dibujado en (0,0) -> y + 60)."""
    a = HUD.imagen(tex[0xFE], 0)[..., 3] < 128
    H, W = a.shape
    lab = np.zeros(a.shape, np.int32)
    out, n = [], 0
    for y in range(H):
        for x in range(W):
            if a[y, x] and not lab[y, x]:
                n += 1
                pila, pts = [(y, x)], []
                lab[y, x] = n
                while pila:
                    cy, cx = pila.pop()
                    pts.append((cy, cx))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = cy + dy, cx + dx
                        if 0 <= yy < H and 0 <= xx < W and a[yy, xx] and not lab[yy, xx]:
                            lab[yy, xx] = n
                            pila.append((yy, xx))
                if len(pts) > 1000:
                    ys = [p[0] for p in pts]
                    xs = [p[1] for p in pts]
                    out.append((min(xs), min(ys) + 60, max(xs) + 1 - min(xs), max(ys) + 1 - min(ys)))
    return sorted(out)


def rect_info(x, y, w, h):
    cx, cy = x + w / 2, y + h / 2
    return dict(px_640x480=dict(x=x, y=y, w=w, h=h),
                frac_centro=dict(cx=round((cx - 320) / 640, 5), cy=round((240 - cy) / 480, 5),
                                 w=round(w / 640, 5), h=round(h / 480, 5),
                                 izq=round((x - 320) / 640, 5), der=round((x + w - 320) / 640, 5),
                                 arriba=round((240 - y) / 480, 5), abajo=round((240 - y - h) / 480, 5)),
                ndc=dict(x0=round((x - 320) / 320, 5), x1=round((x + w - 320) / 320, 5),
                         y0=round((240 - y - h) / 240, 5), y1=round((240 - y) / 240, 5)))


def camara_ventana(r, pers_pos, pers_ang):
    """Camara equivalente para dibujar SOLO esa ventana (viewport propio): mismo ojo y orientacion que la del codec,
    proyeccion off-axis = el pedazo del frustum de fov 50 que cae en la ventana."""
    t = math.tan(math.radians(CAM_FOVY / 2))
    n = r['ndc']
    fov_v = 2 * math.degrees(math.atan((n['y1'] - n['y0']) / 2 * t))
    ancho, alto = (n['x1'] - n['x0']), (n['y1'] - n['y0'])
    ojo_rel = [(CAM_POS[i] - pers_pos[i]) * SCALE for i in range(3)]
    c, s = math.cos(-pers_ang), math.sin(-pers_ang)
    ojo_local = [c * ojo_rel[0] + s * ojo_rel[2], ojo_rel[1], -s * ojo_rel[0] + c * ojo_rel[2]]
    return dict(
        ojo_m=[c_ * SCALE for c_ in CAM_POS], mira_a='-Z (0, 0, -1), arriba +Y',
        fov_vertical_grados=round(fov_v, 4), aspecto=round(ancho * 4 / 3 / alto, 5),
        desplazamiento_lente=dict(x=round((n['x0'] + n['x1']) / 2 / ancho, 5), y=round((n['y0'] + n['y1']) / 2 / alto, 5),
                                  unidad='centro del frustum de la ventana respecto del eje de la camara: x en '
                                         'fracciones del ANCHO de la ventana, y del ALTO (en Blender el shift va en '
                                         'fracciones del lado MAYOR: como el alto es mayor, shift_x = x * aspecto, '
                                         'shift_y = y)'),
        frustum_tangentes=dict(izq=round(n['x0'] * t * 4 / 3, 5), der=round(n['x1'] * t * 4 / 3, 5),
                               abajo=round(n['y0'] * t, 5), arriba=round(n['y1'] * t, 5),
                               nota='glFrustum(izq*near, der*near, abajo*near, arriba*near, near, far)'),
        ojo_relativo_al_personaje_m=[round(v, 4) for v in ojo_rel],
        ojo_en_espacio_local_del_personaje_m=[round(v, 4) for v in ojo_local],
        aprox_simetrica=dict(
            mirar_al_centro_de_la_ventana=True,
            direccion=[round((n['x0'] + n['x1']) / 2 * t * 4 / 3, 5), round((n['y0'] + n['y1']) / 2 * t, 5), -1.0],
            fov_vertical_grados=round(fov_v, 4),
            nota='camara sin desplazamiento de lente girada hacia el centro de la ventana: diferencia de perspectiva '
                 'minima (< 1 px en los bordes)'))


def ui(n_frames):
    os.makedirs(OUT_UI, exist_ok=True)
    ids, cuadros, tex = simular_ui(n_frames, DISPARO)
    _, fuente = texturas_ui()
    imgs = {}

    def cache(t, n):
        if (t, n) not in imgs:
            imgs[(t, n)] = HUD.imagen(tex[t], n)
        return imgs[(t, n)]
    usadas = {}
    pistas, estatico = {}, {}
    for c, cuadro in enumerate(cuadros):
        vistos = set()
        for orden, (u, st) in enumerate(cuadro):
            k = '%s_%02X' % (CAPA[u.clase]['nombre'], u.no)
            vistos.add(k)
            usadas.setdefault(u.tex, set()).add(st['tex_no'])
            esq = [[round(v, 1) for v in HUD.a_pantalla(st['mat'], p)] for p in st['ver']]
            est = [c, 1, orden, esq, [int(x) for x in st['col']], st['tex_no']]
            if k not in estatico:
                r = u.rec
                cadena, p = [], u.padre
                while p is not None:
                    cadena.append('%02X' % p.no)
                    p = p.padre
                estatico[k] = dict(
                    capa=CAPA[u.clase]['nombre'], no='%02X' % u.no, marca='%02X' % u.mark, padres=cadena,
                    textura='%02X' % u.tex, archivo='ui/tex_%02X.png' % u.tex, fuente_textura=fuente.get(u.tex),
                    trans_type=r['trans'], pow=r['pow'],
                    efecto={0: 'quad texturado', 1: 'NEGATIVO de la pantalla: col*(1 - pantalla*2^pow), alfa col.a*tex.a',
                            2: 'distorsion de la pantalla por la textura (indirecta sin signo) x color',
                            3: 'distorsion de la pantalla por la textura (indirecta con signo) x color'}.get(r['trans']),
                    blend=r['blend'], blend_gl=HUD.BLEND[r['blend']]['gl'], ancla=r['ancla'], tamano=r['tam'],
                    curvas={kk: v for kk, v in zip(('camino_t', 'escala', 'color', 'rotacion'), r['curvas']) if v},
                    camino=r['camino'], loop_bits=r['loop'])
            prev = pistas.setdefault(k, [])
            if not prev or prev[-1][1:] != est[1:]:
                prev.append(est)
        for k, prev in pistas.items():
            if k not in vistos and prev and prev[-1][1] != 0:
                prev.append([c, 0])
    for t, frames in usadas.items():
        for n in sorted(frames):
            nombre = 'tex_%02X.png' % t if n == 0 else 'tex_%02X_f%d.png' % (t, n)
            Image.fromarray(cache(t, n), 'RGBA').save(os.path.join(OUT_UI, nombre))
    huecos = huecos_marco(tex)
    doc = dict(
        nota='Pantalla virtual 640x480 (origen arriba-izquierda; la EFB del sub screen es 640x448, ScreenReSize: la '
             'proyeccion 4:3 de fov 50 cubre las 480 lineas virtuales). c = frame del codec (0 = SsTermMain::init). '
             'Capas: "fondo" (IDC_SSCRN_0, OT 0xC) se dibuja ANTES que los modelos 3D (OT 0xD); "frente" '
             '(IDC_SSCRN_NEAR_0, OT 0xF) DESPUES. Sin z (GXSetZMode(0)). pistas[unidad] = lista de cambios '
             '[c, visible 1, orden_de_dibujo_en_ese_frame, esquinas v0 v1 v2 v3 (px, v0 arriba-izq), rgba, cuadro_tex] o '
             '[c, 0] (deja de dibujarse). El estado se mantiene hasta el proximo cambio.',
        disparo_c=DISPARO, frames=n_frames,
        capacidad=dict(max_unidades=CAPACIDAD, ocupadas_por_ss_cmmn=OCUPADAS, filas_ss9_no_creadas=ids.filas_perdidas,
                       nota='IdSub.gameInit(0x80) (sscrn.cpp, open_flag 0x20); IdSubErase no mata PESETA / MAIN_MENU / '
                            'ETC / BACK_GROUND -> de ss_term SS9 (78 filas) solo se crean 47 (INFERIDO del decomp; '
                            'sin eso los grupos 0x16/0x17 taparian a Hunnigan)'),
        ventanas_del_marco=[dict(nombre=nm, **rect_info(*h)) for nm, h in zip(('hunnigan', 'leon'), huecos)],
        unidades=estatico, pistas=pistas)
    with open(os.path.join(OUT_UI, 'ui.json'), 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print(f'  ui: {len(estatico)} unidades, {sum(len(v) for v in pistas.values())} cambios, ventanas {huecos}')
    return ids, cuadros, cache, huecos


# ---------------------------------------------------------------------------------------------------
#  LINEAS (secuencia + textos + voz)
# ---------------------------------------------------------------------------------------------------
HABLA = {1: 'hunnigan', 0: 'leon'}      # {habla:n} del MDT: 1 = Hunnigan ("Leon. I hope you can hear me."), 0 = Leon


def lineas(seq, txt, segs):
    """Cada entrada de la TermSeq: mensaje n (primera pagina) o -1 (cMes.WaitEnd: termina la espera {espera:-1} ->
    pasa a la pagina siguiente del mensaje actual). mesWait = arg = 0 -> el texto queda hasta el proximo cambio."""
    out, actual, pagina = [], None, 0
    for i, s in enumerate(seq):
        if s['arg'] == -1:
            if out:
                out[-1]['fin_seq'] = s['frame']
            break
        if s['mensaje'] == -1:
            pagina += 1
        else:
            actual, pagina = s['mensaje'], 0
        if out:
            out[-1]['fin_seq'] = s['frame']
        m = txt.get(actual) if txt else None
        quien = None
        if m:
            import re
            h = re.search(r'\{habla:(\d+)\}', m['texto'])
            quien = HABLA.get(int(h.group(1))) if h else None
        e = dict(indice_seq=i, inicio_seq=s['frame'], mensaje=actual, pagina=pagina,
                 id_texto=f'codec_op00:{actual}', habla=quien,
                 texto=m['paginas'][pagina] if m and pagina < len(m['paginas']) else None,
                 color='#87CFA5 ({color:1}, verde)' if quien == 'leon' else ('blanco ({color:2})' if quien else None))
        out.append(e)
    for e in out:
        e['frames'] = e['fin_seq'] - e['inicio_seq']
        e['voz_segmentos'] = [sg for sg in segs if sg[0] < e['fin_seq'] and sg[1] > e['inicio_seq']]
    return out


# ---------------------------------------------------------------------------------------------------
#  RENDERS DE CONTROL
# ---------------------------------------------------------------------------------------------------
def control(cuadros, cache, lins, huecos):
    from PIL import ImageDraw, ImageFont
    dir_ctl = os.path.join(OUT, 'control')
    dir_3d = os.path.join(OUT, 'control', '_3d')
    os.makedirs(dir_3d, exist_ok=True)
    marcas = [0, 2, 20, 60, DISPARO + 6, 150]
    for e in lins:
        marcas.append(DISPARO + e['inicio_seq'] + 25)
    marcas = sorted(set(c for c in marcas if c < len(cuadros)))

    def pose(c):
        if c <= DISPARO:
            return ['espera', c % 60]
        return ['llamada', c - DISPARO - 1]
    spec = dict(salida_dir=dir_3d, cuadros=[dict(nombre='c%04d' % c, leon=pose(c), hunnigan=pose(c)) for c in marcas])
    sp = os.path.join(dir_3d, 'spec.json')
    json.dump(spec, open(sp, 'w'))
    subprocess.run(['blender', '-b', '--python', os.path.join(HERE, 'tools_codec', 'render_codec.py'), '--', sp],
                   check=True, capture_output=True)
    try:
        fuente = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
    except OSError:
        fuente = ImageFont.load_default()
    salidas = []
    for c in marcas:
        i3 = Image.open(os.path.join(dir_3d, 'c%04d.png' % c)).convert('RGBA')
        a = np.asarray(i3).copy()
        a[:60, :, 3] = 0              # el 3D solo dentro de la banda del marco (ver caveats)
        a[420:, :, 3] = 0
        img = componer(cuadros[c], Image.fromarray(a, 'RGBA'), cache)
        if c < 5:                      # FadeSetW(0x80000000, 5): desde negro en 5 frames
            k = c / 5.0
            img = Image.fromarray((np.asarray(img, np.float32) * k).astype(np.uint8), 'RGB')
        d = ImageDraw.Draw(img)
        s = c - DISPARO
        for e in lins:
            if e['inicio_seq'] <= s < e['fin_seq'] and e['texto']:
                col = (0x87, 0xCF, 0xA5) if e['habla'] == 'leon' else (235, 235, 235)
                for k, ln in enumerate(e['texto']):
                    w = d.textlength(ln, font=fuente)
                    d.text((320 - w / 2, 318 + 20 * k), ln, fill=col, font=fuente)
        d.text((6, 462), 'c=%d  seq=%d  (control; texto con fuente del sistema, posicion aprox.)' % (c, s),
               fill=(255, 255, 0), font=ImageFont.load_default())
        p = os.path.join(dir_ctl, 'codec_c%04d.png' % c)
        img.save(p)
        salidas.append(os.path.relpath(p, OUT))
    shutil.rmtree(dir_3d, ignore_errors=True)
    # hoja
    ims = [Image.open(os.path.join(OUT, p)) for p in salidas]
    cols = 4
    filas = (len(ims) + cols - 1) // cols
    hoja = Image.new('RGB', (320 * cols, 240 * filas))
    for i, im in enumerate(ims):
        hoja.paste(im.resize((320, 240)), ((i % cols) * 320, (i // cols) * 240))
    hoja.save(os.path.join(dir_ctl, 'hoja.png'))
    return salidas


# ---------------------------------------------------------------------------------------------------
#  codec.json
# ---------------------------------------------------------------------------------------------------
G_CODEC = 80      # frame global (0 = OpeSetOpenTerm) del primer frame del codec, SIN tiempo de carga (ver caveats)


def luces():
    import re4_extract_look as K
    lit = K.lit_archivo(ss(arc('ss/Eng/ss_cmmn.dat'), 0x15))['cortes'][0]
    return dict(
        fuente='ss_cmmn SS0x15 (LIT, corte 0): sscrnLightCreate crea las luces 0, 1, 2 (ss_main.cpp)',
        ambiente_personajes=lit['ambiente_em'], ambiente_escena=lit['ambiente_scr'],
        tev_mult=lit['tev_mult'], niebla=lit['niebla']['tipo_gx'],
        luces=[dict(n=l['n'], encendida=l['encendida'], tipo='direccional' if l['tipo'] == 5 else l['atenuacion'],
                    hacia_la_luz=[round(v / max(1e-9, math.sqrt(sum(x * x for x in l['dir']))), 5) for v in l['dir']],
                    color_255=l['color_255'][:3], intensidad=l['intensidad'])
               for l in lit['luces'] if l['n'] < 3],
        modelo='cada modelo: LightInfo.init2(0, 1, ofs 0, tamanio (1000, 1000, 0), 1) (ss_model.cpp ssModelLight); '
               'canal GX: ambiente + suma(color * intensidad * max(N.L, 0)), x tev_mult. Direccion en el espacio del '
               'codec (Y arriba, la camara en +Z)')


def escribir_json(info_modelos, info_audio, lins, huecos, controles, segs):
    t = lambda f: round(f / FPS, 3)  # noqa: E731
    fin_c = DISPARO + FIN_SEQ
    h_rect = rect_info(*huecos[0])
    l_rect = rect_info(*huecos[1])
    doc = dict(
        titulo='RE4 GC USA: primera llamada de radio con Hunnigan (op 0, OpeSetOpenTerm(0) al final de r100_StartEvent)',
        unidades='metros (mm del juego * 0.001), Y arriba; frames de 30 fps; pantalla virtual 640x480 (origen '
                 'arriba-izq) y fracciones con ORIGEN EN EL CENTRO (x a la derecha, y hacia ARRIBA, ancho = 640, '
                 'alto = 480)',
        relojes=dict(g='frame global: 0 = OpeSetOpenTerm (Leon empieza a sacar la radio)',
                     c='frame del codec: 0 = SsTermMain::init (primer frame de la pantalla del codec)',
                     s='frame de la secuencia TermSeq (ope.seqCnt): 0 = la voz arranca; s = c - %d' % DISPARO,
                     relacion='g = c + %d (sin tiempo de carga del disco; ver caveats)' % G_CODEC),
        fuentes=['../re4/src/game/sscrn.cpp (OpeSetOpenTerm, SubScreenOpen/Exec/Exit, OpeSetOpenTermEnd)',
                 '../re4/src/Sscrn/ss_term.cpp (SsTermInit, SsTermMain, OpeMes*, termMotion*, terminalCameraInit)',
                 '../re4/src/Sscrn/ss_model.cpp (tel00ModelInit, hunniganModelInit)',
                 '../re4/src/Sscrn/ss_main.cpp (SubScreenTask, SsExitInit, IdSubErase, sscrnLightCreate)',
                 '../re4/src/game/id_sys.cpp (IDSystem: set / move / trans, IdCommonTrans / IdNegativeTrans / '
                 'IdShimmerTrans)', '../re4/src/game/shape.cpp, motion.cpp'],
        archivos_disco=dict(term='files/ss/Eng/ss_term.dat', op='files/op/op01.das (stage_no 1)',
                            partner='files/ss/Cmn/ss_oc101.dat (partnerDataName(0) = "101")',
                            comun='files/ss/Eng/ss_cmmn.dat', voz='files/bgm/bio4evt.sbb #140',
                            no_usados='files/ss/Eng/tel0000_101_b/_f.fcv, tel0100_101_b/_f.fcv (motions sueltas; la de '
                                      'Hunnigan = ss_oc101 SS14, la de Leon difiere) y files/ss/Cmn/ss_tel01.dat: '
                                      'ningun codigo los lee'),
        salida=dict(leon='leon_codec.glb', hunnigan='hunnigan_codec.glb', caras='caras.json', ui='ui/ui.json',
                    control=controles, modelos=info_modelos),
        espacio_3d=dict(
            camara=dict(ojo_m=[v * SCALE for v in CAM_POS], objetivo_m=[0, 0, 0], arriba=[0, 1, 0],
                        fov_vertical_grados=CAM_FOVY, aspecto=4 / 3, cerca_lejos='ZNEAR / ZFAR del juego',
                        fuente='terminalCameraInit (ss_term.cpp): una sola camara para los dos personajes; cada uno '
                               'se ve por su ventana del marco'),
            hunnigan=dict(glb='hunnigan_codec.glb', pos_m=[v * SCALE for v in TERM_PL_POS], rot_y_rad=0.0,
                          nota='term_pl_pos; ya aplicado en hueso_000 de los clips (la armadura va en el origen)'),
            leon=dict(glb='leon_codec.glb', pos_m=[v * SCALE for v in TERM_CAM_POS], rot_y_rad=round(LEON_ANG_Y, 6),
                      nota='term_cam_pos; ang.y = atan2(cam.x - x, cam.z - z) = mira a la camara; ya aplicado en los '
                           'clips'),
            luces=luces(),
            fondo_3d='no hay escenario 3D: detras de los personajes solo esta la capa 2D "fondo" (gris 30,30,30) y lo '
                     'que dejan ver las ventanas; el tinte / nieve de la ventana de Hunnigan lo hacen las unidades 2D del '
                     'frente (IdNegativeTrans / IdShimmerTrans sobre la imagen ya dibujada)'),
        layout=dict(
            pantalla='640x480 virtuales (EFB 640x448 durante el sub screen: ScreenReSize(640, 448))',
            marco=dict(textura='ui/tex_FE.png (640x360, ss_term SS5 id 0xFE, con las dos ventanas transparentes)',
                       **rect_info(0, 60, 640, 360)),
            fuera_del_marco='negro (y = 0..60 y 420..480)',
            ventana_hunnigan=dict(h_rect, camara=camara_ventana(h_rect, TERM_PL_POS, 0.0),
                                  rotulo='"In coming image"'),
            ventana_leon=dict(l_rect, camara=camara_ventana(l_rect, TERM_CAM_POS, LEON_ANG_Y),
                              rotulo='"Out going image"'),
            subtitulos=dict(
                posicion_px=[320, 320], frac_centro=dict(cx=0.0, cy=round((240 - 320) / 480, 5)),
                fuente='OpeMesSet: unidad 0xFE de IDC_SSCRN_NEAR_0 en (0, -80) -> MesSet(x = (0 + 320) * 0.8, '
                       'y = (240 + 80) * 0.8) en la pantalla de mensajes 512x384, layout LAYOUT_OPERATOR, '
                       'attr 0x03000054 (ver out/texto/ para la fuente del codec: whisk3d/fuente_re4_codec.*)',
                banda=dict(nota='unidades 0x2F (640x100, rojo oscuro (10,0,0) alfa 145) y lineas 0x30/0x31 (tex 0x3E)',
                           **rect_info(0, 305, 640, 100))),
            capas_2d='ui/ui.json: unidades con textura, rect, color, blend y efecto, y pistas por frame del codec'),
        transiciones=dict(
            abrir=[
                dict(g=0, que='Leon saca la radio: motion pl00 0x79 (71 f) = clip "radio" de out/r100_intro/leon_radio.glb; '
                              'tono bio4evt #3 (audio/str1_003.wav, %.2f s); PlSetEyeMode(1)' %
                              info_audio['tono_radio']['duracion_s']),
                dict(g=22, que='aparece la radio (out/r100_intro/radio.glb) en la mano izquierda (parts 0x10, '
                               'pos (111, -22, 66) mm, rot (-0.4887, 0.3142, -0.7330)); setLeftHand(2)'),
                dict(g=71, que='fin de la motion -> SubScreenOpen(SS_OPEN_TERM = 0x20)'),
                dict(g=72, frames=3, que='SubScreenExec: FadeSetW(0, 3) = fundido A NEGRO en 3 frames (sin SE: '
                                         'open_flag 0x20 no llama SndCall(0, 2))'),
                dict(g=75, frames=5, que='negro: pantalla 640x448, carga del REL + ss_term.dat + op01.das + '
                                         'ss_oc101.dat (lecturas bloqueantes: tiempo real de disco, no modelado)'),
                dict(c=0, frames=5, que='FadeSetW(0x80000000, 5): fundido DESDE negro en 5 frames; SE 0x14 '
                                        '(audio/se_codec_abrir.wav); modelos en "espera" (loop); la unidad 0x07 '
                                        '(negro 640x430) se desvanece en 12 frames; la ventana de Hunnigan muestra '
                                        'nieve/blanco (grupo 0x04: hasta c 133-140) y la de Leon ya muestra a Leon'),
                dict(c=OPE_WAIT, que='ope.wait (30) llega a 0 -> OpeMdtSet'),
                dict(c=OPE_WAIT + 1, que='SndStrStopBlock(tono) + SndStrReq(1, 0x8C) (precarga de la voz)'),
                dict(c=DISPARO, que='stream listo (latencia SUPUESTA %d f) -> arranca la voz, motions "llamada" '
                                    '(mezcla de 10 f desde "espera") + caras, grupos 0x13/0x14 (marcos de las '
                                    'ventanas) se abren con su curva de color, primer subtitulo' % LATENCIA_STREAM),
                dict(c=140, que='termina de despejarse la ventana de Hunnigan (grupo 0x04 / 0x09 a alfa 0)')],
            cerrar=[
                dict(c=fin_c, s=FIN_SEQ, que='TermSeq arg -1: para el stream, borra los mensajes -> SsTermMain::quit: '
                                               'SE 0x15 (audio/se_codec_cerrar.wav)'),
                dict(c=fin_c + 1, frames=3, que='SsExitInit: FadeSetW(0, 3) = fundido a negro 3 frames'),
                dict(c=fin_c + 4, frames=6, que='negro: SubScreenExit (vuelve la pantalla 512x448, la camara y la '
                                                 'memoria del juego)'),
                dict(c=fin_c + 10, frames=10, que='OpeSetOpenTermEnd: radio destruida, mano izquierda normal '
                                                   '(setLeftHand(0x63)), PlSetEyeMode(0), FadeSetW(0x80000001, 10) = '
                                                   'fundido DESDE negro en 10 frames; vuelve el juego (SceEventEnd)')],
            saltear='START (Key 0x20000000) en cualquier momento, o B durante la llamada (para la voz y pasa los '
                    'mensajes con A/B; pone las motions de fin termMotionCancel(10))'),
        audio=info_audio,
        lineas=[dict(e, inicio_c=DISPARO + e['inicio_seq'], fin_c=DISPARO + e['fin_seq'],
                     inicio_s=t(e['inicio_seq']), fin_s=t(e['fin_seq']), audio='audio/str1_140.wav',
                     audio_offset_s=t(e['inicio_seq'])) for e in lins],
        verificacion=dict(
            voz_s=info_audio['voz']['duracion_s'], secuencia_s=t(FIN_SEQ),
            clip_llamada_leon_s=info_modelos['leon']['clips']['llamada']['segundos'],
            clip_llamada_hunnigan_s=info_modelos['hunnigan']['clips']['llamada']['segundos'],
            voz_segmentos_frames=segs,
            nota='la voz (26.13 s) termina antes del fin de la secuencia (27.0 s): quedan ~0.9 s de silencio con el '
                 'ultimo subtitulo; cada tramo de voz cae dentro de su linea (voz_segmentos de cada linea)'),
        timeline_global=dict(
            nota='nominal, sin carga de disco',
            radio_g=[0, 71], negro_g=[72, G_CODEC], codec_g=[G_CODEC, G_CODEC + fin_c + 1],
            voz_g=[G_CODEC + DISPARO, G_CODEC + DISPARO + round(info_audio['voz']['duracion_s'] * FPS)],
            vuelta_al_juego_g=G_CODEC + fin_c + 10, total_s=t(G_CODEC + fin_c + 20)),
        motions=dict(
            espera='termMotionCancel(no 0): MotionSetCore(.., hokan 0, 0x8004 = loop) en los dos, desde c 0',
            llamada='termMotionSet(pTelDat, 10): MotionSetCore(.., hokan 10, 0x8000) en c %d; el frame k del clip se '
                    've en c = %d + k (MotionMove al principio del frame siguiente); las caras: ShapeSet(cabeza, 0, '
                    'fcv, 2) Leon / (.., 0xA) Hunnigan (x1.37), un rate por frame y se sostiene el ultimo' %
                    (DISPARO, DISPARO + 1),
            despues='el clip termina (815 / 814 f) despues del fin de la secuencia (810): la pantalla se cierra '
                    'antes; si se saltea, termMotionCancel(10) = "espera" con mezcla de 10 f'),
        caveats=[
            'Cabeza de Leon: tel00ModelInit pide SS12/SS13 de ss_term.dat pero SS13 es un FCV (60 f); la unica '
            'textura que calza con la cabeza (ss_term:8, texturas 0/1/2) es ss_oc101:12 (SS16, no la referencia el '
            'codigo): la cara de Leon 256x256 + pelo. Se uso esa (el render confirma que es correcta). La motion '
            '"espera" de Leon es ss_term:9 (termMotionCancel pide SS14 de pTermDat, que no existe en el archivo).',
            'Capacidad de IdSub (128): de SS9 solo entran 47 filas (inferido; sin eso Hunnigan quedaria tapada por '
            'un televisor gris). No verificado en un emulador.',
            'Latencia del stream (SndStrStatusCk) y tiempo de carga del disco no modelados: DISPARO = c %d supone 1 '
            'frame.' % DISPARO,
            'Los efectos 1/2/3 de las unidades 2D (negativo / distorsion de la imagen) se aproximaron en los renders '
            'de control; la fuerza de la distorsion es estimada.',
            'El 3D en los renders de control se recorta a la banda del marco (y 60..420): el decomp no muestra '
            'scissor; afuera el juego podria dejar ver piernas/torso por abajo. En Whisk3D: dibujar a cada personaje '
            'solo en su ventana.',
            'Iluminacion de los renders de control: plana (textura). Las luces del juego estan en espacio_3d.luces.',
            'Las partes sin claves de las motions (Leon: solo 18 canales) quedan en el reposo del .bin.'])
    with open(os.path.join(OUT, 'codec.json'), 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=DEFAULT_DISC)
    ap.add_argument('--sin-control', action='store_true', help='no renderizar las imagenes de control (Blender)')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    asegurar(args.disc)
    info_modelos = modelos()
    info_audio = audio(args.disc)
    segs = envolvente_voz(os.path.join(OUT, info_audio['voz']['wav']))
    seq = secuencia()
    txt = textos()
    lins = lineas(seq, txt, segs)
    ids, cuadros, cache, huecos = ui(DISPARO + FIN_SEQ + 1)
    controles = [] if args.sin_control else control(cuadros, cache, lins, huecos)
    doc = escribir_json(info_modelos, info_audio, lins, huecos, controles, segs)
    print('lineas:')
    for e in doc['lineas']:
        print(f"  s {e['inicio_seq']:4d}-{e['fin_seq']:4d} {e['habla'] or '?':9s} {e['id_texto']} p{e['pagina']}: "
              f"{' / '.join(e['texto'] or [])}")
    print(f'-> {os.path.join(OUT, "codec.json")}')


if __name__ == '__main__':
    main()
