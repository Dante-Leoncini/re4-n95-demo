#!/usr/bin/env python3
"""
El COMIENZO REAL de r100 (Resident Evil 4, GameCube USA), hasta la pelea en la casa, para Whisk3D:

  out/r100_intro/plan.json            la secuencia del juego (st1/r120.cpp + st1/r100.cpp): que eventos corren y cuando,
                                      donde queda Leon, la puerta, el aldeano, la musica (loops), la escena de la ventana
  out/r100_intro/camara_ventana.json  la camara de la escena de la ventana (corte de camara 0xA del cuarto), por frame
  out/r100_intro/leon_evento.glb      Leon_ev (MISMO esqueleto / mallas / atlas que out/evento_s03/leon_evento.glb) con el
                                      clip "ventana": la motion ROOM_ARC 0x34 que el juego le pone a Leon en esa escena,
                                      con la raiz en el MUNDO (armadura en el origen)
  out/r100_intro/coche_juego.glb      la camioneta de la policia estacionada (obm2a00 = ROOM_ARC 0x1D/0x1E) como la deja
                                      R100Init, clip "juego" de 1 frame (raiz en el mundo)
  out/r100_intro/camion_juego.glb     el camion viejo que tapa el camino (ROOM_ARC 0x1F/0x20, W->carSub) en su lugar
  out/r100_intro/policia_juego.glb    los dos policias de juego (cuerpo + cabeza, ROOM_ARC 0x24.. 0x2A) con "quieto"
  out/r100_intro/policia_a_juego.glb  (loop, 0x2B / 0x2C) y "hablar" (0x35 / 0x36, el boton A cerca del coche)
  out/r100_intro/audio/*.wav          el stream de la escena de la ventana (bio4evt #34), la musica del cuarto partida
                                      en intro + loop, y los sonidos del cuarto que usa el guion (SE 0, 5, 6, 0x28, 0x29)
  out/evento_s40/obm1a00.glb          la camioneta del evento r100s40 con sus vidrios (obm3000a..f) y los clips s40_cNN

La cutscene de la llegada (r100s40) se extrae con los extractores de siempre (ver plan.json "comandos").

Uso:
  python3 re4_extract_intro_r100.py
"""
import argparse
import json
import math
import os
import struct
import sys
import types

import numpy as np

import re4_extract_leon as L
import re4_evento as E
import re4_extract_ganado as G
import re4_extract_personajes_evento as P
import re4_extract_evento as EV
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'r100_intro')
OUT_S40 = os.path.join(HERE, 'out', 'evento_s40')
MM = 0.001
FPS = 30.0

# ---- datos de st1/r100.cpp (mm / radianes del juego) ----
CARRO_POS, CARRO_ROT = (-102497.0, -687.0, 1953.0), (0.0, 0.812328577, 0.0)       # R100Init: W->car
CARRO2_POS, CARRO2_ROT = (-60821.0, -55.0, -17230.0), (0.0, -1.50098312, 0.0)     # R100Init: W->carSub (camion)
LEON_INICIO_POS, LEON_INICIO_ROT_Y = (-99685.0, -484.0, -1343.0), 2.246           # r100_StartEvent
LEON_VENTANA_POS, LEON_VENTANA_ROT_Y = (-80540.0, -8.0, -12073.0), 2.99           # r100_HouseEvent
CAM_VENTANA = 0xA                                                                   # CamCtrl.CutCall(0xA)
ARC = dict(carro_bin=0x1D, carro_tpl=0x1E, carro2_bin=0x1F, carro2_tpl=0x20, poli_bin=0x24, poli_tpl=0x25,
           poli_a_bin=0x26, poli_cab=0x27, poli_cab_tpl=0x28, poli_a_cab=0x29, poli_a_cab_tpl=0x2A,
           poli_quieto=0x2B, poli_a_quieto=0x2C, leon_ventana=0x34, poli_hablar=0x35, poli_a_hablar=0x36)


def arc_room(r, n):
    """ROOM_ARC_PTR(pRoom, n): entrada n - 4 del cuerpo del .das."""
    return r.entry(n - 4)


# ------------------------------------------------------------------------------------------------
#  CAMARA de un corte del cuarto (cam_ctrl.cpp HermiteExport + CameraMotion::move)
# ------------------------------------------------------------------------------------------------
def cortes_camara(cam):
    """B40x (cam_ctrl.h): cabecera 0x10, CameraAreaRec[numArea] 0x10, CameraAreaInfo[numArea] 0x30, CameraCut[numCut]
    0x34 (offsets del archivo, calcAddr los reubica)."""
    ncut, narea = cam[4], cam[5]
    base = 0x10 + narea * 0x10 + narea * 0x30
    out = {}
    for i in range(ncut):
        o = base + i * 0x34
        _, cno, typ, _ = struct.unpack('>BbbB', cam[o:o + 4])
        fr, = struct.unpack('>I', cam[o + 0x10:o + 0x14])
        num, pos, at, roll, fov = struct.unpack('>iIIII', cam[o + 0x20:o + 0x34])
        k = dict(camera_no=cno, tipo=typ, num=num)
        if num > 0 and typ in (6, 7):     # CameraMotion (HermiteExport); los tipo 8 (hombro) usan num para otra cosa
            k['frames'] = [struct.unpack('>H', cam[fr + 2 * j:fr + 2 * j + 2])[0] for j in range(num)] if fr else \
                [30 * j for j in range(num)]
            k['pos'] = [struct.unpack('>3f', cam[pos + 12 * j:pos + 12 * j + 12]) for j in range(num)]
            k['at'] = [struct.unpack('>3f', cam[at + 12 * j:at + 12 * j + 12]) for j in range(num)]
            k['roll'] = [struct.unpack('>f', cam[roll + 4 * j:roll + 4 * j + 4])[0] for j in range(num)]
            k['fovy'] = [struct.unpack('>f', cam[fov + 4 * j:fov + 4 * j + 4])[0] for j in range(num)]
        out[cno] = k
    return out


def camara_motion(corte):
    """Frames de la camara de un corte tipo 6 (CameraMotion) exactamente como el juego:
    HermiteExport: llaves = los puntos del corte en sus frames; valor v y UNA tangente t (entrada = salida):
      k = 0: t = (v1 - v) / dt1;  ultima: t = (v - v0) / dt0;  medio: (dt1 * (v - v0) / dt0 + dt0 * (v1 - v) / dt1) / (dt0 + dt1)
      y despues t *= dt0 (dt0 = frames[k] - frames[k - 1], 0 en la primera llave -> tangente 0). fov en radianes.
    CameraMotion: maxFrame = frames[ultima] + 1; move() evalua HermiteInterpolation (flags 2) en frame = 0, 1, ...
    y CameraSequenceCtrl termina (IsMotionEnd) cuando frame >= maxFrame: se ven los frames 0..maxFrame (el ultimo
    repite la ultima llave)."""
    fr = corte['frames']
    n = corte['num']

    def pista(vals):
        tans = []
        for k in range(n):
            k0, k1 = max(k - 1, 0), min(k + 1, n - 1)
            v, v0, v1 = vals[k], vals[k0], vals[k1]
            dt0, dt1 = float(fr[k] - fr[k0]), float(fr[k1] - fr[k])
            if k == 0:
                t = (v1 - v) / dt1
            elif k == n - 1:
                t = (v - v0) / dt0
            else:
                t = (dt1 * ((v - v0) / dt0) + dt0 * ((v1 - v) / dt1)) / (dt0 + dt1)
            tans.append(t * dt0)
        return tans

    max_frame = fr[-1] + 1

    def evaluar(vals, tans, f):
        if f >= max_frame:
            return vals[-1]
        for i in range(n):
            if fr[i] == f:
                return vals[i]
            if fr[i] < f < fr[min(i + 1, n - 1)]:
                return EV.hermite((vals[i], vals[i + 1]), (tans[i], tans[i + 1]), (f - fr[i]) / (fr[i + 1] - fr[i]))
        return vals[-1]
    comps = {}
    for nombre, serie in (('pos', corte['pos']), ('at', corte['at'])):
        comps[nombre] = []
        for c in range(3):
            vals = [p[c] for p in serie]
            comps[nombre].append((vals, pista(vals)))
    rv = list(corte['roll'])
    fv = [math.radians(x) for x in corte['fovy']]
    roll_t, fov_t = pista(rv), pista(fv)
    salida = dict(ojo=[], objetivo=[], arriba=[], roll_grados=[], fov_grados=[])
    for f in range(max_frame + 1):
        pos = [evaluar(*comps['pos'][c], f) for c in range(3)]
        at = [evaluar(*comps['at'][c], f) for c in range(3)]
        roll = evaluar(rv, roll_t, f)
        fov = evaluar(fv, fov_t, f)
        up = EV.camara_arriba(pos, at, roll)
        salida['ojo'].append(EV.r3([x * MM for x in pos]))
        salida['objetivo'].append(EV.r3([x * MM for x in at]))
        salida['arriba'].append(EV.r3(up))
        salida['roll_grados'].append(round(math.degrees(roll), 4))
        salida['fov_grados'].append(round(math.degrees(fov), 4))
    return salida


