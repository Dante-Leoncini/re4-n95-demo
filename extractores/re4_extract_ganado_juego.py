#!/usr/bin/env python3
"""
El GANADO de r100 (el aldeano de la casa, el de la cutscene r100s03) con sus animaciones de JUEGO -> GLB para
Whisk3D, sobre el MISMO esqueleto y las MISMAS mallas que el modelo de la cutscene (ganado_evento.glb de
re4_extract_personajes_evento.py): asi, terminada la cutscene, la misma armadura "Ganado" puede seguir con estos
clips.

  out/ganado_juego/ganado_juego.glb     armadura "ganado" (hueso_000..hueso_033 = las 34 partes de em1000.bin),
                                         mallas Ganado_ev_cuerpo / _mano_der / _cara (9 shapes) / _ojos / _mano_izq
                                         (identicas a ganado_evento.glb) + Ganado_hacha, clips de juego
  out/ganado_juego/ganado_juego_atlas.png   atlas a resolucion completa (las texturas del evento + la del hacha)
  out/ganado_juego/clips.json           por clip: motion / seq de origen, espejo, frames, loop, desplazamiento de la
                                         raiz por ciclo, frames clave (del campo Free de la secuencia) y bbox

DE DONDE SALE (la decompilacion ../re4/src):
  - El aldeano de la casa NO es de em10.drs: st1/r100.cpp R100Init lo pone a mano con EmSetEvent(id 0x12, type 0,
    set 0x13, flag 0x21000020, hp 500): id 0x12 = EmFileTbl[0x12] = FileTbl[0x2B] = em/em12.das -> em12.drs (el
    modulo em12 = em10.cpp + em12_set.cpp). Sus motions son las de em10.drs (mismos bytes), pero em12.drs trae
    solo el subconjunto que usa. Cuerpo ARC 0x1BC (= em1000.bin del evento, mismo esqueleto), mano derecha 0x1C0
    (= em10rh00), mano izquierda 0x1C8 (= em10lh03, la de agarre: em10HandSet con arma y zurdo), hacha
    ARC 0x26C / 0x26D (Em12WeaponSet mot[65] / mot[66]; mismo .bin y .tpl que el prop obm0300 del evento).
  - flag 0x20000000 -> Wep_type 2 = hacha (em10WeaponInit), flag 0x01000000 -> ZURDO: el hacha va en la parte
    0x10 (hueso_016 = mano IZQUIERDA; em10WeaponSet: pos (313.85, -21.2, 102.21) mm, ang (0, -1.0402162, pi)) y
    todas las motions "de arma" (quieto, caminar, correr, atacar, retroceder, golpe en la cabeza) se reproducen
    ESPEJADAS (MotionSetCore flag 0x40 con em10_xflip_tbl: partes 5..10 <-> 11..16, 18..21 <-> 22..25; rot y/z
    y pos x negadas, idem la raiz). Aca el espejo se aplica a los datos de la motion antes de evaluarla con el
    codigo del juego (evalhost), exactamente como lo hace MotionMoveCore.
  - Que motion usa cada rutina: em10.cpp (em10SetWaitMotion, em10SetWalkMotion, em10SetDashMotion,
    em10_R1_AxeAtk, em10_R1_Catch, em10_R1_NeckHang, em10_R1_Dm_*, em10_R1_DownWake, em10_R1_Die_*, ...),
    ver CLIPS abajo (PL_ARC n = entrada n - 4 del .drs).

CONVENCIONES (como leon.glb / ganado_evento.glb): nodo raiz "ganado" + hueso_NNN, metros, 30 fps,
extras.frameRate. DIFERENCIA con los clips del evento: aca la raiz es LOCAL. hueso_000 lleva el movimiento de
la raiz de la motion (claves "Null" pos/rot, lo que el juego suma a em->pos / em->ang con Mot_attr bit 0) relativo
al frame 0: el clip arranca en el origen de la armadura mirando a +Z, y la armadura la ubica / rota Lua.
  - raiz(f) = [RotMatrix(A(f) - A(0)) | RotY(-A(0).y) * (P(f) - P(0))] delante del l_mat de la parte 0
    (motion.cpp MotionGetSpeed / MotionAddSpeed: el juego acumula exactamente eso en em->pos / em->ang).
  - Clips en loop: el ultimo frame es el cierre del ciclo (= frame 0 + el desplazamiento del ciclo). Para
    reproducir el juego, al dar la vuelta Lua suma a la armadura el "raiz_ciclo_m" (girado por el yaw de la
    armadura) y el "giro_ciclo_rad". El clip ya trae el avance dentro del ciclo: NO mover ademas la armadura
    por velocidad (velocidad_m_s en clips.json es solo informativa: raiz_ciclo / periodo).
  - Cambio de clip a mitad de un ciclo: sumar a la armadura la raiz del frame actual (clips.json
    "raiz_por_frame"[f] = [x, y, z, yaw]) antes de arrancar el clip nuevo; el juego hace lo mismo (em->pos
    acumula frame a frame).
  - Sin loop: al terminar, Lua suma a la armadura el desplazamiento final (raiz_final_m / giro_final_rad) y
    cambia de clip.

Uso:
  python3 re4_extract_ganado_juego.py            # -> out/ganado_juego/*
  python3 re4_extract_ganado_juego.py --render   # + PNG de control (poses clave) en out/ganado_juego/control/
"""
import argparse
import copy
import json
import math
import os
import sys

import numpy as np

import re4_extract_leon as L
import re4_evento as E
import re4_extract_ganado as G
import re4_extract_personajes_evento as P
from motion import modelbin, meshbin, gxtex, gltf, fcv, evalhost  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'ganado_juego')
ARCHIVO = 'em12'          # EmFileTbl[0x12]
FPS = 30.0

# em10.cpp em10_xflip_tbl (MotionWork::flip): parte -> parte espejo
XFLIP = [0x00, 0x01, 0x02, 0x03, 0x04, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x05, 0x06, 0x07, 0x08, 0x09,
         0x0A, 0x11, 0x16, 0x17, 0x18, 0x19, 0x12, 0x13, 0x14, 0x15, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
         0x20, 0x21, 0x22, 0x23]

