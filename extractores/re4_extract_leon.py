#!/usr/bin/env python3
"""
Extractor de Leon (Resident Evil 4, GameCube) -> GLB para Whisk3D, optimizado para moviles viejos
(Nokia N95): UNA malla skinneada con 2 mesh parts (opaco + transparente), UN atlas de texturas a la
mitad de resolucion, y las armas como objetos RIGIDOS aparte (se cuelgan de la mano con un
constraint Child Of en Whisk3D: una matriz por frame en vez de skinning vertice por vertice).

Lee directo del disco original (.rvz / .iso / .gcm) con dtk (decomp-toolkit) y reusa los parsers de
la decompilacion (../re4/tools/motion): meshbin (modelo .bin), modelbin (esqueleto), gxtex (TPL),
fcv + evalhost (las animaciones, evaluadas con el codigo del propio juego, IK incluida).

Leon se arma como en el juego con la pistola equipada (cPlLeon::setModel + cObjRuger::setMotion, wep/objRuger.cpp):
cuerpo, chaqueta, cabeza, pelo, ojos/pestanas, mano derecha de agarre (wep02:6) y mano izquierda 4
(pl00:0x18). Armas (vertices en el espacio LOCAL del hueso 10 = la mano derecha, que es de donde
las cuelga el juego: pParts->pParent = getPartsPtr(0xA)):
  Leon_pistola   wep02:2 (cObjRuger modelo 0x6: la pistola inicial, weapon_no 2 / item 0x23)
  Leon_cuchillo  pl00:9  (el "face" de la tabla de character.py: en realidad es el cuchillo)

Uso:
  python3 re4_extract_leon.py                     # -> out/leon/leon.glb + leon_atlas.png
  python3 re4_extract_leon.py --sin-anim          # solo la pose de reposo
  python3 re4_extract_leon.py --anim wep02:13=caminar --anim 33=patada   # animaciones a eleccion
  python3 re4_extract_leon.py --evento r100s03.evd   # + los clips s03_cNN de Leon en la cutscene (raiz en el mundo)
  python3 re4_extract_leon.py --combate           # -> out/combate/leon_combate.glb: el set de la demo + recarga,
                                                  #    danos, agarre, muerte y locomocion herida (atlas completo,
                                                  #    malla sin simplificar) + leon_combate_clips.json; + las ACCIONES
                                                  #    (ventanas, vallas, patada frontal, puerta; ACCIONES_ANIMS)

Spec de animacion: [ARCHIVO:]N[+S][=nombre]; N = entrada FCV del archivo (indice PL_ARC - 4), S = entrada SEQ
opcional: la tabla de secuencia que el juego le pasa a MotionSetCore junto a la motion (fija el largo del clip
= cantidad de keys, el frame de motion de cada frame, y los sonidos de pasos/voz: cPlayer::seqSeCtrl).
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf  # noqa: E402

DEFAULT_DISC = os.path.join(HERE, '..', 'Resident Evil 4 (USA) (Disc 1)', 'Resident Evil 4 (USA) (Disc 1).rvz')
DTK = os.path.join(HERE, 'tools', 'dtk')

# (archivo, BIN, archivo, TPL): las piezas del cuerpo con la pistola equipada
CUERPO = [('pl00', 0, 'pl00', 1),     # cuerpo
          ('pl00', 6, 'pl00', 1),     # chaqueta
          ('pl00', 4, 'pl00', 3),     # cabeza
          ('pl00', 2, 'pl00', 3),     # pelo
          ('pl00', 5, 'pl00', 3),     # ojos / pestanas (transparente)
          ('wep02', 6, 'pl00', 13),   # mano derecha de agarre (initWepHand(WEP_ARC 0xA), paleta PL_ARC 0x11)
          ('pl00', 20, 'pl00', 13)]   # mano izquierda 4 (setLeftHand(4) = PL_ARC 0x18)
HUESO_MANO = 10                       # parts 0xA: la mano derecha
LASER_LARGO = 15.0                    # metros (el juego: 19 m o hasta lo que toca)
ARMAS = [('Leon_pistola', 'wep02', 2, 'wep02', 1, False),   # (nombre, BIN, TPL, en espacio del modelo?)
         ('Leon_cuchillo', 'pl00', 9, 'pl00', 1, True)]     # el cuchillo viene en el espacio de Leon

# set de la demo con la pistola: la locomocion que pone cObjRuger::setMotion en m_MotTbl (0 quieto, 2
# caminar, 6 correr, 8 atras, 0xB giro rapido, 0xD/0xF girar) y el arma de pl_handgun.cpp (0x22 draw,
# 0x24 holster, 0x26 aim, 0x29 fire, 0x2D reload), mas acciones del archivo del jugador (pl00).
# OJO: 0x26/0x27/0x28 (y los fire 0x29/0x2A/0x2B) son HORIZONTAL / ARRIBA / ABAJO (verificado renderizando;
# el comentario de pl_handgun.cpp dice down/level/up)
DEMO_ANIMS = ['wep02:7=quieto', 'wep02:13=caminar', 'wep02:17=correr', 'wep02:15=atras', 'wep02:19=giro180',
              'wep02:9=girar_izq', 'wep02:11=girar_der', 'wep02:30=desenfundar', 'wep02:32=enfundar',
              'wep02:34=apuntar', 'wep02:37=disparar', 'wep02:41=recargar',
              'pl00:33=patada', 'pl00:75=golpe', 'pl00:72=morir',
              # la PUNTERIA arriba/abajo: el juego mezcla la horizontal con estas segun el pitch (cMot3, pl_class.cpp)
              'wep02:35=apuntar_arriba', 'wep02:36=apuntar_abajo', 'wep02:38=disparar_arriba', 'wep02:39=disparar_abajo',
              # el CUCHILLO (pl_knife.cpp): desenfundar, quieto (horizontal/arriba/abajo), tajo (idem) y guardar
              'pl00:31=cuchillo_desenfundar', 'pl00:125=cuchillo_quieto', 'pl00:127=cuchillo_arriba', 'pl00:129=cuchillo_abajo',
              'pl00:126=cuchillo_tajo', 'pl00:128=cuchillo_tajo_arriba', 'pl00:130=cuchillo_tajo_abajo',
              'wep02:46=cuchillo_guardar']

# --combate: lo que le falta a la demo para pelear (indices = entrada del archivo = PL_ARC_PTR - 4; +S = su SEQ).
#  - danos (game/pl_dmg.cpp damageNormal, r_no_3 = PL_DM_TYPE de emhit.h: bit0 = desde atras, 0/1 golpe ALTO
#    (a la cabeza, el punto de impacto >= 1.3 m sobre los pies: em_sub.cpp EmAtkSetDamage), 2..5 al cuerpo)
#  - dano fuerte (damageBlow: PL_DM_BACK/AUTO = kind 7/8 -> vuela al piso 0x51 y se levanta 0x4F) y el
#    tambaleo de explosion (damageBlast, kind 9 AUTO_SML, 0x52)
#  - muerte (Pl_R0_Die: 0x4C + SEQ 0x4D; damageBlow muerto: 0x4E + SEQ 0x66)
#  - agarre del ganado (em10/em10.cpp plem10_NeckHang: motions del archivo del GANADO em10 sobre Leon)
#  - locomocion herida (pl_leon.cpp: m_MotTbl 0x5F..0x66 = pl00 0x32..0x39; se usa con vida < 2/3 del maximo,
#    pl_class.cpp dmMotCk)
COMBATE_ANIMS = ['pl00:68=dano_cabeza_frente', 'pl00:69=dano_cabeza_atras',
                 'pl00:70+96=dano_frente', 'pl00:71+97=dano_atras',
                 'pl00:77+99=dano_fuerte', 'pl00:75+76=levantarse', 'pl00:78=dano_tambaleo',
                 'pl00:72+73=muerte', 'pl00:74+98=muerte_fuerte',
                 'em10:659=agarre_estrangulado', 'em10:660=agarre_derribado', 'em10:661=agarre_zafa',
                 'pl00:46+47=herido_quieto', 'pl00:48+49=herido_caminar', 'pl00:50+51=herido_atras',
                 'pl00:52+53=herido_correr']

# --combate, ACCIONES del boton de accion en r100 (ver out/combate/acciones.json, re4_extract_acciones.py):
#  - saltar la VENTANA (game/emwindow.cpp cEmWindow::ExeWindowEvent): las 3 motions vienen del ETM del cuarto (r100.das,
#    GetEtcAddr(arc, "pl00537.fcv") ...), no de pl00.drs; MotionSetCore(pPL, mot, 0, hokan 0, attr 0x201, 0)
#  - la VALLA / ventana ya rota (player.cpp pl_R1_Fance): pl00 0x53+0x54 (ancha) / 0x55+0x56 (angosta)
#  - la patada al ganado aturdido DE PIE (em10.cpp plem10Kick sin r_no_3): motion 0x29D del archivo del GANADO
#    (em10.drs = em12.drs, mismos bytes); la de rodillas es la "patada" (pl00 0x25) que ya estaba
#  - la PUERTA (game/emdoor.cpp): abrir 0x1E, patada que la abre 0x1C, patada trabada 0x1D
ACCIONES_ANIMS = ['etm/r100:pl00537.fcv=ventana_saltar_afuera', 'etm/r100:pl00538.fcv=ventana_saltar_adentro',
                  'etm/r100:pl00536.fcv=ventana_saltar_abajo',
                  'pl00:79+80=valla_saltar', 'pl00:81+82=valla_saltar_angosta',
                  'em10:665=patada_frontal',
                  'pl00:26=puerta_abrir', 'pl00:24=puerta_patada', 'pl00:25=puerta_patada_trabada']

# cuadros clave de las acciones (frame del clip = iteracion del bucle del juego desde MotionSetCore)
EVENTOS_CLIPS = {
    'ventana_saltar_afuera': {'vidrio_rompe': 15, 'est_ventana_8_en_leon': 0,
                              'sonidos': [[3, 1, 0x29], [4, 1, 0x34], [5, 1, 0x43], [35, 5, 5], [41, 5, 0x12], [44, 5, 0x13]],
                              'aterriza': 35, 'fin': 'Motion.Mot_state & 4 (ultimo frame) -> SceEventEnd'},
    'ventana_saltar_adentro': {'vidrio_rompe': 16, 'est_ventana_2_en_leon': 0,
                               'sonidos': [[3, 1, 0x29], [4, 1, 0x34], [5, 1, 0x43], [45, 5, 5], [51, 5, 0x12], [55, 5, 0x13]],
                               'aterriza': 45, 'fin': 'ultimo frame -> SceEventEnd'},
    'ventana_saltar_abajo': {'vidrio_rompe': 13, 'est_ventana_4_en_leon': 0,
                             'sonidos': [[3, 1, 0x29], [4, 1, 0x34], [5, 1, 0x43], [40, 5, 5], [55, 5, 0x12], [57, 5, 0x13]],
                             'aterriza': 40, 'fin': 'ultimo frame -> SceEventEnd'},
    'valla_saltar': {'ajuste_lateral_hasta': 24, 'sonidos': [[28, 5, 0xE], [30, 5, 0xD]], 'cancelable_desde': 30,
                     'motbase_frames': 10},
    'valla_saltar_angosta': {'ajuste_lateral_hasta': 24, 'sonidos': [[28, 5, 0xE], [30, 5, 0xD]], 'cancelable_desde': 30,
                             'motbase_frames': 10},
    'patada_frontal': {'gira_hacia_ganado_frames': 10, 'gira_rad_por_frame_max': 0.19635,
                       'sonidos': [[9, 1, 0x11], [9, 1, 0x10]], 'golpe': 16, 'cancelable_desde': 33},
    'puerta_abrir': {'patada_si_accion_antes_de': 45, 'hokan': 5},
    'puerta_patada': {'puerta_se_abre': 14, 'hokan': 5},
    'puerta_patada_trabada': {'puerta_golpe': [14, 17], 'hokan': 5},
}

# notas por clip para leon_combate_clips.json (frames = frames del clip a 30 fps; SE = SndCall(kind, no))
NOTAS_CLIPS = {
    'disparar': 'wep02:37 = PL 0x29 (horizontal; 0x2A/0x2B arriba/abajo). Tiro (trigger, EstSet muzzle, SE 2/0,1,2, '
                'casquillo, rayo de 50 m desde (234.5, -24, 38.3) mm del hueso 10 con +-0.2 m de dispersion al final) '
                'en el frame 0 (pl_handgun.cpp wep02_r3_fire00); el siguiente tiro se habilita al cruzar el f12 '
                '(PlShotFrameTbl[2][0] = 14, menos 2: wep02_r3_fire10); la pistola corre pistola.glb "disparar"',
    'recargar': 'wep02:41 = PL 0x2D (nivel de recarga 0; mejoras 1/2 = wep02:42 (45 f) / wep02:43 (28 f)); blend de '
                'entrada 3 frames (MotionSetCore hokan 3). La PISTOLA corre a la vez pistola.glb "recargar" (o '
                '"recargar_vacia"): cargador suelto f10, el nuevo entra f26-30 (asentado f30), MUNICION RECARGADA en '
                'f31 (objRuger.cpp moveReload: ItemMgr.reload() en reloadEnd[0] = 31); se puede salir desde f36 '
                '(pl_class.cpp PlReloadEndTbl[2] = 36/32/18 por nivel) -> apuntar (mezcla 8 frames, pl_handgun.cpp '
                'wep02_r2_reload) o enfundar; si no, dura los 52 frames. SE 2/0x16 en f0 (2/0x20, 2/0x21 en las '
                'mejoras), un solo sonido largo que se corta si se interrumpe; vacia: la corredera se suelta en f37',
    'dano_cabeza_frente': 'pl_dmg.cpp damageNormal r_no_3 0 = PL_DM_UP_FRONT (golpe ALTO desde adelante). Blend 5 f, '
                          'gira hacia el atacante, voz de dolor SE 1/(9..11 al azar) en f0 (PlSetDamageSe(0)), cara '
                          'de dolor hasta f20; se puede cortar con cualquier tecla despues de 30 frames (m_Work0 0x1E)',
    'dano_cabeza_atras': 'damageNormal r_no_3 1 = PL_DM_UP_BACK (golpe alto desde atras); se corta despues de 35 f',
    'dano_frente': 'damageNormal r_no_3 2/4 = PL_DM_MIDDLE/DOWN_FRONT (al cuerpo desde adelante; el ataque basico '
                   'del ganado); se corta despues de 35 f',
    'dano_atras': 'damageNormal r_no_3 3/5 = PL_DM_MIDDLE/DOWN_BACK (al cuerpo desde atras); se corta despues de 35 f',
    'dano_fuerte': 'damageBlow (setDamage kind 7/8 = PL_DM_BACK/AUTO: golpe fuerte, explosion): vuela ~3.9 m hacia '
                   'atras y cae; SE 5/5 en f10, efecto pl00 est 5 (polvo); sigue "levantarse"',
    'levantarse': 'pl00 0x4F + SEQ 0x50 (r_no_2 0xA de damageNormal/damageBlow); efecto pl00 est 0xF (polvo); vuelve '
                  'a la rutina 0 al terminar (EndPlDamage, 5 frames invulnerable)',
    'dano_tambaleo': 'damageBlast (kind 9 = PL_DM_AUTO_SML: onda de explosion lejana); cara de dolor hasta f20',
    'muerte': 'Pl_R0_Die: 0x4C + SEQ 0x4D, blend 5 f; grito SE 1/0xD en f0, efecto pl00 est 3, vibracion en f40 y '
              'f70; al terminar queda en el ultimo frame (game over)',
    'muerte_fuerte': 'damageBlow con vida 0: 0x4E + SEQ 0x66; SE 1/0x4A en f0, efecto pl00 est 0xD',
    'agarre_estrangulado': 'em10/em10.cpp plem10_NeckHang: motion del archivo del GANADO (em10 0x297) sobre Leon; el '
                           'ganado corre em10 0x28F. EmCatchPLSet: se miran de frente, el ganado queda en (-0.18, 0, '
                           '0.47) m del espacio de Leon (cada uno se corre la mitad). Arma oculta. Machacar boton '
                           '(PlGacha); en el frame 35 del ganado: <= 9 pulsaciones (x1.5 en facil) -> '
                           'agarre_derribado, si no -> agarre_zafa. Dano 10*poder POR FRAME mientras dura',
    'agarre_derribado': 'em10 0x298: falla el forcejeo, el ganado lo tira: SE 1/9 en f5, en f37 dano 180*poder '
                        '(SE 5/5 + 1/0x12), efecto em10 est 0x21 (polvo); al terminar -> levantarse, o muerte si vida 0',
    'agarre_zafa': 'em10 0x299: se libera de una patada (el ganado corre 0x292 y recibe 100 de dano, 9999 si >30 '
                   'pulsaciones); los primeros 14 f sigue pegado al ganado; SE 1/0x4F en f19, 5/0x14 en f38',
    'herido_quieto': 'pl_leon.cpp m_MotTbl 0x5F (pl00 0x32 + SEQ 0x33): reemplaza a "quieto" cuando la vida < 800 '
                     '(2/3 de 1200: pl_class.cpp dmMotCk / cPlayer::motionSet)',
    'herido_caminar': 'm_MotTbl 0x61 (pl00 0x34 + SEQ 0x35): caminar con vida < 800',
    'herido_atras': 'm_MotTbl 0x63 (pl00 0x36 + SEQ 0x37): retroceder con vida < 800',
    'herido_correr': 'm_MotTbl 0x65 (pl00 0x38 + SEQ 0x39): correr con vida < 800',
    'morir': 'viejo clip de la demo (pl00:72 sin su SEQ, 88 f): usar "muerte"',
    'golpe': 'viejo clip de la demo: es pl00 0x4F = levantarse del piso (sin SEQ); usar "levantarse"',
    'ventana_saltar_afuera': 'emwindow.cpp ExeWindowEvent breakDir 0 (Leon DETRAS de la ventana = lado -Z local, con piso '
                             'del otro lado): r100.das ETM pl00537.fcv. Leon se pone en (90, -1000, -1610) mm del espacio de '
                             'la ventana mirando +Z (ang ventana + 0), evento (colision off: beginEvent throughOn), la raiz '
                             'lo lleva 5.43 m hacia +Z (termina 3.8 m pasada la ventana). Vidrio: SetBreakAll(pos inicial, 1, 1) '
                             'en f15 si no estaba rota (SE 6/0x3B, est 0 de et00.eff, modelo et0001 = marco roto, sin '
                             'colision). SE 1/0x29 f3, 1/0x34 f4, 1/0x43 f5, cuerpo al piso 5/5 f35, pasos 5/0x12 f41, 5/0x13 f44',
    'ventana_saltar_adentro': 'breakDir 1 (Leon DELANTE de la ventana, lado +Z local): pl00538.fcv desde (-210, -1000, '
                              '1990) mm mirando -Z (ang ventana + pi); avanza 5.44 m (termina 3.45 m adentro). Vidrio f16 '
                              '(est 1). SE 1/0x29 f3, 1/0x34 f4, 1/0x43 f5, 5/5 f45, 5/0x12 f51, 5/0x13 f55',
    'ventana_saltar_abajo': 'breakDir 2 (detras y SIN piso del otro lado: CalFloor ve > 3 m de caida, la ventana 1 del '
                            'piso de arriba de r100): pl00536.fcv desde (0, -1000, -980) mirando +Z; avanza 9.24 m y BAJA '
                            '3.24 m (pista_y). Vidrio f13 (est 3). SE 1/0x29 f3, 1/0x34 f4, 1/0x43 f5, 5/5 f40, 5/0x12 f55, '
                            '5/0x13 f57',
    'valla_saltar': 'player.cpp pl_R1_Fance, pl00 0x53 + SEQ 0x54 (valla ANCHA: fanceWidthCheck; las vallas de r100 con '
                    'attr 0x20). MotBase: ancla en (golpe de la pared + normal*400) o PlFancePos (ventana ROTA: ventana + '
                    'lado*400), mirando a traves; Leon converge al ancla en 10 frames y sigue la raiz (1.9 m). hokan 3. '
                    'fanceAdjust hasta f24, SE 5/0xE en f28 y 5/0xD en f30, con una tecla corta desde f30. dmg 2 = no '
                    'recibe dano; atari.clrFlag100 (sin empuje contra paredes)',
    'valla_saltar_angosta': 'pl00 0x55 + SEQ 0x56 (valla angosta; SIEMPRE la de la ventana ROTA: r_no_3 5 -> bit2). Igual '
                            'que valla_saltar',
    'patada_frontal': 'em10.cpp em10KickAction -> plem10Kick sin r_no_3: motion 0x29D del archivo del GANADO (em10:665) '
                      'sobre Leon, hokan 6, attr 1 (raiz). Para el ganado aturdido DE PIE (golpe en la cabeza: '
                      'em10_R1_Dm_Head, tambien con el CUCHILLO en la cabeza; rodilla antes del Free 2). Gira hacia el ganado '
                      '10 frames (max 0.196 rad/f), SE 1/0x11 + 1/0x10 en f9, golpe en f16 (esferas r 1.2 m en (0, 1.5, 0.3) y '
                      '(0, 1.0, 0.3) m del espacio de Leon, arma 0x14 = 200 de dano, SE 1/0xF si pega); se corta desde f33',
    'puerta_abrir': 'emdoor.cpp plemDoorOpen: pl00 0x1E, hokan 5, attr 1; Leon gira hacia la puerta (pi/16 por frame) y '
                    'se desliza 10%/frame a (-638.54, 0, +-440.4) mm del espacio de la puerta; la puerta setOpen2. Accion otra '
                    'vez antes de 45 frames -> puerta_patada desde el frame 6',
    'puerta_patada': 'plemDoorKick (puerta que se puede patear: ckKick): pl00 0x1C; la puerta se abre de golpe en f14 '
                     '(setOpen, campana de ruido)',
    'puerta_patada_trabada': 'plemDoorKick (puerta trabada / no pateable): pl00 0x1D; setShock en f14 y f17',
}


def ensure_dtk():
    if os.path.isfile(DTK):
        return
    os.makedirs(os.path.dirname(DTK), exist_ok=True)
    subprocess.check_call([sys.executable, os.path.join(RE4, 'tools', 'download_tool.py'), 'dtk', DTK, '--tag', 'v1.8.3'])


def extract_from_disc(disc, name, cache_dir):
    """files/em/<name> del disco -> cache_dir/<name> (una sola vez)."""
    out = os.path.join(cache_dir, name)
    if not os.path.isfile(out):
        ensure_dtk()
        os.makedirs(cache_dir, exist_ok=True)
        subprocess.check_call([DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/em/{name}', out])
    return out


class Archivos:
    """plNN / wepNN -> archive.Archive, extrayendo del disco la primera vez."""

    def __init__(self, disc):
        self.disc = disc
        self.cache = {}

    def __call__(self, stem):
        if stem not in self.cache:
            self.cache[stem] = archive.Archive(extract_from_disc(self.disc, f'{stem}.drs', os.path.join(HERE, 'extracted', 'em')))
        return self.cache[stem]

    def etm(self, cuarto, nombre):
        """Un archivo del ETM (archivo "etc" del cuarto: modelos de ventanas/puertas y las motions de Leon para
        saltar ventanas, GetEtcAddr) de St<N>/<cuarto>.das; ej. etm('r100', 'pl00537.fcv')."""
        clave = 'etm:' + cuarto
        if clave not in self.cache:
            dest = os.path.join(HERE, 'extracted', 'St' + cuarto[1])
            das = os.path.join(dest, cuarto + '.das')
            if not os.path.isfile(das):
                ensure_dtk()
                os.makedirs(dest, exist_ok=True)
                subprocess.check_call([DTK, 'vfs', 'cp', f'{os.path.abspath(self.disc)}:files/St{cuarto[1]}/{cuarto}.das', das])
            ent = [e for e in archive.Archive(das).entries() if e.tag == 'ETM'][0]
            self.cache[clave] = dict(archive.parse_etm(ent.data))
        return self.cache[clave][nombre]


def rest_world(skel):
    """Posicion de reposo en mundo de cada parte (la pose de reposo solo traslada: cModel::initJoint)."""
    out = [None] * skel.n_parts
    for p in skel.parts:
        base = (0.0, 0.0, 0.0) if p.parent < 0 else out[p.parent]
        out[p.no] = tuple(base[i] + p.pos[i] for i in range(3))
    return out


def play(skel, motion, ik=True):
    from motion import evalhost
    player = evalhost.Player(skel, motion, ik=ik)
    return [player.frame(f) for f in range(motion.n_frames)]


def play_seq(skel, motion, seq, ik=True):
    """Como play() pero con la tabla de secuencia (SEQ) del juego: un frame por key, en el frame de motion de la key
    (MotionSeqKey.frame, 10.6 fijo; motion.cpp MotionSetCore: Seq_frame_num = cantidad de keys)."""
    from motion import evalhost
    player = evalhost.Player(skel, motion, ik=ik)
    return [player.frame(k.frame_f) for k in seq.keys]


def raiz_movimiento(poses, scale, con_y=False):
    """El DESPLAZAMIENTO de raiz que el juego le aplica al personaje (no va en el clip: los clips quedan en el lugar).
    Con Mot_attr bit0 (MotionSetCore(..., attr 1/5): todas las de dano, muerte, agarre y locomocion) MotionGetSpeed
    (motion.cpp) toma el delta de las keys de raiz (Null_pos / Null_rot) de un frame al siguiente y MotionAddSpeed lo
    suma a pos/ang del modelo; acumulado = key(f) - key(0) en el espacio del personaje al empezar el clip (+Z = adelante,
    +Y arriba). Devuelve el total y la pista por frame [x, z, rotY] (m, rad)."""
    p0, r0 = poses[0].root_pos, poses[0].root_rot
    pista = [[round((p.root_pos[0] - p0[0]) * scale, 4), round((p.root_pos[2] - p0[2]) * scale, 4),
              round(p.root_rot[1] - r0[1], 4)] for p in poses]
    out = {'total_m': pista[-1][:2], 'giro_total_rad': pista[-1][2],
           'se_mueve': any(abs(v) > 1e-3 for fila in pista for v in fila), 'pista_x_z_rotY': pista}
    if con_y:   # los clips de ACCIONES: el juego tambien suma el delta Y de la raiz (MotionAddSpeed; saltar abajo)
        out['pista_y'] = [round((p.root_pos[1] - p0[1]) * scale, 4) for p in poses]
        out['total_y_m'] = out['pista_y'][-1]
    return out


def parse_spec(spec):
    """'[ARCHIVO:]N[+S][=nombre]' -> (archivo, N, S o None, nombre o None). Con ARCHIVO 'etm/rNNN' N es el nombre del
    archivo dentro del ETM del cuarto (ej. 'etm/r100:pl00537.fcv=ventana_saltar_afuera')."""
    ref, _, nombre = spec.partition('=')
    stem, _, idx_txt = ref.rpartition(':')
    idx_txt, _, seq_txt = idx_txt.partition('+')
    if stem.startswith('etm/'):
        return stem, idx_txt, None, (nombre or None)
    return stem or 'pl00', int(idx_txt, 0), (int(seq_txt, 0) if seq_txt else None), (nombre or None)


# sonidos de la SEQ (cPlayer::seqSeCtrl, pl_class.cpp): no = Se - 1; pasos (no 0/2/0xD en el pie izq, parts 0x15;
# 1/3/0xE/0x14 en el derecho, parts 0x19) con SndCall kind 5 + el roce de ropa kind 1 (0x2A / 0x2F); Free & 7 cambia
# el kind: 1 -> 1 (voz / cuerpo de Leon), 2 -> 6, 3 -> 2 (armas)
def sonidos_seq(seq):
    out = []
    for f, k in enumerate(seq.keys):
        if not k.se:
            continue
        no = k.se - 1
        parts = 0x15 if no in (0, 2, 0xD) else 0x19 if no in (1, 3, 0xE, 0x14) else 0
        kind = 5 if no in (0, 1, 2, 3, 4, 5, 0xD, 0xE, 0x14) else 1
        kind = {1: 1, 2: 6, 3: 2}.get(k.free & 7, kind)
        out.append({'frame': f, 'kind': kind, 'no': no, 'parte': parts,
                    'que': 'paso' if parts else ('voz/cuerpo' if kind == 1 else 'sonido')})
    return out


# ---------------------------------------------------------------------------------------------------
#  ATLAS: cada textura usada (con su alpha compuesta) a la MITAD exacta, empaquetada en estantes en un
#  PNG potencia de 2 (lo que exige el PowerVR MBX del N95), con 2 px de borde repetido para que el
#  filtrado bilineal no traiga el color de la vecina.
# ---------------------------------------------------------------------------------------------------
PAD = 2


ATLAS_COMPLETO = False   # --atlas-completo: las texturas a su tamanio original (version "full"); default: a la mitad (N95)


def armar_atlas(imagenes):
    """imagenes: {clave: RGBA numpy (h, w, 4)} -> (atlas numpy, {clave: (x, y, w, h)} en px del atlas)."""
    import numpy as np
    from PIL import Image
    mitad = {}
    for k, img in imagenes.items():
        h, w = img.shape[:2]
        mitad[k] = img if ATLAS_COMPLETO else \
            np.asarray(Image.fromarray(img, 'RGBA').resize((max(1, w // 2), max(1, h // 2)), Image.BOX))
    orden = sorted(mitad, key=lambda k: (-mitad[k].shape[0], -mitad[k].shape[1], str(k)))
    area = sum((m.shape[0] + 2 * PAD) * (m.shape[1] + 2 * PAD) for m in mitad.values())
    W = 64
    ancho = max(m.shape[1] for m in mitad.values()) + 2 * PAD
    while W < 1024 and (W * W < area or W < ancho):   # que entre la mas ancha (props chicos: una textura de 64)
        W *= 2
    while True:   # estantes: izquierda a derecha, fila nueva cuando no entra; si queda muy alto, mas ancho
        pos, x, y, alto_fila = {}, 0, 0, 0
        for k in orden:
            h, w = mitad[k].shape[:2]
            if x + w + 2 * PAD > W:
                x, y, alto_fila = 0, y + alto_fila, 0
            pos[k] = (x + PAD, y + PAD, w, h)
            x += w + 2 * PAD
            alto_fila = max(alto_fila, h + 2 * PAD)
        H = 1
        while H < y + alto_fila:
            H *= 2
        if H <= W or W >= 1024:
            break
        W *= 2
    atlas = np.zeros((H, W, 4), np.uint8)
    for k, (x, y, w, h) in pos.items():
        bloque = np.pad(mitad[k], ((PAD, PAD), (PAD, PAD), (0, 0)), mode='edge')
        atlas[y - PAD:y + h + PAD, x - PAD:x + w + PAD] = bloque
    return atlas, pos


def uv_atlas(uv, rect, W, H):
    x, y, w, h = rect
    u = min(max(uv[0], 0.0), 1.0)
    v = min(max(uv[1], 0.0), 1.0)
    return ((x + u * w) / W, (y + v * h) / H)


def primitiva(b, pos, nrm, uv, idx, material, parte, jo=None, we=None):
    attrs = {'POSITION': b.accessor('3f', gltf.FLOAT, 'VEC3', pos, gltf.ARRAY_BUFFER, minmax=True),
             'NORMAL': b.accessor('3f', gltf.FLOAT, 'VEC3', nrm, gltf.ARRAY_BUFFER),
             'TEXCOORD_0': b.accessor('2f', gltf.FLOAT, 'VEC2', uv, gltf.ARRAY_BUFFER)}
    if jo is not None:
        attrs['JOINTS_0'] = b.accessor('4H', gltf.U16, 'VEC4', jo, gltf.ARRAY_BUFFER)
        attrs['WEIGHTS_0'] = b.accessor('4f', gltf.FLOAT, 'VEC4', we, gltf.ARRAY_BUFFER)
    chico = len(pos) < 65536
    return {'attributes': attrs,
            'indices': b.accessor('H' if chico else 'I', gltf.U16 if chico else gltf.U32, 'SCALAR', idx, gltf.ELEMENT_ARRAY_BUFFER),
            'mode': 4, 'material': material, 'extras': {'w3d_part': parte}}   # nombre del mesh part en Whisk3D


def malla_skinneada(fuentes, clave_de, rects, W, H, scale, reducir):
    """[(meshbin, TPL, prefijo)] -> ({transparente?: (index, pos, nrm, uv, jo, we, idx)}, triangulos, alphaCutoff):
    todas las piezas en UNA malla skinneada, opaco / transparente separados, UV al atlas; simplificada con
    meshoptimizer si reducir > 0."""
    grupos = {False: ({}, [], [], [], [], [], []), True: ({}, [], [], [], [], [], [])}  # index, pos, nrm, uv, jo, we, idx
    cutoff = 1.0
    n_tri = 0
    for mi, (m, tex, pref) in enumerate(fuentes):
        for part in m.parts:
            tris = part.triangles()
            if not tris:
                continue
            k = clave_de(tex, pref, part)
            transp = k[2] is not None
            if transp:
                cutoff = min(cutoff, (part.alpha_ref + 1) / 255.0)
            index, pos, nrm, uv, jo, we, idx = grupos[transp]
            vistos = set()
            for tri in tris:
                if len({v[0] for v in tri}) < 3 or frozenset(tri) in vistos:
                    continue   # degenerado / cara repetida (pl00:4 trae una)
                vistos.add(frozenset(tri))
                for v in tri:
                    vk = (mi, k, v)
                    i = index.get(vk)
                    if i is None:
                        i = index[vk] = len(pos)
                        pos.append(tuple(c * scale for c in m.position(v[0])))
                        nrm.append(tuple(gltf.normalize(m.normal(v[1]))))
                        uv.append(uv_atlas(m.texcoord(v[3]), rects[k], W, H))
                        pares = m.skin(v[0])
                        pares = pares + [(0, 0.0)] * (4 - len(pares))
                        jo.append(tuple(j for j, _ in pares))
                        we.append(tuple(w for _, w in pares))
                    idx.append(i)
                n_tri += 1
    # SIMPLIFICACION del cuerpo (N95): meshoptimizer quita vertices SIN moverlos, asi cada vertice que queda conserva
    # sus pesos. Los pesos van como atributo para que no colapse a traves de las articulaciones; las normales y el
    # UV para respetar la silueta y las costuras del atlas.
    if reducir > 0:
        import numpy as np
        sys.path.insert(0, os.path.join(HERE, 'tools', 'meshopt'))
        import meshopt
        antes = despues = 0
        for transp in (False, True):
            index, pos, nrm, uv, jo, we, idx = grupos[transp]
            if not idx:
                continue
            P = np.array(pos, np.float32)
            attrs = np.concatenate([np.array(nrm), np.array(uv), np.array(we)], axis=1).astype(np.float32)
            nuevo, _ = meshopt.simplificar(np.array(idx), P, attrs, [0.5, 0.5, 0.5, 1, 1, 1, 1, 1, 1], 0.4,
                                           reducir, 0)
            usados, remap = np.unique(nuevo, return_inverse=True)
            remap = meshopt.orden_cache(remap.astype(np.uint32), len(usados))
            antes += len(idx) // 3
            despues += len(remap) // 3
            grupos[transp] = (index, [pos[i] for i in usados], [nrm[i] for i in usados], [uv[i] for i in usados],
                              [jo[i] for i in usados], [we[i] for i in usados], [int(i) for i in remap])
        print(f'cuerpo simplificado: {antes} -> {despues} triangulos (error {reducir})')
    return grupos, n_tri, cutoff


def clip_esqueleto(b, nodes, n, poses, nombre, fps, scale, raiz=None, raices=(0,)):
    """Animacion glTF de las poses (evalhost) sobre los nodos hueso_NNN (nodes[i + 1]). raiz: None, o por frame
    una matriz 3x4 del juego que se aplica ANTES del l_mat de las partes raiz `raices` (el modelo en el mundo)."""
    times = b.accessor('f', gltf.FLOAT, 'SCALAR', [f / fps for f in range(len(poses))], minmax=True)
    t0 = b.accessor('f', gltf.FLOAT, 'SCALAR', [0.0], minmax=True)
    samplers, channels = [], []

    def chan(node, path, values, fmt, typ, rest_val):
        # canal constante: se omite si es el reposo, o va con UNA key (sin 119 huesos x N frames de curvas quietas)
        if all(max(abs(a - c) for a, c in zip(v, values[0])) < 1e-6 for v in values):
            if max(abs(a - c) for a, c in zip(values[0], rest_val)) < 1e-6:
                return
            inp, values = t0, values[:1]
        else:
            inp = times
        samplers.append({'input': inp, 'output': b.accessor(fmt, gltf.FLOAT, typ, values), 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})
    for i in range(n):
        tr, rot, sc, prev = [], [], [], None
        for f, pose in enumerate(poses):
            lm = pose.l_mat[i]
            if raiz is not None and i in raices:
                lm = mat34_mul(raiz[f], lm)
            t, s, r = gltf.decompose(lm)
            q = gltf.quat_continuous(prev, gltf.quat_normalize(list(pose.quat(r))))
            prev = q
            tr.append(tuple(c * scale for c in t))
            rot.append(tuple(q))
            sc.append(tuple(s))
        chan(i + 1, 'translation', tr, '3f', 'VEC3', nodes[i + 1]['translation'])
        chan(i + 1, 'rotation', rot, '4f', 'VEC4', (0.0, 0.0, 0.0, 1.0))
        chan(i + 1, 'scale', sc, '3f', 'VEC3', (1.0, 1.0, 1.0))
    return {'name': nombre, 'samplers': samplers, 'channels': channels,
            'extras': {'frameRate': int(round(fps))}}   # Whisk3D lee el fps de aca


def mat34_mul(a, m):
    """a * m, matrices 3x4 row-major del juego (Mtx)."""
    return tuple(sum(a[4 * r + k] * m[4 * k + c] for k in range(3)) + (a[4 * r + 3] if c == 3 else 0.0)
                 for r in range(3) for c in range(4))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=DEFAULT_DISC, help='imagen del disco (.rvz/.iso/.gcm)')
    ap.add_argument('-o', '--output', default=None, help='default out/leon/leon.glb (--combate: out/combate/leon_combate.glb)')
    ap.add_argument('--anim', action='append', default=[], metavar='[ARCHIVO:]N[=nombre]',
                    help='motion FCV (ej. 46, wep02:13=caminar; repetible). Sin --anim: el set de la demo')
    ap.add_argument('--sin-anim', action='store_true', help='solo la pose de reposo')
    ap.add_argument('--scale', type=float, default=0.001, help='unidades por mm del juego (0.001 = metros)')
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--no-ik', action='store_true')
    ap.add_argument('--atlas-completo', action='store_true',
                    help='texturas a tamanio original (la version "full"; default: a la mitad para el N95)')
    ap.add_argument('--evento', metavar='rNNNsMM.evd',
                    help='agrega las motions de Leon de ese evento (cutscene), un clip por corte "sMM_cNN" con la raiz '
                         'en coordenadas del MUNDO del cuarto (metros); ruta, o nombre en extracted/Evd/ o en el disco')
    ap.add_argument('--evento-modelo', default='pl0000', help='nombre del modelo de Leon en el evento (default pl0000)')
    ap.add_argument('--combate', action='store_true',
                    help='el set de la demo + COMBATE_ANIMS (recarga, danos, agarre, muerte, herido), atlas completo y malla '
                         'sin simplificar (PC), a out/combate/leon_combate.glb + leon_combate_clips.json')
    ap.add_argument('--reducir', type=float, default=None,
                    help='error de la simplificacion del cuerpo (relativo al tamanio; 0 = la malla original del juego). '
                         'Para el N95: ~9100 -> ~5000 triangulos sin que se note a la distancia de la camara del juego')
    args = ap.parse_args()
    if args.output is None:
        args.output = os.path.join(HERE, 'out', 'combate', 'leon_combate.glb') if args.combate else \
            os.path.join(HERE, 'out', 'leon', 'leon.glb')
    if args.reducir is None:
        args.reducir = 0.0 if args.combate else 0.006
    global ATLAS_COMPLETO
    ATLAS_COMPLETO = args.atlas_completo or args.combate
    arc = Archivos(args.disc)
    scale = args.scale

    skel = modelbin.parse(arc('pl00').entry(0).data)
    skel.check_tree()
    n = skel.n_parts
    rest = rest_world(skel)

    def fuente(bst, bi, tst, ti):
        m = meshbin.parse(arc(bst).entry(bi).data)
        tex = gxtex.parse_tpl(arc(tst).entry(ti).data)
        return m, tex, f'{tst}_{ti:03d}'
    cuerpo = [fuente(*c) for c in CUERPO]
    armas = [(nom,) + fuente(bst, bi, tst, ti) + (en_modelo,) for nom, bst, bi, tst, ti, en_modelo in ARMAS]

    # ---- 1. las texturas usadas -> atlas ----
    imagenes = {}

    def clave_de(tex, pref, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (pref, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for m, tex, pref in cuerpo + [a[1:4] for a in armas]:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, pref, part)
    atlas, rects = armar_atlas(imagenes)
    H, W = atlas.shape[:2]
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    atlas_nombre = 'leon_atlas.png'
    with open(os.path.join(out_dir, atlas_nombre), 'wb') as f:
        f.write(gxtex.png(atlas))
    print(f'atlas: {len(imagenes)} texturas a la mitad -> {atlas_nombre} {W}x{H}')

    b = gltf.Builder()
    MAT_OPACO, MAT_TRANSP, MAT_LASER = 0, 1, 2

    # ---- 2. el cuerpo: UNA malla, 2 primitivas (opaco primero, transparente al final), skinneada ----
    grupos, n_tri, cutoff = malla_skinneada(cuerpo, clave_de, rects, W, H, scale, args.reducir)
    prims = []
    for transp, mat, parte in ((False, MAT_OPACO, 'opaco'), (True, MAT_TRANSP, 'transparente')):
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        if idx:
            prims.append(primitiva(b, pos, nrm, uv, idx, mat, parte, jo, we))
    n_vert = sum(len(g[1]) for g in grupos.values())

    # ---- 3. esqueleto (nodo raiz + un nodo por parte; el reposo solo traslada) ----
    nodes = [{'name': 'leon', 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': 'leon_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    meshes = [{'name': 'Leon_cuerpo', 'primitives': prims}]
    mesh_nodes = [len(nodes)]
    nodes.append({'name': 'Leon_cuerpo', 'mesh': 0, 'skin': 0})
    print(f'Leon_cuerpo: {n_vert} vertices, {n_tri} triangulos, {len(prims)} mesh parts (skinneado, {n} huesos)')

    # ---- 4. las armas: rigidas, una primitiva opaca, vertices en el espacio del hueso de la mano ----
    mano = rest[HUESO_MANO]
    for nom, m, tex, pref, en_modelo in armas:
        index, pos, nrm, uv, idx = {}, [], [], [], []
        off = mano if en_modelo else (0.0, 0.0, 0.0)
        for part in m.parts:
            tris = part.triangles()
            if not tris:
                continue
            k = clave_de(tex, pref, part)
            for tri in tris:
                if len({v[0] for v in tri}) < 3:
                    continue
                for v in tri:
                    vk = (k, v)
                    i = index.get(vk)
                    if i is None:
                        i = index[vk] = len(pos)
                        p = m.position(v[0])
                        pos.append(tuple((p[c] - off[c]) * scale for c in range(3)))
                        nrm.append(tuple(gltf.normalize(m.normal(v[1]))))
                        uv.append(uv_atlas(m.texcoord(v[3]), rects[k], W, H))
                    idx.append(i)
        mesh_nodes.append(len(nodes))
        nodes.append({'name': nom, 'mesh': len(meshes)})
        meshes.append({'name': nom, 'primitives': [primitiva(b, pos, nrm, uv, idx, MAT_OPACO, 'opaco')]})
        print(f'{nom}: {len(pos)} vertices, {len(idx) // 3} triangulos (rigido, espacio de hueso_{HUESO_MANO:03d})')

    # ---- 4b. el LASER: una linea (triangulo degenerado A, B, B') en el espacio del hueso de la mano, de la
    # boca del arma hacia -X (el eje del cañon). objWep.cpp: el rayo sale de (228, -24, 29) y se dibuja desde
    # 500 mm mas adelante (~la boca); lo pinta el material de LINEAS de Whisk3D (make_re4_w3d.py le pone
    # 'lineas'). El juego lo corta a 19 m (y con un raycast); aca va fijo a LASER_LARGO.
    a0 = (-0.272, -0.024, 0.029)
    b0 = (a0[0] - LASER_LARGO, a0[1], a0[2])
    b1 = (b0[0], b0[1] + 0.0005, b0[2])
    mesh_nodes.append(len(nodes))
    nodes.append({'name': 'Leon_laser', 'mesh': len(meshes)})
    meshes.append({'name': 'Leon_laser', 'primitives': [primitiva(b, [a0, b0, b1], [(0, 1, 0)] * 3, [(0, 0)] * 3, [0, 1, 2],
                                                                     MAT_LASER, 'laser')]})

    # ---- 5. animaciones ----
    animations = []
    specs = [] if args.sin_anim else (args.anim or DEMO_ANIMS)
    if args.combate and not args.sin_anim:
        specs = DEMO_ANIMS + COMBATE_ANIMS + ACCIONES_ANIMS + args.anim
    info_clips = []
    for spec in specs:
        stem, num, num_seq, nombre = parse_spec(spec)
        if stem.startswith('etm/'):
            motion = fcv.parse(arc.etm(stem[4:], num))
        else:
            e = arc(stem).entry(num)
            if e.tag != 'FCV':
                sys.exit(f'{stem}:{num} es {e.tag}, no una animacion (FCV)')
            motion = fcv.parse(e.data)
        seq = None
        if num_seq is not None:
            es = arc(stem).entry(num_seq)
            if es.tag != 'SEQ':
                sys.exit(f'{stem}:{num_seq} es {es.tag}, no una secuencia (SEQ)')
            seq = fcv.parse_seq(es.data)
            poses = play_seq(skel, motion, seq, ik=not args.no_ik)
        else:
            poses = play(skel, motion, ik=not args.no_ik)
        nombre = nombre or (f'{stem}_{num:03d}' if isinstance(num, int) else os.path.splitext(num)[0])
        animations.append(clip_esqueleto(b, nodes, n, poses, nombre, args.fps, scale))
        es_accion = nombre in EVENTOS_CLIPS
        info = {'clip': nombre, 'archivo': stem, 'fcv': num, 'pl_arc': num + 4 if isinstance(num, int) else None,
                'seq': num_seq, 'frames': len(poses), 'segundos': round(len(poses) / args.fps, 4),
                'sonidos_seq': sonidos_seq(seq) if seq else [],
                'nota': NOTAS_CLIPS.get(nombre, ''), 'raiz': raiz_movimiento(poses, scale, con_y=es_accion)}
        if es_accion:
            info['eventos'] = EVENTOS_CLIPS[nombre]
        info_clips.append(info)
        print(f'  anim {nombre} ({stem}:{num}{"+" + str(num_seq) if seq else ""}): {len(poses)} frames')

    # ---- 5b. las motions de Leon en un EVENTO (--evento): el evento arma "pl0000" con el cuerpo pl00:0 (el mismo
    # esqueleto de 119 partes que este glb; la cabeza de evento ev0002 solo corre el reposo de las partes 32/33/105/113,
    # que aca quedan con el de pl00:0 porque las mallas son las de pl00). Un clip por corte donde el evento le da una
    # motion; la parte 0 lleva la posicion en el MUNDO del cuarto (la motion del evento esta en coordenadas del mundo).
    if args.evento:
        import re4_evento
        ev = re4_evento.Evento(re4_evento.resolver_evd(args.evento, args.disc))
        modelo = args.evento_modelo
        for corte in ev.cortes_de(modelo):
            motion = ev.motion(corte, modelo)
            poses, raiz = re4_evento.poses_corte(skel, motion, ev.cortes[corte], ik=not args.no_ik, lugar=ev.lugar(modelo))
            animations.append(clip_esqueleto(b, nodes, n, poses, ev.clip(corte), args.fps, scale, raiz, skel.roots()))
            x, y, z = re4_evento.raiz_mundo(poses[0], raiz[0] if raiz else None)
            print(f'  anim {ev.clip(corte)} ({ev.mots[(corte, modelo)].rsplit("/", 1)[-1]}): {len(poses)} frames '
                  f'(motion {motion.n_frames}), raiz ({x * scale:.3f}, {y * scale:.3f}, {z * scale:.3f}) m')

    textura = {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_leon.py'},
        'scene': 0,
        'scenes': [{'name': 'leon', 'nodes': [0] + mesh_nodes}],
        'nodes': nodes,
        'skins': [skin],
        'meshes': meshes,
        'images': [{'uri': atlas_nombre}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],   # CLAMP: es un atlas
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': [
            {'name': 'Leon_opaco', 'pbrMetallicRoughness': textura, 'extras': {'w3d_transparent': False}},
            # alphaSetup del juego es un alpha TEST (GX alpha compare) -> MASK; Whisk3D usa su flag propio
            {'name': 'Leon_transparente', 'pbrMetallicRoughness': textura, 'alphaMode': 'MASK', 'alphaCutoff': cutoff,
             'extras': {'w3d_transparent': True}},
            # el laser de la mira: rojo del juego (168, 0, 0), solido semitransparente, sin luz ni textura
            {'name': 'Leon_laser', 'pbrMetallicRoughness': {'baseColorFactor': [168 / 255.0, 0.0, 0.0, 0.6],
                                                            'metallicFactor': 0.0, 'roughnessFactor': 1.0},
             'alphaMode': 'BLEND', 'doubleSided': True,
             'extras': {'w3d_transparent': True, 'w3d_lighting': False, 'w3d_textureOn': False, 'w3d_culling': False}},
        ],
    }
    if animations:
        doc['animations'] = animations
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    gltf.write(doc, bytes(b.blob), args.output)
    print(f'-> {args.output}: {len(meshes)} mallas, 1 atlas, {len(animations)} animaciones')
    if args.combate:
        import json
        sal = os.path.splitext(args.output)[0] + '_clips.json'
        with open(sal, 'w') as f:
            json.dump({'fps': args.fps, 'glb': os.path.basename(args.output), 'clips': info_clips}, f, indent=1,
                      ensure_ascii=False)
        print(f'-> {sal}')


if __name__ == '__main__':
    main()
