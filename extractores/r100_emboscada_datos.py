"""
Datos (de la decompilacion ../re4/src) de lo que pasa en r100 despues de matar al ganado de la casa:
escribe out/r100_emboscada/plan.json y out/r100_emboscada/ia_emboscada.json. Lo llama
re4_extract_emboscada_r100.py (--solo plan). Unidades SI: m (mm * 0.001), rad, s (frames / 30).
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MM = 0.001
F = 30.0


def m3(v):
    return [round(c * MM, 4) for c in v]


def seg(frames):
    return round(frames / F, 4)


def aev(no):
    info = json.load(open(os.path.join(HERE, 'out', 'r100', 'r100.json')))
    a = next(x for x in info['aev'] if x['no'] == no)
    xs = [p[0] for p in a['pts']]
    zs = [p[1] for p in a['pts']]
    return dict(area=no, hex=hex(no), tipo=a['tipo_evento'], piso_m=a['piso'], alto_m=a['alto'],
                x_m=[round(min(xs), 2), round(max(xs), 2)], z_m=[round(min(zs), 2), round(max(zs), 2)],
                poligono_xz_m=a['pts'])


def clip_info(no, nombre):
    ruta = os.path.join(HERE, 'out', 'r100_emboscada', f'clips_e{no:02x}.json')
    if not os.path.isfile(ruta):
        return None
    d = json.load(open(ruta))
    c = next((x for x in d['clips'] if x['clip'] == nombre), None)
    if c is None:
        return None
    return {k: c[k] for k in ('clip', 'frames', 'duracion_s', 'loop', 'espejo', 'transicion_f') if k in c} | \
        {k: c[k] for k in ('velocidad_m_s', 'raiz_final_m', 'frames_clave') if k in c}


FLAGS = {
    0x80000000: 'arma: horca (Wep_type 1; el modulo la llama hoe / suki; modelo ARC 0x254 = horca de 3 puntas)',
    0x20000000: 'arma: hacha (Wep_type 2)',
    0x08000000: 'arma: hoz (Wep_type 3)',
    0x01000000: 'ZURDO: arma en la parte 0x10 (hueso_016) y motions de arma espejadas (MotionSetCore flag 0x40)',
    0x00800000: 'sombrero cObj12 ARC 0x25F / tpl 0x260 en la cabeza',
    0x00080000: 'sombrero cObj12 ARC 0x25F / tpl 0x261 en la cabeza',
    0x00400000: 'gorro cObj12 ARC 0x262 / tpl 0x263 en la cabeza',
    0x00040000: 'gorro cObj12 ARC 0x262 / tpl 0x264 en la cabeza',
    0x80: 'forzado a "encontro a Leon" + correr (em10FindCk / em10WalkRtnSet / em10DashCk: EmRoutineSet(1, 0x11))',
    0x40: 'siempre alerta (no lo usa ninguno aca)',
    0x20: 'sin agarre saltando (em10CatchPLRtnCk: DashCatch 0x39 solo si !(flag & 0x20))',
    0x10: 'no lo alertan los sonidos (em10FindCk salta los modos Goto por SE) y avisa a otros solo a 10 m (no 25 m)',
    0x08: 'quieto / guardia (sin haber encontrado a Leon) gira hacia Leon al instante (Muku con limite pi)',
    0x04: 'danio de sus ataques a la mitad + 1 fuera del modo dificil (em10AtkCk: dmg / 2 + 1)',
    0x01: 'bit de "suelto" que pone el cuarto (R100WalkStay / R100Cliff / Hide lo esperan)',
}


def flags_txt(fl):
    return [f'{b:#010x}: {t}' for b, t in FLAGS.items() if fl & b]


RUTINAS = {
    0: ('set 0, Character 1 -> EmRoutineSet(1, 1) = em10_R1_Keeper (guardia)',
        'Keeper: quieto en su lugar. Si Leon esta a mas de 50 m se desvanece (invisible_factor -0.1 por frame, sin '
        'colision, Be_flg 0x400000); a menos de 50 m vuelve (visible, con colision). Sin haber encontrado a Leon: '
        'gira hacia el si tiene flag 8 y busca con em10FindCk. Encontrado (Be_flg 0x100): gira hacia Leon a 0.0245 '
        'rad/frame (0.736 rad/s) y sale de guardia (em10WalkRtnSet = caminar hacia Leon por la ruta) cuando la '
        'distancia DE RUTA de su puesto (Keep_pos = donde aparecio) a Leon es menor que Guard_r (o flag 0x40); si '
        'Leon queda a su espalda (> 90 grados) hace girar180 y ataca desde ahi. Tambien ataca desde el puesto '
        '(em10AtkRtnCk en el giro).'),
    0x1F: ('set 0x1F -> EmRoutineSet(1, 0x4C) = em10_R1_R100WalkStay',
           'WalkStay: invulnerable mientras dura (dmg.m_Timer = 2 cada frame); camina UN ciclo de "caminar" '
           '(em10SetWalkMotion kind 0: sin haber encontrado a Leon) hacia donde mira, se queda quieto y espera el '
           'flag bit 0 (r100_Sce_zombi_dead se lo pone al terminar s20): borra el bit y Be_flg 0x100 y pasa a '
           'Keeper (Character 1). Es lo que se ve en el corte 2 de s20 (Evt_R100S20_Func les pone NoSuspend).'),
    2: ('set 2/3/4 -> EmRoutineSet(1, 6) = em10_R1_R100Cliff', ''),
}


def escribir(esl, variante, escala_emset, OUT):
    os.makedirs(OUT, exist_ok=True)
    ems = [3, 4, 5, 0x12, 0x13, 0x26, 0x27]
    trio = [6, 7, 8]

    def ficha(no, papel):
        e = esl[no]
        v = variante(e)
        rut = RUTINAS.get(e['set']) or RUTINAS[2]
        d = dict(entrada=no, hex=hex(no), papel=papel, id=hex(e['id']), modulo='em12 (em10.cpp + em12_set.cpp)',
                 type=e['type'], modelo=v['modelo']['que'], set=hex(e['set']), rutina_inicial=rut[0],
                 flag=hex(e['flag']), flag_bits=flags_txt(e['flag']), hp=e['hp'], Character=e['Character'],
                 Guard_r_m=e['Guard_r_m'], pos_m=e['pos_m'], rot_y_rad=e['rot_rad'][1],
                 rot_y_nota='ang.y del juego: mira a (sin a, 0, cos a) = +Z local del glb',
                 escala=escala_emset(no), arma=v['arma']['nombre'] if v['arma'] else None, zurdo=v['zurdo'],
                 sombrero=bool(v['acc']), variante_seq=v['v'],
                 glb=f'out/r100_emboscada/ganado_e{no:02x}.glb', clips=f'out/r100_emboscada/clips_e{no:02x}.json',
                 fuente=f'extracted/etc/emleon00.esl entrada {no:#x} (32 bytes, game/em_set.cpp EM_SET_WORK: pos*10 mm, '
                        f'rot * pi/16384, Guard_r*1000 mm)')
        return d

    emboscada = [ficha(n, p) for n, p in zip(ems, [
        'W->ems[0]: frente a la PUERTA de la casa (a 3.5 m); no se ve en s20; Keeper',
        'W->ems[1]: sube por el camino (se ve caminando en s20 corte 2); WalkStay -> Keeper',
        'W->ems[2]: sube por el camino (se ve caminando en s20 corte 2); WalkStay -> Keeper',
        'W->ems[3]: mas adelante en el camino (x 13), Keeper',
        'W->ems[4]: cerca del final (x 59.6), Keeper',
        'W->ems[5]: cerca del final (x 61.2), Keeper',
        'W->ems[6]: junto a la salida a r101, abajo (x 83.1, y -6.13), Keeper'])]
    for f in emboscada:
        if f['entrada'] in (4, 5):
            f['rutina_detalle'] = RUTINAS[0x1F][1] + ' Despues: ' + RUTINAS[0][1]
            f['al_terminar_s20'] = 'r100_Sce_zombi_dead: flag |= 1 (pasa a Keeper) y Em_list[4/5].set = 0 (si se vuelve ' \
                                   'a entrar al cuarto aparecen directo en guardia)'
        else:
            f['rutina_detalle'] = RUTINAS[0][1]
    cornisa = [ficha(n, 'r100_trap_set (solo si pG->game_cnt == 0: la primera partida): uno de los TRES aldeanos del '
                        'final del camino con motion de evento del cuarto') for n in trio]
    for f, arcn in zip(cornisa, (0x2E, 0x2F, 0x30)):
        f['rutina_detalle'] = (
            f'em10_R1_R100Cliff: hp = 0 y sin colision de golpe desde el primer frame (NO se lo puede lastimar: es '
            f'escenografia). Sostiene el frame 0 de su motion de evento (setEvtMotion ROOM_ARC {arcn:#x}, clip '
            f'"escena_r100") hasta que Leon esta a menos de 28 m (l_pl < 784e6 mm^2) o otro del trio se dispara '
            f'(les pone flag 1 a todos los set 2/3/4); entonces la reproduce una vez (el que tiene set 2 toca el SE 6/4 '
            f'en su posicion), y a (largo - 10) frames se desvanece 0.1 por frame y queda inactivo.')
        f['escena_r100'] = clip_info(f['entrada'], 'escena_r100')
    otros = [
        dict(entrada=9, id='0x21', que='perro (em21) atrapado en un cepo: em21_R1_R100TrapWait hasta que Leon lo suelta',
             pos_m=esl[9]['pos_m'], rot_y_rad=esl[9]['rot_rad'][1], set=hex(esl[9]['set'])),
    ] + [dict(entrada=n, id='0x2a', que=('cepo (em2a type 0)' if esl[n]['type'] == 0 else
                                          f'trampa de alambre con bomba (em2a type {esl[n]["type"]})'),
              pos_m=esl[n]['pos_m'], rot_y_rad=esl[n]['rot_rad'][1], set=hex(esl[n]['set']), hp=esl[n]['hp'])
         for n in (0xA, 0xB, 0xC, 0xD, 0xE, 0x1D, 0x7A)]
    cuervos = [dict(entrada=n, id='0x23', que='cuervo (em23), be_flag 1: aparece al entrar al cuarto (EmSetFromList)',
                    pos_m=esl[n]['pos_m']) for n in (0xF, 0x10, 0x11, 0x20, 0x21)]

    plan = {
        'titulo': 'r100 despues de matar al ganado de la casa: evento r100s20 + emboscada hasta el camino libre (RE4 GC USA)',
        'unidades': 'metros (mm * 0.001), coordenadas del cuarto r100 (Y arriba); radianes; segundos a 30 fps. rot_y = '
                    'ang.y del juego: el modelo mira a (sin a, 0, cos a) (+Z local del glb)',
        'fuentes': ['../re4/src/st1/r100.cpp (r100_Sce_zombi_dead, r100_em_set, r100_trap_set, r100_Car_pos_move, '
                    'Evt_R100S20_Func, r100_DoorCk, r100_WindowBreakCk, r100_StreanChk, R100Main, r100_MesBrige, '
                    'r100_GakeEvent)',
                    '../re4/src/game/em_set.cpp, sce_at.cpp (AEV tipo 4 = flag por frame en Room_flg), emdoor.cpp '
                    '(setCloseLock / setNormal), emwindow.cpp, sscrn.cpp (OpeSetOpenTerm), scroll.cpp (SmdGetObjPtr)',
                    '../re4/src/em10/em10.cpp + em12/em12_set.cpp (modelos, armas, rutinas)',
                    'extracted/etc/emleon00.esl (lista de enemigos), extracted/St1/r100.das (AEV, SMD, motions)'],
        'secuencia': [
            {'paso': 1, 'que': 'muere el ganado de la casa (r100_Sce_zombi_dead, colgado con SceExecLinkEmDead en R100Init)',
             'detalle': [
                 'Espera a que el ganado deje de estar ACTIVE (termina su animacion de muerte) y a poder arrancar un evento.',
                 'SceEventStart(0); SndRoomStrStop(0): la musica de la casa (stream del cuarto, str0_002.wav) se CORTA en seco.',
                 'r100_em_set(): crea YA las 7 entradas de la emboscada (EmSetFromList2 3, 4, 5, 0x12, 0x13, 0x26, 0x27) '
                 '(ver "emboscada"). Durante el evento (STA_SUSPEND) no se mueven ni se dibujan salvo las que tienen '
                 'NoSuspend.',
                 'readEvent(3) = evd/r100s20.evd; el evento corre con EvtStfPlPosNoSet: al terminar Leon NO se mueve '
                 '(queda donde estaba al matar al ganado).']},
            {'paso': 2, 'que': 'evento r100s20 (570 frames = 19.0 s, 5 cortes)',
             'evento': 'out/evento_s20/evento.json (camaras por frame, audio, cortes, luces)',
             'audio': 'out/evento_s20/audio/str1_009.wav (bio4evt.sbb bloque 1 #9, 20.49 s, 32 kHz estereo, voces + '
                      'efectos + musica pre-mezclados; arranca en el frame 0, sin loop). No hay subtitulos en USA.',
             'modelos': {
                 'obm2d00': 'el CAMION viejo (mismo .bin que W->carSub): out/evento_s20/obm2d00.glb clips s20_c00 / s20_c02 '
                            '(raiz en el mundo); oculto en los cortes 1, 3, 4',
                 'pl0000': 'Leon: out/evento_s20/leon_evento.glb (mismo esqueleto / mallas que out/evento_s40 y s03) clips '
                           's20_c01..c04; cara (shapes) en out/evento_s20/caras.json (cortes 3 y 4)',
                 'sin_policias': 'NO hay policias ni camioneta en el evento: el choque no se ve, solo se oye en el stream. '
                                 'La camioneta de juego (W->car) no tiene NoSuspend -> no se dibuja durante el evento.',
                 'ganados': 'Evt_R100S20_Func corte 2 frame 0: W->ems[1] y W->ems[2] (entradas 4 y 5) setNoSuspend(1): se '
                            'ven caminando por el camino (R100WalkStay) al fondo del plano del corte 2 y siguen vivos en 3-4.'},
             'cortes': [
                 {'corte': 0, 'frames': [0, 59], 'que': 'primer plano de la rueda: el camion empieza a rodar camino abajo '
                  'desde su lugar (-65.58, -0.46, -18.12) -> (-68.44, -0.38, -17.72); Evt_R100S20_Func pone be_flag 0x10 '
                  'al camion (frame 0). Efecto est 0 del r100s20.eff (polvo).'},
                 {'corte': 1, 'frames': [60, 149], 'que': 'Leon adentro de la casa, junto a la ventana del frente (hueso '
                  'raiz en (-82.34, 1.84, -31.41)), abre los postigos para mirar.'},
                 {'corte': 2, 'frames': [150, 259], 'que': 'mirada por la ventana: el camion pasa a lo lejos (26 m) de '
                  '(-77.21, -0.01, -13.37) a (-85.71, -0.09, 5.76) rumbo a la camioneta / el puente; los ganados 4 y 5 '
                  'suben por el camino. est 2.'},
                 {'corte': 3, 'frames': [260, 469], 'que': 'teleobjetivo (fov 7.3 -> 4.2 grados) desde afuera sobre la cara '
                  'de Leon en la ventana (140 f); en los ultimos 70 f la camara se aleja volando hasta (-100.7, 2.96, 7.43), '
                  'junto al puente (fov -> 28.6). est 3.'},
                 {'corte': 4, 'frames': [470, 569], 'que': 'primer plano de Leon adentro. Fin: corte directo al juego, sin '
                  'fundido.'}],
             'control': 'out/evento_s20/control/mosaico.png'},
            {'paso': 3, 'que': 'al terminar s20 (r100_Sce_zombi_dead sigue)',
             'detalle': [
                 'W->ems[0..2] setNoSuspend(0); W->ems[1], W->ems[2] flag |= 1 (dejan R100WalkStay -> Keeper); '
                 'Em_list[4].set = Em_list[5].set = 0.',
                 'r100_Car_pos_move(): la camioneta de la policia y el CAMION quedan en el fondo del barranco (ver '
                 '"estado_despues"); se apagan las colisiones de los dos vehiculos en el camino.',
                 'r100_trap_set(): perro atrapado, cepos, trampas de alambre y (primera partida) el trio de la cornisa.',
                 'Area creada en el cuerpo del ganado muerto (SceAtCreateExecAt, cuadrado de 1.5 x 1.5 m, 1 m de alto): '
                 'con el boton de accion: camara mirando al cadaver + mensaje 0xD (r100_MesGanado).',
                 'Area 1 (barranco, x -112.7..-108.1) activa -> r100_GakeEvent (evento r100s30 la primera vez, despues '
                 'corte de camara 9 + mensaje 0x28); readEvent(4) lo precarga.',
                 'SetSstDispFlag(0x11, 1) (grupo de efectos del cuarto 0x11 visible).',
                 'Se apagan las areas 0xC (mensaje del camion que tapa el camino), 0x19 / 0x1A (charla con los policias); '
                 'area 0x18 (puente) -> r100_MesBrige; area 0x1C (colision nueva) ON, 0x1E OFF.',
                 'Room_flg bit 10 = ON (despues de la casa), Scenario SCF_R100_KILL_GANADE_1ST; SceEventEnd.',
                 'OpeSetOpenTerm(1, -81.5, 0.86, -38.9, 1.6): la SEGUNDA llamada de radio con Hunnigan (terminal 1; stream '
                 'strTbl[1] = bloque 3): Leon se ubica en (-81.5, 0.86, -38.9) mirando 1.6 rad durante la llamada y al '
                 'terminar vuelve a donde estaba. (La llamada misma no esta extraida: ver re4_extract_codec.py, que hace '
                 'la 0.)']},
            {'paso': 4, 'que': 'la EMBOSCADA (juego libre, Leon adentro de la casa)',
             'detalle': [
                 'Tres aldeanos cerca de la casa: e03 (horca) parado a 3.5 m frente a la puerta, e04 (hacha) y e05 (hoz, '
                 'zurda) quietos en el camino a 12-15 m. Todos en guardia (Keeper) y con flag 0x3C (ver ia_emboscada.json).',
                 'La musica de persecucion: r100_StreanChk (ver "musica").',
                 'Las ventanas de la casa (ETS 0 planta baja oeste, ETS 1 arriba) quedan HABILITADAS (SetEnableFence(1)): '
                 'Leon puede saltar por ellas (out/combate/acciones.json) y los ganados pueden romperlas y entrar.',
                 'La PUERTA: sigue trabada abierta hasta que algun ganado de los tres (e03, e04, e05) encuentra a Leon '
                 '(ckFindPL) o alguien (Leon o un enemigo) pisa el area 3 (el umbral); entonces se CIERRA (setCloseLock: '
                 'gira hacia el marco 30 % por frame) y queda trabada; si Leon esta adentro (area 9) suena el SE 6/0x28 '
                 'en la puerta. A los 20 frames se activa el area 0xB: boton de accion en la puerta = golpe (SE 6/0x29) + '
                 'mensaje 0xB. Los ganados la golpean (em10_R1_DoorAtk) pero el script la vuelve a cerrar cada frame: '
                 'entran por las ventanas (em10_R1_WindowAtk rompe el vidrio: la ventana tiene 1000 hp, cada golpe de '
                 'ganado resta 50 (minimo 1) y con hp 1 el golpe la rompe; un tiro de Leon la rompe; despues '
                 'em10_R1_ClimbOver = trepar_ventana).',
                 'Nota: el area 3 cuenta a Leon Y a los enemigos (checkType 3) desde s03: si el ganado de la casa o Leon '
                 'pisan el umbral antes de s20, la puerta ya se cierra entonces.']},
            {'paso': 5, 'que': 'Leon sale de la casa',
             'detalle': [
                 'r100_WindowBreakCk: en cuanto Leon NO esta en el area 9 (la casa, flag Room_flg[2] bit 31 que el area '
                 'tipo 4 prende cada frame) se prende Room_flg bit 4 y e03, e04, e05 reciben flag 0x80: dejan la guardia '
                 'y CORREN hacia Leon (em10 rutina 0x11 Dash; Route_type = Rnd() % 3).',
                 'r100_DoorCk: con el bit 4 apaga el area 0xB y la puerta vuelve a ser NORMAL (setNormal: cerrada, se '
                 'abre con el boton como cualquier puerta).',
                 'r100_StreanChk: con el bit 4 queda "armado": la musica suena mientras algun ganado de la emboscada '
                 'haya encontrado a Leon y este a menos de 30 m.']},
            {'paso': 6, 'que': 'el camino hasta r101',
             'detalle': [
                 'El camion ya no tapa el camino (esta en el barranco; colisiones 4 / 0x26 / 0x27 apagadas): el camino '
                 'hacia el este (x creciente) queda libre.',
                 'En el camino: el perro en el cepo (entrada 9, x -28.8), cepos y trampas de alambre, los ganados e12 '
                 '(x 13), e13 / e26 (x 60), e27 (x 83, abajo) en guardia, y el trio de la cornisa (x 83-85).',
                 'La SALIDA: area AEV 0 (tipo 1 = puerta) al final del camino, x 95.6..99.2 / z -11.4..-7.9, piso -6.89 '
                 'm: boton de accion, SIN llave ni condicion (lockType 0) -> r101 (etapa 1, cuarto 0x01) en '
                 '(-52.144, 0.091, 22.524) mirando 2.122 rad.',
                 'R100Main: la primera vez que, despues de s03, Leon esta fuera del area 0xD (la casa) y no hay evento, '
                 'se desvanecen los streams 4, 5 y 6 en 400 frames (13.3 s) (Room_flg bit 12).']},
        ],
        'estado_despues': {
            'camioneta_policia': {'glb': 'out/r100_emboscada/coche_barranco.glb (clip "barranco")',
                                  'pos_m': m3((-120225.0, -14319.0, -2131.0)),
                                  'rot_rad': [-0.159366012, 0.893207133, 3.46660805],
                                  'orden_rotacion': 'RotMatrix = Rz * Ry * Rx (como glTF con el modelo mirando a +Z)',
                                  'partes': '11, 12, 13, 14, 16 escala 0; 15 escala 1; pList[10].ang.x = 0.4363',
                                  'fuente': 'r100_Car_pos_move'},
            'camion': {'glb': 'out/evento_s20/obm2d00.glb clip "barranco" (o out/r100_intro/camion_juego.glb movido)',
                       'pos_m': m3((-120022.0, -14319.2725, 5740.0)),
                       'rot_rad': [5.04974413, 0.090861842, -1.1017915], 'fuente': 'r100_Car_pos_move (W->carSub)'},
            'policias': 'W->cop[0/1] be_flag &= ~2 (se ocultan; de hecho no existen si se entra con el bit 10)',
            'puente_y_mapa': {
                'nota': 'SmdGetObjPtr(id) = obra del SMD residente (r100.das SMD #0) con ese id; be_flag bit 2 = se dibuja',
                'antes': 'id 0x23 (puente sano, en (-121.79, 0, -4.2), 28 m) y 0x44 (16 tris junto a la camioneta, '
                         '(-101.77, 0, 1.44) rot 0.524: la sombra / marca de la camioneta estacionada) VISIBLES; '
                         '0x37 ((-104.06, 0, 1.51), 102 tris: huellas / marcas del arrastre) y 0x38 (el puente ROTO con '
                         'escombros hasta el fondo del barranco, y -17.5) OCULTOS',
                'despues': '0x23 y 0x44 OCULTOS; 0x37 y 0x38 VISIBLES',
                'AVISO': 'out/r100/r100.glb (re4_extract_r100.py) mezcla las 4 obras en los chunks "raiz" sin mirar '
                         'be_flag: hoy se ven el puente sano Y el roto a la vez. Hay que separarlas para poder '
                         'prenderlas / apagarlas (no se toco re4_extract_r100.py).'},
            'colisiones_AEV': {'apagadas': ['4 (camion)', '0x26 / 0x27 (camion)', '5 / 0x25 (camioneta)', '0x1E'],
                               'prendidas': ['0x1C'], 'areas': [aev(n) for n in (4, 5, 0x1C, 0x1E, 0x25, 0x26, 0x27)]},
            'puerta': 'trabada abierta (+pi/2) hasta que la emboscada encuentra a Leon; despues cerrada y trabada '
                      'hasta que Leon sale de la casa (Room_flg bit 4); despues normal',
            'ventanas': 'habilitadas (saltables / rompibles) desde el bit 10',
            'room_flg': {'3': 's03 visto', '10': 'despues de la casa (s20 visto)', '4': 'Leon salio de la casa durante '
                         'la emboscada', '12': 'streams 4/5/6 desvanecidos', '14': 'r100s30 (barranco) visto'},
        },
        'emboscada': emboscada,
        'trio_cornisa': cornisa,
        'otros_enemigos_del_camino': otros,
        'cuervos': cuervos,
        'musica': {
            'al_morir_el_ganado': 'SndRoomStrStop(0): corta la musica de la casa (str0_002.wav) en seco',
            'durante_s20': 'solo el stream del evento (str1_009.wav)',
            'despues': 'r100_StreanChk: tras s03 queda hold = 1 y armed = 0, asi que apenas termina s20 vuelve a sonar '
                       'el stream del cuarto (SndRoomStrStart(1, 0, 1) = el mismo str0_002.wav de la casa, con su loop). '
                       'Sigue mientras hold; cuando alguno de los 7 de la emboscada encontro a Leon (ckFindPL) y esta a '
                       'menos de 30 m (l_pl < 9e8 mm^2), o Leon salio de la casa (bit 4), queda armed = 1 y hold = 0: '
                       'desde ahi suena SOLO mientras haya uno asi; si no hay ninguno se corta (SndRoomStrStop(3)) y no '
                       'se vuelve a revisar por 150 frames (5 s).',
            'wav': 'out/evento_s03/audio/str0_002.wav (o r100_intro/audio/bgm_r100_intro.wav + bgm_r100_loop.wav)'},
        'areas': {'puerta_casa_umbral': aev(3), 'casa_flag_leon_adentro': aev(9), 'casa_bgm': aev(0xD),
                  'mensaje_puerta_trabada': aev(0xB), 'barranco': aev(1), 'puente': aev(0x18), 'salida_r101': aev(0)},
        'r101': {'area': 0, 'tipo': 'puerta (SceAt tipo 1), boton de accion (trigger 2), sin llave',
                 'destino': {'cuarto': 'r101 (etapa 1, cuarto 1)', 'pos_m': [-52.144, 0.091, 22.524], 'rot_y_rad': 2.122}},
        'archivos': {
            'evento_s20': ['out/evento_s20/evento.json', 'out/evento_s20/audio/str1_009.wav (+_n95)',
                           'out/evento_s20/leon_evento.glb (+_mitad) clips s20_c01..c04', 'out/evento_s20/caras.json',
                           'out/evento_s20/obm2d00.glb clips juego / s20_c00 / s20_c02 / barranco'],
            'emboscada': ['out/r100_emboscada/ganado_eNN.glb + clips_eNN.json (NN = 03 04 05 12 13 26 27 06 07 08)',
                          'out/r100_emboscada/coche_barranco.glb', 'out/r100_emboscada/ia_emboscada.json',
                          'out/r100_emboscada/control/*.png']},
        'comandos': ['python3 re4_extract_evento.py --evento r100s20 --out out/evento_s20',
                     'python3 re4_extract_personajes_evento.py --evd r100s20.evd --out out/evento_s20 --malla-de r100s03.evd',
                     'python3 re4_extract_emboscada_r100.py',
                     'python3 tools_r100/unir_clips.py camion_todo.glb out/r100_intro/camion_juego.glb '
                     'out/evento_s20/obm2d00.glb (opcional)'],
        'pendiente': ['la segunda llamada de radio (OpeSetOpenTerm(1)) no esta extraida',
                      'r100s30 (mirar el barranco, area 1 / 0x18) no esta extraido (re4_extract_evento.py --evento r100s30)',
                      'separar en r100.glb las obras 0x23 / 0x37 / 0x38 / 0x44 (puentes)',
                      'SE del cuarto 6/0x28 (portazo), 6/0x29 (golpe a la puerta) estan en out/r100_intro/audio si se '
                      'extrajeron; streams 4/5/6 de R100Main no identificados'],
    }
    with open(os.path.join(OUT, 'plan.json'), 'w') as f:
        json.dump(plan, f, indent=1, ensure_ascii=False)
    print('-> out/r100_emboscada/plan.json')

    # ------------------------------------------------------------------------------------------------
    ia = {
        'descripcion': 'Diferencias de IA de los aldeanos de la emboscada de r100 respecto del ganado de la casa '
                       '(out/ganado_juego/ia.json, que sigue valiendo para todo lo demas: reacciones a los tiros, patada, '
                       'muerte, velocidad de giro, carrera, retroceso, zonas de impacto). Normal = Game_level 5. SI: m, s, '
                       'rad. Referencias archivo:funcion en ../re4/src.',
        'base': 'out/ganado_juego/ia.json',
        'comun': {
            'hp': '500 (las 7 de la emboscada), 1000 el trio de la cornisa (pero R100Cliff les pone hp 0: no se lastiman)',
            'no_tiran_el_arma': 'em10ThrowAxeCk: en la etapa 1 cuarto 0 (r100) NUNCA arrojan hacha / hoz',
            'no_sueltan_el_arma': 'cEm10::setWeaponFall: en r100 no la sueltan con hp > 0 -> los armados nunca agarran',
            'cabeza': 'en r100 la cabeza no revienta (em10LostHead: solo sangre) y el cadaver no se disuelve',
            'encontrar_a_Leon': {
                'fuente': 'em10FindCk (en Wait / Keeper, cada frame, solo si Be_flg 1 = hay linea de vista)',
                'vista_m': 15.0, 'vista_angulo_rad': 1.0472,
                'vista_si_va_a_un_punto_m': 6.0,
                'pasos_de_Leon_m': 5.0, 'siempre_m': 3.5,
                'tambien': 'si hieren a otro ganado cerca (em10SomebodyDamageNowCk), o flag 0x80, o muere',
                'flag_0x10': 'no lo despiertan los sonidos (SE burst) y cuando encuentra a Leon avisa solo a los que '
                             'estan a menos de 10 m (en vez de 25 m)'},
            'guardia_Keeper': RUTINAS[0][1],
            'desvanecer_lejos_m': 50.0,
            'flag_0x04': 'sus golpes hacen danio / 2 + 1 fuera del modo dificil: 380 -> 191 (6.3 golpes para matar a '
                         'Leon con 1200 hp) (em10AtkCk)',
            'flag_0x80': 'cuando Leon sale de la casa (Room_flg bit 4) e03 / e04 / e05 lo reciben: van a correr hacia '
                         'Leon (EmRoutineSet(1, 0x11) desde Wait / Walk / GotoCk; Route_type = Rnd() % 3)',
            'espera_despues_de_atacar_s': {'acerto': 0.5, 'fallo': 0.0, 'bloqueo_grupo_s': 1.5,
                                           'fuente': 'em10_R1_AxeAtk / SukiAtk (Atk_wait 15 f) + em10AtkCk'},
            'ventanas_y_puertas': {
                'chequeo': 'cada 15 frames mientras camina: rayo de 1 m al frente a 0.4 m de altura (em10WindowCk2)',
                'ventana_entera': 'golpear_puerta (em10_R1_WindowAtk): cada golpe -50 hp (min 1); con hp 1 el golpe la '
                                  'rompe (SetBreakAll); solo uno golpea la misma puerta / ventana (em10DootAtkCk, 3 m)',
                'ventana_rota': 'trepar_ventana (em10_R1_ClimbOver): se orienta perpendicular a la ventana y cae 0.4 m '
                                'del otro lado',
                'puerta_cerrada': 'golpear_puerta (em10_R1_DoorAtk): setShock / setOpen, pero r100_DoorCk la vuelve a '
                                  'cerrar y trabar cada frame mientras Leon esta en la casa',
                'piso_mas_bajo_detras': 'si el piso del otro lado esta 0.5 m mas abajo: JumpDown (0x43) (no exportado)'},
        },
        'por_arma': {
            'hacha_y_hoz': {
                'clip': 'ataque (ARC 0x80 / 0x81; espejado si zurdo)', 'rutina': 'em10_R1_AxeAtk (0x26)',
                'empieza_si': {'distancia_m': 1.7, 'distancia_si_Leon_corre_m': 4.0, 'angulo_max_rad': 0.7854,
                               'desnivel_max_m': 1.5, 'fuente': 'em10AxeAtkCk (l_pl < 2.89e6 mm^2)'},
                'golpe': {'danio': 380, 'danio_con_flag_0x04': 191, 'radio_m': 0.25, 'tabla': 'Em10AtkTbl[0]',
                          'volumen': 'capsulas de 0.25 m del punto (0,0,-0.2) y (0,0,0.05) al (0,0,-1.0) en el espacio '
                                     'del arma (igual que el hacha del ganado de la casa)'},
                'frames': clip_info(4, 'ataque')},
            'horca': {
                'nota': 'el codigo la llama hoe / suki (Wep_type 1); el modelo (em12 ARC 0x254) es una horca de 3 puntas. '
                        'Se lleva con las DOS manos (em10HandSet: mano der. mot[9] + izq. mot[14])',
                'clips': {'ataque_horca_alto': 'Leon a menos de 0.1 m por debajo o por encima (terreno plano: ESTE)',
                          'ataque_horca': 'Leon entre 0.1 y 0.8 m mas abajo',
                          'ataque_horca_bajo': 'Leon mas de 0.8 m mas abajo'},
                'rutina': 'em10_R1_SukiAtk (0x29): gira hacia Leon 0.196 rad/frame los primeros 20 frames',
                'empieza_si': {'distancia_m': 2.0, 'distancia_si_Leon_corre_m': 4.5, 'angulo_max_rad': 0.7854,
                               'desnivel_max_m': 1.5, 'fuente': 'EM10_WEP_ATK_CK (l_pl < 4e6 / 20.25e6 mm^2)'},
                'golpe': {'danio': 380, 'danio_con_flag_0x04': 191, 'radio_m': 0.25, 'tabla': 'Em10AtkTbl[8]',
                          'volumen': 'capsulas de 0.25 m desde los puntos z = -1.0, -0.7, -0.4, -0.1, 0.3, 0.6 m hasta '
                                     'z = -2.0 m, en el espacio del arma (EM10_SUKI_SWEEP_CK)'},
                'frames': {'alto': clip_info(3, 'ataque_horca_alto'), 'medio': clip_info(3, 'ataque_horca')},
                'otros_clips': 'quieto 0x14A, caminar_arma 0x14B (siempre, encontrado o no), correr 0x151, retroceder '
                               '0x157, golpe_cuerpo_horca 0x159 (tiros al torso / brazo izq.), golpe_espalda_horca 0x15B'},
            'sin_arma': {'ataque': 'solo agarrar (em10CatchPLRtnCk, como ia.json "agarre": 1.1 m, 2.0 m si Leon corre) y '
                                   'estrangular; con flag 0x20 sin el agarre saltando',
                         'aplica_a': 'e06 / e07 / e08 (el trio de la cornisa), que igual son escenografia (hp 0)'},
        },
        'por_entrada': [dict(entrada=f['hex'], arma=f['arma'], zurdo=f['zurdo'], type=f['type'], hp=f['hp'],
                             Guard_r_m=f['Guard_r_m'], rutina=f['rutina_inicial'], flags=f['flag_bits'],
                             escala=f['escala'], caminar=clip_info(f['entrada'], 'caminar_arma'),
                             caminar_sin_encontrar=clip_info(f['entrada'], 'caminar'),
                             correr=clip_info(f['entrada'], 'correr'))
                        for f in emboscada + cornisa],
        'velocidades': 'cada entrada usa la secuencia de caminar / correr numero emset_no % 5 (em10SetWalkMotion / '
                       'em10SetDashMotion): las velocidades cambian entre aldeanos (ver por_entrada y clips_eNN.json).',
    }
    with open(os.path.join(OUT, 'ia_emboscada.json'), 'w') as f:
        json.dump(ia, f, indent=1, ensure_ascii=False)
    print('-> out/r100_emboscada/ia_emboscada.json')
