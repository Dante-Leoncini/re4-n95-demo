#!/usr/bin/env python3
"""
LO QUE PASA EN r100 DESPUES DE MATAR AL GANADO DE LA CASA (RE4 GameCube USA) -> Whisk3D:
el evento r100s20 (el camion viejo baja rodando por el camino y tira la camioneta de la policia al barranco) y la
EMBOSCADA (los aldeanos de la lista de enemigos que rodean la casa), hasta que el camino queda libre.

  out/evento_s20/obm2d00.glb            el camion (obm2d00 = MISMO .bin que W->carSub = out/r100_intro/camion_juego.glb,
                                         mismo esqueleto / nombres: los clips se pueden unir con tools_r100/unir_clips.py)
                                         clips "juego" (estacionado), s20_c00, s20_c02 (raiz en el MUNDO) y "barranco"
                                         (donde lo deja r100_Car_pos_move)
  out/r100_emboscada/coche_barranco.glb la camioneta de la policia en el fondo del barranco (r100_Car_pos_move: partes
                                         11..14 y 16 escondidas, 15 visible), clip "barranco" (1 frame, raiz en el mundo)
  out/r100_emboscada/ganado_eNN.glb     un aldeano de juego por entrada NN (hex) de la lista etc/emleon00.esl que usa el
                                         cuarto despues de la casa (r100_em_set + r100_trap_set): cuerpo / cabeza / manos
                                         del modelo (type) de em12.drs, el arma rigida en la mano, el sombrero rigido en la
                                         cabeza, texturas a resolucion completa; clips de JUEGO EN EL LUGAR (como
                                         out/ganado_juego/ganado_juego_lugar.glb: mismos nombres de huesos / jerarquia)
  out/r100_emboscada/clips_eNN.json     por clip: motion / seq, espejo, frames, loop, raiz.pista_x_z_rotY, frames clave...
  out/r100_emboscada/plan.json          la secuencia completa (se genera con --plan, datos de la decompilacion)
  out/r100_emboscada/ia_emboscada.json  diferencias de IA de cada aldeano de la emboscada (idem)

Uso:
  python3 re4_extract_emboscada_r100.py                 # todo
  python3 re4_extract_emboscada_r100.py --solo vehiculos
  python3 re4_extract_emboscada_r100.py --solo ganados [--entradas 3,4,5]
  python3 re4_extract_emboscada_r100.py --solo plan

Fuentes (../re4/src): st1/r100.cpp (r100_Sce_zombi_dead, r100_em_set, r100_trap_set, r100_Car_pos_move,
Evt_R100S20_Func, r100_DoorCk, r100_WindowBreakCk, r100_StreanChk), game/em_set.cpp (EmSetFromList2 / EM_SET_WORK),
em12/em12_set.cpp (Em12Set / Em12WeaponSet: modelos por type), em10/em10.cpp (em10ModelInit, em10HeadSet,
em10HandSet, em10WeaponInit, em10WeaponSet, em10SetAccesory, em10SetWaitMotion / WalkMotion / DashMotion, rutinas).
"""
import argparse
import json
import math
import os
import sys
import types

import numpy as np

import re4_extract_leon as L
import re4_evento as E
import re4_extract_ganado as G
import re4_extract_personajes_evento as P
import re4_extract_ganado_juego as GJ
import re4_extract_intro_r100 as IR
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf, evalhost  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'r100_emboscada')
OUT_S20 = os.path.join(HERE, 'out', 'evento_s20')
ESL = os.path.join(HERE, 'extracted', 'etc', 'emleon00.esl')
MM = 0.001
FPS = 30.0
ARCHIVO = 'em12'

# ---- st1/r100.cpp r100_Car_pos_move (mm / rad) ----
COCHE_BARRANCO = ((-120225.0, -14319.0, -2131.0), (-0.159366012, 0.893207133, 3.46660805))
CAMION_BARRANCO = ((-120022.0, -14319.2725, 5740.0), (5.04974413, 0.090861842, -1.1017915))