# El hacha (em10WeaponSet, Wep_type 2, zurdo: pos.x = -pos.x, rot.z = -rot.z + pi; setParent(em, 0x10))
HACHA_BIN, HACHA_TPL = 0x26C, 0x26D        # Em12WeaponSet mot[65] / mot[66]
HACHA_HUESO = 0x10
HACHA_POS = (313.85, -21.2, 102.21)
HACHA_ANG = (0.0, -1.0402162, 3.1415927)

# Significado de los bits del campo Free de las secuencias segun la rutina que las lee (em10.cpp)
FREE_ATAQUE = {1: 'golpe activo (em10AtkCk: esfera del hacha contra Leon)', 8: 'giro lento hacia Leon (0.049 rad/f)',
               0x20: 'SE del hachazo'}
FREE_AGARRE = {2: 'ventana de agarre (em10CatchCk)', 8: 'giro hacia Leon'}
FREE_DANO = {1: 'impacto contra el piso (efecto de polvo)', 2: 'aturdido: Leon puede patearlo (Be_flg 0x40000000)',
             4: 'puede cortar la motion aca', 0x80: 'ya esta en el piso (Be_flg 0x10: caido)', 0x10: 'IK off (cae)'}
FREE_CAIDA = {1: 'impacto contra el piso', 2: 'salpicadura / polvo', 4: 'chequeo de piso (termina la caida)',
              0x10: 'IK off', 0x80: 'ya esta en el piso'}
FREE_GIRO = {8: 'ventana de giro hacia el objetivo', 4: 'giro final', 1: 'aviso (FindNotify)'}
FREE_LEVANTA = {2: 'polvo / agua', 0x80: 'todavia en el piso (Be_flg 0x10)'}
FREE_ESTRANGULA = {1: 'Leon lo patea: impacto', 2: 'polvo', 0x10: 'empuja a los otros (em10SetCrash)',
                   0x80: 'en el piso'}