# ------------------------------------------------------------------------------------------------
#  MALLAS: filtro de partes ocultas (escala 0) y piezas rigidas colgadas de una parte
# ------------------------------------------------------------------------------------------------
class _Parte:
    def __init__(self, part, tris):
        self._p = part
        self._t = tris

    def triangles(self):
        return self._t

    def __getattr__(self, k):
        return getattr(self._p, k)


class MallaFiltrada:
    """Un meshbin sin los triangulos de las partes `ocultas` (su escala es 0 en el juego)."""

    def __init__(self, m, ocultas=()):
        self._m = m
        self.parts = []
        self.quitados = 0
        for part in m.parts:
            tris = []
            for tri in part.triangles():
                if all(m.skin(v[0])[0][0] in ocultas for v in tri):
                    self.quitados += 1
                    continue
                tris.append(tri)
            self.parts.append(_Parte(part, tris))

    def __getattr__(self, k):
        return getattr(self._m, k)


class MallaRigida:
    """Un modelo de 1 parte colgado de la parte `parte` de otro (Pos flag 0x40000000 = OyaSetObj18): sus vertices
    estan en el espacio de esa parte -> se pasan al espacio del modelo en reposo (+ reposo de la parte) y se pesan
    100% a ella."""

    def __init__(self, m, parte, reposo):
        self._m = m
        self.parts = m.parts
        self._parte = parte
        self._off = reposo[parte]

    def position(self, i):
        p = self._m.position(i)
        return tuple(p[c] + self._off[c] for c in range(3))

    def skin(self, i):
        return [(self._parte, 1.0)]

    def __getattr__(self, k):
        return getattr(self._m, k)


def _quat(r):
    """Cuaternion (x, y, z, w) de una matriz 3x4 (sin escala)."""
    m = [[r[0], r[1], r[2]], [r[4], r[5], r[6]], [r[8], r[9], r[10]]]
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        return (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        return ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
    return ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)


def rot_matrix34(ang, pos):
    """math_sub.cpp RotMatrix (Rz * Ry * Rx) + traslacion, 3x4 fila."""
    R = EV.rot_matrix(*ang)
    return (R[0][0], R[0][1], R[0][2], pos[0], R[1][0], R[1][1], R[1][2], pos[1], R[2][0], R[2][1], R[2][2], pos[2])


def pose_estatica(skel, angulos=None):
    """Una 'pose' (como evalhost.Pose) con el reposo del modelo y rotaciones locales por parte (cParts::ang)."""
    angulos = angulos or {}
    return types.SimpleNamespace(
        l_mat=[rot_matrix34(angulos.get(p.no, (0.0, 0.0, 0.0)), p.pos) for p in skel.parts], quat=_quat)


COSTURA_M = 2e-5   # 0.02 mm: separacion de los vertices de partes distintas que caen en la MISMA posicion


def separar_costuras(grupos, paso=COSTURA_M):
    """Los .w3dm de Whisk3D guardan los puntos de control UNICOS POR POSICION (W3dMalla.cpp: W3dmPosKey = los 12
    bytes de la posicion): dos vertices de glTF en la misma posicion pasan a ser UN punto, que queda en los vertex
    groups de LOS DOS huesos (peso 1 + 1, normalizado a 0.5 / 0.5). En la camioneta el borde de cada puerta coincide
    con la carroceria (167 posiciones): al abrir la puerta esos puntos quedaban a mitad de camino y la chapa se
    estiraba (y 12 vertices de los vidrios obm3000 terminaban pesados a la puerta / al chasis). En el juego son
    vertices distintos (cada uno con su matriz de la paleta), asi que aca se separan: en cada posicion repetida el
    primer juego de pesos (el del primer vertice, normalmente la carroceria) queda donde esta y los demas se corren
    k * `paso` hacia el origen del modelo (0.02 mm: invisible, y ya no son la misma posicion en bytes).
    Modifica `grupos` (el de L.malla_skinneada) en el lugar y devuelve la cantidad de vertices corridos."""
    por_pos = {}
    for transp in (False, True):
        _, pos, _, _, jo, we, _ = grupos[transp]
        for i, p in enumerate(pos):
            clave = tuple(np.float32(c).tobytes() for c in p)
            pesos = tuple(sorted((j, round(w, 4)) for j, w in zip(jo[i], we[i]) if w > 0))
            por_pos.setdefault(clave, []).append((transp, i, pesos))
    corridos = 0
    for lista in por_pos.values():
        juegos = []
        for _, _, pesos in lista:
            if pesos not in juegos:
                juegos.append(pesos)
        if len(juegos) < 2:
            continue
        for transp, i, pesos in lista:
            k = juegos.index(pesos)
            if k == 0:
                continue
            pos = grupos[transp][1]
            p = np.array(pos[i], np.float64)
            n = np.linalg.norm(p)
            d = -p / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])
            pos[i] = tuple(float(c) for c in p + d * paso * k)
            corridos += 1
    return corridos


