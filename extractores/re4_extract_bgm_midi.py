#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
re4_extract_bgm_midi.py - BGM SECUENCIADA de Resident Evil 4 (GameCube) -> WAV con loop (chunk 'smpl').

La musica de fondo de r100 (antes del evento de la cabana) NO es un stream: es una secuencia MIDI que
toca el secuenciador del juego (game/snd_seq*.cpp) sobre el sintetizador SYN del SDK de Dolphin
(lib/syn*.c) con un banco de instrumentos DLS convertido a "WT" (muestras DSP-ADPCM en ARAM), mezclado
por la libreria MIX (lib/mix.c) en voces AX. Este script lo EMULA offline siguiendo el codigo de la
decompilacion:

  bgm/bio4midi.hed   : tabla de offsets (u32) de cada BGM dentro de bio4midi.dat (SndMem.bgm_file,
                       SndBgmLoad: DvdRead(0x61, ofs = bgm_file[n])).
  bio4midi.dat[n]    : archivo "con cabecera" del DVD (DvdHeader de 0x20 bytes desde +0x20):
                         TRANS_SND_BLK (1) -> MRAM, bloque de sonido 3 = BGM0 (ISS block)
                         TRANS_SND_PCM (2) -> ARAM, las muestras ADPCM
                         0xFFFFFFFF        -> fin
  ISS block          : u32 num, ofs DLS(WT), ofs SIT, ofs tabla de secuencias (snd_sub3 Snd_iss_blk_init)
  WT (dls)           : 6 offsets (percusion, melodicos, regiones, articulaciones, muestras, ADPCM)
                       = SYNInitSynth; WTINST[128 u16], WTREGION(24), WTART(80), WTSAMPLE(16), WTADPCM(46)
  SIT[n] (0x18)      : note>>8 = banco -> secuencia = tabla[banco + 1] (Snd_iss_new_seq_work)
  Secuencia          : stream unico (todas las pistas mezcladas): delta VLQ + mensaje de 3 bytes
                       (program change avanza 2), FF 51 tempo, FF 2F fin, CC 0x66 marca loop,
                       CC 0x67 salta al loop, CC 0x68 prioridad, CC 0x69 canal de bateria.
                       Reloj: cada ms delta -= division (480); delta = ticks * tempo(ms/negra).