# (nombre, transicion (hokan: frames de mezcla desde la pose anterior que pasa la rutina a MotionSetCore), motion
#  PL_ARC, seq PL_ARC | None, espejo, loop, bits Free, fuente, nota)
# espejo=True: como lo reproduce ESTE ganado (zurdo) o la variante espejada de una reaccion de lado.
CLIPS = [
    # ---- locomocion (zurdo: flag 0x45 = loop + raiz + espejo) ----
    ('quieto', 10, 5, None, True, True, None, 'em10SetWaitMotion (Wep_type 2 -> ARC 5; arranque en frame al azar)', ''),
    ('caminar_hacha', 7, 0xD8, 0xD9, True, True, None,
     'em10SetWalkMotion kind 3: con arma y Be_flg 0x100 (jugador encontrado; tras la cutscene lo esta, em10HideOff)',
     'la caminata de persecucion real de este ganado (seq variante 0: emset_no 0xFF % 5 = 0)'),
    ('caminar', 7, 8, 9, True, True, None, 'em10SetWalkMotion kind 0, Walk_type 0 (Rnd & 1)',
     'caminata sin haber encontrado al jugador'),
    ('caminar_b', 7, 0xE, 0xF, True, True, None, 'em10SetWalkMotion kind 0, Walk_type 1', 'variante al azar de caminar'),
    ('correr', 5, 0xAE, 0xAF, True, True, None, 'em10SetDashMotion (sin arma especial -> 0xAE, seq v=0)', ''),
    ('retroceder_hacha', 5, 0xE4, 0xE5, True, True, None, 'em10_R1_Back EM10_BACK_MOT(0xE4, 0xE5) (con arma)',
     'retrocede cuando Atk_wait corre y Leon esta a < 2 m'),
    ('cubrirse_caminando', 30, 6, 7, True, True, None, 'em10_R1_GuardWalk (0x14): camina cubriendose la cabeza',
     'flag 5 / 0x45 al azar'),
    ('girar180', 10, 0x18, 0x19, False, False, FREE_GIRO, 'em10_R1_Turn180 flag 1 (Go_dir >= 0)', ''),
    ('girar180_espejo', 10, 0x18, 0x19, True, False, FREE_GIRO, 'em10_R1_Turn180 flag 0x41 (Go_dir < 0)', ''),
    ('amenazar', 30, 0x71, 0x72, False, False, None, 'em10_R1_Threat / Guard (jugador del lado +)', ''),
    ('amenazar_espejo', 30, 0x71, 0x72, True, False, None, 'em10_R1_Threat / Guard (jugador del lado -)', ''),
    ('cubrirse', 30, 0x78, None, False, False, None, 'em10_R1_Guard modo 0 (flag 1; modo 1 = espejo)',
     'se cubre la cabeza cuando Leon le apunta a la cabeza (em10HeadLockCk)'),
    # ---- ataque ----
    ('ataque_hacha', 10, 0x80, 0x81, True, False, FREE_ATAQUE, 'em10_R1_AxeAtk (flag 0x41 por zurdo)', 'hachazo'),
    # ---- agarre (solo si perdio el arma: em10CatchPLRtnCk exige pWeapon == 0) ----
    ('agarrar', 10, 0x86, 0x87, False, False, FREE_AGARRE, 'em10_R1_Catch: objetivo a < 75 grados', ''),
    ('agarrar_lado', 10, 0x88, 0x89, False, False, FREE_AGARRE, 'em10_R1_Catch: 75..112 grados, ang > 0 (espejo si < 0)', ''),
    ('agarrar_atras', 10, 0x8A, 0x8B, False, False, FREE_AGARRE, 'em10_R1_Catch: > 112 grados, ang > 0 (espejo si < 0)', ''),
    ('estrangular', 5, 0x28F, None, False, False, None, 'em10_R1_NeckHang paso 0 (Leon agarrado del cuello)',
     'mientras dura: 10 de dano por frame a Leon; termina al frame 35 o por EmCatchMotionMove'),
    ('estrangular_suelta', 5, 0x290, 0x291, False, False, None, 'em10_R1_NeckHang paso 2 (Leon no se solto a tiempo)', ''),
    ('estrangular_pateado', 5, 0x292, 0x293, False, False, FREE_ESTRANGULA,
     'em10_R1_NeckHang paso 4 (Leon se suelta y lo patea)', 'queda en el piso -> levantarse_boca_arriba/abajo'),
    # ---- golpes (Dm_Small / Dm_Head) ----
    ('golpe_cuerpo', 6, 0x26, 0x27, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 0 (torso de frente); alterna espejo', ''),
    ('golpe_cuerpo_b', 6, 0x28, 0x29, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 0/1 (torso o brazo derecho)', ''),
    ('golpe_brazo_izq', 6, 0x2A, 0x2B, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 3 (brazo izquierdo, parte 0xE)', ''),
    ('golpe_brazo_fuerte', 6, 0x33, 0x34, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 1/2 (brazo / antebrazo derecho)', ''),
    ('golpe_brazo_fuerte_espejo', 6, 0x33, 0x34, True, False, FREE_DANO, 'em10_R1_Dm_Small tipo 3/4 (lado izquierdo)', ''),
    ('golpe_mano', 6, 0x32, None, False, False, None, 'em10_R1_Dm_Small tipo 2 (antebrazo derecho, sin soltar)', ''),
    ('golpe_mano_espejo', 6, 0x32, None, True, False, None, 'em10_R1_Dm_Small tipo 4 (antebrazo izquierdo)', ''),
    ('soltar_hacha', 6, 0x55, 0x56, True, False, None,
     'em10_R1_Dm_Small tipo 4 con arma y zurdo (tiro al antebrazo IZQ.: suelta el hacha, setWeaponFall)', ''),
    ('golpe_espalda', 6, 0x45, 0x46, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 7 (tiro por la espalda)', ''),
    ('golpe_espalda_mano', 6, 0x47, 0x48, False, False, FREE_DANO,
     'em10_R1_Dm_Small tipo 0xA (antebrazo derecho por la espalda; 0xB = espejo)', ''),
    ('golpe_cabeza', 6, 0x2C, 0x2D, True, False, FREE_DANO, 'em10_R1_Dm_Head (flag 0x41 por zurdo) variante 0',
     'aturdido: se toma la cara'),
    ('golpe_cabeza_b', 6, 0x2E, 0x2F, True, False, FREE_DANO, 'em10_R1_Dm_Head variante 1', ''),
    ('golpe_cabeza_c', 6, 0x30, 0x31, True, False, FREE_DANO, 'em10_R1_Dm_Head variante 2 (solo de frente)', ''),
    ('golpe_pierna_der', 6, 0x35, 0x36, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 5 (muslo derecho, parte 0x13)', ''),
    ('golpe_pierna_izq', 6, 0x35, 0x36, True, False, FREE_DANO, 'em10_R1_Dm_Small tipo 6 (muslo izquierdo, parte 0x17)', ''),
    ('golpe_pierna_b_der', 6, 0x37, 0x38, False, False, FREE_DANO, 'em10_R1_Dm_Small tipo 5 variante 1', ''),
    ('golpe_pierna_b_izq', 6, 0x37, 0x38, True, False, FREE_DANO, 'em10_R1_Dm_Small tipo 6 variante 1', ''),
    ('rodilla_der', 6, 0x39, 0x3A, False, False, FREE_DANO,
     'em10_R1_Dm_Small tipo 8 (canilla derecha, parte 0x14)',
     'cae sobre una rodilla y se levanta; aturdido (Free 2): la patada de Leon (A) sale como roundhouse'),
    ('rodilla_izq', 6, 0x39, 0x3A, True, False, FREE_DANO, 'em10_R1_Dm_Small tipo 9 (canilla izquierda)', ''),
    ('caer_pierna_der', 6, 0x51, 0x52, False, False, FREE_DANO,
     'em10_R1_Dm_Small tipos 5/8 (1 de 3): le barren la pierna, cae de espaldas (Be_flg 0x20)',
     'queda en el piso: sigue levantarse_boca_arriba'),
    ('caer_pierna_izq', 6, 0x51, 0x52, True, False, FREE_DANO, 'em10_R1_Dm_Small tipos 6/9 (1 de 3)', ''),
    # ---- caidas / en el piso / levantarse ----
    ('caer_aturdido', 15, 0x3D, 0x3E, False, False, FREE_DANO, 'em10_R1_Dm_KneeDown de frente (Be_flg 0x20)', ''),
    ('caer_aturdido_atras', 15, 0x49, 0x4A, False, False, FREE_DANO, 'em10_R1_Dm_KneeDown por la espalda', ''),
    ('caer_atras', 3, 0x43, 0x44, False, False, FREE_CAIDA, 'em10_R1_Dm_Blow golpe de frente (patada), variante 0',
     'vuela hacia atras y queda boca ABAJO (Be_flg 0x20 = 0); espejo al azar'),
    ('caer_atras_b', 3, 0x3F, 0x40, False, False, FREE_CAIDA, 'em10_R1_Dm_Blow golpe de frente, variante 1 (Be_flg 0x20)', ''),
    ('caer_adelante', 3, 0x4B, 0x4C, False, False, FREE_CAIDA, 'em10_R1_Dm_Blow golpe por la espalda, variante 0 (0x20)', ''),
    ('caer_adelante_b', 3, 0x4D, 0x4E, False, False, FREE_CAIDA, 'em10_R1_Dm_Blow golpe por la espalda, variante 1', ''),
    ('caer_muerto', 3, 0x3B, 0x3C, False, False, FREE_CAIDA, 'em10_R1_Dm_Blow que mata (hp <= 0), variante comun', ''),
    ('caer_muerto_b', 3, 0x41, 0x42, False, False, FREE_CAIDA,
     'em10_R1_Dm_Blow que mata, golpe de frente (3 de 10 de las muertes de frente)', ''),
    ('desplomarse', 15, 0x69, 0x6A, False, False, FREE_DANO, 'em10_R1_Dm_KnockOut (muere caminando / brazo)', ''),
    ('tropezar', 15, 0x59, 0x5A, False, False, FREE_DANO, 'em10_R1_Dm_DashDown (tiro en la pierna corriendo)', ''),
    ('caido_golpe_boca_arriba', 5, 0x4F, None, False, False, None, 'em10_R1_Dm_Down con Be_flg 0x20 (le pegan en el piso)', ''),
    ('caido_golpe_boca_abajo', 5, 0x50, None, False, False, None, 'em10_R1_Dm_Down sin Be_flg 0x20', ''),
    ('levantarse_boca_arriba', 15, 0x6D, 0x6E, False, False, FREE_LEVANTA, 'em10_R1_DownWake con Be_flg 0x20', ''),
    ('levantarse_boca_abajo', 15, 0x6F, 0x70, False, False, FREE_LEVANTA, 'em10_R1_DownWake sin Be_flg 0x20', ''),
    # ---- muerte ----
    ('morir', 15, 0x67, 0x68, False, False, FREE_DANO, 'em10_R1_Die_Normal (flag 1: sin espejo)', 'muere de pie'),
    ('morir_boca_arriba', 6, 0x6B, None, False, False, None, 'em10_R1_Die_Down con Be_flg 0x20', 'muere estando en el piso'),
    ('morir_boca_abajo', 6, 0x6C, None, False, False, None, 'em10_R1_Die_Down sin Be_flg 0x20', ''),
]


# ---------------------------------------------------------------------------------------------------
#  espejo (MotionMoveCore con Mot_attr 0x40)
# ---------------------------------------------------------------------------------------------------
def _neg(fmt, v):
    if fmt == 'f':
        return -v
    lim = 32767 if fmt == 'h' else 127
    return max(-lim - 1, min(lim, -v))


def _negar_eje(ax, fcc_type):
    vf, tf = fcv.FCC_FMT[fcc_type]
    nuevas = []
    for k in ax.keys:
        if tf is None:
            nuevas.append((_neg(vf, k[0]),) + tuple(k[1:]))
        else:
            nuevas.append((_neg(vf, k[0]), _neg(tf, k[1]), _neg(tf, k[2])))
    ax.keys = nuevas


def espejar(m):
    """La motion como la ve el juego con Mot_attr 0x40: cada canal va a la parte XFLIP[partsNo]; rotaciones con
    y / z negadas, posiciones (incluidos los objetivos de IK) con x negada; la raiz (claves Null) igual que
    MotionGetSpeed: pos.x y ang.y / ang.z negadas. IKInit usa los numeros de parte SIN remapear: los bits de
    cadena IK (kind 0x30 / 0x80 y el eje, bits 8-11) se quedan en la parte original, asi que se intercambian entre
    los canales espejo (en estas motions las dos piernas tienen la misma configuracion: se verifica)."""
    m2 = copy.deepcopy(m)
    por_parte = {j.parts_no: j for j in m.joints if j.target() is not None}
    for j in m2.joints:
        if j.kind == fcv.KIND_ROOT_POS:
            _negar_eje(j.axes[0], j.fcc_type)
            continue
        if j.kind == fcv.KIND_ROOT_ROT:
            _negar_eje(j.axes[1], j.fcc_type)
            _negar_eje(j.axes[2], j.fcc_type)
            continue
        t = j.target()
        if t == 'rot':
            _negar_eje(j.axes[1], j.fcc_type)
            _negar_eje(j.axes[2], j.fcc_type)
        elif t == 'pos':
            _negar_eje(j.axes[0], j.fcc_type)
        if t is None:
            continue
        original = j.parts_no
        destino = XFLIP[original]
        if j.kind & 0x30:
            otro = por_parte.get(destino)
            if otro is None or (otro.kind & 0xB0, otro.channel) != (j.kind & 0xB0, j.channel):
                raise ValueError(f'cadena IK asimetrica: parte {original} kind {j.kind:#x}/{j.channel} vs '
                                 f'{destino} {None if otro is None else (hex(otro.kind), otro.channel)}')
        j.parts_no = destino
    return m2


# ---------------------------------------------------------------------------------------------------
#  evaluacion (el codigo del juego) + raiz local
# ---------------------------------------------------------------------------------------------------
def _hermite_raiz(m, kind, frame):
    """Valor (x, y, z) de la clave raiz `kind` (Null pos / rot) en `frame` (HermiteInterpolation, sin loop)."""
    def eje(ax, t):
        if not ax.frames:
            return 0.0
        if len(ax.frames) == 1:
            return P._clave(t, ax.keys[0])[0]
        return P.hermite_eje(ax, t, float(frame), float(m.max_frame))   # >= maxFrame: la ultima llave
    for j in m.joints:
        if j.kind == kind:
            return tuple(eje(ax, j.fcc_type) for ax in j.axes)
    return (0.0, 0.0, 0.0)


def frames_motion(m, seq, loop):
    """Frame de la motion en cada frame de juego (MotionSequenceCtrl). Con loop se agrega el cierre del ciclo
    (maxFrame: la secuencia interpola hacia el final al dar la vuelta, MotionSequenceCtrl nx >= Seq_frame_num)."""
    if seq is not None:
        fr = [k.frame_f for k in seq.keys]
    else:
        fr = [float(f) for f in range(m.max_frame + (0 if loop else 1))]
    if loop:
        fr.append(float(m.max_frame))
    return fr


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def evaluar(skel, m, seq, loop, en_lugar=False):
    """-> (poses, raiz 3x4 por frame (mm), frames de motion, (P, A) de la raiz por frame en espacio de la
    armadura). en_lugar: la raiz del clip conserva solo la altura (P.y) y el cabeceo / rolido (A.x, A.z); el XZ y
    el giro sobre Y quedan fuera del clip (los aplica Lua con la pista pista_x_z_rotY)."""
    fr = frames_motion(m, seq, loop)
    player = evalhost.Player(skel, m, ik=True)
    poses = [player.frame(f) for f in fr]
    p0 = np.array(_hermite_raiz(m, fcv.KIND_ROOT_POS, fr[0]))
    a0 = np.array(_hermite_raiz(m, fcv.KIND_ROOT_ROT, fr[0]))
    ry = rot_y(-a0[1])
    raiz, pr = [], []
    for f in fr:
        p = ry @ (np.array(_hermite_raiz(m, fcv.KIND_ROOT_POS, f)) - p0)
        a = np.array(_hermite_raiz(m, fcv.KIND_ROOT_ROT, f)) - a0
        if en_lugar:
            mm = list(player.rot_matrix([float(a[0]), 0.0, float(a[2])]))
            mm[3], mm[7], mm[11] = 0.0, float(p[1]), 0.0
        else:
            mm = list(player.rot_matrix([float(c) for c in a]))
            mm[3], mm[7], mm[11] = (float(c) for c in p)
        raiz.append(tuple(mm))
        pr.append((p, a))
    return poses, raiz, fr, pr


def claves_free(seq, bits, n):
    """{bit: [frames de juego]} de la secuencia (campo Free)."""
    out = {}
    if seq is None or not bits:
        return out
    for i, k in enumerate(seq.keys[:n]):
        for b in bits:
            if k.free & b:
                out.setdefault(b, []).append(i)
    return out


def rangos(lst):
    """[3, 4, 5, 9] -> [[3, 5], [9, 9]]"""
    out = []
    for v in lst:
        if out and v == out[-1][1] + 1:
            out[-1][1] = v
        else:
            out.append([v, v])
    return out


# ---------------------------------------------------------------------------------------------------
#  skinning en numpy (para las cajas y los PNG de control)
# ---------------------------------------------------------------------------------------------------
class Piel:
    def __init__(self, mallas, rest):
        """mallas: [(P mm (n,3), J (n,4), W (n,4))]"""
        self.P = np.concatenate([m[0] for m in mallas])
        self.J = np.concatenate([m[1] for m in mallas]).astype(int)
        self.W = np.concatenate([m[2] for m in mallas])
        self.rest = np.array(rest)
        self.grupos = np.cumsum([0] + [len(m[0]) for m in mallas])

    def posar(self, pose, raiz):
        n = len(self.rest)
        M = np.zeros((n, 3, 4))
        R = np.array(raiz).reshape(3, 4) if raiz is not None else np.hstack([np.eye(3), np.zeros((3, 1))])
        for j in range(n):
            mj = np.array(pose.mat[j]).reshape(3, 4)
            full = R[:, :3] @ mj
            full = np.hstack([full[:, :3], (R[:, :3] @ mj[:, 3] + R[:, 3])[:, None]])
            M[j] = full
        out = np.zeros_like(self.P)
        for k in range(4):
            Mj = M[self.J[:, k]]
            v = self.P - self.rest[self.J[:, k]]
            out += self.W[:, k:k + 1] * (np.einsum('nij,nj->ni', Mj[:, :, :3], v) + Mj[:, :, 3])
        return out


# ---------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=L.DEFAULT_DISC)
    ap.add_argument('--evd', default='r100s03.evd')
    ap.add_argument('--scale', type=float, default=0.001)
    ap.add_argument('--render', action='store_true', help='PNG de control de algunas poses clave')
    ap.add_argument('--en-lugar', action='store_true',
                    help='clips EN EL LUGAR -> ganado_juego_lugar.glb: hueso_000 sin el XZ ni el giro Y de la raiz '
                         '(como los de leon); la pista quitada va en clips.json raiz.pista_x_z_rotY')
    args = ap.parse_args()
    scale = args.scale
    arc = L.Archivos(args.disc)
    ev = E.Evento(E.resolver_evd(args.evd, args.disc))
    em = arc(ARCHIVO)
    cfg = P.PERSONAJES['ganado']
    modelo = cfg['modelo']
    pref = cfg['pref']

    # ---- esqueleto: el del evento; se verifica contra el cuerpo del juego (ARC 0x1BC) ----
    skel, pisa = P.esqueleto_evento(ev, arc, modelo)
    juego = modelbin.parse(em.entry(0x1BC - 4).data)
    if juego.n_parts != skel.n_parts or any(a.parent != b.parent or max(abs(x - y) for x, y in zip(a.pos, b.pos)) > 1e-4
                                            for a, b in zip(skel.parts, juego.parts)):
        sys.exit('el esqueleto del evento no coincide con el del juego (em12 ARC 0x1BC)')
    if list(skel.blend_table or []) != list(juego.blend_table or []):
        sys.exit('blend table distinta entre evento y juego')
    n = skel.n_parts
    rest = L.rest_world(skel)
    print(f'esqueleto: {n} partes, identico al cuerpo del juego {ARCHIVO}:{0x1BC - 4}' + (f' (reposo de {pisa[0]})' if pisa else ''))

    # ---- piezas: las del evento + el hacha ----
    bin_n, tpl_n = ev.modelos[modelo]
    lista = [(modelo, bin_n, tpl_n)] + ev.piezas_de(modelo)
    fuentes = []
    for nombre, b_n, t_n in lista:
        fuentes.append((nombre, meshbin.parse(G.datos(ev, arc, b_n)), gxtex.parse_tpl(G.datos(ev, arc, t_n)),
                        os.path.splitext(os.path.basename(t_n))[0], b_n, t_n))
    hacha = meshbin.parse(em.entry(HACHA_BIN - 4).data)
    hacha_tex = gxtex.parse_tpl(em.entry(HACHA_TPL - 4).data)
    hacha_pref = f'{ARCHIVO}_{HACHA_TPL - 4:03d}'

    imagenes = {}

    def clave_de(tex, tp, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (tp, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for _, m, tex, tp, _, _ in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, tp, part)
    for part in hacha.parts:
        if part.triangles():
            clave_de(hacha_tex, hacha_pref, part)
    atlas, rects = P.armar_atlas_completo(imagenes)
    H, W = atlas.shape[:2]
    os.makedirs(OUT, exist_ok=True)
    png = 'ganado_juego_atlas.png'
    with open(os.path.join(OUT, png), 'wb') as f:
        f.write(gxtex.png(atlas))
    print(f'atlas: {len(imagenes)} texturas a resolucion completa -> {png} {W}x{H}')

    b = gltf.Builder()
    nodes = [{'name': cfg['raiz'], 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': f'{cfg["raiz"]}_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}

    materials = [{'name': f'{pref}_ev_opaco', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                                       'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                  'extras': {'w3d_transparent': False}}]
    meshes, mesh_nodes, piel = [], [], []

    def material_transp(cutoff):
        nombre_mat = f'{pref}_ev_transparente_{int(round(cutoff * 255)) - 1}'
        idx = next((i for i, mt in enumerate(materials) if mt['name'] == nombre_mat), None)
        if idx is None:
            idx = len(materials)
            materials.append({'name': nombre_mat,
                              'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0,
                                                       'roughnessFactor': 1.0},
                              'alphaMode': 'MASK', 'alphaCutoff': cutoff, 'extras': {'w3d_transparent': True}})
        return idx

    for nombre, m, tex, tp, b_n, t_n in fuentes:
        malla = f'{pref}_ev_{cfg["nombres"].get(nombre, nombre)}'
        prims, nv, nt, cutoff, vs = P.malla_pieza(b, m, tex, tp, clave_de, rects, W, H, scale, 0, None)
        for pr in prims:
            if pr['material'] is None:
                pr['material'] = material_transp(cutoff)
        mesh = {'name': malla, 'primitives': prims, 'extras': {'re4': {'pieza': nombre, 'bin': b_n, 'tpl': t_n}}}
        n_sh = len(m.shapes or [])
        if n_sh:
            mesh['weights'] = [0.0] * n_sh
            mesh['extras']['targetNames'] = [f'shape_{k:02d}' for k in range(n_sh)]
        mesh_nodes.append(len(nodes))
        nodes.append({'name': malla, 'mesh': len(meshes), 'skin': 0})
        meshes.append(mesh)
        # para la verificacion: vertices del .bin con sus pesos
        Pm = np.array([m.position(i) for i in range(len(m.vtx))])
        sk = [m.skin(i) + [(0, 0.0)] * (4 - len(m.skin(i))) for i in range(len(m.vtx))]
        piel.append((Pm, np.array([[j for j, _ in s] for s in sk]), np.array([[w for _, w in s] for s in sk])))
        print(f'  {malla:22s} {nombre:7s} {nv:5d} vertices {nt:5d} triangulos' + (f'  {n_sh} shapes' if n_sh else ''))

    # ---- el hacha: skinneada al 100% a hueso_016 (mano izquierda), en su lugar de reposo ----
    tmp = evalhost.Player(skel, fcv.parse(em.entry(5 - 4).data), ik=False)
    Rh = np.array(tmp.rot_matrix(list(HACHA_ANG))).reshape(3, 4)[:, :3]
    th = np.array(HACHA_POS) + np.array(rest[HACHA_HUESO])
    pos, nrm, uv, idx, index = [], [], [], [], {}
    for part in hacha.parts:
        tris = part.triangles()
        if not tris:
            continue
        k = clave_de(hacha_tex, hacha_pref, part)
        for tri in tris:
            if len({v[0] for v in tri}) < 3:
                continue
            for v in tri:
                i = index.get((k, v))
                if i is None:
                    i = index[(k, v)] = len(pos)
                    pv = Rh @ np.array(hacha.position(v[0])) + th
                    pos.append(tuple(float(c) * scale for c in pv))
                    nrm.append(tuple(float(c) for c in gltf.normalize(list(Rh @ np.array(hacha.normal(v[1]))))))
                    uv.append(L.uv_atlas(hacha.texcoord(v[3]), rects[k], W, H))
                idx.append(i)
    jo = [(HACHA_HUESO, 0, 0, 0)] * len(pos)
    we = [(1.0, 0.0, 0.0, 0.0)] * len(pos)
    prim = L.primitiva(b, pos, nrm, uv, idx, 0, 'opaco', jo, we)
    mesh_nodes.append(len(nodes))
    nodes.append({'name': 'Ganado_hacha', 'mesh': len(meshes), 'skin': 0})
    meshes.append({'name': 'Ganado_hacha', 'primitives': [prim],
                   'extras': {'re4': {'bin': f'{ARCHIVO}.drs:{HACHA_BIN - 4} (ARC {HACHA_BIN:#x}) = obm0300.bin',
                                      'hueso': f'hueso_{HACHA_HUESO:03d}',
                                      'local_mm': {'pos': HACHA_POS, 'ang_rad': HACHA_ANG,
                                                   'orden': 'RotMatrix (Rz*Ry*Rx) + traslacion, relativo al hueso'}}}})
    Ph = np.array([np.array(p) / scale for p in pos])
    piel.append((Ph, np.array(jo), np.array(we)))
    print(f'  Ganado_hacha           {len(pos):5d} vertices {len(idx) // 3:5d} triangulos (100% hueso_{HACHA_HUESO:03d})')
    pielx = Piel(piel, rest)

    # ---- clips ----
    animations, info = [], []
    control = []
    for nombre, hokan, mot, sq, esp, loop, bits, fuente, nota in CLIPS:
        e = em.entry(mot - 4)
        if e.tag != 'FCV':
            sys.exit(f'{nombre}: {ARCHIVO}:{mot - 4} no es FCV')
        m = fcv.parse(e.data)
        seq = None
        if sq is not None:
            es = em.entry(sq - 4)
            if es.tag != 'SEQ':
                sys.exit(f'{nombre}: {ARCHIVO}:{sq - 4} no es SEQ')
            seq = fcv.parse_seq(es.data)
            if seq.flags & 1:
                sys.exit(f'{nombre}: secuencia en reversa no soportada')
        if esp:
            m = espejar(m)
        poses, raiz, fr, pr = evaluar(skel, m, seq, loop, args.en_lugar)
        anim = L.clip_esqueleto(b, nodes, n, poses, nombre, FPS, scale, raiz, skel.roots())
        nf = len(poses)
        # cajas (skinning numpy): en frames repartidos
        muestras = sorted(set([0, nf - 1] + list(range(0, nf, max(1, nf // 12)))))
        cajas = []
        for f in muestras:
            V = pielx.posar(poses[f], raiz[f])
            cajas.append((V.min(0), V.max(0)))
        lo = np.min([c[0] for c in cajas], 0) * scale
        hi = np.max([c[1] for c in cajas], 0) * scale
        V0 = pielx.posar(poses[0], raiz[0])
        c0 = (V0.min(0) * scale, V0.max(0) * scale)
        Vn = pielx.posar(poses[-1], raiz[-1])
        cn = (Vn.min(0) * scale, Vn.max(0) * scale)
        pf, af = pr[-1]
        # pose final: altura de la cadera y hacia donde mira el torso (parte 2, +Z local)
        R = np.array(raiz[-1]).reshape(3, 4)
        cadera = R[:, :3] @ np.array(poses[-1].mat[0]).reshape(3, 4)[:, 3] + R[:, 3]
        frente = R[:, :3] @ np.array(poses[-1].mat[2]).reshape(3, 4)[:, :3] @ np.array([0.0, 0.0, 1.0])
        if cadera[1] > 700:
            pose_final = 'de_pie'
        elif cadera[1] > 400:
            pose_final = 'agachado'
        else:
            pose_final = 'boca_arriba' if frente[1] > 0.5 else ('boca_abajo' if frente[1] < -0.5 else 'de_costado')
        # cierre del loop: la pose (sin la raiz) del ultimo frame contra la del primero
        cierre = None
        if loop:
            cierre = max(float(np.abs(np.array(poses[-1].mat[j]).reshape(3, 4)[:, 3] -
                                      np.array(poses[0].mat[j]).reshape(3, 4)[:, 3]).max()) for j in range(n))
        d = {'clip': nombre, 'motion': f'{ARCHIVO}.drs:{mot - 4} (ARC {mot:#x})',
             'seq': f'{ARCHIVO}.drs:{sq - 4} (ARC {sq:#x})' if sq is not None else None,
             'espejo': esp, 'loop': loop, 'frames': nf, 'duracion_s': round((nf - 1) / FPS, 4),
             'frames_motion': m.max_frame + 1, 'transicion_f': hokan, 'fuente': fuente}
        if nota:
            d['nota'] = nota
        desp = [round(float(c) * scale, 4) for c in pf]
        giro = round(float(af[1]), 4)
        if loop:
            d['raiz_ciclo_m'] = desp
            d['giro_ciclo_rad'] = giro
            d['periodo_s'] = round((nf - 1) / FPS, 4)
            dist = math.hypot(desp[0], desp[2])
            d['velocidad_m_s'] = round(dist / ((nf - 1) / FPS), 4)
        else:
            d['raiz_final_m'] = desp
            d['giro_final_rad'] = giro
        d['pose_final'] = pose_final
        pista = [[round(float(p_[0]) * scale, 4), round(float(p_[2]) * scale, 4), round(float(a_[1]), 4)]
                 for p_, a_ in pr]
        d['raiz'] = {'total_m': pista[-1][:2], 'giro_total_rad': pista[-1][2],
                     'se_mueve': any(abs(v) > 1e-3 for fila in pista for v in fila), 'pista_x_z_rotY': pista}
        d['raiz_por_frame'] = [[round(float(p_[0]) * scale, 4), round(float(p_[1]) * scale, 4),
                                round(float(p_[2]) * scale, 4), round(float(a_[1]), 4)] for p_, a_ in pr]
        if cierre is not None:
            d['cierre_loop_mm'] = round(cierre, 2)
        cl = claves_free(seq, bits, nf)
        if cl:
            d['frames_clave'] = {f'{b_:#x} {bits[b_]}': rangos(v) for b_, v in sorted(cl.items())}
        d['bbox_m'] = {'min': [round(float(c), 3) for c in lo], 'max': [round(float(c), 3) for c in hi]}
        d['bbox_frame0_m'] = {'min': [round(float(c), 3) for c in c0[0]], 'max': [round(float(c), 3) for c in c0[1]]}
        d['bbox_ultimo_m'] = {'min': [round(float(c), 3) for c in cn[0]], 'max': [round(float(c), 3) for c in cn[1]]}
        anim['extras'] = dict(anim['extras'], loop=loop, espejo=esp,
                              **({'raiz_ciclo_m': desp, 'giro_ciclo_rad': giro} if loop else
                                 {'raiz_final_m': desp, 'giro_final_rad': giro}))
        animations.append(anim)
        info.append(d)
        print(f'  {nombre:26s} {nf:4d} f {"loop" if loop else "    "} {"esp" if esp else "   "} raiz {desp} '
              f'giro {giro:+.3f}  alto {c0[1][1] - c0[0][1]:.3f} m, pies y={c0[0][1]:+.3f} -> {pose_final}'
              + (f' cierre {cierre:.2f} mm' if cierre is not None else ''))
        if args.render:
            control.append((nombre, poses, raiz, cl))

    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_ganado_juego.py'},
        'scene': 0,
        'scenes': [{'name': cfg['raiz'], 'nodes': [0] + mesh_nodes}],
        'nodes': nodes,
        'skins': [skin],
        'meshes': meshes,
        'images': [{'uri': png}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': materials,
        'animations': animations,
        'extras': {'modelo': f'{modelo} (cutscene r100s03) = {ARCHIVO} ARC 0x1BC (juego)',
                   'raiz': 'LOCAL: hueso_000 relativo al origen de la armadura (la ubica / rota Lua); ver clips.json',
                   'escala_juego': 'el juego escala este ganado x1.02..1.04 (em10_R0_Init, emset_no 0xFF); aca 1.0 '
                                   'como en la cutscene'},
    }
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    salida = os.path.join(OUT, 'ganado_juego_lugar.glb' if args.en_lugar else 'ganado_juego.glb')
    gltf.write(doc, bytes(b.blob), salida)
    print(f'-> {salida}: {len(meshes)} mallas, {len(animations)} clips')

    with open(os.path.join(OUT, 'clips.json'), 'w') as f:
        json.dump({
            'glb': 'out/ganado_juego/ganado_juego_lugar.glb (en el lugar, --en-lugar) / ganado_juego.glb (raiz en '
                   'el clip); los datos de este json son los mismos para los dos',
            'raiz_pista': 'raiz.pista_x_z_rotY[f] = [x, z, rotY] (m, rad), relativo al frame 0, en el espacio de la '
                          'armadura (+Z adelante): lo que el juego suma a em->pos / em->ang. En ganado_juego_lugar.glb '
                          'hueso_000 NO lo lleva (solo altura y cabeceo / rolido): Lua mueve / gira la armadura con el '
                          'delta de cada frame (en loop, al dar la vuelta suma raiz.total_m / giro_total_rad del ciclo).',
            'fps': FPS, 'archivo': f'em/{ARCHIVO}.drs',
            'convencion': 'hueso_000 lleva la raiz de la motion (claves Null) relativa al frame 0: '
                          'raiz(f) = [RotMatrix(A(f)-A(0)) | RotY(-A0.y)(P(f)-P(0))]. Loop: el ultimo frame es el '
                          'cierre del ciclo; al dar la vuelta sumar raiz_ciclo_m (en el espacio de la armadura: '
                          'girarlo por el yaw de la armadura) y giro_ciclo_rad a la armadura. Sin loop: al terminar '
                          'sumar raiz_final_m / giro_final_rad y cambiar de clip. frames_clave: rangos [desde, hasta] '
                          'de frames de juego (0 = primer frame del clip) con ese bit en el campo Free de la secuencia.',
            'post_cutscene': {'fuente': 'st1/r100.cpp r100_Sce_look',
                              'ganado_pos_m': [-79.116, 0.86, -38.89], 'ganado_yaw_rad': -1.39,
                              'leon_pos_m': [-82.91, 0.86, -38.48], 'leon_yaw_rad': 1.75,
                              'nota': 'al terminar r100s03 el juego teletransporta a los dos aca; el ganado aparece '
                                      'caminando (em10_R1_Hide -> HideOff -> em10WalkRtnSet) con Dash_wait 150 f'},
            'clips': info}, f, indent=1, ensure_ascii=False)
    print(f'-> {os.path.join(OUT, "clips.json")}')

    # ---- verificacion contra ganado_evento.glb ----
    ruta_ev = os.path.join(HERE, 'out', 'evento_s03', 'ganado_evento.glb')
    if os.path.isfile(ruta_ev):
        import struct as st
        with open(ruta_ev, 'rb') as fh:
            data = fh.read()
        jl = st.unpack('<I', data[12:16])[0]
        gev = json.loads(data[20:20 + jl])
        ev_nodes = [(nd['name'], nd.get('translation'), nd.get('children')) for nd in gev['nodes'][:n + 1]]
        mi_nodes = [(nd['name'], nd.get('translation'), nd.get('children')) for nd in nodes[:n + 1]]
        ok = ev_nodes == mi_nodes and gev['skins'][0]['joints'] == skin['joints']
        mallas_ev = [ms['name'] for ms in gev['meshes']]
        print(f'verificacion vs ganado_evento.glb: huesos {"IDENTICOS" if ok else "DISTINTOS"} ({n}), '
              f'mallas del evento {mallas_ev} presentes: {all(x in [mm["name"] for mm in meshes] for x in mallas_ev)}')
        if not ok:
            sys.exit('el esqueleto no coincide con ganado_evento.glb')

    if args.render:
        render_control(control, pielx, os.path.join(OUT, 'control'))


def render_control(control, pielx, carpeta):
    """PNG de control: nube de vertices skinneados (frente y costado) en frames clave."""
    from PIL import Image, ImageDraw
    os.makedirs(carpeta, exist_ok=True)
    g0, g1 = pielx.grupos[-2], pielx.grupos[-1]    # el hacha es la ultima malla
    # la mano izquierda (hueso_016) en azul: vertices con peso mayor a 0.5 en la parte 16
    izq = (pielx.J == 16) & (pielx.W > 0.5)
    izq = izq.any(1)
    izq[g0:g1] = False
    S, PX = 240, 100.0          # px por celda, px por metro
    for nombre, poses, raiz, cl in control:
        nf = len(poses)
        fs = [0, nf // 3, 2 * nf // 3, nf - 1]
        if cl.get(1):
            fs[1] = cl[1][0]
        img = Image.new('RGB', (S * len(fs), 2 * S), 'white')
        dr = ImageDraw.Draw(img)
        for c, f in enumerate(fs):
            V = pielx.posar(poses[f], raiz[f]) / 1000.0
            cx = V[:, 0].mean() if nombre.startswith(('caer', 'caminar', 'correr')) else 0.0
            cz = V[:, 2].mean() if nombre.startswith(('caer', 'caminar', 'correr')) else 0.0
            for r, (i, t, c0) in enumerate(((0, 'frente x', cx), (2, 'costado z', cz))):
                ox, oy = c * S + S // 2, r * S + S - 10
                dr.line([(c * S, oy), (c * S + S, oy)], fill=(180, 180, 255))
                for grupo, col in ((slice(0, g0), (0, 0, 0)), (slice(g0, g1), (220, 0, 0))):
                    for v in V[grupo]:
                        dr.point((ox + (v[i] - c0) * PX, oy - v[1] * PX), fill=col)
                for v in V[izq]:
                    dr.point((ox + (v[i] - c0) * PX, oy - v[1] * PX), fill=(0, 90, 255))
                dr.text((c * S + 4, r * S + 4), f'{nombre} f{f} {t}', fill=(0, 120, 0))
        img.save(os.path.join(carpeta, f'{nombre}.png'))
    print(f'-> PNG de control en {carpeta}')


if __name__ == '__main__':
    main()