# ---- em12/em12_set.cpp Em12Set: PL_ARC por type (mot[1] cuerpo, mot[0] tpl del cuerpo / cabeza / manos,
#      mot[2] cabeza (mot[5] = su tpl = mot[0]), voz Em10SetSeTbl) ----
TIPOS = {
    0: dict(cuerpo=0x1BC, tpl=0x1BD, cabeza=0x1BE, voz=0, que='aldeano (hombre), voz 0'),
    1: dict(cuerpo=0x1D8, tpl=0x1D9, cabeza=0x1DA, voz=1, que='aldeano (cuerpo type 1), juego de voces 1 (Em10SetSeTbl)'),
    3: dict(cuerpo=0x1DC, tpl=0x1DD, cabeza=0x1DE, voz=2, que='aldeano (otro cuerpo), voz 2'),
    4: dict(cuerpo=0x1E0, tpl=0x1E1, cabeza=0x1E2, voz=3, que='aldeano (otro cuerpo), voz 3'),
}
# manos mot[6..15] (em10HandSet): 6 der. relajada, 7 der. abierta, 8 der. senalando, 9 der. agarre, 10 der. guadana,
# 11 izq. relajada, 12 izq. abierta, 13 izq. senalando, 14 / 15 izq. agarre
MANO = {6: 0x1C0, 7: 0x1C1, 8: 0x1C2, 9: 0x1C3, 10: 0x1C4, 11: 0x1C5, 12: 0x1C6, 13: 0x1C7, 14: 0x1C8}
# armas (Em12WeaponSet mot[41..66] = ARC 0x254..0x26D; em10WeaponInit / em10MakeWeapon / em10WeaponSet)
ARMAS = {
    1: dict(nombre='horca', bin=0x254, tpl=0x255, bit=0x80000000, pos=(-843.58, 5.81, 866.87), ang=(0.0, -0.7166758, 0.0),
            que='horca (el modulo la llama hoe / suki; el modelo ARC 0x254 es una horca de 3 puntas; Wep_type 1: flag bit31, mot[41]/[42])'),
    2: dict(nombre='hacha', bin=0x26C, tpl=0x26D, bit=0x20000000, pos=(-313.85, -21.2, 102.21), ang=(0.0, -1.0402162, 0.0),
            que='hacha (hatchet, Wep_type 2: flag bit29, mot[65]/[66])'),
    3: dict(nombre='hoz', bin=0x26A, tpl=0x26B, bit=0x08000000, pos=(-313.85, -21.2, 102.21), ang=(0.0, -1.0402162, 0.0),
            que='hoz (sickle, Wep_type 3: flag bit27, mot[63]/[64])'),
}
# accesorios cObj12 colgados de la parte 4 (la cabeza) (em10SetAccesory, types 0/1/3/4; solo el primero: !pCap)
ACCESORIOS = [
    (0x00800000, 0x25F, 0x260, (0.0, 125.7, 20.0), 1),
    (0x00080000, 0x25F, 0x261, (0.0, 125.7, 20.0), 2),
    (0x00400000, 0x262, 0x263, (0.0, 5.0, 0.0), 3),
    (0x00040000, 0x262, 0x264, (0.0, 5.0, 0.0), 4),
]
ZURDO = 0x01000000

# entradas de etc/emleon00.esl que usa r100 despues de la casa
EMBOSCADA = [3, 4, 5, 0x12, 0x13, 0x26, 0x27]          # r100_em_set (W->ems[0..6])
TRAMPAS_GANADOS = [6, 7, 8]                             # r100_trap_set (con pG->game_cnt == 0, motions de evento)
EVT_MOT_CUARTO = {6: 0x2E, 7: 0x2F, 8: 0x30}           # setEvtMotion(ROOM_ARC 0x2E / 0x2F / 0x30)
TRAMPAS_OTRAS = [9, 0xA, 0xB, 0xC, 0xD, 0xE, 0x1D, 0x7A]