Salida (por defecto entrada 0 = r100):
  out/bgm/r100_bgm.wav  (32 kHz estereo 16 bit, chunk smpl con el loop, fin INCLUSIVO)
  out/bgm/r100_bgm.json (tempo, duracion, loop, canales, instrumentos, tabla de BGMs, caveats)
  out/bgm/control/*.png (espectrograma, forma de onda, costura del loop)

Uso: python3 re4_extract_bgm_midi.py [--entrada N] [--sit S] [--nombre r100_bgm] [--todas]
"""
import argparse
import bisect
import json
import math
import os
import struct
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
DAT = os.path.join(AQUI, 'extracted', 'tmp', 'bio4midi.dat')
HED = os.path.join(AQUI, 'extracted', 'bgm', 'bio4midi.hed')
BGMTBL = os.path.join(AQUI, 'extracted', 'bgm', 'bgmtbl.dat')
SALIDA = os.path.join(AQUI, 'out', 'bgm')

FS = 32000            # AX: 32 kHz nominal, cuadro de audio = 160 muestras = 5 ms
CUADRO = 160
MS = FS // 1000       # 32 muestras por ms de secuenciador

# ---------------------------------------------------------------------------------------------
# Tablas de la decompilacion (lib/mix.c, lib/synmix.c, lib/synpitch.c, lib/synlfo.c, game/snd_sub0.cpp)
# ---------------------------------------------------------------------------------------------
# __MIXPanTable (dB*10)
MIX_PAN = [0, 0, -1, -1, -1, -2, -2, -2, -3, -3, -4, -4, -4, -5, -5, -5, -6, -6, -7, -7, -7, -8, -8, -9, -9,
           -10, -10, -10, -11, -11, -12, -12, -13, -13, -14, -14, -14, -15, -15, -16, -16, -17, -17, -18, -18,
           -19, -20, -20, -21, -21, -22, -22, -23, -23, -24, -25, -25, -26, -26, -27, -28, -28, -29, -30, -30,
           -31, -32, -33, -33, -34, -35, -36, -36, -37, -38, -39, -40, -40, -41, -42, -43, -44, -45, -46, -47,
           -48, -49, -50, -51, -52, -54, -55, -56, -57, -59, -60, -61, -63, -64, -66, -67, -69, -71, -72, -74,
           -76, -78, -80, -83, -85, -87, -90, -93, -96, -99, -102, -106, -110, -115, -120, -126, -133, -140,
           -150, -163, -180, -210, -904]
# __SYNAttackAttnTable (dB*10 << 16)
SYN_ATAQUE = [-62914560, -26157189, -22211529, -19903465, -18265868, -16995649, -15957805, -15080320,
              -14320208, -13649742, -13050501, -12507447, -12012145, -11556511, -11134660, -10741926,
              -10374548, -10029449, -9704081, -9396310, -9104329, -8826596, -8561787, -8308750,
              -8066484, -7834110, -7610850, -7396018, -7189001, -6989246, -6796265, -6609613,
              -6428887, -6253723, -6083789, -5918780, -5758421, -5602455, -5450650, -5302787,
              -5158668, -5018109, -4880936, -4746991, -4616126, -4488202, -4363090, -4240668,
              -4120824, -4003451, -3888449, -3775725, -3665190, -3556760, -3450358, -3345907,
              -3243339, -3142586, -3043586, -2946278, -2850605, -2756514, -2663953, -2572873,
              -2483227, -2394971, -2308063, -2222461, -2138128, -2055026, -1973120, -1892376,
              -1812761, -1734244, -1656795, -1580386, -1504989, -1430578, -1357127, -1284611,
              -1213008, -1142294, -1072448, -1003449, -935276, -867909, -801331, -735522,
              -670466, -606144, -542542, -479642, -417429, -355889, -295008, -234770,
              -175164, -116175, -57791, 0]
# Snd_dls_vol_tbl[90] (volumen 90 del SIT -> atenuacion AX en dB*10)
DLS_VOL_90 = -60
ENV_INF = -0x80000000   # 0x80000000 = "sin tiempo" en las articulaciones


def cdiv(a, b):
    """division entera de C (trunca hacia 0)"""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def cmod(a, b):
    return a - cdiv(a, b) * b


def s32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


def f32(x):
    return float(np.float32(x))


def syn_vol_atten(v):
    """__SYNVolumeAttenuation[v]: 40*log10(v/127) dB, en dB*10 << 16 (tabla verificada contra synmix.c)"""
    if v == 0:
        return -960 << 16
    return int(round(400.0 * math.log10(v / 127.0) * 65536.0))


def mix_get_volume(db):
    """__MIXGetVolume: dB*10 -> ganancia 1.15 (0x8000 = 0 dB); tabla de mix.c = esta formula +-1"""
    if db <= -904:
        return 0
    if db >= 60:
        return 0xFF64
    return int(round(32768.0 * 10.0 ** (db / 200.0)))


# __SYNCentsTable / Octaves / Semitones (f32 = 2^(x/1200) redondeado a 6 decimales en la fuente)
_CENTS = [f32(round(2.0 ** (c / 1200.0), 6)) for c in range(100)]
_SEMI_UP = [f32(round(2.0 ** (s / 12.0), 6)) for s in range(12)]
_SEMI_DN = [f32(round(2.0 ** (-s / 12.0), 6)) for s in range(128)]
_LFO = [f32(round(math.sin(2 * math.pi * i / 64.0), 5)) for i in range(64)]


def syn_relative_pitch(cents_fx):
    """__SYNGetRelativePitch: cents (<<16) -> factor f32, con la aritmetica entera de C"""
    cents = cdiv(cents_fx, 65536)
    if cents > 0:
        octv = cents // 1200
        semi = (cents % 1200) // 100
        c = cents % 100
        return f32(f32(float(1 << octv) * _SEMI_UP[semi]) * _CENTS[c])
    if cents < 0:
        semi = cdiv(cents, 100)
        c = cmod(cents, 100)
        if c != 0:
            c += 100
            semi -= 1
        return f32(_SEMI_DN[-semi] * _CENTS[c])
    return 1.0


def syn_envelope_time(scale, mod, key):
    """__SYNGetEnvelopeTime (ms); ojo: con modulacion divide por 65535 (asi esta en synenv.c)"""
    if scale == ENV_INF:
        return 0
    if mod == ENV_INF:
        return int(f32(1000.0 * f32(2.0 ** f32(scale / (65536 * 1200)))))
    n128 = key / 128.0
    return int(f32(1000.0 * f32(2.0 ** f32((scale + mod * n128) / (65535 * 1200)))))


# ---------------------------------------------------------------------------------------------
# DSP-ADPCM
# ---------------------------------------------------------------------------------------------
def adpcm_decode(data, nib_start, n, coefs, ps, yn1, yn2):
    """Decodifica n muestras desde la direccion de nibble nib_start (que NO apunta a una cabecera).
    Igual que el acelerador del DSP: cada vez que la direccion cae en el inicio de un cuadro de 16 nibbles
    lee la cabecera (pred_scale) y saltea 2 nibbles."""
    out = np.zeros(n, np.int16)
    a = nib_start
    cs = [(c - 65536 if c >= 32768 else c) for c in coefs]
    for i in range(n):
        if (a & 15) == 0:
            ps = data[a >> 1]
            a += 2
        scale = 1 << (ps & 15)
        ci = (ps >> 4) & 7
        b = data[a >> 1]
        nb = (b >> 4) if (a & 1) == 0 else (b & 15)
        if nb >= 8:
            nb -= 16
        v = ((nb * scale) << 11) + cs[ci * 2] * yn1 + cs[ci * 2 + 1] * yn2
        v = (v + 1024) >> 11
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out[i] = v
        yn2, yn1 = yn1, v
        a += 1
    return out


def nib_addr(count):
    """__SYNGetNibbleAddress"""
    return (count // 14) * 16 + 2 + count % 14


# ---------------------------------------------------------------------------------------------
# Archivo bio4midi.dat
# ---------------------------------------------------------------------------------------------
class BancoBgm:
    """Una entrada de bio4midi.dat: bloque ISS (WT + SIT + secuencias) + muestras ARAM."""

    def __init__(self, dat, ofs, tam):
        e = dat[ofs:ofs + tam]
        self.ofs, self.tam = ofs, tam
        self.mram = self.aram = None
        p = 0x20
        self.cabeceras = []
        while True:
            typ, size, dest, fofs, stype, sarg, sno, x1c = struct.unpack('>8I', e[p:p + 32])
            if typ == 0xFFFFFFFF:
                break
            self.cabeceras.append(dict(tipo=typ, tam=size, ofs=fofs, bloque_snd=stype))
            if typ == 1:     # TRANS_SND_BLK -> MRAM (bloque 3 = BGM0)
                self.mram = e[fofs:fofs + size]
            elif typ == 2:   # TRANS_SND_PCM -> ARAM
                self.aram = e[fofs:fofs + size]
            p += 32
        b = self.mram
        self.num_sit, o_dls, o_sit, o_seq = struct.unpack('>4I', b[:16])
        w = b[o_dls:]
        self.wt = w
        h = struct.unpack('>6I', w[:24])
        self.h = h
        # WTINST: percusion en h[0], melodicos en h[1] (SYNInitSynth); el numero se deduce del siguiente offset
        self.n_inst = (h[2] - h[1]) // 256
        self.inst = [struct.unpack('>128H', w[h[1] + i * 256:h[1] + i * 256 + 256]) for i in range(self.n_inst)]
        self.perc = [struct.unpack('>128H', w[h[0] + i * 256:h[0] + i * 256 + 256])
                     for i in range((h[2] - h[0]) // 256)]
        self.rgn = []
        for i in range((h[3] - h[2]) // 24):
            u, kg, ft, attn, ls, ll, ai, si = struct.unpack('>BBhiIIII', w[h[2] + i * 24:h[2] + i * 24 + 24])
            self.rgn.append(dict(unity=u, keygroup=kg, finetune=ft, attn=attn, loop_start=ls, loop_len=ll,
                                 art=ai, sample=si))
        self.art = []
        nombres = ['lfoFreq', 'lfoDelay', 'lfoAtten', 'lfoPitch', 'lfoMod2Atten', 'lfoMod2Pitch', 'eg1Attack',
                   'eg1Decay', 'eg1Sustain', 'eg1Release', 'eg1Vel2Attack', 'eg1Key2Decay', 'eg2Attack',
                   'eg2Decay', 'eg2Sustain', 'eg2Release', 'eg2Vel2Attack', 'eg2Key2Decay', 'eg2Pitch', 'pan']
        for i in range((h[4] - h[3]) // 80):
            self.art.append(dict(zip(nombres, struct.unpack('>20i', w[h[3] + i * 80:h[3] + i * 80 + 80]))))
        self.smp = []
        for i in range((h[5] - h[4]) // 16):
            fmt, rate, sofs, ln, ai = struct.unpack('>HHIIH', w[h[4] + i * 16:h[4] + i * 16 + 14])
            self.smp.append(dict(formato=fmt, rate=rate, ofs=sofs, largo=ln, adpcm=ai))
        n_adp = max(s['adpcm'] for s in self.smp) + 1
        self.adpcm = []
        for i in range(n_adp):
            x = struct.unpack('>23H', w[h[5] + i * 46:h[5] + i * 46 + 46])
            sg = lambda v: v - 65536 if v >= 32768 else v
            self.adpcm.append(dict(coefs=list(x[:16]), gain=x[16], ps=x[17], yn1=sg(x[18]), yn2=sg(x[19]),
                                   lps=x[20], lyn1=sg(x[21]), lyn2=sg(x[22])))
        self.sit = []
        for i in range(self.num_sit):
            r = b[o_sit + i * 0x18:o_sit + i * 0x18 + 0x18]
            note, vs, vn, prio, pan, vol = struct.unpack('>HbbbbB', r[:7])
            flag, = struct.unpack('>H', r[0x16:0x18])
            self.sit.append(dict(note=note, banco=note >> 8, voice_start=vs, voice_num=vn, prio=prio, pan=pan,
                                 vol=vol, flag=flag, wall_vol=r[0x15]))
        t = b[o_seq:]
        n, = struct.unpack('>I', t[:4])
        self.seq_ofs = list(struct.unpack('>%dI' % n, t[4:4 + 4 * n]))
        self.seq_base = o_seq
        self.mram_bytes = b
        self._dec = {}

    def secuencia(self, banco):
        """(bytes del bloque MRAM, offset de inicio) de la secuencia del banco"""
        return self.mram_bytes, self.seq_base + self.seq_ofs[banco]

    def muestra(self, si, rgn):
        """Devuelve (A, Lp): A = decodificacion lineal desde el inicio hasta el fin (de loop o de muestra),
        Lp = la region de loop decodificada con el contexto de loop (lo que suena despues de cada salto)."""
        clave = (si, rgn['loop_start'], rgn['loop_len'])
        if clave in self._dec:
            return self._dec[clave]
        s = self.smp[si]
        if s['formato'] != 0:
            raise NotImplementedError('formato de muestra %d (solo ADPCM)' % s['formato'])
        ad = self.adpcm[s['adpcm']]
        base = s['ofs']              # nibbles desde el inicio del bloque ARAM
        con_loop = (rgn['loop_start'] + rgn['loop_len']) != 0
        fin = (rgn['loop_start'] + rgn['loop_len']) if con_loop else s['largo']
        A = adpcm_decode(self.aram, base + 2, fin, ad['coefs'], ad['ps'], ad['yn1'], ad['yn2'])
        Lp = None
        if con_loop:
            # el AX salta a loopAddr (= inicio + nib_addr(loopStart), nunca una cabecera) y carga
            # loop_pred_scale / loop_yn1 / loop_yn2 del PB (__SYNSetupAdpcm los copia de WTADPCM)
            Lp = adpcm_decode(self.aram, base + nib_addr(rgn['loop_start']), rgn['loop_len'], ad['coefs'],
                              ad['lps'], ad['lyn1'], ad['lyn2'])
        self._dec[clave] = (A, Lp)
        return A, Lp


def leer_hed():
    h = open(HED, 'rb').read()
    ofs = list(struct.unpack('>%dI' % (len(h) // 4), h))
    tam_dat = os.path.getsize(DAT)
    # la tabla termina en el primer 0 despues del primero
    n = 1
    while n < len(ofs) and ofs[n] != 0:
        n += 1
    ofs = ofs[:n]
    return [(o, (ofs[i + 1] if i + 1 < n else tam_dat) - o) for i, o in enumerate(ofs)]


# ---------------------------------------------------------------------------------------------
# Secuenciador del juego (snd_seq1/2/3) + voice works (snd_sub1)
# ---------------------------------------------------------------------------------------------
class Secuenciador:
    """Emula Snd_midi_sequencer ms a ms; produce los mensajes que llegan al SYN (con su ms y orden)."""

    def __init__(self, data, inicio, sit):
        self.d = data
        self.pos = inicio
        self.top = inicio
        self.loop = inicio
        self.tempo = 1000
        self.division = 480
        self.activo = True
        self.ch_prio = [0] * 16
        self.ch_flag = [0] * 16
        self.sit = sit
        self.vw = [dict(status=0, prio=0, count_f=0, ch=-1, note=-1) for _ in range(sit['voice_num'] + 1)]
        self.salida = []      # (ms, [status, d1, d2])
        self.marcas = []      # (ms, 'loop_set'|'loop_jump'|'fin'|'tempo', valor)
        self.notas_descartadas = 0
        self.robos = 0
        self.delta = self.get_delta()   # OJO: el primer delta NO se multiplica por el tempo (seq3)

    def get_delta(self):
        d = self.d[self.pos]
        self.pos += 1
        if d & 0x80:
            c = self.d[self.pos]
            self.pos += 1
            d = ((d & 0x7F) << 7) | (c & 0x7F)
            if c & 0x80:
                c = self.d[self.pos]
                self.pos += 1
                d = (d << 7) | (c & 0x7F)
                if c & 0x80:
                    c = self.d[self.pos]
                    self.pos += 1
                    d = (d << 7) | (c & 0x7F)
        return d

    def enviar(self, ms, msg):
        self.salida.append((ms, list(msg)))

    # --- voice works (Snd_voice_work_open_ck): rango del SIT, robo del mas viejo de menor prioridad ---
    def abrir_voz(self, ms, prio):
        fr = ms // 5
        for v in self.vw:
            if v['status'] == 0:
                return v
        min_p = 0x7F
        for v in self.vw:
            if min_p >= v['prio']:
                min_p = v['prio']
        if min_p > prio:
            return None
        if min_p == prio and not (self.sit['flag'] & 0x4000):
            return None
        found, count = None, 0
        for v in self.vw:
            if min_p != v['prio']:
                continue
            c = fr - v['count_f']
            if count <= c:
                found, count = v, c
        if found is None:
            return None
        # Snd_stop_voice_work: nota off (9x vel 0) al synth
        self.enviar(ms, [0x90 | found['ch'], found['note'], 0])
        found['status'] = 0
        self.robos += 1
        return found

    def drums(self, msg):
        ch = msg[0] & 15
        if self.ch_flag[ch] & 1:
            msg[0] = (msg[0] & 0xF0) | 9
        return msg

    def mensaje(self, ms):
        d = self.d
        p = self.pos
        msg = [d[p], d[p + 1], d[p + 2]]
        typ, ch = msg[0] & 0xF0, msg[0] & 15
        if typ == 0x90 and msg[2] != 0:
            self.pos += 3
            v = self.abrir_voz(ms, self.ch_prio[ch])
            if v is None:
                self.notas_descartadas += 1
                return
            v['prio'] = self.ch_prio[ch]
            msg = self.drums(msg)
            v.update(status=1, count_f=ms // 5, ch=msg[0] & 15, note=msg[1])
            self.enviar(ms, msg)
        elif typ == 0x80 or typ == 0x90:
            self.pos += 3
            msg = self.drums(msg)
            chn = msg[0] & 15
            for v in self.vw:   # Snd_search_voice_work_seq (el primero que coincide)
                if v['status'] and v['ch'] == chn and v['note'] == msg[1]:
                    v['status'] = 0
                    self.enviar(ms, msg)
                    break
        elif typ == 0xC0:
            self.pos += 2
            self.enviar(ms, msg[:2] + [0])
        elif typ == 0xB0:
            self.pos += 3
            cc = msg[1]
            if cc in (0x06, 0x26):
                # seq_ctrl_data_entry: manda RPN 0 (64/65 = 0) y NO reenvia el data entry
                self.enviar(ms, [0xB0 | ch, 0x64, 0])
                self.enviar(ms, [0xB0 | ch, 0x65, 0])
                return
            if cc == 0x66:
                self.loop = self.pos
                self.marcas.append((ms, 'loop_set', self.pos))
                return
            if cc == 0x67:
                self.pos = self.loop
                self.marcas.append((ms, 'loop_jump', self.loop))
                return
            if cc == 0x68:
                self.ch_prio[ch] = msg[2]
                return
            if cc == 0x69:
                self.ch_flag[ch] |= 1
                return
            if cc not in (0x01, 0x07, 0x0A, 0x0B, 0x40, 0x5B, 0x5C):
                raise ValueError('SND SEQ data error: %02X %02X %02X' % tuple(msg))
            self.enviar(ms, msg)
        elif typ == 0xE0:
            self.pos += 3
            self.enviar(ms, msg)
        elif typ == 0xF0:
            if msg[1] == 0x2F:
                self.activo = False
                self.marcas.append((ms, 'fin', 0))
            elif msg[1] == 0x51:
                self.pos += 2
                self.get_delta()
                t = (d[self.pos] << 16) | (d[self.pos + 1] << 8) | d[self.pos + 2]
                self.pos += 3
                self.tempo = t // 1000
                self.marcas.append((ms, 'tempo', t))
            else:
                raise ValueError('SEQ data error: %02X %02X %02X' % tuple(msg))
        else:
            raise ValueError('SND SEQ data error: %02X %02X %02X' % tuple(msg))

    def un_ms(self, ms):
        """seq_one_msec"""
        while True:
            if self.delta == 0:
                self.mensaje(ms)
                if not self.activo:
                    return
                self.delta = self.get_delta() * self.tempo
            else:
                self.delta -= self.division
                if self.delta > 0:
                    break
                self.delta = 0

    def correr(self, hasta_ms, pasadas_loop=None):
        ms = 0
        saltos = 0
        while ms < hasta_ms and self.activo:
            n = len(self.marcas)
            self.un_ms(ms)
            saltos += sum(1 for m in self.marcas[n:] if m[1] == 'loop_jump')
            if pasadas_loop is not None and saltos >= pasadas_loop:
                break
            ms += 1
        return ms


def analizar_secuencia(banco, banco_seq, sit, max_ms=30 * 60 * 1000):
    """Recorre la secuencia hasta el primer salto de loop (o el fin): tiempos, notas, canales."""
    data, ini = banco.secuencia(banco_seq)
    sq = Secuenciador(data, ini, sit)
    sq.correr(max_ms, pasadas_loop=1)
    r = dict(tempos=[m for m in sq.marcas if m[1] == 'tempo'])
    ls = [m[0] for m in sq.marcas if m[1] == 'loop_set']
    lj = [m[0] for m in sq.marcas if m[1] == 'loop_jump']
    fin = [m[0] for m in sq.marcas if m[1] == 'fin']
    r['loop_ms'] = (ls[-1], lj[0]) if (ls and lj) else None
    r['fin_ms'] = fin[0] if fin else None
    r['notas'] = sum(1 for _, m in sq.salida if (m[0] & 0xF0) == 0x90 and m[2])
    r['canales'] = sorted({m[0] & 15 for _, m in sq.salida if (m[0] & 0xF0) == 0x90})
    return r, sq


# ---------------------------------------------------------------------------------------------
# SYN (synctrl.c) a nivel de mensajes: estado de canal en el tiempo + lista de voces
# ---------------------------------------------------------------------------------------------
class Voz:
    __slots__ = ('ch', 'key', 'vel', 'rgn', 'art', 'si', 'ms', 'orden', 'rel_ms', 'kill_ms', 'pan_fijo', 'pase',
                 'prog', '_hold')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        self._hold = False


class Synth:
    def __init__(self, banco, master_db):
        self.b = banco
        self.master = master_db << 16
        self.ctrl = [[0] * 128 for _ in range(16)]
        self.rpn = [0] * 16
        self.pw_max = [0xC80000] * 16
        self.pw = [0] * 16
        self.vol_attn = [0] * 16
        self.exp_attn = [0] * 16
        self.prog = [0] * 16
        self.inst_perc = [False] * 16
        self.voz = [[None] * 128 for _ in range(16)]
        self.keygroup = [[None] * 16 for _ in range(16)]
        self.voces = []
        self.faltantes = 0
        # historial por canal: (ms, orden, vol_attn, exp_attn, pan, pw_cents, mod, auxA)
        self.hist = [[] for _ in range(16)]
        self.orden = 0
        self.ms = 0
        for ch in range(16):        # __SYNResetAllControllers
            self.program(ch, 0)
            self.reset_ctrl(ch)
        self.orden = -1
        for ch in range(16):
            self.snap(ch)
        self.orden = 0

    def snap(self, ch):
        self.hist[ch].append((self.ms, self.orden, self.vol_attn[ch], self.exp_attn[ch], self.ctrl[ch][10],
                              self.pw[ch], self.ctrl[ch][1], syn_vol_atten(self.ctrl[ch][0x5B])))

    def program(self, ch, p):
        self.inst_perc[ch] = (ch == 9)
        self.prog[ch] = p

    def reset_ctrl(self, ch):
        self.pw_max[ch] = 0xC80000
        self.pw[ch] = 0
        self.ctrl[ch] = [0] * 128
        for f, v in ((7, 100), (10, 64), (11, 127), (0x5B, 0), (0x5C, 0)):
            self.set_ctrl(ch, f, v)

    def release(self, v):
        if v is not None and v.rel_ms is None:
            v.rel_ms = self.ms

    def set_ctrl(self, ch, f, val):
        self.ctrl[ch][f] = val
        if f in (6, 0x26):
            if self.rpn[ch]:
                prm = (self.ctrl[ch][0x65] << 8) + self.ctrl[ch][0x64]
                if prm == 0:
                    self.pw_max[ch] = (self.ctrl[ch][0x26] + self.ctrl[ch][6] * 100) << 16
        elif f == 7:
            self.vol_attn[ch] = syn_vol_atten(val)
        elif f == 11:
            self.exp_attn[ch] = syn_vol_atten(val)
        elif f == 0x40:
            if val < 64:
                for k in range(128):
                    v = self.voz[ch][k]
                    if v is not None and getattr(v, '_hold', False):
                        self.release(v)
                        self.voz[ch][k] = None
        elif f in (0x62, 0x63):
            self.rpn[ch] = 0
        elif f in (0x64, 0x65):
            self.rpn[ch] = 1
        elif f in (0x78, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F):
            for k in range(128):
                if self.voz[ch][k] is not None:
                    self.release(self.voz[ch][k])
                    self.voz[ch][k] = None
        elif f == 0x79:
            if val == 0:
                vol, pan, exp = self.ctrl[ch][7], self.ctrl[ch][10], self.ctrl[ch][11]
                self.pw_max[ch] = 0xC80000
                self.pw[ch] = 0
                self.ctrl[ch] = [0] * 128
                for ff, vv in ((7, vol), (10, pan), (11, exp), (0x5B, 0), (0x5C, 0)):
                    self.set_ctrl(ch, ff, vv)
            else:
                self.reset_ctrl(ch)

    def note_off(self, ch, key):
        v = self.voz[ch][key]
        if v is not None:
            if self.ctrl[ch][64] > 64:
                v._hold = True
                return
            self.release(v)
            self.voz[ch][key] = None

    def note_on(self, ch, key, vel, pase):
        if vel == 0:
            self.note_off(ch, key)
            return
        if self.voz[ch][key] is not None:
            self.release(self.voz[ch][key])
            self.voz[ch][key] = None
        tabla = self.b.perc if self.inst_perc[ch] else self.b.inst
        if self.prog[ch] >= len(tabla):
            self.faltantes += 1
            return
        ri = tabla[self.prog[ch]][key]
        if ri == 0xFFFF:
            self.faltantes += 1
            return
        rgn = self.b.rgn[ri]
        art = self.b.art[rgn['art']]
        v = Voz(ch=ch, key=key, vel=vel, rgn=rgn, art=art, si=rgn['sample'], ms=self.ms, orden=self.orden,
                rel_ms=None, kill_ms=None, pan_fijo=(art['pan'] if ch == 9 else None), pase=pase,
                prog=self.prog[ch])
        self.voz[ch][key] = v
        kg = rgn['keygroup']
        if kg:
            old = self.keygroup[ch][kg]
            if old is not None and old.kill_ms is None:
                old.kill_ms = self.ms           # AXFreeVoice inmediato
                if self.voz[ch][old.key] is old:
                    self.voz[ch][old.key] = None
            self.keygroup[ch][kg] = v
        self.voces.append(v)

    def midi(self, ms, msg, pase):
        self.ms = ms
        self.orden += 1
        st, d1, d2 = msg
        f, ch = st >> 4, st & 15
        if f == 8:
            self.note_off(ch, d1)
        elif f == 9:
            self.note_on(ch, d1, d2, pase)
        elif f == 11:
            self.set_ctrl(ch, d1, d2)
            self.snap(ch)
        elif f == 12:
            self.program(ch, d1)
        elif f == 14:
            pos = d1 + (d2 << 7) - 0x2000
            self.pw[ch] = int(f32(self.pw_max[ch] * f32(pos / 8192.0)))
            self.snap(ch)



class Historial:
    """Busqueda rapida del estado de un canal: antes de un ms (servicio de voz) o en un orden (note on)."""

    def __init__(self, hist):
        self.h = hist
        self.ms = [x[0] for x in hist]
        self.orden = [x[1] for x in hist]

    def antes_de_ms(self, t):
        i = bisect.bisect_left(self.ms, t) - 1
        return self.h[max(i, 0)]

    def en_orden(self, o):
        i = bisect.bisect_left(self.orden, o) - 1
        return self.h[max(i, 0)]


# ---------------------------------------------------------------------------------------------
# Render de una voz (synvoice/synenv/synlfo/synpitch/synmix + MIX + AX)
# ---------------------------------------------------------------------------------------------
def render_voz(v, banco, hist, master, horizonte_ms):
    """Devuelve (inicio_muestra, L, R) o None. Cuadros de 5 ms locales a la voz (bloque 0 = el del note on)."""
    art, rgn = v.art, v.rgn
    smp = banco.smp[v.si]
    A, Lp = banco.muestra(v.si, rgn)
    con_loop = Lp is not None
    N = len(A)
    # --- __SYNSetupPitch / Volume / Lfo / VolumeEnvelope / PitchEnvelope ---
    src_ratio = f32(smp['rate'] / 32000.0)
    cents = (((v.key - rgn['unity']) * 100 + rgn['finetune']) << 16)
    attn = rgn['attn'] + syn_vol_atten(v.vel)
    lfo_state = lfo_attn = 0
    lfo_cents = art['lfoPitch']          # (sic) synlfo: lfoCents = lfoPitch; lfoCents_ nunca se asigna (=0)
    lfo_freq, lfo_delay = art['lfoFreq'], art['lfoDelay']
    lfo_attn_, lfo_cents_ = art['lfoAtten'], 0
    lfo_mod_attn, lfo_mod_cents = art['lfoMod2Atten'], art['lfoMod2Pitch']
    # volumen
    if art['eg1Attack'] == ENV_INF:
        ve_state, ve_attn = 1, 0
        if art['eg1Decay'] == ENV_INF:
            ve_state, ve_attn = 2, art['eg1Sustain']
        ve_attack = ve_attack_d = 0
    else:
        fr = cdiv(syn_envelope_time(art['eg1Attack'], art['eg1Vel2Attack'], v.vel), 5)
        ve_attack = 0
        ve_attack_d = cdiv(0x640000, fr) if fr != 0 else 0x640000
        ve_attn = -0x03C00000
        ve_state = 0
    ve_decay = 0
    if ve_state < 2:
        fr = cdiv(syn_envelope_time(art['eg1Decay'], art['eg1Key2Decay'], v.key), 5)
        ve_decay = cdiv(-0x03C00000, fr) if fr != 0 else -0x03C00000
    ve_sus, ve_rel = art['eg1Sustain'], art['eg1Release']
    # tono
    pe_cents = 0
    pe_pitch = art['eg2Pitch']
    pe_state = 2
    pe_attack = pe_decay = pe_sus = pe_rel = 0
    if pe_pitch != 0:
        if art['eg2Attack'] == ENV_INF:
            pe_state, pe_cents = 1, pe_pitch
            if art['eg2Decay'] == ENV_INF:
                pe_state, pe_cents = 2, art['eg2Sustain']
        else:
            fr = cdiv(syn_envelope_time(art['eg2Attack'], art['eg2Vel2Attack'], v.vel), 5)
            pe_attack = cdiv(pe_pitch, fr) if fr != 0 else pe_pitch
            pe_state = 0
        if pe_state < 2:
            fr = cdiv(syn_envelope_time(art['eg2Decay'], art['eg2Key2Decay'], v.key), 5)
            pe_decay = -(cdiv(pe_pitch, fr) if fr != 0 else pe_pitch)
        pe_sus, pe_rel = art['eg2Sustain'], art['eg2Release']

    def estado_mix(h):
        _, _, vol_a, exp_a, pan, pw, mod, aux = h
        fader = (vol_a + exp_a + master) >> 16
        p = v.pan_fijo if v.pan_fijo is not None else pan
        return fader, p, pw, mod

    def ganancias(inp, fader, pan):
        vv = mix_get_volume(inp)
        vl = mix_get_volume(fader + MIX_PAN[pan] + MIX_PAN[0])      # span 127 -> f = PanTable[0]
        vr = mix_get_volume(fader + MIX_PAN[127 - pan] + MIX_PAN[0])
        return vv, vl, vr

    def ratio_de(pw):
        r = src_ratio * syn_relative_pitch(cents + lfo_cents + pe_cents + pw)
        u = int(65536.0 * f32(r))
        return min(u, 0x40000)

    h0 = hist.en_orden(v.orden)
    fader, pan, pw, mod = estado_mix(h0)
    inp = (attn + lfo_attn + ve_attn) >> 16
    g = ganancias(inp, fader, pan)
    ratios = [ratio_de(pw)]
    gan = [g]
    liberada = False
    k = 0
    pos = 0                  # 16.16 en muestras del "sample" desenrollado
    fin_bloque = None
    kill_bloque = None
    if v.kill_ms is not None:
        kill_bloque = (v.kill_ms - v.ms + 4) // 5     # AXFreeVoice en el cuadro del note on siguiente
    max_bloques = (horizonte_ms - v.ms) // 5 + 1
    pos += ratios[0] * CUADRO
    if not con_loop and (pos >> 16) >= N:
        fin_bloque = 0
    while True:
        k += 1
        if k >= max_bloques or (kill_bloque is not None and k >= kill_bloque):
            break
        t = v.ms + 5 * k
        if fin_bloque is not None:            # type 0 y pb.state 0 -> veState 4
            break
        if not liberada and v.rel_ms is not None and v.rel_ms < t:
            liberada = True
            ve_state = 3
            pe_state = 3
        # __SYNRunVolumeEnvelope
        if ve_state == 0:
            ve_attack += ve_attack_d
            ve_attn = 0 if ve_attack >= 0x630000 else SYN_ATAQUE[ve_attack >> 16]
            if ve_attn == 0:
                ve_state = 1
        elif ve_state == 1:
            ve_attn += ve_decay
            if ve_attn <= ve_sus:
                ve_attn = ve_sus
                ve_state = 2
            if ve_attn <= -0x02D00000:
                ve_state = 4
        elif ve_state == 3:
            if ve_attn <= -0x02D00000:
                ve_state = 4
            else:
                ve_attn += ve_rel
        if ve_state == 4:
            break
        h = hist.antes_de_ms(t)
        fader, pan, pw, mod = estado_mix(h)
        # __SYNRunLfo
        if lfo_delay != 0:
            lfo_delay -= 1
        else:
            lfo_state = s32(lfo_state + lfo_freq)
            amp = _LFO[(lfo_state >> 16) % 64]
            mw = mod / 128.0
            lfo_attn = int(f32(amp * (lfo_attn_ + lfo_mod_attn * mw)))
            lfo_cents = int(f32(amp * (lfo_cents_ + lfo_mod_cents * mw)))
        # __SYNRunPitchEnvelope
        if pe_pitch != 0:
            if pe_state == 0:
                pe_cents += pe_attack
                if (pe_pitch > 0 and pe_cents >= pe_pitch) or (pe_pitch < 0 and pe_cents <= pe_pitch):
                    pe_pitch = pe_cents
                    pe_state = 1
            elif pe_state == 1:
                pe_cents += pe_decay
                if pe_pitch > 0:
                    if pe_cents <= 0:
                        pe_cents = pe_pitch = 0
                    elif pe_cents <= pe_sus:
                        pe_cents, pe_state = pe_sus, 2
                else:
                    if pe_cents >= 0:
                        pe_cents = pe_pitch = 0
                    elif pe_cents >= pe_sus:
                        pe_cents, pe_state = pe_sus, 2
            elif pe_state == 3:
                pe_cents += pe_rel
                if (pe_pitch > 0 and pe_cents <= 0) or (pe_pitch < 0 and pe_cents >= 0):
                    pe_cents = pe_pitch = 0
        inp = (attn + lfo_attn + ve_attn) >> 16
        gan.append(ganancias(inp, fader, pan))
        ratios.append(ratio_de(pw))
        pos += ratios[-1] * CUADRO
        if not con_loop and (pos >> 16) >= N:
            fin_bloque = k
    nb = len(ratios)
    if nb == 0:
        return None
    # --- AX: SRC lineal + rampas de volumen de MIX (160 muestras por cuadro) ---
    rat = np.repeat(np.array(ratios, np.int64), CUADRO)
    p = np.concatenate([[0], np.cumsum(rat)[:-1]])
    idx = p >> 16
    frac = (p & 0xFFFF).astype(np.float64) / 65536.0

    def leer(i):
        if con_loop:
            out = np.empty(len(i), np.float64)
            m = i < N
            out[m] = A[i[m]]
            j = i[~m]
            out[~m] = Lp[(j - N) % len(Lp)]
            return out
        out = np.zeros(len(i), np.float64)
        m = i < N
        out[m] = A[i[m]]
        return out

    x0 = leer(idx)
    x1 = leer(idx + 1)
    x = x0 + (x1 - x0) * frac
    if not con_loop:
        x[idx >= N] = 0.0          # el AX para en la muestra final (inclusive)
    G = np.array(gan, np.float64)   # (nb, 3) ganancias finales de cada cuadro
    prev = np.vstack([G[:1], G[:-1]])
    # MIXUpdateSettings: current = anterior, delta = (nuevo - anterior) / 160 (entero de C)
    delta = np.trunc((G - prev) / CUADRO)
    n = np.arange(CUADRO, dtype=np.float64)
    env = prev[:, None, :] + delta[:, None, :] * n[None, :, None]    # (nb,160,3)
    env[0] = G[0]                  # cuadro del note on: MIXInitChannel sin rampa
    env = env.reshape(-1, 3)
    vv = env[:, 0] / 32768.0
    L = x * vv * env[:, 1] / 32768.0
    R = x * vv * env[:, 2] / 32768.0
    return v.ms * MS, L, R


# ---------------------------------------------------------------------------------------------
# Render completo
# ---------------------------------------------------------------------------------------------
def render(banco, sit_idx, pasadas=3, cola_ms=12000, log=print):
    sit = banco.sit[sit_idx]
    info, _ = analizar_secuencia(banco, sit['banco'], sit)
    data, ini = banco.secuencia(sit['banco'])
    sq = Secuenciador(data, ini, sit)
    if info['loop_ms']:
        l0, l1 = info['loop_ms']
        P = l1 - l0
        hasta = l0 + pasadas * P + cola_ms
    else:
        l0 = P = None
        hasta = info['fin_ms'] + 1
    sq.correr(hasta)
    # numero de pase (0 = intro, 1.. = vueltas del loop) de cada mensaje
    saltos = [m[0] for m in sq.marcas if m[1] == 'loop_jump']
    syn = Synth(banco, DLS_VOL_90)
    for ms, msg in sq.salida:
        pase = bisect.bisect_right(saltos, ms)
        syn.midi(ms, msg, pase)
    hists = [Historial(h) for h in syn.hist]
    fin_ms = hasta + (0 if l0 is not None else cola_ms)
    total = fin_ms * MS
    L = np.zeros(total, np.float64)
    R = np.zeros(total, np.float64)
    usados = {}
    max_poly = 0
    rangos = []
    for v in syn.voces:
        r = render_voz(v, banco, hists[v.ch], syn.master, fin_ms)
        if r is None:
            continue
        s0, l, rr = r
        n = min(len(l), total - s0)
        if n <= 0:
            continue
        L[s0:s0 + n] += l[:n]
        R[s0:s0 + n] += rr[:n]
        rangos.append((s0, s0 + n))
        u = usados.setdefault((v.ch, v.prog), dict(notas=0, teclas=set()))
        u['notas'] += 1
        u['teclas'].add(v.key)
    # polifonia maxima (voces AX simultaneas)
    ev = sorted([(a, 1) for a, _ in rangos] + [(b, -1) for _, b in rangos])
    c = 0
    for _, d in ev:
        c += d
        max_poly = max(max_poly, c)
    log('  mensajes al SYN: %d, voces: %d, polifonia AX max: %d, robos de voice work: %d, descartadas: %d'
        % (len(sq.salida), len(syn.voces), max_poly, sq.robos, sq.notas_descartadas))
    return dict(L=L, R=R, info=info, l0=l0, P=P, syn=syn, sq=sq, usados=usados, max_poly=max_poly)


# ---------------------------------------------------------------------------------------------
# WAV con chunk smpl
# ---------------------------------------------------------------------------------------------
def escribir_wav(ruta, st, loop_ini, loop_fin_incl):
    datos = st.astype('<i2').tobytes()
    fmt = struct.pack('<HHIIHH', 1, 2, FS, FS * 4, 4, 16)
    smpl = struct.pack('<9I', 0, 0, int(round(1e9 / FS)), 60, 0, 0, 0, 1, 0)
    smpl += struct.pack('<6I', 0, 0, loop_ini, loop_fin_incl, 0, 0)
    cuerpo = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt
    cuerpo += b'smpl' + struct.pack('<I', len(smpl)) + smpl
    cuerpo += b'data' + struct.pack('<I', len(datos)) + datos
    with open(ruta, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', len(cuerpo)) + cuerpo)


def leer_smpl(ruta):
    b = open(ruta, 'rb').read()
    p = 12
    r = {}
    while p < len(b):
        cid, n = b[p:p + 4], struct.unpack('<I', b[p + 4:p + 8])[0]
        if cid == b'smpl':
            r['loop'] = struct.unpack('<2I', b[p + 8 + 36 + 8:p + 8 + 36 + 16])
        if cid == b'data':
            r['frames'] = n // 4
        p += 8 + n + (n & 1)
    return r


# ---------------------------------------------------------------------------------------------
# PNG de control (PIL)
# ---------------------------------------------------------------------------------------------
def _colormap(t):
    """t en [0,1] -> RGB (negro-violeta-naranja-amarillo, tipo 'inferno' aproximado)"""
    pts = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21],
                    [250, 193, 39], [252, 255, 164]], np.float64)
    x = np.clip(t, 0, 1) * (len(pts) - 1)
    i = np.minimum(x.astype(int), len(pts) - 2)
    f = (x - i)[..., None]
    return (pts[i] * (1 - f) + pts[i + 1] * f).astype(np.uint8)


def png_espectrograma(ruta, mono, marcas, titulo):
    from PIL import Image, ImageDraw
    nfft, hop = 2048, 512
    n = (len(mono) - nfft) // hop
    win = np.hanning(nfft)
    frames = np.lib.stride_tricks.as_strided(mono, (n, nfft), (mono.strides[0] * hop, mono.strides[0]))
    S = np.abs(np.fft.rfft(frames * win, axis=1)).T          # (bins, n)
    db = 20 * np.log10(S + 1e-9)
    db -= db.max()
    # eje de frecuencia logaritmico 30 Hz .. 16 kHz, 360 filas
    H, W = 360, 1400
    fr = np.fft.rfftfreq(nfft, 1 / FS)
    ys = np.geomspace(30, 16000, H)[::-1]
    bi = np.clip(np.searchsorted(fr, ys), 0, len(fr) - 1)
    xs = np.linspace(0, n - 1, W).astype(int)
    img = db[bi][:, xs]
    rgb = _colormap((img + 90) / 90)
    im = Image.fromarray(rgb, 'RGB')
    canvas = Image.new('RGB', (W + 60, H + 50), (20, 20, 20))
    canvas.paste(im, (50, 30))
    d = ImageDraw.Draw(canvas)
    d.text((50, 8), titulo, fill=(230, 230, 230))
    dur = len(mono) / FS
    for s in range(0, int(dur) + 1, 10):
        x = 50 + int(s / dur * W)
        d.line([(x, H + 30), (x, H + 36)], fill=(200, 200, 200))
        d.text((x - 6, H + 37), '%d' % s, fill=(200, 200, 200))
    for f in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
        y = 30 + int(np.argmin(np.abs(ys - f)))
        d.text((2, y - 6), ('%dk' % (f // 1000)) if f >= 1000 else str(f), fill=(200, 200, 200))
    for t, etiqueta, col in marcas:
        x = 50 + int(t / dur * W)
        d.line([(x, 30), (x, H + 30)], fill=col)
        d.text((x + 3, 32), etiqueta, fill=col)
    canvas.save(ruta)


def png_onda(ruta, st, marcas, titulo):
    from PIL import Image, ImageDraw
    W, H = 1400, 300
    x = st.astype(np.float64) / 32768.0
    n = len(x)
    im = Image.new('RGB', (W + 60, H + 50), (20, 20, 20))
    d = ImageDraw.Draw(im)
    d.text((50, 8), titulo, fill=(230, 230, 230))
    for c, (col, y0) in enumerate((((120, 190, 255), 30 + H // 4), ((255, 170, 110), 30 + 3 * H // 4))):
        ch = x[:, c]
        edges = np.linspace(0, n, W + 1).astype(int)
        for i in range(W):
            seg = ch[edges[i]:edges[i + 1]]
            if len(seg) == 0:
                continue
            a, b = seg.min(), seg.max()
            d.line([(50 + i, y0 - int(b * H / 4)), (50 + i, y0 - int(a * H / 4))], fill=col)
    dur = n / FS
    for t, etiqueta, col in marcas:
        xx = 50 + int(t / dur * W)
        d.line([(xx, 30), (xx, H + 30)], fill=col)
        d.text((xx + 3, H + 32), etiqueta, fill=col)
    im.save(ruta)


def png_costura(ruta, st, a, b, titulo, radio=400):
    """Muestras alrededor del fin del loop (b = ultima muestra) seguidas por las del inicio (a):
    lo que suena al dar la vuelta."""
    from PIL import Image, ImageDraw
    seg = np.concatenate([st[b - radio + 1:b + 1], st[a:a + radio]]).astype(np.float64) / 32768.0
    W, H = 1200, 320
    im = Image.new('RGB', (W + 60, H + 50), (20, 20, 20))
    d = ImageDraw.Draw(im)
    d.text((50, 8), titulo, fill=(230, 230, 230))
    pk = max(np.abs(seg).max(), 1e-6)
    for c, col in enumerate(((120, 190, 255), (255, 170, 110))):
        y0 = 30 + H // 4 + c * H // 2
        pts = [(50 + int(i * W / len(seg)), y0 - int(seg[i, c] / pk * H / 4.4)) for i in range(len(seg))]
        d.line(pts, fill=col)
    xm = 50 + int(radio * W / len(seg))
    d.line([(xm, 30), (xm, H + 30)], fill=(255, 80, 80))
    d.text((xm + 4, H + 32), 'vuelta del loop', fill=(255, 80, 80))
    im.save(ruta)


# ---------------------------------------------------------------------------------------------
# Tabla de BGMs por cuarto (bgm/bgmtbl.dat, SndBgmTblSet)
# ---------------------------------------------------------------------------------------------
def tabla_cuartos():
    if not os.path.exists(BGMTBL):
        return None
    bt = open(BGMTBL, 'rb').read()
    ro, lo = struct.unpack('>II', bt[:8])
    res = []
    i, p = 0, lo
    while True:
        r, = struct.unpack('>H', bt[p:p + 2])
        if r == 0xFFFF:
            break
        o = ro + struct.unpack('>I', bt[ro + 4 * i:ro + 4 * i + 4])[0]
        n, = struct.unpack('>I', bt[o:o + 4])
        for j in range(n):
            e = struct.unpack('>13I', bt[o + 4 + 52 * j:o + 56 + 52 * j])
            for k in range(6):
                for slot in range(2):
                    b = (e[1 + k] >> (16 * slot)) & 0xFFFF
                    if b & 0x8000:
                        res.append(dict(cuarto='r%03x' % r, tabla=e[0], bgm_tbl_idx=k, slot=slot,
                                        valor=hex(b), entrada=b & 0xFF, sit=(b >> 8) & 3,
                                        auto=bool(b & 0x4000), vol1=bool(b & 0x2000)))
        p += 2
        i += 1
    return res


# ---------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--entrada', type=int, default=0, help='entrada de bio4midi.hed (0 = r100)')
    ap.add_argument('--sit', type=int, default=0, help='SIT / secuencia (bits 8-9 del valor de la tabla)')
    ap.add_argument('--nombre', default=None, help='nombre base de salida (por defecto r100_bgm / bgmNN_S)')
    ap.add_argument('--todas', action='store_true', help='renderizar todas las entradas de bio4midi.dat')
    a = ap.parse_args()
    os.makedirs(os.path.join(SALIDA, 'control'), exist_ok=True)
    dat = open(DAT, 'rb').read()
    entradas = leer_hed()
    print('bio4midi.dat: %d entradas' % len(entradas))
    # --- documentacion de todas las entradas ---
    cuartos = tabla_cuartos() or []
    tabla = []
    bancos = {}
    for n, (o, t) in enumerate(entradas):
        try:
            b = BancoBgm(dat, o, t)
        except Exception as ex:          # noqa
            tabla.append(dict(entrada=n, ofs=hex(o), tam=hex(t), error=str(ex)))
            continue
        bancos[n] = b
        seqs = []
        for si, s in enumerate(b.sit):
            try:
                inf, _ = analizar_secuencia(b, s['banco'], s)
                tp = inf['tempos'][0][2] if inf['tempos'] else None
                seqs.append(dict(sit=si, banco_seq=s['banco'], vol=s['vol'], notas=inf['notas'],
                                 canales=inf['canales'], tempo_us_negra=tp,
                                 bpm=round(60e6 / tp, 3) if tp else None,
                                 loop_ms=inf['loop_ms'], fin_ms=inf['fin_ms']))
            except Exception as ex:      # noqa
                seqs.append(dict(sit=si, error=str(ex)))
        usos = sorted({'%s tabla %d slot %d' % (c['cuarto'], c['tabla'], c['slot'])
                       for c in cuartos if c['entrada'] == n})
        tabla.append(dict(entrada=n, ofs=hex(o), tam=hex(t), instrumentos=b.n_inst, regiones=len(b.rgn),
                          muestras=len(b.smp), aram_bytes=len(b.aram), sit=len(b.sit), secuencias=seqs,
                          cuartos=usos[:60], n_usos=len(usos)))
    lista = list(bancos) if a.todas else [a.entrada]
    for n in lista:
        b = bancos[n]
        sits = range(len(b.sit)) if a.todas else [a.sit]
        for si in sits:
            nombre = a.nombre or ('r100_bgm' if (n == 0 and si == 0) else 'bgm%02d_%d' % (n, si))
            procesar(b, n, si, nombre, tabla, cuartos)


def procesar(b, n, si, nombre, tabla, cuartos):
    print('entrada %d, SIT %d -> %s' % (n, si, nombre))
    sit = b.sit[si]
    r = render(b, si)
    info, l0, P = r['info'], r['l0'], r['P']
    L, R = r['L'], r['R']
    avisos = []
    if l0 is not None:
        S0, Pn = l0 * MS, P * MS
        S1, S2, S3 = S0 + Pn, S0 + 2 * Pn, S0 + 3 * Pn
        pk_all = max(np.abs(L).max(), np.abs(R).max(), 1e-9)

        def dif(a0, a1, n_):
            d = max(np.abs(L[a0:a0 + n_] - L[a1:a1 + n_]).max(), np.abs(R[a0:a0 + n_] - R[a1:a1 + n_]).max())
            return 20 * math.log10(d / pk_all + 1e-12)
        d_estable = dif(S1, S2, Pn)       # vuelta 2 vs vuelta 3: estado estacionario
        d_intro = dif(S0, S1, Pn)         # vuelta 1 (despues de la intro) vs vuelta 2
        if d_estable > -90:
            avisos.append('La secuencia NO llega a un estado estacionario (vuelta 2 vs 3: %.1f dB): el robo de '
                          'voice works / notas colgadas cambia de una vuelta a otra (tambien en el juego). El loop '
                          'del WAV es una aproximacion: la vuelta es continua pero no identica a lo que seguiria.'
                          % d_estable)
        print('  diferencia vuelta2-vuelta3: %.1f dB, vuelta1-vuelta2: %.1f dB (rel. al pico)'
              % (d_estable, d_intro))
        # las vueltas 2 y 3 son identicas (estado estacionario); la vuelta 1 puede diferir al principio por
        # las colas (release) de notas de la intro. Si las diferencias se apagan pronto, el loop del WAV
        # empieza apenas despues (S0 + delta): intro + UNA vuelta (rotada delta), costura exacta.
        dd = np.maximum(np.abs(L[S0:S1] - L[S1:S2]), np.abs(R[S0:S1] - R[S1:S2]))
        malos = np.nonzero(dd > 1e-9 * pk_all)[0]
        delta = 0 if len(malos) == 0 else ((int(malos[-1]) + 1 + MS - 1) // MS) * MS
        if delta <= Pn // 2:
            ini, fin = S0 + delta, S1 + delta
            corte = fin
            esquema = ('intro + 1 vuelta; el loop del WAV empieza %.3f s despues del CC 0x66 porque hasta ahi '
                       'suenan las colas de la intro (release de notas previas) que en las vueltas siguientes '
                       'son colas del final del loop; desde ese punto la vuelta 1 es identica a la 2 y a la 3'
                       % (delta / FS)) if delta else 'intro + 1 vuelta (la vuelta 1 ya es igual a las siguientes)'
            if delta:
                avisos.append('Loop rotado %d muestras (%.3f s) respecto del CC 0x66 del juego: mismo contenido '
                              'musical, pero el punto de loop del WAV no coincide con la marca de la secuencia '
                              '(ver secuencia.cc66_marca_loop_ms).' % (delta, delta / FS))
        else:
            ini, fin = S1, S2
            corte = S2
            esquema = 'intro + vuelta 1 (con las colas de la intro) + vuelta 2 = loop estacionario'
            avisos.append('La vuelta 1 del loop difiere de las siguientes (%.1f dB rel. al pico) porque arrastra '
                          'notas / colas de la intro; por eso el loop del WAV es la vuelta 2 y el archivo trae '
                          'intro + 2 vueltas.' % d_intro)
        st = np.stack([L[:corte], R[:corte]], 1)
    else:
        st = np.stack([L, R], 1)
        ini = fin = None
        d_estable = d_intro = None
        esquema = 'sin loop (la secuencia termina con FF 2F)'
    # normalizar a -1 dBFS de pico
    pk = np.abs(st).max()
    gan = (10 ** (-1 / 20)) * 32767.0 / pk
    sti = np.clip(np.round(st * gan), -32768, 32767).astype(np.int16)
    recortes = int(np.sum(np.abs(st * gan) > 32767))
    wav = os.path.join(SALIDA, nombre + '.wav')
    lf = None
    if ini is not None:
        lf = fin - 1
        escribir_wav(wav, sti, ini, lf)
    else:
        escribir_wav(wav, sti, 0, len(sti) - 1)
    # --- verificaciones de la costura ---
    ver = {}
    if ini is not None:
        # continuidad: lo que sigue a la ultima muestra del loop en el WAV (vuelta) vs lo que seguiria en el
        # render completo (la vuelta siguiente)
        cont = np.stack([L[fin:fin + 64], R[fin:fin + 64]], 1) * gan
        wrap = sti[ini:ini + 64].astype(np.float64)
        ver['max_dif_vuelta_vs_render_continuo_64m'] = float(np.abs(cont - wrap).max())
        salto = np.abs(sti[ini].astype(np.float64) - sti[lf].astype(np.float64))
        paso_tip = np.median(np.abs(np.diff(sti[ini - 3200:ini + 3200].astype(np.float64), axis=0)), 0)
        paso_max = np.abs(np.diff(sti[ini - 3200:ini + 3200].astype(np.float64), axis=0)).max(0)
        ver['salto_en_la_vuelta_LR'] = salto.tolist()
        ver['salto_normal_fin_loop_LR'] = np.abs(sti[lf].astype(np.float64) - sti[lf - 1]).tolist()
        ver['paso_mediano_alrededor_LR'] = paso_tip.tolist()
        ver['paso_maximo_alrededor_LR'] = paso_max.tolist()
        ver['ultimas_4_muestras_loop'] = sti[lf - 3:lf + 1].tolist()
        ver['primeras_4_muestras_loop'] = sti[ini:ini + 4].tolist()
        ver['dif_estacionaria_dB'] = round(d_estable, 1)
        ver['dif_vuelta1_vs_vuelta2_dB'] = round(d_intro, 1)
    pico_db = 20 * math.log10(np.abs(sti).max() / 32768.0)
    rms = 20 * math.log10(np.sqrt(np.mean((sti.astype(np.float64) / 32768.0) ** 2)) + 1e-12)
    chk = leer_smpl(wav)
    ver.update(pico_dBFS=round(pico_db, 2), rms_dBFS=round(rms, 2), muestras_recortadas=recortes,
               smpl_leido=chk)
    # --- PNGs ---
    ctrl = os.path.join(SALIDA, 'control')
    marcas = []
    if ini is not None:
        marcas = [(ini / FS, 'loop inicio', (80, 255, 80)), (lf / FS, 'loop fin', (255, 80, 80))]
        if ini != l0 * MS:
            marcas.insert(0, (l0 * MS / FS, 'CC 0x66 (1a vez)', (150, 150, 255)))
    mono = sti.astype(np.float64).mean(1) / 32768.0
    png_espectrograma(os.path.join(ctrl, nombre + '_espectrograma.png'), mono, marcas,
                      '%s: bio4midi entrada %d SIT %d - espectrograma (log f, 90 dB)' % (nombre, n, si))
    png_onda(os.path.join(ctrl, nombre + '_onda.png'), sti, marcas, '%s: forma de onda L (azul) / R' % nombre)
    if ini is not None:
        png_costura(os.path.join(ctrl, nombre + '_costura.png'), sti, ini, lf,
                    '%s: 400 muestras antes del fin del loop + 400 desde el inicio' % nombre)
    # --- JSON ---
    tempos = [dict(ms=m[0], us_por_negra=m[2], bpm=round(60e6 / m[2], 3)) for m in info['tempos']]
    canales = []
    for (ch, prog), u in sorted(r['usados'].items()):
        ri = (b.perc if ch == 9 else b.inst)[prog]
        regs = sorted({ri[k] for k in u['teclas']})
        canales.append(dict(canal=ch, programa=prog, notas_renderizadas=u['notas'], teclas=sorted(u['teclas']),
                            regiones=regs))
    inst = []
    for prog in sorted({c['programa'] for c in canales}):
        for rg in sorted({x for x in b.inst[prog] if x != 0xFFFF}):
            rgn = b.rgn[rg]
            s = b.smp[rgn['sample']]
            art = b.art[rgn['art']]
            f = lambda x: None if x == ENV_INF else x
            inst.append(dict(programa=prog, region=rg, muestra=rgn['sample'], unity_note=rgn['unity'],
                             finetune=rgn['finetune'], attn=rgn['attn'], keygroup=rgn['keygroup'],
                             loop=(None if rgn['loop_start'] + rgn['loop_len'] == 0 else
                                   [rgn['loop_start'], rgn['loop_start'] + rgn['loop_len'] - 1]),
                             rate=s['rate'], largo_muestras=s['largo'], largo_s=round(s['largo'] / s['rate'], 3),
                             ataque_ms=syn_envelope_time(art['eg1Attack'], art['eg1Vel2Attack'], 127),
                             decay_ms_96dB=syn_envelope_time(art['eg1Decay'], art['eg1Key2Decay'], 60),
                             sustain_dB=round(art['eg1Sustain'] / 655360.0, 2),
                             release_dB_por_cuadro=round(art['eg1Release'] / 655360.0, 4),
                             release_s_hasta_72dB=(round(72 / (-art['eg1Release'] / 655360.0) * 0.005, 2)
                                                   if art['eg1Release'] < 0 else None),
                             pan_art=art['pan'], lfo=dict(freq=art['lfoFreq'], delay=art['lfoDelay'],
                                                          atten=art['lfoAtten'], pitch=art['lfoPitch'],
                                                          mod_atten=art['lfoMod2Atten'],
                                                          mod_pitch=art['lfoMod2Pitch']),
                             eg2_pitch=art['eg2Pitch']))
    usos = sorted({'%s tabla %d' % (c['cuarto'], c['tabla']) for c in cuartos if c['entrada'] == n and c['sit'] == si})
    js = dict(
        que='BGM secuenciada de RE4 GC: bio4midi.dat entrada %d, SIT %d (banco de secuencia %d), '
            'renderizada emulando el secuenciador del juego + SYN/MIX/AX del SDK' % (n, si, sit['banco']),
        wav=os.path.relpath(wav, AQUI), formato='PCM 16 bit estereo, %d Hz' % FS,
        esquema=esquema,
        duracion_muestras=len(sti), duracion_s=round(len(sti) / FS, 4),
        loop_inicio_muestra=ini, loop_fin_muestra_inclusive=lf,
        loop_inicio_s=None if ini is None else round(ini / FS, 5),
        loop_fin_s=None if lf is None else round((lf + 1) / FS, 5),
        loop_largo_muestras=None if ini is None else fin - ini,
        loop_largo_s=None if ini is None else round((fin - ini) / FS, 5),
        secuencia=dict(tempos=tempos, division=480,
                       cc66_marca_loop_ms=l0, cc67_salto_ms=None if l0 is None else l0 + P,
                       loop_largo_ms=P, fin_ms=info['fin_ms'],
                       notas_por_vuelta=info['notas'],
                       nota_tiempo='1 ms de secuenciador = 32 muestras; eventos cuantizados al ms como en '
                                   'seq_one_msec (delta -= 480 por ms, delta = ticks * (us_por_negra/1000))'),
        sit=sit, volumen_maestro_dB=DLS_VOL_90 / 10.0,
        ganancia_normalizacion_dB=round(20 * math.log10(gan / 32767.0 * 32768.0), 2),
        canales=canales, instrumentos=inst,
        polifonia_max=r['max_poly'],
        usado_en=usos,
        verificacion=ver,
        tabla_bio4midi=tabla,
        caveats=[
            'Emulacion bit a bit de la logica (no del DSP): secuenciador (snd_seq1/2/3), voice works con robo '
            '(snd_sub1), SYN (synctrl/synenv/synlfo/synpitch/synmix/synsample), MIX (tablas de pan/volumen, '
            'rampas de 160 muestras) y AX (DSP-ADPCM, SRC lineal 16.16, loop con loop_pred_scale/yn1/yn2).',
            'Tiempo: 1 ms de secuencia = 32 muestras exactas. El juego avanza 4.995 ms por cuadro de 160 '
            'muestras (el DSP real corre a ~32029 Hz), y cuantiza los eventos al cuadro de 5 ms; aca se '
            'cuantizan al ms y los cuadros de control (envolventes, rampas) son locales a cada voz. Diferencia '
            '< 5 ms por evento y 0.09 % de tempo / 1.6 cents: inaudible, y hace que el loop sea exacto.',
            'Sin reverb: los envios AUX A (CC 91) son de %s y la reverb del cuarto (efx HI) no se emula.'
            % ('-44 dB (CC91 = 10)' if n == 0 else 'lo que diga la secuencia'),
            'Sin el filtro/sobremuestreo final del DSP ni el ducking de eventos (SndEventInit baja a vol 1 en '
            '2 s, SndEventEnd la sube en 1 s): eso lo tiene que hacer el motor.',
            'Volumen maestro = Snd_dls_vol_tbl[90] (vol del SIT) con los volumenes de sistema al maximo; el WAV '
            'esta normalizado a -1 dBFS de pico, asi que el nivel absoluto relativo a otros sonidos NO es el '
            'del juego (ganancia_normalizacion_dB).',
            'SRC lineal simple (x0 + (x1-x0)*frac); el AX usa el mismo tipo (srcSelect = 1) pero con su '
            'historial interno: diferencias del orden de 1 LSB.',
        ] + avisos,
    )
    with open(os.path.join(SALIDA, nombre + '.json'), 'w') as f:
        json.dump(js, f, indent=1, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    print('  %s: %.2f s, loop %s..%s (%.3f s), pico %.2f dBFS, rms %.1f dBFS'
          % (wav, len(sti) / FS, ini, lf, 0 if ini is None else (fin - ini) / FS, pico_db, rms))
    if ver.get('max_dif_vuelta_vs_render_continuo_64m') is not None:
        print('  costura: max |vuelta - render continuo| = %.2f LSB, salto %s, paso max alrededor %s'
              % (ver['max_dif_vuelta_vs_render_continuo_64m'], ver['salto_en_la_vuelta_LR'],
                 ver['paso_maximo_alrededor_LR']))


if __name__ == '__main__':
    main()