def glb_modelo(fuentes, skel, clips, salida, raiz_nombre, malla_nombre, extras=None):
    """fuentes [(malla (meshbin o envoltorio), TPL, prefijo)] -> glb skinneado (todas las piezas en UNA malla, opaco /
    transparente) con el atlas a resolucion COMPLETA; clips [(nombre, poses, raiz 3x4 por frame o None)]."""
    L.ATLAS_COMPLETO = True
    scale = MM
    n = skel.n_parts
    rest = L.rest_world(skel)
    imagenes = {}

    def clave_de(tex, pref, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (pref, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for m, tex, pref in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, pref, part)
    atlas, rects = L.armar_atlas(imagenes)
    H, W = atlas.shape[:2]
    out_dir = os.path.dirname(os.path.abspath(salida))
    os.makedirs(out_dir, exist_ok=True)
    atlas_nombre = os.path.splitext(os.path.basename(salida))[0] + '_atlas.png'
    with open(os.path.join(out_dir, atlas_nombre), 'wb') as f:
        f.write(gxtex.png(atlas))
    b = gltf.Builder()
    grupos, n_tri, cutoff = L.malla_skinneada(fuentes, clave_de, rects, W, H, scale, 0.0)
    costuras = separar_costuras(grupos)
    if costuras:
        print(f'{malla_nombre}: {costuras} vertices en la misma posicion que otro de OTRA parte -> separados '
              f'{COSTURA_M * 1000:.2f} mm (los .w3dm sueldan por posicion)')
    prims = []
    for transp, mat, parte in ((False, 0, 'opaco'), (True, 1, 'transparente')):
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        if idx:
            prims.append(L.primitiva(b, pos, nrm, uv, idx, mat, parte, jo, we))
    nodes = [{'name': raiz_nombre, 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': f'{raiz_nombre}_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    mesh_node = len(nodes)
    nodes.append({'name': malla_nombre, 'mesh': 0, 'skin': 0})
    animations = [L.clip_esqueleto(b, nodes, n, poses, nombre, FPS, scale, raiz, skel.roots())
                  for nombre, poses, raiz in clips]
    textura = {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
    pref = malla_nombre.split('_')[0]
    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_intro_r100.py'},
        'scene': 0,
        'scenes': [{'name': raiz_nombre, 'nodes': [0, mesh_node]}],
        'nodes': nodes,
        'skins': [skin],
        'meshes': [{'name': malla_nombre, 'primitives': prims}],
        'images': [{'uri': atlas_nombre}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': [
            {'name': f'{pref}_opaco', 'pbrMetallicRoughness': textura, 'extras': {'w3d_transparent': False}},
            # alphaRef 0 en todas las piezas con alphaTex de estos modelos: el GX no descarta nada y MEZCLA (vidrios
            # al 60 %) -> BLEND; con alphaRef > 0 seria un alpha test (MASK)
            dict({'name': f'{pref}_transparente', 'pbrMetallicRoughness': textura, 'extras': {'w3d_transparent': True}},
                 **({'alphaMode': 'BLEND'} if cutoff <= 1.5 / 255 else {'alphaMode': 'MASK', 'alphaCutoff': cutoff})),
        ],
        'extras': dict({'raiz': 'hueso_000 en coordenadas del mundo del cuarto (m); la armadura va en el origen'},
                       **(extras or {})),
    }
    if animations:
        doc['animations'] = animations
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    gltf.write(doc, bytes(b.blob), salida)
    n_vert = sum(len(g[1]) for g in grupos.values())
    print(f'-> {os.path.relpath(salida, HERE)}: {malla_nombre} {n_vert} vertices, {n_tri} triangulos, atlas {W}x{H}, '
          f'{len(animations)} clips ({", ".join(a["name"] for a in animations)})')
    return dict(glb=os.path.relpath(salida, HERE), vertices=n_vert, triangulos=n_tri, atlas=[W, H],
                clips={nombre: len(poses) for nombre, poses, _ in clips}, costuras_separadas=costuras)


def lugar_mm_grados(pos, rot):
    return (pos, tuple(math.degrees(r) for r in rot))


# ------------------------------------------------------------------------------------------------
#  1. la camioneta del evento r100s40 (obm1a00 + vidrios obm3000a..f)
# ------------------------------------------------------------------------------------------------
def coche_evento(ev, arc):
    """EventCarInit (st1/r120.cpp) en el corte 0 frame 0: obm1a00 partes 0x0F y 0x12..0x17 con escala 0 (los vidrios
    de baja calidad y la parte 15 no se dibujan en todo el evento); en su lugar van obm3000a..f, colgadas por paquete
    Pos flag 0x40000000 de las partes 16, 17, 11, 12, 13, 14 (motion vacia: quedan en el reposo de esa parte)."""
    b_n, t_n = ev.modelos['obm1a00']
    skel = modelbin.parse(G.datos(ev, arc, b_n))
    skel.check_tree()
    rest = L.rest_world(skel)
    cuerpo = MallaFiltrada(meshbin.parse(G.datos(ev, arc, b_n)), ocultas={0x0F, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17})
    fuentes = [(cuerpo, gxtex.parse_tpl(G.datos(ev, arc, t_n)), 'obm1a00')]
    vidrios = []
    for hijo, padre, parte in ev.adjuntos():
        if padre != 'obm1a00':
            continue
        hb, ht = ev.modelos[hijo]
        hs = modelbin.parse(G.datos(ev, arc, hb))
        if hs.n_parts != 1 or ev.cortes_de(hijo):
            raise ValueError(f'{hijo}: se esperaba 1 parte y motion vacia')
        fuentes.append((MallaRigida(meshbin.parse(G.datos(ev, arc, hb)), parte, rest),
                        gxtex.parse_tpl(G.datos(ev, arc, ht)), os.path.splitext(os.path.basename(ht))[0]))
        vidrios.append({'modelo': hijo, 'hueso': f'hueso_{parte:03d}'})
    clips = []
    for corte in ev.cortes_de('obm1a00'):
        poses, raiz = E.poses_corte(skel, ev.motion(corte, 'obm1a00'), ev.cortes[corte], lugar=ev.lugar('obm1a00'))
        clips.append((ev.clip(corte), poses, raiz))
    print(f'obm1a00: {cuerpo.quitados} triangulos de las partes ocultas quitados; vidrios {vidrios}')
    info = glb_modelo(fuentes, skel, clips, os.path.join(OUT_S40, 'obm1a00.glb'), 'obm1a00', 'obm1a00_malla',
                      extras={'evento': ev.nombre, 'modelo': 'obm1a00 (la camioneta de la policia)',
                              'vidrios': vidrios, 'partes_ocultas': [0x0F] + list(range(0x12, 0x18))})
    info['vidrios'] = vidrios
    return info


# ------------------------------------------------------------------------------------------------
#  2. la escena de la VENTANA (r100_HouseEvent): Leon con la motion ROOM_ARC 0x34
# ------------------------------------------------------------------------------------------------
def leon_ventana(ev03, arc, room):
    """pPL->motionSet(ROOM_ARC 0x34, hokan 10, frame 0, attr 1): MotionSetCore flags 1 = la velocidad de las claves
    raiz (Null) mueve a Leon desde (-80.54, -0.008, -12.073) rot Y 2.99 (r100_HouseEvent). Se evalua sobre el
    esqueleto de Leon_ev (el de leon_evento.glb de r100s03) con la raiz en el mundo: Pos * RotY * Null(f)
    (la Null vale 0 en el frame 0, asi que es identico a sumar los deltas como MotionAddSpeed)."""
    mot = fcv.parse(arc_room(room, ARC['leon_ventana']).data)
    shim = types.SimpleNamespace(
        nombre='r100_ventana', cortes=[mot.n_frames], modelos=ev03.modelos, piezas_de=ev03.piezas_de, bins=ev03.bins,
        cortes_de=lambda m: [0], motion=lambda c, m: mot, clip=lambda c: 'ventana',
        lugar=lambda m: ((LEON_VENTANA_POS[0], LEON_VENTANA_POS[1], LEON_VENTANA_POS[2]),
                         (0.0, math.degrees(LEON_VENTANA_ROT_Y), 0.0)))
    P.OUT = OUT
    args = types.SimpleNamespace(scale=MM, fps=FPS, no_ik=False)
    h = P.exportar(shim, arc, P.PERSONAJES['leon'], args, ev03)
    return h, mot


# ------------------------------------------------------------------------------------------------
#  3. los objetos de juego que R100Init deja junto al camino (antes de la muerte del primer ganado)
# ------------------------------------------------------------------------------------------------
def objetos_juego(room):
    datos = lambda n: arc_room(room, n).data   # noqa: E731
    res = {}
    # la camioneta: pList[10].ang.x = 0.4363 (la parte 10 es el VOLANTE: su inclinacion, la misma que traen todas las
    # motions de obm1a00), partes 11, 13, 15 con escala 0 (los vidrios delanteros bajados + la parte 15)
    skel = modelbin.parse(datos(ARC['carro_bin']))
    ms = MallaFiltrada(meshbin.parse(datos(ARC['carro_bin'])), ocultas={11, 13, 15})
    pose = pose_estatica(skel, {10: (0.436332315, 0.0, 0.0)})
    raiz = [rot_matrix34(CARRO_ROT, CARRO_POS)]
    res['coche'] = glb_modelo([(ms, gxtex.parse_tpl(datos(ARC['carro_tpl'])), 'obm2a00')], skel,
                              [('juego', [pose], raiz)], os.path.join(OUT, 'coche_juego.glb'), 'coche', 'Coche_malla',
                              extras={'fuente': 'r100.das ROOM_ARC 0x1D / 0x1E (obm2a00)',
                                      'nota': 'R100Init: SetObjSmd en (-102.497, -0.687, 1.953) rot Y 0.8123; '
                                              'pList[10].ang.x = 0.4363; partes 11, 13, 15 escala 0'})
    res['coche']['partes_ocultas'] = [11, 13, 15]
    res['coche']['triangulos_quitados'] = ms.quitados
    # el CAMION viejo que tapa el camino (W->carSub: 5 partes = chasis + 4 ruedas; st1/r100.cpp lo llama 'car sub';
    # r100_Car_pos_move lo tira al barranco despues de s20)
    skel2 = modelbin.parse(datos(ARC['carro2_bin']))
    res['camion'] = glb_modelo([(meshbin.parse(datos(ARC['carro2_bin'])), gxtex.parse_tpl(datos(ARC['carro2_tpl'])),
                                 'camion')], skel2,
                               [('juego', [pose_estatica(skel2)], [rot_matrix34(CARRO2_ROT, CARRO2_POS)])],
                               os.path.join(OUT, 'camion_juego.glb'), 'camion', 'Camion_malla',
                               extras={'fuente': 'r100.das ROOM_ARC 0x1F / 0x20 (W->carSub: el camion viejo)',
                                       'nota': 'R100Init: SetObjSmd en (-60.821, -0.055, -17.23) rot Y -1.501'})
    # los policias: cuerpo (0x24 / 0x26, tpl 0x25) + addModel (0x27 / 0x29 con tpl 0x28 / 0x2A), en el lugar del
    # coche; quieto = MotionSetCore(0x2B / 0x2C, flags 5 = loop), hablar = 0x35 / 0x36 (hokan 10, flags 5) al A
    for clave, cuerpo, cab, cab_tpl, quieto, hablar in (
            ('policia', ARC['poli_bin'], ARC['poli_cab'], ARC['poli_cab_tpl'], ARC['poli_quieto'], ARC['poli_hablar']),
            ('policia_a', ARC['poli_a_bin'], ARC['poli_a_cab'], ARC['poli_a_cab_tpl'], ARC['poli_a_quieto'],
             ARC['poli_a_hablar'])):
        sk = modelbin.parse(datos(cuerpo))
        sk.check_tree()
        fuentes = [(meshbin.parse(datos(cuerpo)), gxtex.parse_tpl(datos(ARC['poli_tpl'])), f'r100_{ARC["poli_tpl"]:02x}'),
                   (meshbin.parse(datos(cab)), gxtex.parse_tpl(datos(cab_tpl)), f'r100_{cab_tpl:02x}')]
        clips = []
        for nombre, n_arc in (('quieto', quieto), ('hablar', hablar)):
            m = fcv.parse(datos(n_arc))
            largo = m.max_frame + 1
            poses, raiz = E.poses_corte(sk, m, largo, lugar=lugar_mm_grados(CARRO_POS, CARRO_ROT))
            clips.append((nombre, poses, raiz))
        res[clave] = glb_modelo(fuentes, sk, clips, os.path.join(OUT, f'{clave}_juego.glb'), clave,
                                ('Policia' if clave == 'policia' else 'PoliciaA') + '_juego',
                                extras={'fuente': f'r100.das ROOM_ARC {cuerpo:#x} + {cab:#x}, motions {quieto:#x} / '
                                                  f'{hablar:#x}',
                                        'nota': 'objeto en el lugar del coche (R100Init); la motion lo ubica'})
    return res


# ------------------------------------------------------------------------------------------------
#  4. audio
# ------------------------------------------------------------------------------------------------
def audio(disco):
    os.makedirs(os.path.join(OUT, 'audio'), exist_ok=True)
    res = {}
    st = EV.Streams(disco)
    # el stream de la escena de la ventana: SndStrReq(1, 0x22, 0x80000003, 0, 0, 0.0f)
    h = st.shd(1, 0x22)
    rit = st.rit(1, 0x22)
    ruta = os.path.join(OUT, 'audio', 'str1_034.wav')
    if not os.path.isfile(ruta):
        canales, rate, _ = st.decodificar(1, 0x22)
        EV.escribir_wav(ruta, canales, rate)
        EV.escribir_n95(os.path.join(OUT, 'audio', 'str1_034_n95.wav'), canales, rate)
    res['ventana'] = dict(wav='audio/str1_034.wav', wav_n95='audio/str1_034_n95.wav', archivo_disco='bgm/bio4evt.sbb',
                          bloque=1, numero=0x22, str_no=rit['str_no'], rate=h['rate'], muestras=h['samples'],
                          canales=2 if (h['flag'] & 1) and not (h['flag'] & 2) else 1,
                          duracion_s=round(h['samples'] / h['rate'], 4), loop=bool(h['flag'] & 4),
                          volumen_rit=rit['vol'])
    disco.limpiar()
    # la musica del cuarto (bio4bgm #2, la misma de out/evento_s03/audio/str0_002.wav) partida en intro + loop
    src = os.path.join(HERE, 'out', 'evento_s03', 'audio', 'str0_002.wav')
    import wave
    with wave.open(src) as w:
        n, rate, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), '<i2').reshape(-1, ch)
    hb = st.shd(0, 2)
    lp0 = EV.nibble_a_muestra(hb['lptop_nbl'])
    lp1 = EV.nibble_a_muestra(hb['lpend_nbl'])
    for nombre, a, b_ in (('bgm_r100_intro.wav', 0, lp0), ('bgm_r100_loop.wav', lp0, lp1 + 1)):
        with wave.open(os.path.join(OUT, 'audio', nombre), 'wb') as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.ascontiguousarray(x[a:b_]).astype('<i2').tobytes())
    res['musica_cuarto'] = dict(
        fuente='out/evento_s03/audio/str0_002.wav (bgm/bio4bgm.sbb, RIT 2 -> SHD 1)', rate=rate, muestras=n,
        shd_flag=hb['flag'], lptop_nbl=hb['lptop_nbl'], lpend_nbl=hb['lpend_nbl'],
        loop_inicio_muestra=lp0, loop_fin_muestra_inclusive=lp1, loop_inicio_s=round(lp0 / rate, 5),
        loop_fin_s=round((lp1 + 1) / rate, 5), loop_largo_s=round((lp1 + 1 - lp0) / rate, 5),
        intro_wav='audio/bgm_r100_intro.wav', loop_wav='audio/bgm_r100_loop.wav',
        nota='nibble -> muestra: (nbl // 16) * 14 + (nbl % 16 - 2). El AX salta de la muestra lpend (inclusive) a la '
             'lptop sin corte (snd_str3.cpp str_ax_voice_para_set: loopFlag 1, loop = aram + loop_start, end = aram + '
             'loop_end). El WAV completo ya trae el chunk smpl con ese loop. Tocar intro_wav una vez y despues '
             'loop_wav en loop es identico.')
    # sonidos del cuarto (bloque ROOM 6 de St1/r100.das) que usa st1/r100.cpp
    sys.path.insert(0, os.path.join(HERE, 'tools'))
    import re4_sonidos as R
    banco = R.load_bank('St1/r100.das', 6)
    ses = {0: ('aldea_llamado', 'r100_StreanChk: SndCall(6, 0, (-78.589, 0.86, -36.7)) cada 180 + 5 * Rnd(30) frames '
                                '(el primero a los 60 + Rnd(45)) mientras Room_flg[2] bit 31, hasta el evento s03'),
           5: ('policia_a_hablar', 'R100Main: boton A cerca del coche con Room_flg[2] bit 30 apagado: '
                                   'policia pl0700a (motion 0x36) + SndCall(6, 5) + mensaje 0x33'),
           6: ('policia_hablar', 'R100Main: con Room_flg[2] bit 30 prendido: policia pl0700 (0x35) + SndCall(6, 6)'),
           0x28: ('puerta_aviso', 'r100_DoorCk: SndCall(6, 0x28) cuando la emboscada encuentra a Leon (despues de s20)'),
           0x29: ('puerta_golpe', 'r100_MesDoor (area 0xB): puerta trabada, SndCall(6, 0x29) + mensaje 0xB')}
    res['se_cuarto'] = []
    for no, (nombre, nota) in ses.items():
        fr = R.render_se(banco, no)
        fn = os.path.join(OUT, 'audio', f'se_{nombre}.wav')
        R.write_wav_stereo(fn, fr, 32000)
        res['se_cuarto'].append(dict(se=no, wav=f'audio/se_{nombre}.wav', duracion_s=round(len(fr) / 32000, 3),
                                     nota=nota))
    return res