# ---------------------------------------------------------------------------------------------------
#  la lista de enemigos (game/em_set.cpp EM_SET_WORK; include/global.h EmListData)
# ---------------------------------------------------------------------------------------------------
def leer_esl(ruta=ESL):
    import struct
    d = open(ruta, 'rb').read()
    out = {}
    for i in range(len(d) // 32):
        r = d[i * 32:i * 32 + 32]
        be, idn, ty, st, fl, hp, en, ch = struct.unpack('>BBBBIHBB', r[:12])
        pos = struct.unpack('>3h', r[12:18])
        rot = struct.unpack('>3h', r[18:24])
        room, gr = struct.unpack('>Hh', r[24:28])
        out[i] = dict(no=i, be_flag=be, id=idn, type=ty, set=st, flag=fl, hp=hp, Character=ch,
                      pos_mm=[p * 10 for p in pos], rot_raw=list(rot), room=room, Guard_r_raw=gr,
                      pos_m=[round(p * 10 * MM, 4) for p in pos],
                      rot_rad=[round(r_ * math.pi / 16384.0, 6) for r_ in rot],
                      Guard_r_m=gr * 1000 * MM)
    return out


def escala_emset(no):
    """em10_R0_Init: escala por emset_no & 0xF (7 -> 1.1; 0, 4, 9, 0xB -> 1.01 +- 0.01; el resto 1.03 +- 0.01)."""
    k = no & 0xF
    if k == 7:
        return dict(valor=1.1, rango=[1.1, 1.1])
    if k in (0, 4, 9, 0xB):
        return dict(valor=1.01, rango=[1.0, 1.02])
    return dict(valor=1.03, rango=[1.02, 1.04])


def variante(e):
    """Lo que arma em10ModelInit para la entrada e (types 0/1/3/4 del modulo em12)."""
    t = e['type'] if e['type'] in TIPOS else 0
    fl = e['flag']
    wep = 0
    # em10WeaponInit (Ganado 0, sin bit 0x2000): el orden de los if deja el ultimo que aplica
    if fl & 0x80000000:
        wep = 1
    if fl & 0x20000000 and not fl & 0x2000:
        wep = 2
    if fl & 0x08000000 and not fl & 0x2000:
        wep = 3
    zurdo = bool(fl & ZURDO) and wep in (1, 2, 3)
    # em10HandSet: con arma type = 3 (default): der mot[6] / izq mot[11]; zurdo -> izq mot[14], si no der mot[9];
    # horca (Wep 1): der mot[9] + izq mot[14]
    der, izq = 6, 11
    if wep:
        if zurdo:
            izq = 14
        else:
            der = 9
        if wep == 1:
            der, izq = 9, 14
    acc = None
    for bit, b, tp, pos, kind in ACCESORIOS:
        if fl & bit:
            acc = dict(bit=bit, bin=b, tpl=tp, pos=pos, kind=kind)
            break
    arma = None
    if wep:
        a = dict(ARMAS[wep])
        pos, ang = list(a['pos']), list(a['ang'])
        if zurdo:
            if wep == 1:
                pos[0], ang[1], ang[2] = -pos[0], -ang[1], -ang[2]
            else:
                pos[0], ang[2] = -pos[0], -ang[2] + 3.1415927
        a.update(pos=tuple(pos), ang=tuple(ang), hueso=0x10 if zurdo else 0xA, wep_type=wep)
        arma = a
    return dict(type=t, modelo=TIPOS[t], wep=wep, arma=arma, zurdo=zurdo, mano_der=der, mano_izq=izq, acc=acc,
                v=e['no'] % 5)


# ---------------------------------------------------------------------------------------------------
#  clips por variante (a partir de la lista del ganado de la casa, re4_extract_ganado_juego.CLIPS)
# ---------------------------------------------------------------------------------------------------
DEP_ZURDO = {'quieto', 'caminar_hacha', 'caminar', 'caminar_b', 'correr', 'retroceder_hacha', 'ataque_hacha',
             'soltar_hacha', 'golpe_cabeza', 'golpe_cabeza_b', 'golpe_cabeza_c'}
AGARRE = {'agarrar', 'agarrar_lado', 'agarrar_atras', 'estrangular', 'estrangular_suelta', 'estrangular_pateado'}
FREE_VENTANA = {4: 'IK off / sin choque (Be_flg 0x20000): pasa el marco'}
FREE_PUERTA = {1: 'golpe (em10SetDamageDoor 1: abre o sacude la puerta / rompe la ventana)',
               0x20: 'sacudida (SetShake de la ventana, setShock de la puerta)',
               4: 'si la puerta / ventana sigue en pie: segundo golpe (golpear_puerta_2)'}


def clips_variante(var):
    wep, z, v = var['wep'], var['zurdo'], var['v']
    out = []
    for c in GJ.CLIPS:
        nombre, hokan, mot, sq, esp, loop, bits, fuente, nota = c
        if nombre in DEP_ZURDO:
            esp = z
        if nombre in AGARRE and wep:
            continue            # r100: con arma no lo suelta mientras vive (cEm10::setWeaponFall) -> no agarra
        if nombre == 'quieto':
            if wep == 1:
                mot, fuente = 0x14A, 'em10SetWaitMotion (Wep_type 1 -> ARC 0x14A; arranque en frame al azar)'
            elif not wep:
                fuente = 'em10SetWaitMotion (sin arma -> ARC 5; arranque en frame al azar)'
        elif nombre == 'caminar_hacha':
            if not wep:
                continue
            nombre = 'caminar_arma'
            if wep == 1:
                mot, sq = 0x14B, 0x14C + v
                fuente = f'em10SetWalkMotion kind 4 (horca, siempre): ARC 0x14B + seq 0x14C + emset_no % 5 ({v})'
                nota = 'la caminata de la horca (con o sin jugador encontrado)'
            else:
                sq = 0xD9 + v
                fuente = f'em10SetWalkMotion kind 3 (arma y Be_flg 0x100 = jugador encontrado): ARC 0xD8 + seq 0xD9 + {v}'
                nota = 'la caminata de persecucion (ya encontro a Leon)'
        elif nombre in ('caminar', 'caminar_b'):
            if wep == 1:
                continue        # la horca camina siempre con kind 4
            sq = (9 if nombre == 'caminar' else 0xF) + v
            fuente = f'em10SetWalkMotion kind 0, Walk_type {0 if nombre == "caminar" else 1}: seq + emset_no % 5 ({v})'
        elif nombre == 'correr':
            if wep == 1:
                mot, sq = 0x151, 0x152 + v
                fuente = f'em10SetDashMotion (horca): ARC 0x151 + seq 0x152 + {v}'
            else:
                sq = 0xAF + v
                fuente = f'em10SetDashMotion: ARC 0xAE + seq 0xAF + emset_no % 5 ({v})'
        elif nombre == 'retroceder_hacha':
            nombre = 'retroceder'
            if wep == 1:
                mot, sq, fuente = 0x157, 0x158, 'em10_R1_Back EM10_BACK_MOT(0x157, 0x158) (horca)'
            elif not wep:
                mot, sq, fuente = 0x15, 0x14, 'em10_R1_Back EM10_BACK_MOT(0x15, 0x14) (sin arma)'
        elif nombre == 'ataque_hacha':
            if not wep:
                continue
            if wep == 1:
                for n2, m2, s2, cuando in (('ataque_horca', 0x15D, 0x15E, 'Leon entre 0.1 y 0.8 m mas abajo (sel 0)'),
                                           ('ataque_horca_alto', 0x15F, 0x160, 'Leon a menos de 0.1 m por debajo o mas '
                                                                               'alto (sel 1: el caso normal en terreno plano)'),
                                           ('ataque_horca_bajo', 0x161, 0x162, 'Leon mas de 0.8 m mas abajo (sel 2)')):
                    out.append((n2, 10, m2, s2, z, False, GJ.FREE_ATAQUE, 'em10_R1_SukiAtk: ' + cuando, 'golpe con la horca'))
                continue
            nombre = 'ataque'
            fuente = 'em10_R1_AxeAtk (ARC 0x80 / 0x81; flag 0x41 si zurdo) = hacha y hoz'
        elif nombre == 'soltar_hacha':
            if not wep:
                continue
            nombre = 'golpe_antebrazo_arma'
            fuente = ('em10_R1_Dm_Small tipo 2 (diestro) / 4 (zurdo): tiro al antebrazo de la mano del arma '
                      '(ARC 0x55 / 0x56; setWeaponFall no suelta el arma en r100 con hp > 0)')
        out.append((nombre, hokan, mot, sq, esp, loop, bits, fuente, nota))
    if wep == 1:
        out.append(('golpe_cuerpo_horca', 6, 0x159, 0x15A, z, False, GJ.FREE_DANO,
                    'em10_R1_Dm_Small tipos 0 / 1 / 3 con horca (DM_SMALL_WEP_MOT(0x159, 0x15A))', ''))
        out.append(('golpe_espalda_horca', 6, 0x15B, 0x15C, z, False, GJ.FREE_DANO,
                    'em10_R1_Dm_Small tipo 7 con horca (DM_SMALL_WEP_MOT(0x15B, 0x15C))', ''))
    out.append(('trepar_ventana', 10, 0x1F, 0x20, False, False, FREE_VENTANA,
                'em10_R1_ClimbOver (0x3C): pasa por la ventana rota (em10WindowCk2 == 1); ademas la rutina acerca '
                'em->pos al punto de destino 20 % por frame (Target_pos = 0.4 m detras del plano de la ventana)', ''))
    out.append(('golpear_puerta', 10, 0x79, 0x7A, z, False, FREE_PUERTA,
                'em10_R1_DoorAtk (0x3D) / em10_R1_WindowAtk (0x3F): golpea la puerta cerrada o la ventana entera', ''))
    out.append(('golpear_puerta_2', 10, 0x79, 0x7B, z, False, None,
                'em10_R1_DoorAtk / WindowAtk paso 2: el segundo golpe si sigue en pie', ''))
    return out


# ---------------------------------------------------------------------------------------------------
#  un aldeano de juego (glb + clips json)
# ---------------------------------------------------------------------------------------------------
def rigida(b, m, tex, pref, clave_de, rects, W, H, R, t, hueso, scale):
    """Malla rigida (arma / sombrero) skinneada 100 % a `hueso`: v' = R v + t (mm, espacio de reposo del modelo)."""
    pos, nrm, uv, idx, index = [], [], [], [], {}
    for part in m.parts:
        tris = part.triangles()
        if not tris:
            continue
        k = clave_de(tex, pref, part)
        for tri in tris:
            if len({v[0] for v in tri}) < 3:
                continue
            for v in tri:
                i = index.get((k, v))
                if i is None:
                    i = index[(k, v)] = len(pos)
                    pv = R @ np.array(m.position(v[0])) + t
                    pos.append(tuple(float(c) * scale for c in pv))
                    nrm.append(tuple(float(c) for c in gltf.normalize(list(R @ np.array(m.normal(v[1]))))))
                    uv.append(L.uv_atlas(m.texcoord(v[3]), rects[k], W, H))
                idx.append(i)
    jo = [(hueso, 0, 0, 0)] * len(pos)
    we = [(1.0, 0.0, 0.0, 0.0)] * len(pos)
    return pos, nrm, uv, idx, jo, we


def exportar_ganado(arc, em, room, e, args, ref_nodes):
    scale = MM
    var = variante(e)
    tp = var['modelo']
    nombre_base = f'ganado_e{e["no"]:02x}'
    skel = modelbin.parse(em.entry(tp['cuerpo'] - 4).data)
    skel.check_tree()
    n = skel.n_parts
    rest = L.rest_world(skel)
    tex_cuerpo = gxtex.parse_tpl(em.entry(tp['tpl'] - 4).data)
    pref_cuerpo = f'{ARCHIVO}_{tp["tpl"] - 4:03d}'
    piezas = [('cuerpo', tp['cuerpo']), ('cabeza', tp['cabeza']),
              ('mano_der', MANO[var['mano_der']]), ('mano_izq', MANO[var['mano_izq']])]
    fuentes = [(nom, meshbin.parse(em.entry(bn - 4).data), bn) for nom, bn in piezas]
    extra = []    # (nombre, malla, tex, pref, R, t, hueso, info)
    if var['arma']:
        a = var['arma']
        R = np.array(evalhost.Player(skel, fcv.parse(em.entry(5 - 4).data), ik=False).rot_matrix(list(a['ang']))
                     ).reshape(3, 4)[:, :3]
        t = np.array(a['pos']) + np.array(rest[a['hueso']])
        extra.append(('Ganado_arma', meshbin.parse(em.entry(a['bin'] - 4).data), gxtex.parse_tpl(em.entry(a['tpl'] - 4).data),
                      f'{ARCHIVO}_{a["tpl"] - 4:03d}', R, t, a['hueso'],
                      {'arma': a['nombre'], 'bin': f'{ARCHIVO}.drs ARC {a["bin"]:#x}', 'tpl': f'ARC {a["tpl"]:#x}',
                       'hueso': f'hueso_{a["hueso"]:03d}',
                       'local_mm': {'pos': a['pos'], 'ang_rad': a['ang'],
                                    'orden': 'RotMatrix (Rz*Ry*Rx) + traslacion, relativo al hueso (em10WeaponSet)'}}))
    if var['acc']:
        c = var['acc']
        t = np.array(c['pos']) + np.array(rest[4])
        extra.append(('Ganado_sombrero', meshbin.parse(em.entry(c['bin'] - 4).data),
                      gxtex.parse_tpl(em.entry(c['tpl'] - 4).data), f'{ARCHIVO}_{c["tpl"] - 4:03d}', np.eye(3), t, 4,
                      {'accesorio': f'cObj12 kind {c["kind"]} (flag {c["bit"]:#x})', 'bin': f'ARC {c["bin"]:#x}',
                       'tpl': f'ARC {c["tpl"]:#x}', 'hueso': 'hueso_004', 'local_mm': {'pos': c['pos']},
                       'fuente': 'em10SetAccesory EM10_ACC_OBJ12 -> SetObj12 + setParent(em, 4, 1)'}))

    imagenes = {}

    def clave_de(tex, tpn, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (tpn, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for _, m, _ in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex_cuerpo, pref_cuerpo, part)
    for _, m, tex, tpn, *_ in extra:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, tpn, part)
    atlas, rects = P.armar_atlas_completo(imagenes)
    H, W = atlas.shape[:2]
    os.makedirs(OUT, exist_ok=True)
    png = f'{nombre_base}_atlas.png'
    with open(os.path.join(OUT, png), 'wb') as f:
        f.write(gxtex.png(atlas))

    b = gltf.Builder()
    nodes = [{'name': 'ganado', 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': 'ganado_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    tex_pbr = {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
    materials = [{'name': 'Ganado_opaco', 'pbrMetallicRoughness': tex_pbr, 'extras': {'w3d_transparent': False}}]

    def material_transp(cutoff):
        nm = f'Ganado_transparente_{int(round(cutoff * 255)) - 1}'
        idx = next((i for i, mt in enumerate(materials) if mt['name'] == nm), None)
        if idx is None:
            idx = len(materials)
            materials.append({'name': nm, 'pbrMetallicRoughness': tex_pbr, 'alphaMode': 'MASK', 'alphaCutoff': cutoff,
                              'extras': {'w3d_transparent': True}})
        return idx
    meshes, mesh_nodes, piel = [], [], []
    info_mallas = []
    for nom, m, bn in fuentes:
        malla = f'Ganado_{nom}'
        prims, nv, nt, cutoff, _ = P.malla_pieza(b, m, tex_cuerpo, pref_cuerpo, clave_de, rects, W, H, scale, 0, None)
        for pr in prims:
            if pr['material'] is None:
                pr['material'] = material_transp(cutoff)
        mesh_nodes.append(len(nodes))
        nodes.append({'name': malla, 'mesh': len(meshes), 'skin': 0})
        meshes.append({'name': malla, 'primitives': prims,
                       'extras': {'re4': {'bin': f'{ARCHIVO}.drs ARC {bn:#x}', 'tpl': f'ARC {tp["tpl"]:#x}'}}})
        Pm = np.array([m.position(i) for i in range(len(m.vtx))])
        sk = [m.skin(i) + [(0, 0.0)] * (4 - len(m.skin(i))) for i in range(len(m.vtx))]
        piel.append((Pm, np.array([[j for j, _ in s] for s in sk]), np.array([[w for _, w in s] for s in sk])))
        info_mallas.append(dict(malla=malla, bin=f'ARC {bn:#x}', vertices=nv, triangulos=nt))
    for malla, m, tex, tpn, R, t, hueso, info in extra:
        pos, nrm, uv, idx, jo, we = rigida(b, m, tex, tpn, clave_de, rects, W, H, R, t, hueso, scale)
        prim = L.primitiva(b, pos, nrm, uv, idx, 0, 'opaco', jo, we)
        mesh_nodes.append(len(nodes))
        nodes.append({'name': malla, 'mesh': len(meshes), 'skin': 0})
        meshes.append({'name': malla, 'primitives': [prim], 'extras': {'re4': info}})
        piel.append((np.array([np.array(p_) / scale for p_ in pos]), np.array(jo), np.array(we)))
        info_mallas.append(dict(malla=malla, vertices=len(pos), triangulos=len(idx) // 3, rigida_en=f'hueso_{hueso:03d}'))
    pielx = GJ.Piel(piel, rest)

    # ---- clips ----
    lista = clips_variante(var)
    animations, info = [], []
    control = []
    evt = EVT_MOT_CUARTO.get(e['no'])
    for spec in lista + ([('escena_r100', 0, ('cuarto', evt), None, False, False, None,
                           f'em10_R1_R100Cliff (set {e["set"]}): setEvtMotion(ROOM_ARC {evt:#x}) (r100_trap_set)',
                           'r100.das ROOM_ARC; motion de evento del cuarto')] if evt else []):
        nombre, hokan, mot, sq, esp, loop, bits, fuente, nota = spec
        if isinstance(mot, tuple):
            ent = room.entry(mot[1] - 4)
            etq = f'r100.das ROOM_ARC {mot[1]:#x}'
        else:
            ent = em.entry(mot - 4)
            etq = f'{ARCHIVO}.drs:{mot - 4} (ARC {mot:#x})'
        if ent.tag != 'FCV':
            sys.exit(f'{nombre}: {etq} no es FCV')
        m = fcv.parse(ent.data)
        seq = None
        if sq is not None:
            es = em.entry(sq - 4)
            if es.tag != 'SEQ':
                sys.exit(f'{nombre}: seq {sq:#x} no es SEQ')
            seq = fcv.parse_seq(es.data)
            if seq.flags & 1:
                sys.exit(f'{nombre}: secuencia en reversa no soportada')
        if esp:
            m = GJ.espejar(m)
        poses, raiz, fr, pr = GJ.evaluar(skel, m, seq, loop, en_lugar=True)
        anim = L.clip_esqueleto(b, nodes, n, poses, nombre, FPS, scale, raiz, skel.roots())
        nf = len(poses)
        muestras = sorted(set([0, nf - 1] + list(range(0, nf, max(1, nf // 12)))))
        cajas = [(lambda V: (V.min(0), V.max(0)))(pielx.posar(poses[f], raiz[f])) for f in muestras]
        lo = np.min([c[0] for c in cajas], 0) * scale
        hi = np.max([c[1] for c in cajas], 0) * scale
        pf, af = pr[-1]
        Rr = np.array(raiz[-1]).reshape(3, 4)
        cadera = Rr[:, :3] @ np.array(poses[-1].mat[0]).reshape(3, 4)[:, 3] + Rr[:, 3]
        frente = Rr[:, :3] @ np.array(poses[-1].mat[2]).reshape(3, 4)[:, :3] @ np.array([0.0, 0.0, 1.0])
        if cadera[1] > 700:
            pose_final = 'de_pie'
        elif cadera[1] > 400:
            pose_final = 'agachado'
        else:
            pose_final = 'boca_arriba' if frente[1] > 0.5 else ('boca_abajo' if frente[1] < -0.5 else 'de_costado')
        d = {'clip': nombre, 'motion': etq, 'seq': f'{ARCHIVO}.drs:{sq - 4} (ARC {sq:#x})' if sq is not None else None,
             'espejo': esp, 'loop': loop, 'frames': nf, 'duracion_s': round((nf - 1) / FPS, 4),
             'frames_motion': m.max_frame + 1, 'transicion_f': hokan, 'fuente': fuente}
        if nota:
            d['nota'] = nota
        desp = [round(float(c) * scale, 4) for c in pf]
        giro = round(float(af[1]), 4)
        if loop:
            d.update(raiz_ciclo_m=desp, giro_ciclo_rad=giro, periodo_s=round((nf - 1) / FPS, 4),
                     velocidad_m_s=round(math.hypot(desp[0], desp[2]) / ((nf - 1) / FPS), 4))
        else:
            d.update(raiz_final_m=desp, giro_final_rad=giro)
        d['pose_final'] = pose_final
        pista = [[round(float(p_[0]) * scale, 4), round(float(p_[2]) * scale, 4), round(float(a_[1]), 4)] for p_, a_ in pr]
        d['raiz'] = {'total_m': pista[-1][:2], 'giro_total_rad': pista[-1][2],
                     'se_mueve': any(abs(v_) > 1e-3 for fila in pista for v_ in fila), 'pista_x_z_rotY': pista}
        d['raiz_por_frame'] = [[round(float(p_[0]) * scale, 4), round(float(p_[1]) * scale, 4),
                                round(float(p_[2]) * scale, 4), round(float(a_[1]), 4)] for p_, a_ in pr]
        cl = GJ.claves_free(seq, bits, nf)
        if cl:
            d['frames_clave'] = {f'{b_:#x} {bits[b_]}': GJ.rangos(v_) for b_, v_ in sorted(cl.items())}
        d['bbox_m'] = {'min': [round(float(c), 3) for c in lo], 'max': [round(float(c), 3) for c in hi]}
        anim['extras'] = dict(anim['extras'], loop=loop, espejo=esp,
                              **({'raiz_ciclo_m': desp, 'giro_ciclo_rad': giro} if loop else
                                 {'raiz_final_m': desp, 'giro_final_rad': giro}))
        animations.append(anim)
        info.append(d)
        if args.render and nombre in ('quieto', 'caminar_arma', 'caminar', 'ataque', 'ataque_horca_alto', 'agarrar',
                                      'escena_r100', 'trepar_ventana'):
            control.append((f'{nombre_base}_{nombre}', poses, raiz, cl))

    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_emboscada_r100.py'},
        'scene': 0,
        'scenes': [{'name': 'ganado', 'nodes': [0] + mesh_nodes}],
        'nodes': nodes, 'skins': [skin], 'meshes': meshes,
        'images': [{'uri': png}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': materials, 'animations': animations,
        'extras': {'modelo': f'em12 type {var["type"]} ({tp["que"]}), lista emleon00.esl entrada {e["no"]:#x}',
                   'raiz': 'LOCAL, clips EN EL LUGAR (como ganado_juego_lugar.glb): hueso_000 sin el XZ ni el giro Y; '
                           'la pista va en clips_eNN.json raiz.pista_x_z_rotY',
                   'escala_juego': escala_emset(e['no'])},
    }
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    salida = os.path.join(OUT, f'{nombre_base}.glb')
    gltf.write(doc, bytes(b.blob), salida)

    # ---- comparacion con el esqueleto de ganado_juego_lugar.glb ----
    comp = None
    if ref_nodes:
        mis = [(nd['name'], nd.get('children')) for nd in nodes[:n + 1]]
        suyos = [(nd['name'], nd.get('children')) for nd in ref_nodes[:n + 1]]
        dif = []
        for a_, r_ in zip(nodes[1:n + 1], ref_nodes[1:n + 1]):
            dd = max(abs(x - y) for x, y in zip(a_['translation'], r_['translation']))
            if dd > 1e-5:
                dif.append({'hueso': a_['name'], 'reposo_m': [round(x, 5) for x in a_['translation']],
                            'en_ganado_juego_m': [round(x, 5) for x in r_['translation']], 'dif_m': round(dd, 5)})
        comp = {'nombres_y_jerarquia_iguales': mis == suyos, 'huesos_con_otro_reposo': dif}

    res = {'glb': os.path.relpath(salida, HERE), 'atlas': [W, H], 'mallas': info_mallas, 'clips': len(animations),
           'esqueleto_vs_ganado_juego_lugar': comp}
    with open(os.path.join(OUT, f'clips_e{e["no"]:02x}.json'), 'w') as f:
        json.dump({
            'glb': res['glb'], 'fps': FPS, 'archivo': f'em/{ARCHIVO}.drs',
            'entrada_lista': e['no'], 'variante': {
                'type': var['type'], 'modelo': tp['que'], 'arma': var['arma']['nombre'] if var['arma'] else None,
                'zurdo': var['zurdo'], 'mano_der': f'mot[{var["mano_der"]}] ARC {MANO[var["mano_der"]]:#x}',
                'mano_izq': f'mot[{var["mano_izq"]}] ARC {MANO[var["mano_izq"]]:#x}',
                'sombrero': (f'flag {var["acc"]["bit"]:#x}: ARC {var["acc"]["bin"]:#x} + tpl {var["acc"]["tpl"]:#x}'
                             if var['acc'] else None),
                'variante_seq_caminar_correr': var['v']},
            'raiz_pista': 'raiz.pista_x_z_rotY[f] = [x, z, rotY] (m, rad) relativo al frame 0 en el espacio de la armadura '
                          '(+Z adelante): lo que el juego suma a em->pos / em->ang. hueso_000 NO lo lleva (solo altura y '
                          'cabeceo / rolido): Lua mueve / gira la armadura con el delta de cada frame (en loop, al dar la '
                          'vuelta suma raiz.total_m / giro_total_rad). Igual que out/ganado_juego/clips.json.',
            'escala_juego': escala_emset(e['no']),
            'esqueleto_vs_ganado_juego_lugar': comp,
            'clips': info}, f, indent=1, ensure_ascii=False)
    print(f'-> {res["glb"]}: type {var["type"]}, {var["arma"]["nombre"] if var["arma"] else "sin arma"}'
          f'{" zurdo" if var["zurdo"] else ""}{" + sombrero" if var["acc"] else ""}, atlas {W}x{H}, '
          f'{len(animations)} clips; esqueleto: {"mismos nombres" if comp and comp["nombres_y_jerarquia_iguales"] else "?"}'
          f', reposo distinto en {[x["hueso"] for x in comp["huesos_con_otro_reposo"]] if comp else "?"}')
    if args.render and control:
        GJ.render_control(control, pielx, os.path.join(OUT, 'control'))
    return res


# ---------------------------------------------------------------------------------------------------
#  vehiculos: el camion del evento s20 y la camioneta en el barranco
# ---------------------------------------------------------------------------------------------------
def vehiculos(arc, room, ev20):
    res = {}
    datos = lambda n: IR.arc_room(room, n).data   # noqa: E731
    b_n, t_n = ev20.modelos['obm2d00']
    d_ev = G.datos(ev20, arc, b_n)
    if d_ev != datos(IR.ARC['carro2_bin']):
        print('AVISO: obm2d00.bin del evento no es identico a ROOM_ARC 0x1F (W->carSub)')
    skel = modelbin.parse(d_ev)
    skel.check_tree()
    clips = [('juego', [IR.pose_estatica(skel)], [IR.rot_matrix34(IR.CARRO2_ROT, IR.CARRO2_POS)])]
    for corte in ev20.cortes_de('obm2d00'):
        poses, raiz = E.poses_corte(skel, ev20.motion(corte, 'obm2d00'), ev20.cortes[corte], lugar=ev20.lugar('obm2d00'))
        clips.append((ev20.clip(corte), poses, raiz))
    clips.append(('barranco', [IR.pose_estatica(skel)], [IR.rot_matrix34(CAMION_BARRANCO[1], CAMION_BARRANCO[0])]))
    res['camion'] = IR.glb_modelo(
        [(meshbin.parse(d_ev), gxtex.parse_tpl(G.datos(ev20, arc, t_n)), 'camion')], skel, clips,
        os.path.join(OUT_S20, 'obm2d00.glb'), 'camion', 'Camion_malla',
        extras={'evento': 'r100s20', 'modelo': 'obm2d00 = el camion viejo (mismo .bin que ROOM_ARC 0x1F, W->carSub)',
                'clips': 'juego = estacionado (R100Init); s20_c00 / s20_c02 = el evento; barranco = r100_Car_pos_move'})
    # la camioneta en el barranco: r100_Car_pos_move esconde 11, 12, 13, 14, 16 y muestra 15; pList[10].ang.x queda
    # en 0.4363 (R100Init: la puerta del conductor abierta)
    skc = modelbin.parse(datos(IR.ARC['carro_bin']))
    ms = IR.MallaFiltrada(meshbin.parse(datos(IR.ARC['carro_bin'])), ocultas={11, 12, 13, 14, 16})
    pose = IR.pose_estatica(skc, {10: (0.436332315, 0.0, 0.0)})
    res['coche_barranco'] = IR.glb_modelo(
        [(ms, gxtex.parse_tpl(datos(IR.ARC['carro_tpl'])), 'obm2a00')], skc,
        [('barranco', [pose], [IR.rot_matrix34(COCHE_BARRANCO[1], COCHE_BARRANCO[0])])],
        os.path.join(OUT, 'coche_barranco.glb'), 'coche', 'Coche_barranco_malla',
        extras={'fuente': 'r100.das ROOM_ARC 0x1D / 0x1E (obm2a00), st1/r100.cpp r100_Car_pos_move',
                'nota': 'en (-120.225, -14.319, -2.131) rot (-0.1594, 0.8932, 3.4666); partes 11..14 y 16 escala 0, '
                        '15 escala 1 (el techo aplastado); pList[10].ang.x = 0.4363'})
    res['coche_barranco']['partes_ocultas'] = [11, 12, 13, 14, 16]
    res['coche_barranco']['triangulos_quitados'] = ms.quitados
    return res


def escribir_plan(esl):
    import r100_emboscada_datos as D
    D.escribir(esl, variante, escala_emset, OUT)


# ---------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=L.DEFAULT_DISC)
    ap.add_argument('--solo', choices=['vehiculos', 'ganados', 'plan'])
    ap.add_argument('--entradas', default=None, help='entradas de la lista (hex, separadas por coma); default todas')
    ap.add_argument('--render', action='store_true', help='PNG de control (nube de puntos) de algunos clips')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    arc = L.Archivos(args.disc)
    room = archive.Archive(os.path.join(HERE, 'extracted', 'St1', 'r100.das'))
    resultado = {}
    if args.solo in (None, 'vehiculos'):
        ev20 = E.Evento(E.resolver_evd('r100s20.evd', args.disc))
        resultado['vehiculos'] = vehiculos(arc, room, ev20)
    if args.solo in (None, 'ganados'):
        esl = leer_esl()
        em = arc(ARCHIVO)
        ref = os.path.join(HERE, 'out', 'ganado_juego', 'ganado_juego_lugar.glb')
        ref_nodes = None
        if os.path.isfile(ref):
            import struct as st
            data = open(ref, 'rb').read()
            jl = st.unpack('<I', data[12:16])[0]
            ref_nodes = json.loads(data[20:20 + jl])['nodes']
        lista = [int(x, 16) for x in args.entradas.split(',')] if args.entradas else EMBOSCADA + TRAMPAS_GANADOS
        resultado['ganados'] = {f'{no:#x}': exportar_ganado(arc, em, room, esl[no], args, ref_nodes) for no in lista}
    if args.solo in (None, 'plan'):
        escribir_plan(leer_esl())
    ruta = os.path.join(OUT, '_resultado.json')
    viejo = json.load(open(ruta)) if os.path.isfile(ruta) else {}
    viejo.update(resultado)
    with open(ruta, 'w') as f:
        json.dump(viejo, f, indent=1, default=str)


if __name__ == '__main__':
    main()
