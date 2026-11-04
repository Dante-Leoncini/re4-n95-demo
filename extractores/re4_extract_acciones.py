#!/usr/bin/env python3
"""
El BOTON DE ACCION de r100 (RE4 GameCube, disco USA) -> datos para Whisk3D:

  out/combate/acciones.json          TODO el sistema contextual de r100: ventanas (saltar), vallas, puertas, hablar con
                                     los policias, patada al ganado aturdido, areas AEV con boton / tecla de accion,
                                     prioridades, textos de los carteles (del disco), clips, cuadros clave, sonidos y efectos.
                                     Metros; angulos en radianes con la convencion del juego (yaw 0 = +Z, mira hacia
                                     (sin y, 0, cos y)).
  out/combate/ventana.glb            la ventana et00 (r100.das ETM): "Ventana_intacta" (et0000.bin, el vidrio) y
                                     "Ventana_rota" (et0001.bin, los picos de vidrio que quedan en el marco), en el
                                     espacio de la ventana (origen = centro del borde de abajo, +Z = frente); el marco de
                                     madera es parte del mapa. + ventana_tNN.png
  out/combate/ventana_N.glb          lo mismo POR VENTANA (N = etc no del ETS: 0 planta baja, 1 piso de arriba); las dos
                                     son et00 en el juego (ETS id 0 -> Et00_init), asi que son iguales a ventana.glb
  out/combate/vidrio_trozos.glb      los modelos de efecto (EFM 0x0E y 0x10 de core.das) que usan los records esp 0xFE
                                     (obj05: trozos que salen volando) de los efectos de vidrio + vidrio_tNN.png
  out/combate/efectos_ventana.json   los est de et00.eff (vidrio que estalla, polvo sobre Leon, astillado por bala) en el
                                     MISMO formato que out/combate/efectos.json; texturas en out/combate/tex/
  out/sonidos/acciones/*.wav         + sonidos.json: vidrio (ROOM 6/0x3B, 0x2E, 0x3A), voz/cuerpo de Leon al saltar
                                     (PL 0x29/0x34/0x43), caidas y pasos (FOOT 5/0x12/0x13/0xD/0xE)

Las ANIMACIONES de Leon (ventana_saltar_*, valla_saltar*, patada_frontal, puerta_*) van en
`re4_extract_leon.py --combate` (out/combate/leon_combate.glb + leon_combate_clips.json, con 'pista_y' y 'eventos').
Este script las LEE de leon_combate_clips.json para verificar que la raiz lleve a Leon a traves de la ventana.

Fuentes (decomp ../re4/src): game/act_btn.cpp (cActionButton), game/pl_class.cpp (actionSelect, windowCheck,
fanceCheck, windowOn), game/emwindow.cpp (cEmWindow, ExeWindowEvent, WindowData), game/et00.cpp, game/player.cpp
(pl_R1_Fance), game/cMotBase.cpp, game/sce_at.cpp (sceAtCheck_main, sceAtHitCheck, SceAtCreateFieldAt), game/area.cpp,
game/emdoor.cpp (emDoorActEvtCk, plemDoorOpen/Kick), em10/em10.cpp (em10ActEvtSetKick, plem10Kick, Dm_Small/Head,
em10DmSetWep02), st1/r100.cpp (R100Init, R100Main, r100_WindowBreakCk, r100_DoorCk, r100_Mes*), game/objWep.cpp
(STA_PL_DONT_FIRE), game/pl_sub.cpp (joyFireTrg), game/mes.cpp.

Uso:  python3 re4_extract_acciones.py
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import re4_extract_leon as L          # noqa: E402  (pone ../re4/tools en el path)
import re4_extract_look as LOOK       # noqa: E402
import re4_extract_r100 as R          # noqa: E402  (solo lectura: sat(), area_data())
from motion import archive, meshbin, gxtex, gltf  # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'tools'))
import re4_eff  # noqa: E402
import re4_sonidos as S  # noqa: E402

meshbin._zero_pad = lambda *a: None
OUT = os.path.join(HERE, 'out', 'combate')
OUT_SND = os.path.join(HERE, 'out', 'sonidos', 'acciones')
EXT = os.path.join(HERE, 'extracted')
DAS = os.path.join(EXT, 'St1', 'r100.das')
MM = 0.001
FPS = 30.0
r = LOOK.r


def rn(v, n=4):
    return [round(x, n) for x in v] if isinstance(v, (list, tuple)) else round(v, n)


# ---------------------------------------------------------------------------------------------------------------
#  TEXTO de los mensajes (MDT): u16 por caracter. Ingles (idioma 1): A..Z = 0xA7.., a..z = 0xC1.., espacio 0x80;
#  0x03 salto de linea, 0x08 espera de boton, 0x04 pagina nueva, 0x01 fin, 0x00 inicio.
# ---------------------------------------------------------------------------------------------------------------
PUNT = {0x80: ' ', 0x95: '.', 0x9A: '!', 0x9B: ',', 0x123: "'", 0x9C: '"', 0x9D: '"', 0x96: '?', 0x97: '-',
        0x98: ':'}


def mdt_textos(d, idioma=1):
    """MDT -> lista de textos del idioma (1 = ingles USA; MessageData::getAddr: tbl[lang + 1])."""
    o = struct.unpack_from('>I', d, 4 * (idioma + 1))[0]
    _, cnt = struct.unpack_from('>II', d, o)
    out = []
    for no in range(cnt):
        p = o + struct.unpack_from('>I', d, o + 8 + 4 * no)[0]
        s = ''
        for _ in range(2000):
            c = struct.unpack_from('>H', d, p)[0]
            p += 2
            if c == 1:
                break
            if c == 0:
                continue
            if 0xA7 <= c <= 0xC0:
                s += chr(ord('A') + c - 0xA7)
            elif 0xC1 <= c <= 0xDA:
                s += chr(ord('a') + c - 0xC1)
            elif 0x81 <= c <= 0x8A:
                s += chr(ord('0') + c - 0x81)
            elif c in PUNT:
                s += PUNT[c]
            elif c == 3:
                s += '\n'
            elif c == 4:
                s += ' / '
            elif c == 8:
                pass
            elif c == 9:          # codigo 9 + argumento (ej. voz / referencia): se anota crudo
                a = struct.unpack_from('>H', d, p)[0]
                p += 2
                s += '{9:%#x}' % a
            else:
                s += '{%#x}' % c
        out.append(s.strip())
    return out


# ---------------------------------------------------------------------------------------------------------------
#  AEV completo (SceAtWork 0x9C por registro, include/sce_at.h)
# ---------------------------------------------------------------------------------------------------------------
TIPOS_AT = {0: 'NORMAL', 1: 'DOOR', 2: 'EXEC', 3: 'ITEM', 4: 'FLG', 5: 'MES', 6: 'PLANTER', 7: 'JUMP', 8: 'SAVE',
            9: 'SHD_DISP', 10: 'DAMAGE', 11: 'SCR_AT', 12: 'CAM_CTRL', 13: 'FIELD_INFO', 14: 'STOOP', 15: 'SKEY',
            16: 'LADDER', 17: 'USE', 18: 'HIDE', 19: 'POS_JUMP', 20: 'ITEM_PARENT'}
ACT = ['TALK', 'CHECK', 'JUMP_OUT', 'JUMP_IN', 'JUMP_DOWN', 'JUMP_OVER', 'PUSH', 'KICK', 'GO_UP', 'GET_DOWN',
       'KNOCK_DOWN', 'STAND', 'JUMP_AT', 'LOOK', 'PEEP', 'SNIPING', 'OPEN', 'SWIM', 'JUMP_BACK', 'STOOP', 'OPERATION',
       'RESCUE', 'RIDE_SHOULDER', 'SEARCH_ATTACK', 'SPRINT', 'CLIMB', 'JUMP', 'SLIDE_DOWN', 'CATCH', 'PULL_UP',
       'WAIT_OTHER', 'SEPARATE_OTHER', 'HIDE_OTHER', 'FOLLOW_OTHER', 'HELP_OTHER', 'RIDE', 'GET_OFF', 'GUARD', 'HIDE',
       'THROUGH', 'PICK_UP', 'QUICK_STICK', 'ROTATE', 'RESIST', 'SUPLEX', 'HELI_ORDER', 'SHOOTING', 'SAVE', 'NO_DISP',
       'ACCELERATE', 'ACCELE', 'THROUGH_OTHER', 'SIT_DOWN', 'THROW_DOWN', 'ANSWER', 'SNEAK', 'SENPUU', 'BACKKICK',
       'POISON_NEEDLE', 'EXECUTE', 'PALM_SHOCK', 'NERICHAGI', 'JUMP_MOVE', 'PUSH_SWITCH', 'GET_DOWN_1M', 'FIRE',
       'OPERATION2', 'WIRE']

# lo que hace r100.cpp con cada area (R100Init / R100Main / r100_*): (funcion, descripcion)
ROL_R100 = {
    0: ('puerta a r101', 'area de puerta (sceAtFunc_door) al final del camino'),
    1: ('r100_GakeEvent', 'mirar el barranco (evento s40 / camara) - SOLO despues de la muerte del ganado (Rsf 10)'),
    2: ('(sin funcion)', 'EXEC sin SceAtDataSet_exec: nunca hace nada (sceAtCheck_main salta EXEC con func 0)'),
    3: ('flag', 'FLG: Room_flg bit 0 (jugador o enemigo)'),
    4: ('colision de escenario', 'SCR_AT'), 5: ('colision de escenario', 'SCR_AT'),
    6: ('R100Main', 'al pisarla la 1a vez pre-carga los eventos 0 (s03) y 3 (s20); Rsf 0'),
    7: ('R100Main', 'Rsf 1'), 8: ('R100Main', 'Rsf 1 (la puerta de la casa)'),
    9: ('flag', 'FLG: Room_flg[2] 0x80000000 (flag 64) = Leon EN LA CASA; r100_WindowBreakCk / r100_StreanChk / '
                'r100_DoorCk lo leen'),
    10: ('r100_Sce_look', 'al entrar a la casa la 1a vez: cutscene s03 (Rsf 3), coloca ganado y Leon'),
    11: ('r100_MesDoor', 'puerta de la casa TRABADA durante la emboscada: golpe SE 6/0x29 + mensaje 0xB (habilitada '
                         'recien 20 frames despues de que r100_DoorCk la traba)'),
    12: ('r100_MesTruck', 'mensaje 0xC sobre el camion que tapa el camino (antes de Rsf 10)'),
    13: ('R100Main', 'la casa: si Rsf 3 y Leon SALE de esta area -> baja los 3 streams de batalla (Rsf 12)'),
    14: ('campo', 'FIELD_INFO (luz de lo que se tira adentro de la casa)'), 15: ('campo', 'FIELD_INFO'),
    16: ('mensaje', 'MES'), 17: ('mensaje', 'MES'), 18: ('mensaje', 'MES'), 19: ('mensaje', 'MES'),
    20: ('SAVE', 'maquina de escribir? (tipo 8)'),
    21: ('r100_HouseEvent', 'escena de la VENTANA (el aldeano a traves del vidrio, camara corte 0xA, stream #34)'),
    22: ('r100_mes_gaikotu', 'la calavera: stream de voz + mensaje 0xB del up-cut 0x2F'),
    23: ('mensaje', 'MES'),
    24: ('r100_MesBrige', 'el puente: antes de Rsf 10 mensaje 0xF; despues el evento del barranco / mensaje 0xE'),
    25: ('r100_MesCar00', 'HABLAR con el policia al volante: evento r100s41 (readEvent 5); solo antes de Rsf 10'),
    26: ('r100_MesCar01', 'HABLAR con el otro policia: evento r100s43 (readEvent 7); solo antes de Rsf 10'),
    27: ('r100_EventBrige', 'al pisarla (sin boton): evento r100s44 de los policias en el puente (readEvent 8)'),
    28: ('colision', 'SCR_AT (0x1C: se habilita despues de Rsf 10)'), 29: ('mensaje', 'MES'),
    30: ('colision', 'SCR_AT (0x1E: habilitada antes de Rsf 10)'), 31: ('mensaje', 'MES'), 32: ('mensaje', 'MES'),
    33: ('mensaje', 'MES'),
    34: ('r100_mes_gaikotu_bgm_down', 'baja el stream del cuarto al entrar'),
    35: ('r100_mes_gaikotu_bgm_up', 'lo restaura'),
    36: ('flag', 'FLG: Room_flg[2] 0x40000000 (flag 65) = Leon del lado del policia al volante (R100Main elige que '
                 'policia reacciona si le apuntas)'),
    37: ('colision', 'SCR_AT'), 38: ('colision', 'SCR_AT'), 39: ('colision', 'SCR_AT'),
}


CARTELES = {}


def aev_completo(d, textos_cuarto):
    n, = struct.unpack('>H', d[6:8])
    out = []
    for i in range(n):
        rr = d[0x10 + 0x9C * i:0x10 + 0x9C * (i + 1)]
        a = R.area_data(rr[4:0x34])
        flag, typ, no, chk, trig, ctype, prio, _ = rr[0x34:0x3C]
        ot = rr[0x44]
        ang, rng = struct.unpack('>bb', rr[0x48:0x4A])
        kind = rr[0x4A]
        pay = rr[0x5C:0x9C]
        e = dict(no=no, hex='0x%02X' % no, tipo=typ, tipo_nombre=TIPOS_AT.get(typ, '?'), area=a,
                 habilitada_en_archivo=bool(flag & 1), check_flag=chk,
                 prueba=('punto 0.55 m ADELANTE de Leon (a +0.25 m de altura)' if chk & 1 else
                         'posicion de Leon + 0.25 m de altura'),
                 trigger='0x%X' % trig,
                 dispara=('BOTON DE ACCION con cartel (ActBtn)' if trig & 8 else
                          'tecla de accion SIN cartel (STA_PL_CHECK = Key.trg 0x400)' if trig & 2 else
                          'al estar adentro' if trig & 1 else '-') + (' ; se deshabilita al usarse' if trig & 0x80 else ''),
                 quien={1: 'Leon', 2: 'enemigos', 3: 'Leon y enemigos', 8: 'compañera'}.get(ctype, ctype),
                 ot_prioridad=ot)
        if chk & 2:
            e['mirada'] = dict(yaw_rad=round(math.radians(ang * 2), 4), rango_rad=round(math.radians(rng * 2), 4),
                               regla='|LIMIT_ANGLE(yaw - Leon.yaw)| <= rango (sceAtHitCheck)')
        if trig & 8:
            e['cartel'] = dict(kind=kind, nombre=ACT[kind] if kind < len(ACT) else '?', boton='A',
                               texto=CARTELES.get(kind))
        if typ == 1:
            dx, dy, dz, dang = struct.unpack('>4f', pay[0:16])
            e['puerta'] = dict(destino_stage=pay[0x10], destino_cuarto='r%d%02x' % (pay[0x10], pay[0x11]),
                               destino_pos_m=rn([dx * MM, dy * MM, dz * MM]), destino_yaw=round(dang, 4),
                               traba=pay[0x12], traba_flag=pay[0x13], se_trabada=struct.unpack('b', pay[0x19:0x1A])[0],
                               puerta_no=pay[0x1A])
        if typ == 4:
            k, off, fno = pay[0], pay[1], struct.unpack('>H', pay[2:4])[0]
            e['flag'] = dict(clase=['Room_flg (por frame)', 'flag guardada del cuarto (Rsf)', 'Scenario_flg'][k] if k < 3
                             else k, apaga=bool(off), no=fno,
                             palabra_bit=('Room_flg[%d] 0x%08X' % (fno >> 5, 0x80000000 >> (fno & 31))) if k == 0 else None)
        if typ == 5:
            t, mno = struct.unpack('>hh', pay[0:4])
            e['mensaje'] = dict(no='0x%X' % mno, camara_corte=pay[4] - 1 if pay[4] else None,
                                se=(pay[6] << 8 | pay[7]) - 1 if (pay[6] << 8 | pay[7]) else None,
                                texto=textos_cuarto[mno] if 0 <= mno < len(textos_cuarto) else None)
        fn, desc = ROL_R100.get(no, ('?', ''))
        e['r100'] = dict(funcion=fn, que=desc)
        out.append(e)
    return out


# ---------------------------------------------------------------------------------------------------------------
#  geometria: transformaciones del juego (RotMatrix Y: local (0,0,1) -> (sin y, 0, cos y))
# ---------------------------------------------------------------------------------------------------------------
def a_mundo(pos_m, yaw, local_m):
    x, y, z = local_m
    s, c = math.sin(yaw), math.cos(yaw)
    return [pos_m[0] + c * x + s * z, pos_m[1] + y, pos_m[2] - s * x + c * z]


def pisos_en(V, tris, x, z):
    out = []
    for a, b, c, attr, cl in tris:
        if cl == 2:
            continue
        A, B, C = V[a], V[b], V[c]
        d = (B[2] - C[2]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[2] - C[2])
        if abs(d) < 1e-12:
            continue
        l1 = ((B[2] - C[2]) * (x - C[0]) + (C[0] - B[0]) * (z - C[2])) / d
        l2 = ((C[2] - A[2]) * (x - C[0]) + (A[0] - C[0]) * (z - C[2])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-6:
            out.append(l1 * A[1] + l2 * B[1] + l3 * C[1])
    return sorted(out)


def piso_bajo(V, tris, x, y, z):
    """SatMgr.hitCheck hacia abajo desde y: el piso mas alto por debajo de y."""
    p = [h for h in pisos_en(V, tris, x, z) if h <= y + 1e-3]
    return max(p) if p else None


# ---------------------------------------------------------------------------------------------------------------
#  modelos estaticos (meshbin + TPL) -> glb con PNGs sueltos
# ---------------------------------------------------------------------------------------------------------------
def glb_estatico(salida, modelos, pref_png):
    """modelos: [(nombre_nodo, meshbin, tpl_parseado, blend)] -> glb (un mesh por modelo, una primitiva por material)."""
    b = gltf.Builder()
    imagenes, materiales, claves = [], [], {}
    nodes, meshes = [], []
    carpeta = os.path.dirname(salida)
    for nombre, m, tex, blend in modelos:
        prims = []
        por_mat = {}
        for part in m.parts:
            tris = part.triangles()
            if not tris:
                continue
            alpha = part.alpha_tex if part.flags & 4 else None
            k = (id(tex), part.tex_id, alpha)
            if k not in claves:
                img = gltf.compose_image(tex, part.tex_id, alpha)
                fn = '%s_%d.png' % (pref_png, len(imagenes))
                with open(os.path.join(carpeta, fn), 'wb') as f:
                    f.write(gxtex.png(img))
                imagenes.append({'uri': fn})
                transp = alpha is not None or blend
                mat = {'name': '%s_%d' % (pref_png, len(materiales)),
                       'pbrMetallicRoughness': {'baseColorTexture': {'index': len(imagenes) - 1}, 'metallicFactor': 0.0,
                                                'roughnessFactor': 1.0},
                       'doubleSided': True, 'extras': {'w3d_transparent': bool(transp)}}
                if transp:
                    mat['alphaMode'] = 'BLEND'
                materiales.append(mat)
                claves[k] = len(materiales) - 1
            g = por_mat.setdefault(claves[k], ({}, [], [], [], []))
            index, pos, nrm, uv, idx = g
            for tri in tris:
                if len({v[0] for v in tri}) < 3:
                    continue
                for v in tri:
                    i = index.get(v)
                    if i is None:
                        i = index[v] = len(pos)
                        pos.append(tuple(c * MM for c in m.position(v[0])))
                        nrm.append(tuple(gltf.normalize(m.normal(v[1]))))
                        uv.append(tuple(m.texcoord(v[3])))
                    idx.append(i)
        for mat, (index, pos, nrm, uv, idx) in por_mat.items():
            prims.append(L.primitiva(b, pos, nrm, uv, idx, mat, 'transparente' if materiales[mat].get('alphaMode') else 'opaco'))
        nodes.append({'name': nombre, 'mesh': len(meshes)})
        meshes.append({'name': nombre, 'primitives': prims})
    doc = {'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_acciones.py'}, 'scene': 0,
           'scenes': [{'name': pref_png, 'nodes': list(range(len(nodes)))}], 'nodes': nodes, 'meshes': meshes,
           'images': imagenes, 'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 10497, 'wrapT': 10497}],
           'textures': [{'source': i, 'sampler': 0} for i in range(len(imagenes))], 'materials': materiales,
           'accessors': b.accessors, 'bufferViews': b.buffer_views}
    gltf.write(doc, bytes(b.blob), salida)


def caja(m):
    vs = {v[0] for p in m.parts for t in p.triangles() for v in t}
    P = [m.position(i) for i in vs]
    return [rn([min(p[k] for p in P) * MM for k in range(3)]), rn([max(p[k] for p in P) * MM for k in range(3)])]


# ---------------------------------------------------------------------------------------------------------------
#  SONIDOS
# ---------------------------------------------------------------------------------------------------------------
SONIDOS = [
    ('vidrio_rompe.wav', 'ROOM', 0x3B, 'la ventana ESTALLA (et00)',
     'emwindow.cpp SetBreakAll (tipo Et00: default): al saltar a traves (f13/15/16) o al romperla a tiros / cuchillo'),
    ('vidrio_astilla.wav', 'ROOM', 0x2E, 'bala en el vidrio que NO lo rompe todavia',
     'cEmWindow::DmCk: hp > 0 (et00 tiene 1000 hp, la pistola le saca 500): SE + est 5 (astillado)'),
    ('vidrio_golpe.wav', 'ROOM', 0x3A, 'alguien choca la ventana (tiembla 10 frames)', 'cEmWindow::SetShake (et00)'),
    ('ventana_leon_1.wav', 'PL', 0x29, 'Leon al tirarse por la ventana (1 de 3, frame 3)', 'ExeWindowEvent i == 3'),
    ('ventana_leon_2.wav', 'PL', 0x34, 'Leon al tirarse por la ventana (2 de 3, frame 4)', 'ExeWindowEvent i == 4'),
    ('ventana_leon_3.wav', 'PL', 0x43, 'Leon al tirarse por la ventana (3 de 3, frame 5)', 'ExeWindowEvent i == 5'),
    ('ventana_cae_cuerpo.wav', 'FOOT', 5, 'el cuerpo de Leon cae al piso (rueda)',
     'ExeWindowEvent: afuera f35 / adentro f45 / abajo f40 (SndCall(5, 5)); tambien damageBlow'),
    ('ventana_paso_1.wav', 'FOOT', 0x12, 'pisada al levantarse (izq)', 'ExeWindowEvent f41 / f51 / f55'),
    ('ventana_paso_2.wav', 'FOOT', 0x13, 'pisada al levantarse (der)', 'ExeWindowEvent f44 / f55 / f57'),
    ('valla_pie_1.wav', 'FOOT', 0xE, 'pie al saltar la valla (frame 28)', 'player.cpp pl_R1_Fance Seq_frame 27.7..28.3'),
    ('valla_pie_2.wav', 'FOOT', 0xD, 'pie al caer de la valla (frame 30)', 'pl_R1_Fance Seq_frame 29.7..30.3'),
]
BANCOS = {'ROOM': ('St1/r100.das', 6), 'PL': ('em/pl00.drs', 1), 'FOOT': ('St1/r100.das', 5)}


def sonidos():
    os.makedirs(OUT_SND, exist_ok=True)
    bancos = {k: S.load_bank(*v) for k, v in BANCOS.items()}
    lista = []
    for fn, bk, no, que, cuando in SONIDOS:
        b = bancos[bk]
        s = b.sit(no)
        pcm, eff, info = S.sit_render(b, no)
        rate = int(round(eff))
        S.write_wav(os.path.join(OUT_SND, fn), pcm, rate)
        g = (s['vol'] if s['vol'] >= 0 else 127) / 127.0 * 10 ** ((info['rgn']['attn'] / 65536.0) / 200.0)
        grp = b.rnd_group(s['rnd_no'])
        lista.append(dict(archivo=fn, que=que, cuando=cuando, banco='%s (SndCall bloque %d) %s' % (bk, BANCOS[bk][1],
                                                                                              BANCOS[bk][0]),
                          se='%#04x' % no, volumen=round(g, 3), hz=rate, segundos=round(len(pcm) / eff, 3),
                          grupo_rnd=grp or None))
        print('  %-26s %-4s %#05x %.3fs %d Hz' % (fn, bk, no, len(pcm) / eff, rate))
    doc = dict(descripcion='Sonidos del boton de accion en r100 (ventanas, vallas). WAV mono 16 bit a la frecuencia '
                           'efectiva del SIT, SIN volumen (multiplicar por "volumen"). FOOT = superficie 0 (tierra); '
                           'footSeCheck suma 30 * tipo de piso (la casa puede sonar distinto). Generado por '
                           're4_extract_acciones.py',
               ya_existentes={'patada': 'out/sonidos/combate/patada_voz.wav (PL 0x10), patada_swing.wav (0x11), '
                                        'patada_impacto.wav (0xF)',
                              'policias': 'out/r100_intro/audio/se_policia_hablar.wav (ROOM 6), se_policia_a_hablar.wav (5)',
                              'puerta_casa': 'out/r100_intro/audio/se_puerta_golpe.wav (ROOM 0x29), se_puerta_aviso.wav (0x28)'},
               sonidos=lista)
    with open(os.path.join(OUT_SND, 'sonidos.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return {x['se'] + '_' + x['banco'][:4].strip(): 'out/sonidos/acciones/' + x['archivo'] for x in lista}


# ---------------------------------------------------------------------------------------------------------------
#  EFECTOS de la ventana (et00.eff, dueno EFF 0x54 = w->eff)
# ---------------------------------------------------------------------------------------------------------------
EFECTOS_VENTANA = [
    (0, 'vidrio_estalla_evento_afuera', 'Leon salta a traves (breakDir 0): SetBreakAll(pos, 1, 1) -> SetBreakEsp tblB[0][1]'),
    (1, 'vidrio_estalla_evento_adentro', 'breakDir 1 (desde el frente): tblB[1][1]'),
    (3, 'vidrio_estalla_evento_abajo', 'breakDir 2 (sin piso detras, ventana de arriba): tblB[2][1]'),
    (6, 'vidrio_estalla_bala_detras', 'rota a tiros / cuchillo desde DETRAS (o sin piso): tblA[0|2][0] (armas chicas; '
                                      'escopeta y grandes = tblA[..][1] = est 0 / 1)'),
    (7, 'vidrio_estalla_bala_frente', 'rota a tiros desde el FRENTE (+Z de la ventana): tblA[1][0]'),
    (5, 'vidrio_astilla_bala', 'bala que no la rompe: EmDmBloodSet3(this, eff, 5, 0, 0x801, 0x31) (en el punto de dano)'),
    (8, 'leon_ventana_afuera', 'EstSet(pPL, -1, 0, 0, eff, 8, 1) en el frame 0 del salto breakDir 0 (sobre Leon)'),
    (2, 'leon_ventana_adentro', 'idem breakDir 1 (est 2)'),
    (4, 'leon_ventana_abajo', 'idem breakDir 2 (est 4)'),
]


def efectos(etm):
    eff = re4_eff.Eff(etm['et00.eff'], 'et00')
    core = re4_eff.load_effs(os.path.join(EXT, 'etc', 'core.das'), 1)[0]
    usados = {'et00': set(), 'core': set()}
    for no, *_ in EFECTOS_VENTANA:
        for q in eff.est[no]['records']:
            if q['Id'] in re4_eff.NO_TEX_IDS or q['Id'] == 0xFE:
                continue
            ids = {q['Tex_id']} | ({q['MaskTex_id']} if q['Tool_flg'] & 0x4000 else set())
            for t in ids:
                (usados['et00'] if t in eff.tex else usados['core']).add(t)
    carpeta = os.path.join(OUT, 'tex')
    arch = dict(LOOK.exportar_texturas([('core', core)], {'core': usados['core']}, carpeta))
    arch.update(LOOK.exportar_texturas([('et00', eff)], {'et00': usados['et00']}, carpeta))

    def tl(t):
        return eff.tex.get(t) or core.tex.get(t)
    grupos = []
    for no, nombre, cuando in EFECTOS_VENTANA:
        s = eff.est[no]
        recs = []
        for q in s['records']:
            e = LOOK.emisor_de(q, arch, (lambda t: None) if q['Id'] == 0xFE else tl)
            if q['Id'] == 0xFE:
                e['textura'] = None
                e['modelo_efm'] = dict(id='0x%02X' % q['Tex_id'], glb='vidrio_trozos.glb', nodo='efm_%02x' % q['Tex_id'],
                                       que='TROZOS de vidrio 3D (core.das EFM): obj05 = modelo cuyas partes salen '
                                           'volando del centro cuando el radio que crece las alcanza, con velocidad y giro '
                                           'propios, rebotan en el piso y quedan planas; el cuerpo escala / se desvanece '
                                           'como obj04')
            recs.append(e)
        grupos.append(dict(nombre=nombre, fuente='r100.das ETM et00.eff est %d (EFF 0x54)' % no, est=no, cuando=cuando,
                           orientacion=('matriz de la VENTANA (origen = centro del borde de abajo, +Z = frente); la '
                                        'cabeza del est va en pos_m' if no not in (2, 4, 8, 5) else
                                        ('sobre Leon (EstSet(pPL, ...))' if no != 5 else 'en el punto del impacto')),
                           cabeza=dict(pos_m=r([x * MM for x in s['pos']]), rot_grados=r(s['rot_deg']), parte=s['parts']),
                           emisores=recs,
                           crudo=[{k: (list(v) if isinstance(v, tuple) else v) for k, v in q.items()} for q in s['records']]))
    doc = dict(fuente='r100.das ETM et00.eff (cargado por Et00_init como EFF 0x54) + core.das (texturas y EFM)',
               unidades='metros, segundos (30 fps); ver out/combate/efectos.json "semantica"',
               cuando_se_usa={'salto': 'est del evento (0/1/3) en el frame de rotura + est 8/2/4 sobre Leon en el f0',
                              'a_tiros': 'est 6 / 7 al romperse; est 5 en cada impacto que no la rompe',
                              'ambiente': 'et00 NO tiene destello de vidrio intacto (WindowData[0].breakEff = 0)'},
               grupos=grupos)
    with open(os.path.join(OUT, 'efectos_ventana.json'), 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    # los EFM de trozos (core)
    d, h = core.d, core.h
    n = struct.unpack_from('>I', d, h[5])[0]
    ids = [struct.unpack_from('>H', d, h[5] + 4 + 8 * i)[0] for i in range(n)]
    modelos = []
    for i, idn in enumerate(ids):
        if idn not in (0x0E, 0x10):
            continue
        eo = h[11] + struct.unpack_from('>I', d, h[11] + 4 + 4 * i)[0]
        _, om, ot, _, _ = struct.unpack_from('>5I', d, eo)
        m = meshbin.parse(d[eo + om:eo + ot])
        tpl = gxtex.parse_tpl(d[eo + ot:])
        modelos.append(('efm_%02x' % idn, m, tpl, True))
    glb_estatico(os.path.join(OUT, 'vidrio_trozos.glb'), modelos, 'vidrio')
    print('efectos_ventana.json: %d grupos; vidrio_trozos.glb: %s' % (len(grupos), [x[0] for x in modelos]))
    return [g['nombre'] for g in grupos]


# ---------------------------------------------------------------------------------------------------------------
def main():
    das = archive.Archive(DAS)
    ent = list(das.entries())
    etm = dict(archive.parse_etm(next(e for e in ent if e.tag == 'ETM').data))
    V, tris = R.sat(next(e for e in ent if e.tag == 'SAT').data)
    textos_cuarto = mdt_textos(next(e for e in ent if e.tag == 'MDT').data)
    core_das = archive.Archive(os.path.join(EXT, 'etc', 'core.das'))
    textos_core = mdt_textos(next(e for e in core_das.entries() if e.index == 6).data)   # pCore->ofs_28
    carteles = {ACT[k]: textos_core[k + 0x16] for k in range(len(ACT)) if k + 0x16 < len(textos_core)}
    CARTELES.update({k: textos_core[k + 0x16] for k in range(len(ACT)) if k + 0x16 < len(textos_core)})
    aev = aev_completo(next(e for e in ent if e.tag == 'AEV').data, textos_cuarto)
    ets = R.ets(next(e for e in ent if e.tag == 'ETS').data)

    # ---- los modelos de la ventana ----
    tpl = gxtex.parse_tpl(etm['et0000.tpl'])
    m_int, m_rota = meshbin.parse(etm['et0000.bin']), meshbin.parse(etm['et0001.bin'])
    glb_estatico(os.path.join(OUT, 'ventana.glb'), [('Ventana_intacta', m_int, tpl, False),
                                                   ('Ventana_rota', m_rota, tpl, False)], 'ventana')
    print('ventana.glb: intacta %s, rota %s' % (caja(m_int), caja(m_rota)))

    clips = {c['clip']: c for c in json.load(open(os.path.join(OUT, 'leon_combate_clips.json')))['clips']}
    faltan = [c for c in ('ventana_saltar_afuera', 'ventana_saltar_adentro', 'ventana_saltar_abajo', 'valla_saltar',
                          'valla_saltar_angosta', 'patada_frontal', 'puerta_abrir') if c not in clips]
    if faltan:
        sys.exit('faltan clips en leon_combate_clips.json (correr re4_extract_leon.py --combate): %s' % faltan)

    # ---- las 2 ventanas de r100 (ETS no 0 y 1, id 0 = Et00 -> WindowData[0]) ----
    SALTOS = {0: ('ventana_saltar_afuera', (90, -1000, -1610), 0.0, 15, 0),
              1: ('ventana_saltar_adentro', (-210, -1000, 1990), math.pi, 16, 1),
              2: ('ventana_saltar_abajo', (0, -1000, -980), 0.0, 13, 3)}
    ventanas = []
    verif = []
    for e in [x for x in ets if x['id'] == 0]:
        pos = [c * MM for c in e['pos']]
        yaw = e['rot'][1]
        # el modelo de ESTA ventana: EtcModelSet -> id 0 (ETC_WINDOW00) -> Et00_init(arc, d, &model, flag 0) ->
        # SetWindow(et0000.bin, et0000.tpl, ..., WindowData[0], etcNo = d->type): las DOS ventanas de r100 son et00
        # (el ETM de r100 no trae otra ventana). Un glb por ventana, en SU espacio (mismas mallas que ventana.glb)
        glb_v = os.path.join(OUT, 'ventana_%d.glb' % e['no'])
        glb_estatico(glb_v, [('Ventana_intacta', m_int, tpl, False), ('Ventana_rota', m_rota, tpl, False)], 'ventana')
        fr = [a_mundo(pos, yaw, (0, 0, s)) for s in (2.0, -2.0)]
        pisos = [piso_bajo(V, tris, p[0], p[1], p[2]) for p in fr]
        sin_piso = any(h is None or h < pos[1] - 3.0 for h in pisos)    # CalFloor
        campo = [a_mundo(pos, yaw, (x * MM, 0, z * MM))[0::2] for x, z in ((500, -1000), (500, 1000), (-500, 1000),
                                                                           (-500, -1000))]
        v = dict(etc_no=e['no'], id=0, modelo='et0000.bin (intacta) -> et0001.bin (rota)', window_type='WindowTypeEt00',
                 glb='out/combate/ventana_%d.glb' % e['no'],
                 colocacion=dict(nodos=['Ventana_intacta', 'Ventana_rota (oculta hasta que se rompe)'], pos_m=rn(pos),
                                 rot_grados=[0.0, round(math.degrees(yaw), 4), 0.0], escala=list(e['sc']),
                                 que='ETS no %d: EtcSetData id 0 (ETC_WINDOW00) -> Et00_init -> SetWindow(et0000.bin, '
                                     'WindowData[0]); RotMatrix(ang) + TransMatrix(pos) + ScaleMatrix(1): el origen del '
                                     'modelo es el centro del borde de ABAJO del vidrio' % e['no'],
                                 origen_del_modelo='las dos ventanas usan EL MISMO modelo et00 (1.322 x 1.438 m): el '
                                                   'ETS de r100 tiene id 0 en las dos y el ETM del cuarto no trae otra '
                                                   'ventana; ventana_%d.glb = ventana.glb' % e['no']),
                 pos_m=rn(pos), yaw_rad=round(yaw, 5), frente_mundo=rn([math.sin(yaw), 0, math.cos(yaw)]),
                 vidrio_m=dict(ancho=1.322, alto=1.438, espesor=0.032, nota='origen = centro del borde de ABAJO del vidrio'),
                 piso_detras_m=rn(pisos[1]) if pisos[1] is not None else None,
                 piso_delante_m=rn(pisos[0]) if pisos[0] is not None else None,
                 sin_piso=sin_piso,
                 que=('planta baja, pared OESTE de la casa (frente +Z = afuera, hacia -X del mundo)' if e['no'] == 0 else
                      'PISO DE ARRIBA de la casa (piso adentro 3.34 m, afuera 0.16 m: CalFloor ve la caida -> solo se '
                      'puede saltar desde adentro, hacia abajo)'),
                 hp=1000, danio=dict(pistola=500, cuchillo='rompe de una (GetWepSizeGroup(0x10) = 2)',
                                     escopeta_y_grandes='rompe de una', patada_0x14='no le hace nada'),
                 colision=dict(que='caja 1.7 x 1.8 m (x +-0.85, y de -0.2 a +1.6 m, z +-0.0005) attr SAT 0x40 = tapa el '
                                   'paso hasta que se rompe (SetAtariOff); EAT 0x400000 = la bala le pega',
                               esquinas_mundo=[rn(a_mundo(pos, yaw, (x, y, 0))) for x, y in ((-0.85, -0.2), (0.85, -0.2),
                                                                                              (0.85, 1.6), (-0.85, 1.6))]),
                 campos_de_salto=dict(
                     que='2 areas FIELD_INFO (SceAtCreateFieldAt, valor 1) iguales: rectangulo 1 m (x local +-0.5) por 2 m '
                         '(z local +-1.0) centrado en la ventana, piso = ventana.y - 2.0, alto 3.0 (area.cpp: y + 0.1 >= '
                         'piso y y < piso + alto). Los angulos 0 / -pi (+-80 grados) NO se usan: ChkWindow llama '
                         'SceAtCheckFieldInfo sin modelo',
                     poligono_xz=[rn(p) for p in campo], piso_m=round(pos[1] - 2.0, 4), alto_m=3.0),
                 habilitada=('NO mientras Rsf 10 == 0 (antes de que muera el ganado de la casa y termine s20): '
                             'r100_WindowBreakCk hace SetEnableFence(0, 0) CADA FRAME (Leon y enemigos no pueden cruzar); '
                             'despues SetEnableFence(1, 0): Leon y los ganados de la emboscada la cruzan'))
        saltos = []
        for bd in ((0, 1) if not sin_piso else (2,)):
            clip, loc, dang, f_rompe, est = SALTOS[bd]
            ini = a_mundo(pos, yaw, [c * MM for c in loc])
            yaw_l = yaw + dang
            c = clips[clip]
            pista = c['raiz']['pista_x_z_rotY']
            py = c['raiz']['pista_y']
            fin = [ini[0] + math.sin(yaw_l) * pista[-1][1] + math.cos(yaw_l) * pista[-1][0], ini[1] + py[-1],
                   ini[2] + math.cos(yaw_l) * pista[-1][1] - math.sin(yaw_l) * pista[-1][0]]
            # verificacion: ¿cruza el plano de la ventana? distancia firmada a lo largo del frente
            def lado(p):
                return (p[0] - pos[0]) * math.sin(yaw) + (p[2] - pos[2]) * math.cos(yaw)
            f_cruce = None
            for f, (x, z, _) in enumerate(pista):
                p = [ini[0] + math.sin(yaw_l) * z + math.cos(yaw_l) * x, 0, ini[2] + math.cos(yaw_l) * z - math.sin(yaw_l) * x]
                if f_cruce is None and (lado(p) > 0) != (lado(ini) > 0):
                    f_cruce = f
            piso_fin = piso_bajo(V, tris, fin[0], fin[1] + 0.5, fin[2])
            saltos.append(dict(
                break_dir=bd, clip=clip,
                cartel='JUMP_IN' if bd == 1 else 'JUMP_OUT',
                desde=('DETRAS (lado -Z local)' if bd != 1 else 'DELANTE (lado +Z local)'),
                leon_inicio_local_mm=list(loc), leon_inicio_mundo_m=rn(ini), leon_yaw_rad=round(yaw_l, 5),
                leon_fin_mundo_m=rn(fin), piso_al_final_m=rn(piso_fin) if piso_fin is not None else None,
                recorrido_m=rn(math.hypot(pista[-1][0], pista[-1][1])), baja_m=rn(py[-1]),
                cruza_el_plano_en_frame=f_cruce, vidrio_rompe_frame=f_rompe, est_rotura=est,
                fin_pasado_la_ventana_m=rn(abs(lado(fin)))))
            verif.append('ventana %d %s: inicio %s -> fin %s (piso %s), cruza en f%s, rompe f%d' % (
                e['no'], clip, rn(ini, 2), rn(fin, 2), rn(piso_fin, 2) if piso_fin is not None else None, f_cruce, f_rompe))
        v['saltos'] = saltos
        v['rota_valla'] = ('con la ventana YA rota y breakDir 0/1 el cartel es JUMP_OVER y salta como una valla '
                           '(fanceOn: pl_R1_Fance sub 5 = clip valla_saltar_angosta) con el ancla MotBase en PlFancePos = '
                           'ventana + lado_del_jugador * 0.4 m, mirando a traves; con breakDir 2 sigue siendo el evento '
                           '(windowOn, sin romper nada)')
        ventanas.append(v)

    # ---- vallas (paredes SAT con attr 0x20) ----
    vallas = []
    grupos = []
    for a, b, c, attr, cl in tris:
        if cl == 2 and attr & 0x20:
            P = [V[a], V[b], V[c]]
            cen = [sum(p[k] for p in P) / 3 for k in range(3)]
            for g in grupos:
                if math.hypot(g['cen'][0] - cen[0], g['cen'][2] - cen[2]) < 1.5:
                    g['tris'].append((P, attr))
                    break
            else:
                grupos.append(dict(cen=cen, tris=[(P, attr)]))
    for g in grupos:
        pts = [p for P, _ in g['tris'] for p in P]
        ys = [p[1] for p in pts]
        # los dos extremos del segmento: el par de puntos mas separado en XZ
        xz = sorted({(round(p[0], 3), round(p[2], 3)) for p in pts})
        e0, e1 = max(((u, w) for u in xz for w in xz), key=lambda t: math.hypot(t[0][0] - t[1][0], t[0][1] - t[1][1]))
        # normal XZ de la pared (la de la primera cara) y espesor = separacion entre las caras a lo largo de ella
        P0 = g['tris'][0][0]
        ux, uz = P0[1][0] - P0[0][0], P0[1][2] - P0[0][2]
        if math.hypot(ux, uz) < 1e-3:
            ux, uz = P0[2][0] - P0[0][0], P0[2][2] - P0[0][2]
        ln = math.hypot(ux, uz)
        nx, nz = -uz / ln, ux / ln
        dist = [sum((p[0] - g['cen'][0]) * nx + (p[2] - g['cen'][2]) * nz for p in P) / 3 for P, _ in g['tris']]
        espesor = max(dist) - min(dist)
        pisos = [piso_bajo(V, tris, g['cen'][0] + nx * k, 3.0, g['cen'][2] + nz * k) for k in (1.0, -1.0)]
        vallas.append(dict(attrs=sorted({'0x%08X' % at for _, at in g['tris']}), triangulos=len(g['tris']),
                           extremos_xz=[list(e0), list(e1)], largo_m=round(math.hypot(e0[0] - e1[0], e0[1] - e1[1]), 3),
                           normal_xz=rn([nx, nz]), espesor_m=round(espesor, 3),
                           base_m=round(min(ys), 3), tope_m=round(max(ys), 3),
                           pisos_a_1m_de_cada_lado_m=[rn(h) if h is not None else None for h in pisos],
                           que=('baranda del PORCHE de la casa (lado oeste de la puerta)' if g['cen'][0] < -84 else
                                'cerca de madera frente a la casa')))
    # ---- acciones.json ----
    area = {a['no']: a for a in aev}
    doc = dict(
        titulo='Boton de ACCION (contextual) en r100 - RE4 GameCube USA',
        unidades='metros; yaw en radianes, convencion del juego: 0 = +Z, direccion = (sin yaw, 0, cos yaw); frames a 30 fps',
        fuentes='decomp ../re4/src: game/act_btn.cpp, game/pl_class.cpp, game/emwindow.cpp, game/player.cpp, '
                'game/cMotBase.cpp, game/sce_at.cpp, game/area.cpp, game/emdoor.cpp, em10/em10.cpp, st1/r100.cpp, '
                'game/objWep.cpp, game/pl_sub.cpp; disco: r100.das (AEV, ETS, ETM, SAT, MDT), core.das (MDT 6, EFF)',
        sistema=dict(
            como_funciona='Cada frame el codigo del juego OFRECE acciones con ActBtn.set(kind, slot, funcion, ...) (max 8 '
                          'por frame, se borran al final de ActBtn.move). move() recorre de slot 15 a 0 (dentro de un slot '
                          'la ULTIMA ofrecida primero), salta las que checkPLStatus rechaza y usa LA PRIMERA valida: '
                          'dibuja el cartel (mensaje core kind + 0x16 junto al icono del boton A: out/combate/hud.json '
                          '"boton_accion") y, si se aprieta A ese frame, ejecuta la funcion. Una sola accion por frame.',
            boton='A (STA_PL_ACTION = Key.trg 0x80000). Las areas AEV sin cartel usan STA_PL_CHECK (Key.trg 0x400, '
                  'tambien A en la config normal)',
            slots_prioridad={'11 (0xB)': 'patada / agarres de enemigos (em10ActEvtSetKick)',
                             '5': 'puertas (emDoorActEvtCk)', '2': 'ventana, valla, saltar, bajar, empujar (actionSelect) '
                                                                    'y las areas AEV de r100 (otNo 2)'},
            orden_en_slot_2='actionSelect ofrece en este orden: empujar, bajar de cornisa, VALLA, saltar pared, VENTANA, '
                            'subir/bajar escalon -> la ventana se muestra antes que la valla si hubiera las dos',
            condiciones_generales=['pPL->hp > 0 y pPL->actCheck() (control normal; flags ACTCTR_ENFORCE_EXEC lo saltea)',
                                   'APUNTANDO (PlGetStatus & 0x10) solo valen las acciones con ACTCTR_WEP_SET_IGNORE '
                                   '(la patada): puertas, ventanas, hablar desaparecen mientras se apunta; la patada '
                                   'pone STA_ACT_DONT_FIRE -> ese A patea en vez de disparar',
                                   'actionSelect (ventana / valla) solo en la rutina 0 del jugador (r_no_0 == 0) y sin '
                                   'adelante+atras apretados; no en SPF_ACTBTN ni durante la muerte',
                                   'se oculta el cartel con DPF_ACTBTN o ACTCTR_NO_DISP pero la accion sigue'],
            carteles=carteles,
            color='cartel blanco; las puertas con ACTCTR_DOOR_COLOR (color de mensaje 7)'),
        ventanas=dict(
            deteccion='pl_class.cpp windowCheck: p0 = Leon + (0, 0.4, 0), p1 = p0 + 1 m hacia adelante (yaw de Leon). '
                      'ChkWindow: p1 dentro de un campo de salto (poligono + altura) de una ventana habilitada para Leon '
                      '(ChkEnableFence(1)) y el segmento p0->p1 CRUZA el plano de la ventana (Front_check +-90 grados: '
                      'p0 de un lado y p1 del otro). O sea: Leon a menos de ~1 m del vidrio, mirando hacia el (cualquier '
                      'angulo que haga cruzar la linea de 1 m) y dentro de +-0.5 m del centro. EmRackCk: nada en el medio.',
            regla_numerica=dict(
                punto='p1 = (Leon.x, Leon.y + 0.4, Leon.z) + 1.0 m * (sin yaw, 0, cos yaw) de Leon',
                en_espacio_ventana='con Leon en (x0, z0) local (z0 del lado de donde viene) y th = angulo entre su frente y '
                                   'la normal hacia el vidrio: se cruza si 1.0 * cos(th) > |z0|; p1 debe quedar en '
                                   '|x0 + sin(th)| <= 0.5 y |z_p1| <= 1.0 (el rectangulo del campo)',
                ejemplo='Leon pegado al vidrio y centrado (x0 = 0): th <= 30 grados (asin 0.5); a 0.5 m: th <= 60 grados '
                        'por el cruce pero x0 + sin(th) <= 0.5 manda -> ~30 grados si esta centrado',
                altura='Leon.y en [ventana.y - 2.5, ventana.y + 0.6) (p1.y + 0.1 >= piso del campo = ventana.y - 2 y '
                       'p1.y < ventana.y + 1)'),
            break_dir='ChkBreakDir(pos de Leon): 1 si Leon esta DELANTE (+Z local, +-90 grados), si no 2 cuando '
                      'CalFloor vio una caida > 3 m a 2 m de algun lado de la ventana, si no 0',
            carteles={'intacta, breakDir 0': 'JUMP_OUT -> windowOn (evento)', 'intacta, breakDir 1': 'JUMP_IN -> windowOn',
                      'intacta, breakDir 2': 'JUMP_OUT -> windowOn', 'rota, breakDir 2': 'JUMP_OUT -> windowOn',
                      'rota, breakDir 0/1': 'JUMP_OVER -> fanceOn (salto de valla, clip valla_saltar_angosta)'},
            evento='windowOn -> SceExec(ExeWindowEvent): SceEventStart, ventana SetStatus(2), pPL->beginEvent(0) = '
                   'rutina de evento + atari.throughOn() (SIN colision contra el mapa ni personajes durante todo el salto) '
                   '+ el arma vuelve a reposo; setFace(2); Leon se TELETRANSPORTA a leon_inicio (espacio de la ventana) '
                   'mirando a traves; MotionSetCore(clip, hokan 0, attr 0x201: la raiz mueve a Leon en X, Y y Z = '
                   'pista_x_z_rotY + pista_y, rotadas por el yaw inicial); rompe el vidrio en su frame; al terminar la '
                   'motion setFace(0), SceEventEnd -> endEvent: colision de nuevo, 10 frames invulnerable, control. '
                   'No hay piso ni gravedad durante el evento: la pista_y de ventana_saltar_abajo (-3.24 m) lo baja.',
            rotura='SetBreakAll: SE 6/0x3B (vidrio_rompe.wav), est de rotura (efectos_ventana.json), modelo -> Ventana_rota '
                   '(et0001), SetAtariOff (se va la colision SAT/EAT), etc flag bit0 = rota (queda rota en el cuarto)',
            lista=ventanas),
        vallas=dict(
            deteccion='pl_class.cpp actWallCheck + fanceCheck: pared a 1 m adelante (a +0.4 m de altura), tambien a +-0.35 m '
                      'a los costados; su attr SAT tiene 0x20; del otro lado (1 m detras de la pared) nada entre +-0.4 m y '
                      'un piso a menos de 0.3 m de la altura de Leon. Cartel JUMP_OVER, fanceOn -> pl_R1_Fance',
            salto='clip valla_saltar (ancha: fanceWidthCheck) o valla_saltar_angosta; MotBase ancla = punto de la pared + '
                  'normal * 0.4 m (del lado de Leon), yaw = mirando a la pared; Leon converge al ancla en 10 frames y despues '
                  'sigue la raiz (1.90 m hacia adelante); colision con paredes off (atari.clrFlag100), sin dano',
            lista=vallas,
            nota='en r100 NO hay cornisas para bajar (attr 0x100010), paredes para saltar (0x80000) ni escalones (0x200000 / '
                 '0x2000): la unica accion de "saltar" son las 2 vallas y las ventanas'),
        puertas=dict(
            casa=dict(etc_no=2, id='0x0D (et0d00)', tipo_emdoor=1, cartel='OPEN',
                      estados='r100_DoorCk: trabada ABIERTA (+90 grados) hasta Rsf 3 (s03); despues normal hasta que la '
                              'emboscada encuentra a Leon (Rsf 10): se CIERRA y queda trabada (area 11 = golpe + mensaje 0xB) '
                              'hasta Rsf 4; luego normal',
                      deteccion='emdoor.cpp emDoorActEvtCk: puerta cerrada y con hp, Leon mirando la puerta (+-45 grados '
                                'de su eje, de cualquiera de los 2 lados), a 0..0.8 m de la puerta, dentro del ancho y '
                                '+-0.5 m de altura',
                      abrir='plemDoorOpen: clip puerta_abrir (pl00 0x1E); si se vuelve a apretar A en 45 frames -> patada',
                      patear='plemDoorKick: puerta_patada (0x1C, se abre en f14) o puerta_patada_trabada (0x1D, golpes f14/17)'),
            a_r101=area.get(0)),
        policias=dict(
            hablar=dict(areas=[area.get(25), area.get(26)],
                        cartel='TALK (A)', condicion='antes de Rsf 10 (vivos, junto a la camioneta); el punto 0.55 m '
                                                     'adelante de Leon dentro del area; sin chequeo de mirada',
                        resultado='area 0x19 -> evento r100s41 (policia al volante), area 0x1A -> r100s43; ver '
                                  'out/evento_s41, out/evento_s43'),
            apuntarles=dict(condicion='antes de Rsf 10: apuntando con el LASER sobre la camioneta/policias (colision de '
                                      'efectos tipo ROOM1 de r100 con AtEffInfo flag 2 = "no disparar", a menos de 20 m) '
                                      '-> STA_PL_DONT_FIRE; al apretar DISPARO (A, Key.trg 0x80) no dispara y un policia '
                                      'reacciona',
                            quien='Room_flg[2] 0x40000000 (area 36, del lado del conductor) -> policia pl0700 motion 0x35 + '
                                  'SE 6/6; si no -> policia pl0700a motion 0x36 + SE 6/5; mensaje 0x33',
                            clips='out/r100_intro/policia_juego.glb / policia_a_juego.glb clip "hablar"; sonidos '
                                  'out/r100_intro/audio/se_policia_hablar.wav / se_policia_a_hablar.wav',
                            mensaje_0x33='sin texto: codigo 9 = espera de 0x5A = 90 frames (mes.cpp code09) con attr 0x52 '
                                         '(no para el juego): es solo un temporizador invisible de 3 s; lo que se oye '
                                         'es el SE del policia',
                            vuelta='al terminar la motion (W->cnt = largo) vuelven a "quieto" con hokan 10')),
        patada=dict(
            cartel='KICK (A, slot 11: le gana a todo lo demas; funciona APUNTANDO)',
            condicion='em10ActEvtSetKick: ganado vivo, Leon a <= 1.5 m (l_pl <= 2250000), el ganado dentro de +-60 grados '
                      'del frente de Leon, |dy| <= 0.7 m, sin pared SAT entre los dos a 1.5 m de altura',
                      # noqa
            cuando_se_ofrece={
                'golpe_cabeza (em10_R1_Dm_Head)': 'todo el clip -> patada_frontal (em10KickAction)',
                'rodilla (Dm_Small tipos 8/9: tiro en la CANILLA, 2 de 3 veces motion 0x39)':
                    'TmpU32 = 1 -> patada; antes del Free 2 de la motion = patada_frontal; desde el Free 2 (Be_flg '
                    '0x40000000: ya de rodillas) = patada (roundhouse, pl00 0x25, em10KneeDownAction)',
                'flash (Dm_Flash)': 'todo el clip (no hay granadas en r100)'},
            cuchillo={'cabeza': 'el cuchillo en la CABEZA (parte 5) va SIEMPRE a Dm_Head (no pasa por el 1-de-3 sin '
                                'reaccion) -> patada_frontal disponible todo el clip',
                      'canilla': 'Dm_Small tipo 8/9 como la bala (2/3 rodilla -> patada; 1/3 caer_pierna) pero el '
                                 'cuchillo antes tira Rnd()%3 == 0 -> SIN reaccion (1 de 3 cuchilladas)',
                      'cuerpo / brazos / muslo': 'Dm_Small tipos 0..7: NO ofrecen patada',
                      'nota': 'el cuchillo que MATA en la cabeza no la revienta (m_Wep != 0x10)'},
            clips={'de_pie': 'patada_frontal (em10:665 = 0x29D del archivo del ganado)',
                   'de_rodillas': 'patada (pl00:33 = 0x25, el roundhouse)'},
            golpe='frame 16: esferas de 1.2 m en (0, 1.5, 0.3) y (0, 1.0, 0.3) m del espacio de Leon, arma 0x14 (200) a '
                  'TODOS los ganados que toquen -> em10_R1_Dm_Blow (vuela). SE 1/0xF por esfera que pega',
            gira='hacia el ganado a <= 0.196 rad/frame durante 10 (frontal) / 12 (rodillas) frames',
            cancelable='desde f33 (frontal) / f35 (rodillas) con apuntar o moverse; si no hasta el final',
            invulnerable='dmg.set(0, 0x1E) durante la patada; GameAddPoint CRITICALHIT',
            sonidos='out/sonidos/combate/patada_voz.wav (1/0x10) + patada_swing.wav (1/0x11) al terminar el giro, '
                    'patada_impacto.wav (1/0xF)'),
        areas_aev=aev,
        otros='cajas de madera: etc 3..9 = cEmBox (et01/et02) se rompen a tiros / cuchillo (sin cartel en r100); '
              'no hay escaleras de mano, escondites ni items de "PICK UP" por AEV en r100 (ITA aparte)',
        verificacion=verif)
    doc['sonidos'] = sonidos()
    doc['efectos'] = dict(json='out/combate/efectos_ventana.json', grupos=efectos(etm),
                          trozos_glb='out/combate/vidrio_trozos.glb')
    doc['salto_ventana'] = ('out/combate/salto_ventana.json (re4_extract_salto_ventana.py, correr DESPUES de este): '
                            'el evento del salto cuadro por cuadro, la camara por frame en el espacio de la ventana, '
                            'los trozos de vidrio, efectos y sonidos')
    doc['modelos'] = dict(ventana='out/combate/ventana.glb (nodos Ventana_intacta / Ventana_rota, espacio de la ventana: '
                                  'ponerlos en pos_m con yaw_rad; al romperse ocultar intacta y mostrar rota)',
                          dibujo='las ventanas van en la capa TRANSLUCIDA (ot_type = WindowData.type2 = 1: despues de lo '
                                 'opaco). Intacta: UN quad doble (4 triangulos) con el marco PINTADO en la textura 0 (CMPR) y el alpha de la '
                                 'textura 1 (I4): vidrio mezclado (alphaRef 0 -> BLEND). Rota: el marco de madera '
                                 'MODELADO + picos de vidrio en los bordes (76 triangulos), textura 0 sin alpha (opaco); EtcSetAddAmb(6) = ambiente de "ventana"; luz propia LightInfo.init2 2 m',
                          trozos='out/combate/vidrio_trozos.glb: efm_0e (4 partes, textura 16x16) y efm_10 (3 partes, 2x2): '
                                 'cada parte material es un trozo que obj05 hace volar',
                          caja_intacta_m=caja(m_int), caja_rota_m=caja(m_rota))
    doc['clips'] = {k: dict(glb='out/combate/leon_combate.glb', frames=clips[k]['frames'],
                            eventos=clips[k].get('eventos'), total_m=clips[k]['raiz']['total_m'],
                            total_y_m=clips[k]['raiz'].get('total_y_m'))
                    for k in ('ventana_saltar_afuera', 'ventana_saltar_adentro', 'ventana_saltar_abajo', 'valla_saltar',
                              'valla_saltar_angosta', 'patada_frontal', 'puerta_abrir', 'puerta_patada',
                              'puerta_patada_trabada', 'patada')}
    with open(os.path.join(OUT, 'acciones.json'), 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    for l in verif:
        print(' ', l)
    print('-> out/combate/acciones.json')


if __name__ == '__main__':
    main()