# ------------------------------------------------------------------------------------------------
#  5. la llamada por radio despues de la introduccion (r100_StartEvent -> OpeSetOpenTerm(0), game/sscrn.cpp)
# ------------------------------------------------------------------------------------------------
RADIO_BIN, RADIO_TPL, RADIO_MOT = 0x77, 0x78, 0x79          # PL_ARC de pl00 (entrada = n - 4)
RADIO_PARTE, RADIO_POS, RADIO_ROT = 0x10, (111.0, -22.0, 66.0), (-0.48869219, 0.31415927, -0.73303829)


def radio(arc, disco):
    """OpeSetOpenTerm(0): stream bio4evt #3 (strTbl[0] = 3), Leon saca la radio (MotionSetCore pl00 PL_ARC 0x79,
    flags 0x201), la radio (PL_ARC 0x77 / 0x78) en la mano izquierda (parentSet(pl, 0x10, (111, -22, 66),
    (-0.4887, 0.3142, -0.7330))) y setLeftHand(2) (PL_ARC 0x16); despues la pantalla de la terminal (SS_OPEN_TERM)."""
    import subprocess
    res = {}
    st = EV.Streams(disco)
    h = st.shd(1, 3)
    ruta = os.path.join(OUT, 'audio', 'str1_003.wav')
    if not os.path.isfile(ruta):
        canales, rate, _ = st.decodificar(1, 3)
        EV.escribir_wav(ruta, canales, rate)
        EV.escribir_n95(os.path.join(OUT, 'audio', 'str1_003_n95.wav'), canales, rate)
    disco.limpiar()
    res['audio'] = dict(wav='audio/str1_003.wav', wav_n95='audio/str1_003_n95.wav', bloque=1, numero=3,
                        duracion_s=round(h['samples'] / h['rate'], 4), rate=h['rate'])
    # la radio: malla rigida en el espacio LOCAL de hueso_016 (la mano izquierda), metros
    pl = arc('pl00')
    m = meshbin.parse(pl.entry(RADIO_BIN - 4).data)
    tex = gxtex.parse_tpl(pl.entry(RADIO_TPL - 4).data)
    R = EV.rot_matrix(*RADIO_ROT)
    L.ATLAS_COMPLETO = True
    imagenes = {}
    for part in m.parts:
        if part.triangles():
            k = ('radio', part.tex_id, part.alpha_tex if part.flags & 4 else None)
            imagenes.setdefault(k, gltf.compose_image(tex, part.tex_id, k[2]))
    atlas, rects = L.armar_atlas(imagenes)
    H, W = atlas.shape[:2]
    with open(os.path.join(OUT, 'radio_atlas.png'), 'wb') as f:
        f.write(gxtex.png(atlas))
    b = gltf.Builder()
    index, pos, nrm, uv, idx = {}, [], [], [], []
    for part in m.parts:
        k = ('radio', part.tex_id, part.alpha_tex if part.flags & 4 else None)
        for tri in part.triangles():
            if len({v[0] for v in tri}) < 3:
                continue
            for v in tri:
                i = index.get((k, v))
                if i is None:
                    i = index[(k, v)] = len(pos)
                    p = m.position(v[0])
                    q = [sum(R[r][c] * p[c] for c in range(3)) + RADIO_POS[r] for r in range(3)]
                    pos.append(tuple(c * MM for c in q))
                    n = m.normal(v[1])
                    nrm.append(tuple(gltf.normalize([sum(R[r][c] * n[c] for c in range(3)) for r in range(3)])))
                    uv.append(L.uv_atlas(m.texcoord(v[3]), rects[k], W, H))
                idx.append(i)
    doc = {'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_intro_r100.py'}, 'scene': 0,
           'scenes': [{'name': 'radio', 'nodes': [0]}],
           'nodes': [{'name': 'Leon_radio', 'mesh': 0}],
           'meshes': [{'name': 'Leon_radio', 'primitives': [L.primitiva(b, pos, nrm, uv, idx, 0, 'opaco')]}],
           'images': [{'uri': 'radio_atlas.png'}],
           'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
           'textures': [{'source': 0, 'sampler': 0}],
           'materials': [{'name': 'Radio_opaco', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                                          'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                          'extras': {'w3d_transparent': False}}],
           'extras': {'espacio': 'vertices en el espacio LOCAL de hueso_016 (mano izquierda de Leon): Child Of hueso_016 '
                                 'sin inversa, como Leon_pistola / hueso_010',
                      'fuente': 'pl00 PL_ARC 0x77 / 0x78; parentSet(pl, 0x10, (111, -22, 66) mm, rot (-0.4887, 0.3142, '
                                '-0.7330) rad RotMatrix Rz*Ry*Rx)'}}
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    gltf.write(doc, bytes(b.blob), os.path.join(OUT, 'radio.glb'))
    res['radio_glb'] = 'out/r100_intro/radio.glb'
    # el clip de Leon (esqueleto de juego = leon_combate.glb): re4_extract_leon.py con el mismo cuerpo que --combate
    sal = os.path.join(OUT, 'leon_radio.glb')
    subprocess.run([sys.executable, os.path.join(HERE, 're4_extract_leon.py'), '-o', sal, '--anim',
                    f'pl00:{RADIO_MOT - 4}=radio', '--atlas-completo', '--reducir', '0'], check=True,
                   stdout=subprocess.DEVNULL)
    mot = fcv.parse(pl.entry(RADIO_MOT - 4).data)
    res['leon_radio_glb'] = 'out/r100_intro/leon_radio.glb'
    res['radio_frames'] = mot.n_frames
    print(f'-> radio: audio {res["audio"]["duracion_s"]} s, motion {mot.n_frames} frames, radio.glb {len(idx) // 3} tri')
    return res


# ------------------------------------------------------------------------------------------------
#  6. plan.json
# ------------------------------------------------------------------------------------------------
def aev(info, no):
    a = next(x for x in info['aev'] if x['no'] == no)
    return dict(area=no, hex=hex(no), piso_m=a['piso'], alto_m=a['alto'], poligono_xz_m=a['pts'], tipo=a['tipo_evento'])


def plan(cam_doc, h_leon, mot_leon, coche40, juego, aud, rad):
    info = json.load(open(os.path.join(HERE, 'out', 'r100', 'r100.json')))
    ev40 = json.load(open(os.path.join(OUT_S40, 'evento.json')))
    ev03 = json.load(open(os.path.join(HERE, 'out', 'evento_s03', 'evento.json')))
    esl25 = dict(indice=0x25, id='0x12 (em12 = ganado de r100, mismo modelo que el de la casa)', tipo=0, set='0x1B',
                 flag='0x00000024 (sin arma, no zurdo)', hp=1000, pos_m=[-83.95, 0.83, -32.96], rot_y_rad=0.001,
                 archivo='etc/emleon00.esl (lista 0 = "1st-1", entrada 0x25 cuarto 0x100)')
    ventana_leon = [round(x, 4) for x in (LEON_VENTANA_POS[0] * MM, LEON_VENTANA_POS[1] * MM, LEON_VENTANA_POS[2] * MM)]
    cortes40 = [dict(corte=c['indice'], inicio=c['inicio'], frames=c['frames'],
                     visibles=[m['nombre'] for m in ev40['modelos'] if m['cortes'][c['indice']]['visible']])
                for c in ev40['cortes']]
    doc = {
        'titulo': 'r100: el comienzo real del juego hasta la pelea en la casa (RE4 GameCube USA)',
        'unidades': 'metros (mm del juego * 0.001), coordenadas del cuarto r100 (Y arriba); angulos en radianes; '
                    'rot_y = ang.y del juego: el modelo mira a (sin a, 0, cos a) (RotMatrix Rz*Ry*Rx, igual que glTF '
                    'con el modelo mirando a +Z); frames de 30 fps',
        'fuentes': ['../re4/src/st1/r120.cpp (R120Init / R120Event / Evt_R120S00_Func / Evt_R120S01_Func / EventCarInit)',
                    '../re4/src/st1/r100.cpp (R100Init, r100_StartEvent, r100_HouseEvent, r100_Sce_look, r100_DoorCk, '
                    'r100_StreanChk, r100_evtName, readEvent, Evt_R100S40_Func)',
                    '../re4/src/game/cam_ctrl.cpp (CutCall, HermiteExport), cam_motion.cpp, emdoor.cpp (setOpenLock), '
                    'em10/em10.cpp (set 0x1B -> em10_R1_R100TurnWalk), snd.cpp (SndBgmTblSet, SndRoomBgmStart, '
                    'SndRoomStrStart, SndEventInit/End), snd_str*.cpp (loops), sscrn.cpp (OpeSetOpenTerm), obj.cpp / '
                    'trans.cpp (STA_SUSPEND)'],
        'correccion_importante': {
            'r100s00_no_es_la_intro': 'r100s00.evd NO lo carga ningun codigo: no esta en r100_evtName (st1/r100.cpp) ni '
                                      'en ningun EvtReadExec. Es un evento suelto de 1 corte / 89 frames (2.97 s): la '
                                      'camara recorre el interior de la casa desde la ventana hasta el aldeano em1000 '
                                      'agachado frente al fuego (sin audio). Render: out/r100_intro/control/r100s00_sin_uso_*.png; no se exporta '
                                      '(se puede con los extractores: --evd r100s00.evd --solo ganado).',
            'la_intro_de_r100_es_r100s40': 'r100_StartEvent hace readEvent(9) y r100_evtName[9] = "evd/r100s40.evd": la '
                                           'camioneta llega por el camino con Leon atras y los dos policias adelante, '
                                           'charlan, Leon se baja y se aleja (8 cortes, 1175 frames = 39.17 s). Los '
                                           'comentarios de la decompilacion dicen "s40: the ravine" pero la tabla manda: '
                                           'el barranco es s30 (readEvent(4) en r100_GakeEvent).',
            'tabla_r100_evtName': {'0': 'r100s03 (casa)', '1': 'r100s01 (no esta en el disco)',
                                   '2': 'r100s02 (no esta en el disco)', '3': 'r100s20 (el camion tira el coche al barranco)',
                                   '4': 'r100s30 (mirada al barranco)', '5': 'r100s41 (charla policia pl0700a)',
                                   '6': 'r100s42 (no esta en el disco)', '7': 'r100s43 (charla policia pl0700)',
                                   '8': 'r100s44 (los policias en el puente)', '9': 'r100s40 (la llegada = intro)'},
            'antes_de_r100': 'El juego nuevo NO arranca en r100 sino en r120 (st1/r120.cpp, otro cuarto: St1/r120.das, '
                             'no extraido): R120Event pasa la pelicula movie/opening.sfd (Sofdec, FMV pre-renderizada), '
                             'despues el evento r120s00 (el viaje: Leon atras, los policias adelante, espejo retrovisor '
                             'por render-to-texture; 9 cortes, 1970 f = 65.7 s, stream bio4evt #30) y r120s01 (la '
                             'camioneta para en el camino, charla, un policia baja; 15 cortes, 2360 f = 78.7 s, stream '
                             '#31) y salta a r100 (SceAtExecRoomJump(0x100, (-109.45, -0.515, 0.82))). r120s00 no se '
                             'repite si Scenario_flg[1] & 0x10; si se saltea (FuncType 3) se prende SCF_R120_EVENT_CANCEL y '
                             'tampoco se ven r120s01 ni r100s40. Esos dos eventos necesitan el mapa r120: quedan fuera.'},
        'secuencia': [
            {'paso': 1, 'que': 'R100Init (una vez al entrar al cuarto)',
             'detalle': [
                 'Room_flg bit 10 (policias muertos), 3 (s03 visto) y 13 (intro vista) apagados en un juego nuevo '
                 '(JumpPoint 1 / DebugTrg(1) los prende y saltea todo).',
                 'Pre-carga los eventos 5, 7, 8, 9 (s41, s43, s44, s40).',
                 'El ganado de la casa: EmSetEvent(id 0x12, type 0, set 0x13, flag 0x21000020 (hacha + zurdo), hp 500) en '
                 '(-77.63, 0.86, -36.50) m (EmListData.pos s16 x 10 mm), rot Y 0x2000 = pi/2. '
                 'set 0x13 -> em10_R1_Hide: INVISIBLE e inactivo hasta que r100_Sce_look le pone flag bit 0 despues de s03 '
                 '(no esta en la ventana ni se ve antes de s03).',
                 'La camioneta de juego (ROOM_ARC 0x1D/0x1E, obm2a00) en (-102.497, -0.687, 1.953) rot Y 0.8123, '
                 'pList[10].ang.x = 0.4363 (la inclinacion del volante), partes 11/13/15 escala 0 -> '
                 'out/r100_intro/coche_juego.glb.',
                 'El camion viejo (W->carSub, ROOM_ARC 0x1F/0x20) en (-60.821, -0.055, -17.23) rot Y -1.501 -> '
                 'out/r100_intro/camion_juego.glb (NO esta en r100.glb: es un objeto aparte).',
                 'Los dos policias SENTADOS en la camioneta: cuerpo ROOM_ARC 0x24 / 0x26 + cabeza 0x27 / 0x29, en el lugar '
                 'de la camioneta, motion quieto 0x2B / 0x2C en loop (flags 5) -> policia_juego.glb / policia_a_juego.glb '
                 '(clips "quieto" 60 f, "hablar" 160 f).',
                 'Tareas: r100_WindowBreakCk (ventanas sin rejas hasta bit 10), r100_DoorCk (la puerta), r100_StreanChk '
                 '(llamado de la aldea), y las areas AEV de abajo.',
                 'Como Room_flg bit 13 esta apagado: lo prende y lanza r100_StartEvent.'],
             'objetos_en_eventos': 'Durante un evento (STA_SUSPEND) los objetos sin setNoSuspend(1) NO se mueven NI se '
                                   'dibujan (obj.cpp objMove, trans.cpp): en r100s40 la camioneta / policias / camion de '
                                   'juego no se ven (el evento trae los suyos); en s41 / s43 el juego les pone NoSuspend y '
                                   'si se ven.'},
            {'paso': 2, 'que': 'r100_StartEvent -> evento r100s40 (la llegada)',
             'condicion': 'se saltea si System_flg SYS_START_EVT_SKIP o SCF_R120_EVENT_CANCEL (intro cancelada en r120)',
             'evento': 'out/evento_s40/evento.json', 'frames': ev40['frames_totales'], 'segundos': ev40['duracion_s'],
             'fundido': 'FadeSetW(0x80000002, 30) un frame despues de arrancar: fundido DESDE NEGRO de 30 frames '
                        '(0x80000002 = entrar, 2 = salir a negro). Al final no hay fundido: corte directo al juego.',
             'cortes': cortes40,
             'audio': 'stream bio4evt #15 desde el frame 0 (voces + musica + efectos pre-mezclados): '
                      'out/evento_s40/audio/str1_015.wav, 41.53 s: sigue ~2.33 s despues del final del evento (el evento '
                      'solo lo corta si se cancela: Event::RunEvtCancel -> EvtSndStrStop). snd_flag 0 -> SndEventInit: los '
                      'SE del cuarto se apagan (fade 400) y la BGM se baja; SndEventEnd los devuelve.',
             'subtitulos': 'USA (language 1) no muestra los mensajes del evento (Event::MesSet): el dialogo esta en el audio.',
             'funcion': ev40['funcion_evento']['descripcion']},
            {'paso': 3, 'que': 'fin de r100_StartEvent',
             'leon': dict(pos_m=[round(c * MM, 4) for c in LEON_INICIO_POS], rot_y_rad=LEON_INICIO_ROT_Y,
                          mira_a=[round(math.sin(LEON_INICIO_ROT_Y), 4), 0.0, round(math.cos(LEON_INICIO_ROT_Y), 4)],
                          nota='pPL->setPos(-99685, -484, -1343) / setAng(0, 2.246, 0): Leon queda al lado de la '
                               'camioneta mirando al camino que sube a la casa (render control/juego_inicio_detras.png)'),
             'radio': dict(que='OpeSetOpenTerm(0) (si no se salteo): LLAMADA DE RADIO a Hunnigan antes de jugar',
                           detalle='Leon saca la radio: motion pl00 PL_ARC 0x79 (71 frames, flags 0x201) -> clip "radio" '
                                   'en out/r100_intro/leon_radio.glb (misma malla y esqueleto que out/combate/'
                                   'leon_combate.glb); la radio (pl00 PL_ARC 0x77/0x78) colgada de hueso_016 (mano '
                                   'izquierda) -> out/r100_intro/radio.glb (vertices ya en el espacio de hueso_016); '
                                   'setLeftHand(2) = mano izquierda pl00 PL_ARC 0x16 (entrada 18) mientras dura; stream '
                                   'bio4evt #3 (el tono de la radio, 4.07 s) -> audio/str1_003.wav; despues la pantalla '
                                   'de la terminal (SS_OPEN_TERM, Sscrn/ss_term.cpp: Hunnigan y Leon en 3D con la '
                                   'secuencia op/op01.das #0) - NO extraida. El boton de saltear la cancela. Al terminar '
                                   'vuelve la mano / posicion.',
                           audio=rad.get('audio'), frames_motion=rad.get('radio_frames')),
             'ambiente': 'SeAtSetOnOff(2, 1): vuelven los sonidos de ambiente del area SE 2 (apagados en R100Init)',
             'bgm': 'SndBgmTblSet(0x100, 1) + SndRoomBgmStart(0, 0) + SndRoomBgmStart(1, 0): arranca la BGM SECUENCIADA '
                    'del cuarto (ver "musica")'},
            {'paso': 4, 'que': 'juego libre por el camino (antes de la casa)',
             'opcionales': [
                 {'area': aev(info, 0x19), 'evento': 'r100s41 (out/evento_s41): charla con el policia pl0700a (160 f, '
                                                     'stream #16); r100_MesCar00; solo antes de bit 10'},
                 {'area': aev(info, 0x1A), 'evento': 'r100s43 (out/evento_s43): charla con el policia pl0700 (110 f, '
                                                     'stream #18); r100_MesCar01'},
                 {'area': aev(info, 0x1B), 'evento': 'r100s44 (out/evento_s44): los policias en el puente (150 f, stream '
                                                     '#19); r100_EventBrige pone a Leon en (-112.251, -0.193, -4.42)'},
                 {'area': aev(info, 0xC), 'que': 'mensaje 0xC del camion que tapa el camino (r100_MesTruck)'},
                 {'boton_A_cerca_del_coche': 'R100Main: con STA_PL_DONT_FIRE y A: un policia habla (motion 0x35 pl0700 + '
                                             'SE 6 si Room_flg[2] bit 30, si no 0x36 pl0700a + SE 5) + mensaje 0x33; al '
                                             'terminar la motion vuelven a quieto (hokan 10)',
                  'audio': ['audio/se_policia_hablar.wav', 'audio/se_policia_a_hablar.wav']}],
             'eventos_de_s41_s43': 'al terminar un evento sin EvtStfPlPosNoSet el juego reubica a Leon con la parte 0 '
                                   'del modelo de jugador del evento (event.cpp: GetZeroPartsWorldPos(PPl)); r100.cpp no '
                                   'lo mueve despues de s41 / s43',
             'llamado_de_la_aldea': 'r100_StreanChk: SndCall(6, 0) en (-78.589, 0.86, -36.7) (la casa) la primera vez a '
                                    'los 60 + Rnd(45) frames y despues cada 180 + 5 * Rnd(30), solo mientras Room_flg[2] bit 31 '
                                    '(lo prende codigo fuera de r100.cpp; no se verifico cuando) y hasta s03 -> '
                                    'audio/se_aldea_llamado.wav'},
            {'paso': 5, 'que': 'LA ESCENA DE LA VENTANA (r100_HouseEvent)', 'es_un_evd': False,
             'que_es': 'una escena de guion con la CAMARA DEL CUARTO: CamCtrl.CutCall(0xA) = el corte de camara 0xA de '
                       'la camara del cuarto (entrada CAM "B404" de St1/r100.das), tipo 6 = CameraMotion hecha por '
                       'HermiteExport con 2 llaves. Es el punto de vista del aldeano espiando por la rendija de los '
                       'postigos de la ventana del frente de la casa: se ve a Leon (chico) caminando por el camino '
                       'hacia la casa (renders control/ventana_*.png).',
             'disparo': dict(area=aev(info, 0x15), una_vez='Room_flg bit 15 (y SceAtSetEnable(0x15, 0))'),
             'al_empezar': ['SceEventStart(0); STA_CAMERA_SET_ROOM',
                            'W->emHouse = EmSetFromList2(0x25): un ganado NUEVO de la lista, NoSuspend, be_flag 0x1000',
                            'W->carSub (el camion) NoSuspend',
                            f'Leon a {ventana_leon} rot Y {LEON_VENTANA_ROT_Y} (setPos / setAng), SpfFlagOff(SPF_PL), '
                            'DpfFlagOff(DPF_PL) (se ve y se mueve), NoSuspend',
                            'pPL->motionSet(ROOM_ARC 0x34, hokan 10, frame 0, attr 1): camina hacia la casa con la '
                            'raiz de la motion (5.65 m adelante y 0.23 m al costado en 170 f)',
                            'SndStrReq(1, 0x22, 0x80000003): stream bio4evt #34 (5.53 s, estereo 32 kHz, volumen RIT 90) '
                            '-> out/r100_intro/audio/str1_034.wav',
                            'CamCtrl.CutCall(0xA)'],
             'duracion': f'{len(cam_doc["ojo"])} frames ({len(cam_doc["ojo"]) / 30:.2f} s): mientras !IsMotionEnd; la '
                         'camara evalua los frames 0..151 (maxFrame = ultima llave 150 + 1) y termina',
             'camara': dict(archivo='out/r100_intro/camara_ventana.json (ojo / objetivo / arriba / fov por frame)',
                            llaves=cam_doc['llaves'], fov_grados=25.0, roll=0.0, proyeccion='4:3 (C_MTXPerspective)',
                            nota='llave 0 en el frame 0: ojo (-82.853, 2.418, -32.512) -> objetivo (-81.239, 1.668, '
                                 '-20.276); llave 1 en el frame 150: ojo (-82.938, 2.457, -33.150) -> objetivo (-81.138, '
                                 '1.668, -20.289): un leve travelling hacia atras (64 cm) casi sin girar. Tangentes de '
                                 'HermiteExport: la primera 0 y la ultima = v1 - v0 (ease-in).'),
             'leon': dict(glb=h_leon['glb'], clip='ventana', frames=mot_leon.n_frames,
                          nota='Leon_ev (mismo esqueleto / mallas que out/evento_s03/leon_evento.glb), raiz en el MUNDO '
                               '(armadura en el origen). El juego usa el modelo de JUEGO de Leon: aca va con el del '
                               'evento para reusar la armadura Leon_ev. Se ve a traves de la rendija entre los frames 0 '
                               'y 151.'),
             'aldeano': dict(lista=esl25, rutina='set 0x1B -> em10_R1_R100TurnWalk (R1 0x05): 90 frames quieto (motion '
                                                 'em12 ARC 5, flag 5 loop, frame inicial al azar), despues gira 180 (ARC 0x18 '
                                                 '+ seq 0x19, flag 1) y camina (em10SetWalkMotion 7)',
                             visible='NO: esta 0.45 m DETRAS del plano de la camara y 1.1 m a su izquierda (la camara es su '
                                     'punto de vista); con fov 25 nunca entra en cuadro. No hace falta exportarlo.',
                             al_final='EmMgr.destroy(W->emHouse): desaparece'),
             'al_terminar': 'r100_HouseEvent_exit: Leon NoSuspend(0), destroy del aldeano, STA_CAMERA_SET_ROOM off, '
                            'CamCtrl.Comeback(0) (vuelve la camara de juego), SceEventEnd. Leon sigue donde lo dejo la '
                            'raiz de la motion (~(-80.0, -0.01, -17.1) en el frame 151). Se puede cancelar (SceSetEventCancel).'},
            {'paso': 6, 'que': 'r100s03 (ya hecho en la demo)',
             'disparo': dict(area=aev(info, 0xA), una_vez='Room_flg bit 3; r100_Sce_look'),
             'evento': 'out/evento_s03/evento.json', 'frames': ev03['frames_totales'],
             'despues': ev03['despues_del_evento']},
            {'paso': 7, 'que': 'la pelea', 'musica': 'el stream del cuarto sigue en loop (ver "musica") hasta que el '
                                                      'ganado muere: r100_Sce_zombi_dead -> SndRoomStrStop(0) (corte seco) '
                                                      'y evento r100s20'}],
        'leon_inicio': dict(pos_m=[round(c * MM, 4) for c in LEON_INICIO_POS], rot_y_rad=LEON_INICIO_ROT_Y,
                            fuente='st1/r100.cpp r100_StartEvent', nota='r120 lo habia dejado en (-109.45, -0.515, 0.82) '
                                                                         'pero StartEvent lo pisa'),
        'puerta_de_la_casa': {
            'objeto': 'ETS 2 = id 0x0D (et0d00), r100_puerta en r100.glb: bisagra en (-77.0438, 0.8696, -30.3209), hoja '
                      'de 1.3 m hacia -X local, base_dir (rot Y del ETS) = 0',
            'estado_inicial': 'ABIERTA y TRABADA: r100_DoorCk llama door->setOpenLock(0) TODOS los frames mientras Room_flg '
                              'bit 3 == 0 (antes de s03) y sigue igual despues de s03 hasta que la emboscada encuentra a '
                              'Leon (despues de s20). emDoor_R1_OpenLock con r_no_3 = 0: Open_flag 0, ang.y = base_dir + '
                              'pi/2 = +1.5708 rad al instante (sin animacion); flag |= 0x30000000.',
            'rot_y_rad': 1.5708,
            'hacia_donde': 'con RotMatrix (x\' = cos a x + sin a z, z\' = -sin a x + cos a z) la hoja (-1.3, 0, 0) va a '
                           '(0, 0, +1.3): se abre hacia AFUERA (+Z, el porche; la casa esta en -Z). Es el lado al que se '
                           'abre cuando la empujan desde ADENTRO (emDoor R1_Open: Open_flag 0 si quien abre esta detras). '
                           'La demo hoy usa -95 grados (hacia adentro). Renders: control/puerta_juego_+90.png vs '
                           'puerta_demo_-95.png.',
            'despues': 'setCloseLock mientras Room_flg bit 4 == 0 (emboscada) y setNormal al final (fuera del alcance)'},
        'musica': {
            'antes_de_s03': 'BGM SECUENCIADA (no es un stream): SndBgmTblSet(0x100, 1) -> room_bgm_tbl[0] = 0x0000C000 '
                            '(bgmtbl.dat, cuarto 0x100 tabla 1): slot 0 = 0xC000 (bit 15 hay BGM, bit 14 auto, secuencia '
                            '(b >> 8) & 3 = 0, archivo (u8) b = 0 -> bgm/bio4midi.dat entrada 0 (bio4midi.hed: offset 0, '
                            '0x69000 bytes: banco de instrumentos + secuencia, bloque de sonido 3 = BGM0); slot 1 vacio. '
                            'SndRoomBgmStart(0) -> SndCall(3, 0): la toca el secuenciador del juego (snd_seq*.cpp) en '
                            'loop. NO se puede sacar como WAV sin escribir un sintetizador de ese formato: queda pendiente.',
            'durante_eventos': 'SndEventInit (s40, s03) la baja a volumen 1 en 2 s y SndEventEnd la devuelve en 1 s. '
                               'r100_mes_gaikotu_bgm_down / up (areas 0x22 / 0x23 adentro de la casa) bajan / suben el '
                               'stream del cuarto.',
            'stream_del_cuarto': dict(
                que='bgm/bio4bgm.sbb, RIT 2 -> SHD 1 (room_str_tbl[0] = 0x8002, sin bit 0x4000 de auto-arranque)',
                arranca='en r100s03 corte 14 frame 0 (frame global 1181): paquete Str bloque 0 -> SndRoomStrStart(1, 0, 1), '
                        'sin fundido, en LOOP',
                para='r100_Sce_zombi_dead (el ganado muere): SndRoomStrStop(0) = corte inmediato',
                wav='out/evento_s03/audio/str0_002.wav (51.708 s, 32 kHz estereo, con chunk smpl del loop)',
                **{k: v for k, v in aud['musica_cuarto'].items() if k.startswith('loop') or k.endswith('wav')},
                volumen_rit=70, nota=aud['musica_cuarto']['nota'])},
        'escena_ventana_resumen': 'NO es un .evd: camara del cuarto (corte 0xA) + motion de Leon (ROOM_ARC 0x34) + stream '
                                  '#34, 152 frames; ver secuencia paso 5 y camara_ventana.json',
        'archivos': {
            'evento_s40': ['out/evento_s40/evento.json', 'out/evento_s40/audio/str1_015.wav (+_n95)',
                           'out/evento_s40/leon_evento.glb (+_mitad) clips s40_c00..c07 (esqueleto / mallas / atlas = los '
                           'de out/evento_s03/leon_evento.glb)',
                           'out/evento_s40/policia_evento.glb (pl0700, cara con 23 shapes) clips s40_c00, 01, 02, 04, 06',
                           'out/evento_s40/policia_a_evento.glb (pl0700a, cara 23 shapes + gafas) clips s40_c00, 01, 02, '
                           '04, 06, 07',
                           'out/evento_s40/obm1a00.glb (la camioneta + vidrios obm3000a..f) clips s40_c00..c07',
                           'out/evento_s40/caras.json (pesos de Leon_ev_cara, Policia_ev_cara, PoliciaA_ev_cara por frame)'],
            'r100_intro': ['out/r100_intro/plan.json', 'out/r100_intro/camara_ventana.json',
                           'out/r100_intro/leon_evento.glb (clip ventana)', 'out/r100_intro/coche_juego.glb',
                           'out/r100_intro/camion_juego.glb', 'out/r100_intro/policia_juego.glb',
                           'out/r100_intro/policia_a_juego.glb', 'out/r100_intro/leon_radio.glb', 'out/r100_intro/radio.glb',
                           'out/r100_intro/audio/*.wav', 'out/r100_intro/verificacion.json', 'out/r100_intro/control/*.png'],
            'opcionales': ['out/evento_s41', 'out/evento_s43', 'out/evento_s44 (evento.json, audio, glb, caras.json)']},
        'comandos': ['python3 re4_extract_evento.py --evento r100s40 --out out/evento_s40',
                     'python3 re4_extract_personajes_evento.py --evd r100s40.evd --out out/evento_s40 --malla-de r100s03.evd',
                     'python3 re4_extract_intro_r100.py',
                     'python3 re4_extract_evento.py --evento r100s41 --out out/evento_s41 (idem s43, s44)',
                     'python3 re4_extract_personajes_evento.py --evd r100s41.evd --out out/evento_s41 --malla-de '
                     'r100s03.evd --bins-cuarto (idem s43, s44)',
                     'python3 tools_r100/verificar_intro.py',
                     'blender -b --python tools_r100/render_blender.py -- spec.json (renders de control)'],
        'objetos_de_juego': juego,
        'camioneta_evento': coche40,
    }
    with open(os.path.join(OUT, 'plan.json'), 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False, default=str)
    print('-> out/r100_intro/plan.json')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=L.DEFAULT_DISC)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    arc = L.Archivos(args.disc)
    disco = EV.Disco(args.disc)
    room = archive.Archive(os.path.join(HERE, 'extracted', 'St1', 'r100.das'))
    ev40 = E.Evento(E.resolver_evd('r100s40.evd', args.disc))
    ev03 = E.Evento(E.resolver_evd('r100s03.evd', args.disc))

    # ---- camara de la ventana ----
    cam = cortes_camara(arc_room(room, 4).data)
    c = cam[CAM_VENTANA]
    if c['tipo'] != 6:
        raise SystemExit(f'corte de camara {CAM_VENTANA:#x}: tipo {c["tipo"]} (se esperaba 6 = CameraMotion)')
    frames = camara_motion(c)
    cam_doc = dict(
        fuente='St1/r100.das entrada CAM (B404), corte de camara 0xA (CamCtrl.CutCall(0xA) en st1/r100.cpp '
               'r100_HouseEvent); tipo 6 = CameraMotion armada por HermiteExport',
        llaves=dict(frames=c['frames'], ojo_m=[EV.r3([v * MM for v in p]) for p in c['pos']],
                    objetivo_m=[EV.r3([v * MM for v in p]) for p in c['at']], roll_rad=c['roll'], fov_grados=c['fovy']),
        frames=len(frames['ojo']), fps=30, proyeccion='C_MTXPerspective(fov, 4/3); fov = vertical de la imagen completa',
        nota='frame f = f-esimo frame de la escena (el mismo frame en que CutCall arranca es el 0). El ultimo frame repite '
             'la ultima llave (CameraSequenceCtrl termina cuando frame >= maxFrame = ultima llave + 1).',
        **frames)
    with open(os.path.join(OUT, 'camara_ventana.json'), 'w') as f:
        json.dump(cam_doc, f, indent=1)
    print(f'camara ventana: {len(frames["ojo"])} frames, ojo {frames["ojo"][0]} -> {frames["ojo"][-1]}, '
          f'fov {frames["fov_grados"][0]}')

    # ---- Leon de la ventana ----
    h_leon, mot_leon = leon_ventana(ev03, arc, room)

    # ---- la camioneta del evento s40 ----
    coche40 = coche_evento(ev40, arc)

    # ---- objetos de juego ----
    juego = objetos_juego(room)

    # ---- audio ----
    aud = audio(disco)

    # ---- la radio ----
    rad = radio(arc, disco)

    plan(cam_doc, h_leon, mot_leon, coche40, juego, aud, rad)
    json.dump(dict(camara=cam_doc['frames'], leon=h_leon['glb'], coche_s40=coche40, juego=juego, audio=aud, radio=rad),
              open(os.path.join(OUT, '_resultado.json'), 'w'), indent=1, default=str)
    print('-> out/r100_intro/_resultado.json')


if __name__ == '__main__':
    main()
