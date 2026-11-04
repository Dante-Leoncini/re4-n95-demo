#!/usr/bin/env python3
"""
Sonidos de COMBATE de la demo r100 (RE4 GameCube, disco USA) -> out/sonidos/combate/*.wav + sonidos.json

Usa el lector de bancos de tools/re4_sonidos.py (DSP-ADPCM, SIT, regiones, grupos al azar) sin tocar sus
salidas. Cada WAV es UN SIT del banco, mono 16 bit, a su frecuencia efectiva (la del sample con el tono del SIT
ya aplicado: nota vs unity + fine + pitch_l/h), SIN volumen aplicado: el volumen del juego va en sonidos.json
("volumen" = vol del SIT / 127 * atenuacion de la region; el juego ademas lo atenua por distancia).

Bancos (SndCall(blk, no) -> SIT no del bloque blk; ver tools/re4_sonidos.py):
  1 PL     em/pl00.drs     (voces / cuerpo de Leon)
  2 WEP    em/wep02.drs    (pistola inicial)
  5 FOOT   St1/r100.das    (pasos y caidas; superficie 0 = la tierra por defecto de r100)
  8 ENEMY  em/em12.drs     (el ganado de la casa es id 0x12 -> emSeCheck lo manda al bloque del grupo 0x10;
                            el bloque ENEMY de em12.drs es identico byte a byte al de em10.drs)

Trazas en la decompilacion (../re4/src):
  - Voces del ganado: em10/em10.cpp Em10SetSeTbl (tipo 0 = aldeano hombre) + em10CallVoiceSe / em10CallVoiceSe2 /
    em10SetDamageVoice / em10BreathSe -> game/ctrl11.cpp Ctrl11*SetSe -> SndCall(8, no).
  - Grupos al azar: game/snd.cpp seRandomCheck (SIT rnd_no -> un miembro al azar del grupo, evitando repetir el
    ultimo, 5 intentos). Por eso pedir 0xC suena 12, 145 o 146.
  - Sonidos de la SEQ de las motions del ganado: em10/em10.cpp em10FootSe (Se-1 = 0..3 -> FOOT 0x10..0x13 en el pie)
    y game/em.cpp (el resto: SndCall(8, Se-1) en la parte 0).

Uso:  python3 re4_extract_sonidos_combate.py
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import re4_sonidos as S  # noqa: E402

OUT = os.path.join(HERE, 'out', 'sonidos', 'combate')

BANCOS = {
    'PL': ('em/pl00.drs', 1),
    'WEP': ('em/wep02.drs', 2),
    'FOOT': ('St1/r100.das', 5),
    'ENEMY': ('em/em12.drs', 8),
}
BLK_NO = {'PL': 1, 'WEP': 2, 'FOOT': 5, 'ENEMY': 8}

# (archivo, banco, SIT, que es, cuando lo toca el juego, grupo al azar (texto) o None, dudoso (texto) o None)
# Los grupos: todos los miembros se exportan; "azar" dice que llamada los elige.
SONIDOS = [
    # ------------------------------------------------------------------ LEON
    ('leon_dolor_1.wav', 'PL', 9, 'Leon: quejido de dolor (variante 1 de 3)',
     'game/pl_sub.cpp PlSetDamageSe(0): se_no = 9 + Rnd() % 3 -> SndCall(1, 9..11) en la cabeza (parte 4). Lo llaman '
     'game/pl_dmg.cpp damageNormal (todo golpe normal que no lo mata: el hachazo del ganado, Em10AtkTbl[0] PL_DM_AUTO), '
     'damageBlow (golpe fuerte vivo) y los agarres de em10.cpp',
     'Rnd() % 3 entre leon_dolor_1/2/3 (sin evitar repetir)', None),
    ('leon_dolor_2.wav', 'PL', 10, 'Leon: quejido de dolor (variante 2 de 3)', 'igual que leon_dolor_1',
     'Rnd() % 3 entre leon_dolor_1/2/3', None),
    ('leon_dolor_3.wav', 'PL', 11, 'Leon: quejido de dolor (variante 3 de 3)', 'igual que leon_dolor_1',
     'Rnd() % 3 entre leon_dolor_1/2/3', None),
    ('leon_muerte.wav', 'PL', 0xD, 'Leon: grito de muerte',
     'game/pl_dmg.cpp Pl_R0_Die r_no_1 0 (clip "muerte", frame 0; solo si el modelo tiene pelo = Leon): '
     'SndCall(1, 0xD) en la cabeza. Tambien em10.cpp PlSetDamageSe(0xD) cuando un agarre lo mata', None, None),
    ('leon_muerte_golpe_fuerte.wav', 'PL', 0x4A, 'Leon: grito del golpe fuerte que lo MATA',
     'game/pl_dmg.cpp damageBlow r_no_2 0 con vida <= 0 (clip "muerte_fuerte", frame 0): SndCall(1, 0x4A) en parte 2. '
     'Si el golpe fuerte no lo mata suena leon_dolor_* en su lugar', None, None),
    ('leon_cuerpo_golpe.wav', 'PL', 0x12, 'Leon: golpe seco del cuerpo contra el piso (mismo sample que '
     'patada_impacto, mas grave)',
     'SEQ de pl00: "dano_fuerte" frame 11 y "muerte_fuerte" frame 21 (kind 1 no 0x12); agarre_derribado frame 37 '
     '(em10.cpp: SE 5/5 + 1/0x12)', None,
     'clasificado como golpe (no voz) por el sample compartido con PL 0xF y el cruce por cero bajo (~770 Hz)'),
    ('leon_cae_rodilla.wav', 'FOOT', 4, 'Leon: cae de rodillas (suelo de tierra de r100)',
     'SEQ del clip "muerte" frame 40 (kind 5 no 4); pl_dmg.cpp damageNormal/Blow r_no_2 0xB (levantarse) usa 5/3 y 5/2 '
     '(pasos). FOOT pasa por footSeCheck: + 30 * tipo de superficie (0 aca)', None, None),
    ('leon_cae_cuerpo.wav', 'FOOT', 5, 'Leon: el cuerpo cae al piso (suelo de tierra de r100)',
     'game/pl_dmg.cpp damageBlow frame 10 (golpe fuerte, vivo): SndCall(5, 5); SEQ "muerte" frame 70, "dano_fuerte" '
     'frame 12, "muerte_fuerte" frame 22; agarre_derribado frame 37', None,
     'mismo sonido que out/sonidos/paso_tierra_caida_cuerpo.wav (aca sin volumen aplicado)'),
    ('patada_voz.wav', 'PL', 0x10, 'Leon: grito de esfuerzo de la patada (roundhouse)',
     'em10/em10.cpp plem10Kick: al terminar el giro hacia el ganado (m_Work1: 12 frames con r_no_3 = 1 = ganado de '
     'rodillas, em10KneeDownAction, motion pl00 0x25; 10 frames con la del archivo del ganado 0x29D, em10KickAction) '
     'suenan SndCall(1, 0x11) y SndCall(1, 0x10) juntos', None,
     'cual de 0x10 / 0x11 es la voz y cual el zumbido se decidio por el analisis (0x10: periodicidad 0.33; '
     '0x11: 0.16, 16 kHz, ruido): escuchar para confirmar'),
    ('patada_swing.wav', 'PL', 0x11, 'Leon: zumbido de la pierna al patear', 'igual que patada_voz (mismo frame)',
     None, 'ver patada_voz'),
    ('patada_impacto.wav', 'PL', 0xF, 'Leon: impacto de la patada contra el ganado',
     'em10/em10.cpp plem10Kick: frame 17 (m_Work0 = 0x11), por cada una de las dos esferas (y=1.5 m y 1.0 m, r 1.2 m) '
     'que acierta (PlWepHitCheck3(.., 0x14, ..)): SndCall(1, 0xF). En el ganado ademas suena carne_impacto_* '
     '(em10DmSetWep00: SndCall(8, 0xC)) y su voz de dolor (em10_R1_Dm_Blow: Se_tbl[8] o muerte Se_tbl[0])', None, None),
    # ------------------------------------------------------------------ BALA / CUCHILLO EN CARNE
    ('bala_carne_1.wav', 'ENEMY', 12, 'impacto en la carne del ganado (bala o cuchillo), variante 1',
     'em10/em10.cpp em10DmSetWep02 (pistolas m_Wep 1..4 y cuchillo 0x10; tabla em10DmSet 0x02/0x10): parte sin '
     'armadura y sin nucleo de parasito -> SndCall(8, 0xC) en em->pos. em10DmSetWep00 (patada 0x14) igual',
     'SE 0xC tiene rnd_no 13 = [12, 145, 146]: seRandomCheck elige al azar evitando repetir el ultimo. 12 y 145 usan '
     'el MISMO sample (145 no se exporta aparte)', None),
    ('bala_carne_2.wav', 'ENEMY', 146, 'impacto en la carne del ganado (bala o cuchillo), variante 2',
     'igual que bala_carne_1', 'rnd13 = [12, 145, 146]', None),
    ('cuchillo_carne_1.wav', 'ENEMY', 12, 'cuchillo en la carne del ganado = el MISMO SE que la bala (copia de '
     'bala_carne_1)',
     'wep/pl_knife.cpp hitCheck -> PlWepHitCheck2(.., 0x10, ..) -> em10DmSetWep02 -> SndCall(8, 0xC). El tajo en si '
     'es PL 3 en el frame 3 (out/sonidos/cuchillo_tajo.wav). 1 de 3 cuchilladas no hace reaccion pero el SE ya sono',
     'rnd13 = [12, 145, 146]', None),
    ('cuchillo_carne_2.wav', 'ENEMY', 146, 'cuchillo en la carne, variante 2 (copia de bala_carne_2)',
     'igual que cuchillo_carne_1', 'rnd13 = [12, 145, 146]', None),
    ('bala_agua.wav', 'WEP', 0xB, 'bala en el AGUA (EAT tipo 2 / superficie de agua)',
     'game/est.cpp EspSetEatEffect tipo 2 (r100: 22 triangulos del EAT, r100_eff_info2) y game/pl_wep.cpp '
     'setWaterShot: SndCall(2, 0xB) en el punto de impacto', None, 'solo agua: NO es la bala en tierra/madera'),
    ('bala_charco.wav', 'WEP', 0xC, 'bala en un CHARCO (mismo sample que bala_agua, mas agudo)',
     'game/est.cpp EspSetEatEffect tipo 0 con EspChkInPuddle (FlrAt se.eff_type 1, normal.y > 0.9): SndCall(2, 0xC)',
     None, None),
    # ------------------------------------------------------------------ GANADO: voces (Se_tbl tipo 0)
    ('ganado_voz_acercarse_1.wav', 'ENEMY', 78, 'ganado: frase mientras camina hacia Leon (variante 1)',
     'em10/em10.cpp em10_R1_Walk: al empezar un paso de caminata, 1 de cada 10 (Rnd() % 10 == 0) y sin el aviso '
     '"detras" activo (CTRL12 BACKSIGN): em10CallVoiceSe2(Se_tbl[15] = 0x4E)',
     'SE 0x4E tiene rnd_no 20 = [78, 79]', 'no se puede saber que dice sin escucharlo'),
    ('ganado_voz_acercarse_2.wav', 'ENEMY', 79, 'ganado: frase mientras camina hacia Leon (variante 2)',
     'igual que ganado_voz_acercarse_1', 'rnd20 = [78, 79]', 'idem'),
    ('ganado_voz_encontrar.wav', 'ENEMY', 26, 'ganado: grito al DESCUBRIR a Leon (el tipo "¡forastero!")',
     'em10/em10.cpp em10_R1_Find (en el frame con Free 0x20 de la motion de aviso), em10_R1_Goto / HideSide / '
     'R201EventWait: em10CallVoiceSe2(Se_tbl[4] = 0x1A)', None,
     'en r100 el ganado de la casa arranca ya "encontrado" tras la cutscene (em10HideOff), puede no sonar nunca'),
    ('ganado_voz_detras.wav', 'ENEMY', 91, 'ganado: aviso "esta detras / de espaldas" a los demas',
     'em10/em10.cpp em10BehindSeCk: un ganado a < 3 m delante de si y a la espalda de Leon, que lo ve -> '
     'Se_tbl[16] = 0x5B, bloquea el aviso 300 frames (CTRL12 BACKSIGN) para todos', None, None),
    ('ganado_respiracion.wav', 'ENEMY', 37, 'ganado: respiracion / gruñido al caminar',
     'em10/em10.cpp em10BreathSe (llamado en Walk / Dash / Find / Back ...): cada 120..240 frames (Breath_se_wait = '
     'Rnd() % 120 + 120) Ctrl11SetSe(Se_tbl[7] = 0x25) con enfriamiento del slot 6 de 20..39 frames; no si Be_flg 0x80',
     None, None),
    ('ganado_voz_ataque_1.wav', 'ENEMY', 75, 'ganado: grito al lanzar el hachazo (variante 1)',
     'em10/em10.cpp em10_R1_AxeAtk r_no_2 0 (frame 0 del clip "ataque_hacha"): em10CallVoiceSe2(Se_tbl[12] = 0x4B)',
     'SE 0x4B tiene rnd_no 12 = [21, 75, 76]; 21 y 75 usan el MISMO sample (21 no se exporta aparte)', None),
    ('ganado_voz_ataque_2.wav', 'ENEMY', 76, 'ganado: grito al lanzar el hachazo (variante 2)',
     'igual que ganado_voz_ataque_1', 'rnd12 = [21, 75, 76]', None),
    ('ganado_voz_agarrar_1.wav', 'ENEMY', 27, 'ganado: grito al AGARRAR / embestir a Leon (variante 1)',
     'em10/em10.cpp em10_R1_Catch / em10_R1_DashCatch: em10CallVoiceSe2(Se_tbl[5] = 0x1B)',
     'SE 0x1B tiene rnd_no 3 = [27, 28]',
     'el ganado de r100 con hacha nunca agarra (em10CatchPLRtnCk exige pWeapon == 0); rate 32 kHz y ruidoso: '
     'podria ser un esfuerzo con ropa, no una frase'),
    ('ganado_voz_agarrar_2.wav', 'ENEMY', 28, 'ganado: grito al agarrar (variante 2; tambien es Se_tbl[6], sin uso '
     'directo encontrado)', 'igual que ganado_voz_agarrar_1', 'rnd3 = [27, 28]', 'idem'),
    ('ganado_dolor_1.wav', 'ENEMY', 71, 'ganado: quejido de dolor chico (variante 1)',
     'em10/em10.cpp em10_R1_Dm_Small (el golpe comun: torso, brazos, manos) 2 frames despues del impacto '
     '(Timer3 = 2) -> em10SetDamageVoice(Se_no = Se_tbl[8] = 0x47, ...); tambien Dm_Blow (patada), Dm_FS, Dm_DashDown. '
     'Si el golpe lo mata suena ganado_muerte_* en su lugar',
     'SE 0x47 tiene rnd_no 1 = [71, 72]', None),
    ('ganado_dolor_2.wav', 'ENEMY', 72, 'ganado: quejido de dolor chico (variante 2; 0x48 = Se_tbl[9])',
     'igual que ganado_dolor_1', 'rnd1 = [71, 72]', None),
    ('ganado_dolor_b.wav', 'ENEMY', 23, 'ganado: quejido de dolor alternativo (brazo / torso, variante de motion 1)',
     'em10_R1_Dm_Small: cuando Rnd() % 3 elige la segunda motion (tipos 0..4) Se_no = Se_tbl[1] = 0x17', None, None),
    ('ganado_dolor_cabeza.wav', 'ENEMY', 24, 'ganado: dolor por tiro en la CABEZA (queda aturdido, se toma la cara)',
     'em10/em10.cpp em10_R1_Dm_Head (Timer3): em10SetDamageVoice(Se_tbl[2] = 0x18, Se_tbl[0])', None, None),
    ('ganado_dolor_pierna.wav', 'ENEMY', 25, 'ganado: dolor por tiro en el MUSLO',
     'em10_R1_Dm_Small tipos 5/6 (partes 0x13 / 0x17), variante de motion 1: Se_no = Se_tbl[3] = 0x19', None, None),
    ('ganado_aturdido_rodilla.wav', 'ENEMY', 73, 'ganado: quejido al caer de rodillas / desplomarse aturdido',
     'em10/em10.cpp em10_R1_Dm_KneeDown / Dm_KnockOut / Dm_Heel: em10CallVoiceSe2(Se_tbl[10] = 0x49)', None, None),
    ('ganado_levantarse.wav', 'ENEMY', 74, 'ganado: gruñido al levantarse del piso',
     'em10/em10.cpp em10_R1_DownWake r_no_2 0: em10CallVoiceSe2(Se_tbl[11] = 0x4A) (si no Be_flg 0x80)', None, None),
    ('ganado_muerte_1.wav', 'ENEMY', 22, 'ganado: grito de MUERTE (variante 1, larga)',
     'em10/em10.cpp em10SetDamageVoice con hp <= 0: em10CallVoiceSe2(Se_tbl[0] = 0x16) (desde Dm_Small, Dm_Head, '
     'Dm_Blow, Die_Normal, Die_Down ...)', 'SE 0x16 tiene rnd_no 24 = [22, 38]', None),
    ('ganado_muerte_2.wav', 'ENEMY', 38, 'ganado: grito de MUERTE (variante 2, corta)', 'igual que ganado_muerte_1',
     'rnd24 = [22, 38]', None),
    ('ganado_grito_caida.wav', 'ENEMY', 77, 'ganado: grito al caer de altura (cerca / escalera / techo)',
     'em10_R1_Dm_Fence / Dm_Ladder / Dm_Roof: Se_tbl[14] = 0x4D', None, 'no ocurre en la casa de r100'),
    # ------------------------------------------------------------------ GANADO: hacha y cuerpo
    ('hacha_swing.wav', 'ENEMY', 0x3D, 'hacha: zumbido del hachazo',
     'em10/em10.cpp em10_R1_AxeAtk: en el frame con Free 0x20 de la SEQ del ataque (frame 15 del clip "ataque_hacha") '
     'SndCall(8, 0x3D) (Wep_type 2 -> default)', None, None),
    ('ganado_forcejeo_swing.wav', 'ENEMY', 0x93, 'zumbido del brazo del ganado (mismo sample que hacha_swing, mas '
     'grave)', 'SEQ "estrangular_suelta" frame 28 (Se 0x93)', None, 'solo en el agarre (no pasa en r100 con hacha)'),
    ('ganado_cae_rodilla.wav', 'ENEMY', 4, 'ganado: cae de rodillas / primer golpe contra el piso',
     'SEQ de las motions (game/em.cpp: Se-1 fuera de 0..3 -> SndCall(8, Se-1)): "rodilla_*" f9, "caer_aturdido" f14, '
     '"caer_pierna_*" f12, "desplomarse" f19, "tropezar" f14, "morir" f35, "estrangular_pateado" f44', None, None),
    ('ganado_cae_cuerpo.wav', 'ENEMY', 5, 'ganado: el cuerpo cae al piso (desplomarse / morir)',
     'SEQ: "morir" f66, "desplomarse" f52, "caer_aturdido_atras" f15, "caer_adelante" f23, "caer_adelante_b" f41, '
     '"caer_muerto_b" f39, "tropezar" f24', None, None),
    ('ganado_cae_golpe_fuerte.wav', 'ENEMY', 0x77, 'ganado: golpe fuerte del cuerpo al volar por la patada',
     'SEQ de em10_R1_Dm_Blow: "caer_atras" f15, "caer_atras_b" f14, "caer_adelante(_b)" f10, "caer_muerto" f22, '
     '"caer_muerto_b" f14 (Se 0x77; en el agua em10FootSe lo anula)', None, None),
    ('ganado_levantarse_ropa.wav', 'ENEMY', 6, 'ganado: roce / apoyo al levantarse del piso',
     'SEQ "levantarse_boca_arriba" f47, "levantarse_boca_abajo" f17 (Se 6)', None,
     'suave (rms ~1600) y ruidoso: probablemente ropa / manos en la tierra'),
    ('ganado_paso_caminar_izq.wav', 'FOOT', 0x10, 'ganado: paso caminando, pie izquierdo (tierra)',
     'em10/em10.cpp em10FootSe: Se-1 == 0 en la SEQ (caminar f37/86, caminar_hacha f34/80, ...) -> SndCall(5, 0x10) '
     'en la parte 0x15; footSeCheck suma 30 * tipo de superficie del FlrAt', None,
     'superficie 0 (como paso_tierra_*); el piso de madera de la casa podria tener otro tipo'),
    ('ganado_paso_caminar_der.wav', 'FOOT', 0x11, 'ganado: paso caminando, pie derecho (tierra)',
     'em10FootSe: Se-1 == 1 -> SndCall(5, 0x11) en la parte 0x19', None, 'idem'),
    ('ganado_paso_correr_izq.wav', 'FOOT', 0x12, 'ganado: paso corriendo, pie izquierdo (tierra)',
     'em10FootSe: Se-1 == 2 -> SndCall(5, 0x12) (clip "correr" f20/42)', None, 'idem'),
    ('ganado_paso_correr_der.wav', 'FOOT', 0x13, 'ganado: paso corriendo, pie derecho (tierra)',
     'em10FootSe: Se-1 == 3 -> SndCall(5, 0x13) (clip "correr" f9/31)', None, 'idem'),
]

FALTANTES = {
    'bala_tierra / bala_madera': 'NO EXISTE en el juego: game/est.cpp EspSetEatEffect tipo 0 (EAT_ET_NORMAL, 1440 de '
                                 '1971 triangulos de r100) y tipo 1 (BULLET) solo ponen efectos (core est 0x1F / 0x20), '
                                 'sin SndCall; tipo 4 (follaje, r100_eff_info4.flag = 0) tampoco. Los efectos de esos '
                                 'est son esp 0x00/0x05 (el unico esp con sonido, esp07 SeType, no aparece). Solo el agua '
                                 '(tipo 2 / setWaterShot: WEP 0xB) y los charcos (WEP 0xC) suenan.',
    'hacha_impacto': 'NO EXISTE: em10AtkCk -> EmAtkHitCk -> LifeDownSet2 + PlSetDamage + EmPlBloodSet2 (sangre em10 est '
                     '0x0B, esp 0x00/0x0B) no tocan ningun SE; lo unico que se oye es leon_dolor_* (damageNormal: '
                     'PlSetDamageSe(0)). Si se quiere un golpe, usar bala_carne_* como sustituto (no es fiel).',
    'voces_stream': 'Las frases del ganado son SE del banco ENEMY (notas 0x3xx = juego de voces 0 del aldeano hombre), '
                    'no streams. Los otros juegos de voces del mismo banco: 0x4xx mujer (Se_tbl tipo 1), 0x5xx y 0x6xx '
                    '(tipos 2 y 3, no usados por em12).',
    'Se_tbl[17] = 0xB5': 'fuera del banco (155 SITs): sndExistCheck falla, no suena.',
}


def exportar():
    os.makedirs(OUT, exist_ok=True)
    bancos = {k: S.load_bank(*v) for k, v in BANCOS.items()}
    lista = []
    for fn, bk, no, que, cuando, azar, dudoso in SONIDOS:
        b = bancos[bk]
        s = b.sit(no)
        if s['flag'] & 0x8000 or s['flag'] & 0x4:
            sys.exit(f'{fn}: {bk} {no:#x} es dummy o secuencia')
        if s['flag'] & 0x2000:
            sys.exit(f'{fn}: {bk} {no:#x} esta encadenado (no soportado aca)')
        pcm, eff, info = S.sit_render(b, no)
        rate = int(round(eff))
        S.write_wav(os.path.join(OUT, fn), pcm, rate)
        n = len(pcm)
        pico = max(abs(v) for v in pcm) if n else 0
        rms = math.sqrt(sum(v * v for v in pcm) / max(1, n))
        g = (s['vol'] if s['vol'] >= 0 else 127) / 127.0 * 10 ** ((info['rgn']['attn'] / 65536.0) / 200.0)
        grp = b.rnd_group(s['rnd_no'])
        d = {
            'archivo': fn, 'que': que, 'cuando': cuando,
            'banco': f'{bk} (SndCall bloque {BLK_NO[bk]}) {BANCOS[bk][0]}', 'se': f'{no:#04x}', 'se_dec': no,
            'volumen': round(g, 3), 'vol_sit': s['vol'],
            'azar': azar or False,
            'grupo_rnd': grp if grp else None,
            'hz': rate, 'segundos': round(n / eff, 3), 'pico': pico, 'rms': round(rms),
            'sample': info['rgn']['sample'],
        }
        if info['loop']:
            d['loop'] = True
        if dudoso:
            d['dudoso'] = dudoso
        lista.append(d)
        print(f'{fn:34s} {bk:5s} {no:#05x} {n / eff:6.3f}s {rate:6d} Hz  pico {pico:5d} rms {rms:6.0f}  vol {g:.2f}'
              + ('  ?' if dudoso else ''))
    doc = {
        'descripcion': 'Sonidos de combate de r100 (RE4 GC USA). WAV mono 16 bit a la frecuencia efectiva del SIT '
                       '(tono ya aplicado), SIN volumen: multiplicar por "volumen" (vol del SIT / 127 * atenuacion de '
                       'la region); el juego ademas atenua / panea por distancia a la camara (SndCall + curva del '
                       'SIT). Generado por re4_extract_sonidos_combate.py.',
        'fuente': 'decompilacion ../re4/src (ver "cuando" de cada uno) + bancos del disco (tools/re4_sonidos.py)',
        'ya_existentes': {
            'pistola_vacia_click': 'out/sonidos/pistola_vacia_click.wav (WEP 0x17, wep/pl_handgun.cpp:308)',
            'pistola_recarga': 'out/sonidos/pistola_recarga.wav (WEP 0x16)',
            'disparo': 'out/sonidos/disparo_pistola.wav (WEP 0+1+2)',
            'cuchillo_tajo': 'out/sonidos/cuchillo_tajo.wav (PL 3, knife_r3_fire10 frame 3)',
        },
        'no_existen_en_el_juego': FALTANTES,
        'reglas': {
            'grupos_rnd': 'game/snd.cpp seRandomCheck: si el SIT pedido tiene rnd_no, se toca un miembro al azar del '
                          'grupo (Rnd() % num) evitando repetir el ultimo (hasta 5 intentos)',
            'voces_ganado': 'em10CallVoiceSe2 corta la voz y la respiracion anteriores (SndStop Seid_voice / '
                            'Seid_breath) y no suena si Be_flg 0x80; reinicia la respiracion a 120..239 frames',
            'historial_enemigo': 'game/snd.cpp emSeCheck: el mismo (id, SE) no se repite mientras siga en el '
                                 'historial de 32 entradas (1 frame)',
        },
        'sonidos': lista,
    }
    with open(os.path.join(OUT, 'sonidos.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'{len(lista)} WAV + sonidos.json en {OUT}')


if __name__ == '__main__':
    exportar()
