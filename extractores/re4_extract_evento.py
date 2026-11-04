#!/usr/bin/env python3
"""
Extractor de la cutscene r100s03 (Resident Evil 4, GameCube USA): Leon entra en la casa, intenta
hablar con el aldeano (ganado) y este lo ataca. Escribe una linea de tiempo lista para Whisk3D:

  out/evento_s03/evento.json     cortes, camara por frame, modelos/motions por corte, sonidos,
                                 subtitulos, luces, fades, funciones del evento
  out/evento_s03/audio/*.wav     streams del disco decodificados (DSP-ADPCM -> PCM 16 bit) y una
                                 copia *_n95.wav (22050 Hz mono) para el Nokia N95

Todo sale de la decompilacion (../re4, solo lectura). Referencias:

* Paquetes: include/event.h (EvtHeader, EvtPacket, EvpTp) y src/game/event.cpp:
  Event::Run / IsExePacket / ExePacket (cuando se ejecuta cada paquete: cut < NowCut o
  cut == NowCut && frame <= NowFrame), CalMaxCut / CalMaxFrame / CalMaxTotalFrame (largo de un
  corte = maxFrame del .fcv de camara + 1, o val.no de un CamDammy), ExePacket_* (semantica).
* Camara: src/game/cam_motion.cpp CameraMotion::CameraMotion / move (pistas partsNo 0 ojo,
  1 objetivo, 2 roll(.y, radianes), 3 fov(.y, radianes)), src/game/motion.cpp
  HermiteInterpolation + Fcc_get_data_* + src/game/math_sub.cpp hermite (tangentes SIN escalar
  por dt), src/game/cam_sys.cpp CameraSetOrientationRoll (vector arriba con el roll),
  src/game/camera.cpp CameraMove (C_MTXPerspective(fovy, 4/3)), src/game/cinesco.cpp (barras).
  Orden en un frame del juego (game.cpp): ScenarioMove -> EvtMgr.Run (paquetes) -> ObjMgr.move
  (motions) -> CameraMove (la camara evalua su frame y recien despues avanza,
  CameraSequenceCtrl) => el frame local f de un corte usa la camara en el frame f.
* Base de camara: ExePacket_Pos("cam0000") -> RotMatrix (Rz*Ry*Rx) + TransMatrix en MatCamOya;
  CamCtrl.MotionSet (cada paquete Cam) la vuelve a NULL (cam_ctrl.cpp).
* Visibilidad: Event::ControlTransFlag (un modelo del evento se ve mientras tiene una motion
  activa: MotClear la borra en cada paquete Cam), salvo los que tienen el bit 5 de CommonFlag
  (Obj18CmfOn(m, 5) = 0x04000000), que maneja la funcion del cuarto (st1/r100.cpp
  Evt_R100S03_Func: wep0200).
* Sonido: event.cpp ExePacket_Str / ExePacket_Se / EventMgr::EvtSndStrPlay, game/snd.cpp
  SndStrReq / SndRoomStrStart / SndBgmTblSet / SndEventInit, game/snd_sub3.cpp
  Snd_str_blk_init / Snd_get_rit_adrs / Snd_get_shd_adrs, include/snd_drv.h SND_RIT / SND_SHD,
  game/snd_str0.cpp Snd_str_init (bloques de lectura), game/snd_str2.cpp Snd_str_dvd_read_sub /
  Snd_str_aram_dma_sub (estereo = bloques de 0x8000: 0x4000 izq + 0x4000 der), snd_str3.cpp
  str_ax_voice_para_set (coeficientes / estado ADPCM del SHD). dvd.cpp FileTbl + snd.cpp
  StrFileTbl = {1, 0x5F}: bloque 0 = bgm/bio4bgm.sbb, bloque 1 = bgm/bio4evt.sbb; cabecera
  bgm/bio4str.hed.
* Mensajes: event.cpp ExePacket_Mes / Event::MesSet (NO se muestra si pSys->language == 1, y el
  disco USA es language 1: main.cpp "Fixed language 1"), sce_com.cpp SceMesSet (0xF2 -> archivo
  tipo 1 = el .mdt del evento, ExePacket_SetMdt), mes.cpp MessageData::getAddr (bloque del idioma
  MesData.lang, setLanguage(1) -> 1), getCharCode (glifo = palabra - 0x80), CommandExec (codigos
  de control < 0x80), MessageControl::MesSet (fuera del japones siempre MesFont[0] =
  Font/common_p.fnt).

Uso:
  python3 re4_extract_evento.py                 # r100s03
  python3 re4_extract_evento.py --sin-audio     # sin decodificar los streams
  python3 re4_extract_evento.py --evento r100s40 --out out/evento_s40
"""
import argparse
import array
import json
import math
import os
import struct
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
from motion import archive, fcv  # noqa: E402

DEFAULT_DISC = os.path.join(HERE, '..', 'Resident Evil 4 (USA) (Disc 1)', 'Resident Evil 4 (USA) (Disc 1).rvz')
DTK = os.path.join(HERE, 'tools', 'dtk')
CACHE = os.path.join(HERE, 'extracted')

MM = 0.001            # mm del juego -> metros
FPS = 30
FPS_NTSC = 29.97      # event.cpp EVT_FRAME_RATE (resincronizacion del stream: frame / 29.97 s)

PAQ = ['BeginEvt', 'SetPl', 'SetEm', 'SetOm', 'SetParts', 'SetList', 'Cam', 'CamPos', 'CamDammy', 'Pos',
       'PosPl', 'Mot', 'Shp', 'Esp', 'Lit', 'Str', 'Se', 'Mes', 'Func', 'ParentOn', 'ParentOff', 'EndPl',
       'EndEm', 'EndOm', 'EndParts', 'EndList', 'EndEvt', 'EndPac', 'SetEff', 'Fade', 'Fog', 'Focus', 'SetMdt']
(P_BEGIN, P_SETPL, P_SETEM, P_SETOM, P_SETPARTS, P_SETLIST, P_CAM, P_CAMPOS, P_CAMDAMMY, P_POS, P_POSPL,
 P_MOT, P_SHP, P_ESP, P_LIT, P_STR, P_SE, P_MES, P_FUNC, P_PARENTON, P_PARENTOFF, P_ENDPL, P_ENDEM, P_ENDOM,
 P_ENDPARTS, P_ENDLIST, P_ENDEVT, P_ENDPAC, P_SETEFF, P_FADE, P_FOG, P_FOCUS, P_SETMDT) = range(33)

# dvd.cpp FileTbl[StrFileTbl[blk]] (snd.cpp StrFileTbl = {1, 0x5F})
STR_ARCHIVO = {0: 'bgm/bio4bgm.sbb', 1: 'bgm/bio4evt.sbb'}

# Font/common_p.fnt (la fuente de los mensajes fuera del japones): 1024x192 CI4, celdas 32x32, 32 por
# fila => 192 glifos. Tabla leida del propio atlas (glifo = palabra del mensaje - 0x80, mes.cpp getCharCode).
GLIFOS_P = (
    ' ▶▼0123456789:%&+-/=,.・…()!?“”~★'
    '—<>[]①②ABCDEFGHIJKLMNOPQRSTUVWXY'
    'Zabcdefghijklmnopqrstuvwxyzâêîôû'
    'ÂÊÎÔÛàèìòùÀÈÌÒÙáéíóúýÁÉÍÓÚÝäëïöü'
    'ÿÄËÏÖÜŸãõÃÕñÑåÅçÇøØþÞšŠßĐƒµðæœÆŒ'
    '°¡¿’™;#@→←↑↓'
)
GLIFO_PTAS = 172   # la celda 172 es el simbolo "PTAS"


# ------------------------------------------------------------------------------------------------
# disco
# ------------------------------------------------------------------------------------------------
def dtk_cp(disc, path, dest_dir):
    if not os.path.isfile(DTK):
        os.makedirs(os.path.dirname(DTK), exist_ok=True)
        subprocess.check_call([sys.executable, os.path.join(RE4, 'tools', 'download_tool.py'), 'dtk', DTK, '--tag', 'v1.8.3'])
    os.makedirs(dest_dir, exist_ok=True)
    subprocess.run([DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/{path}', dest_dir + '/'],
                   check=True, stdout=subprocess.DEVNULL)
    return os.path.join(dest_dir, os.path.basename(path))


def archivo_disco(disc, path):
    """files/<path> del disco, cacheado en extracted/<path>."""
    local = os.path.join(CACHE, path)
    if not os.path.isfile(local):
        print(f'  disco: extrayendo {path}')
        dtk_cp(disc, path, os.path.dirname(local))
    return open(local, 'rb').read()


class Disco:
    """Lee archivos del disco con cache; los .sbb grandes se cortan en pedazos."""

    def __init__(self, disc):
        self.disc = disc
        self._tmp = []

    def archivo(self, path):
        return archivo_disco(self.disc, path)

    def rango(self, path, ofs, size):
        local = os.path.join(CACHE, f'{path}@{ofs:x}_{size:x}.bin')
        if os.path.isfile(local):
            return open(local, 'rb').read()
        full = os.path.join(CACHE, path)
        if not os.path.isfile(full):
            full = os.path.join(CACHE, 'tmp', os.path.basename(path))
            if not os.path.isfile(full):
                print(f'  disco: extrayendo {path} (temporal)')
                dtk_cp(self.disc, path, os.path.dirname(full))
                self._tmp.append(full)
        with open(full, 'rb') as f:
            f.seek(ofs)
            d = f.read(size)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        open(local, 'wb').write(d)
        return d

    def limpiar(self):
        for p in self._tmp:
            try:
                os.remove(p)
            except OSError:
                pass
        self._tmp = []


# ------------------------------------------------------------------------------------------------
# paquetes (include/event.h EvtPacket)
# ------------------------------------------------------------------------------------------------
def cstr(b):
    return b.split(b'\0')[0].decode('latin1')


def leer_paquetes(evd):
    """EvtHeader: pacOfs @0x40, pacSize @0x44. EvtPacket: {int id; u32 flag; s16 cut, frame, size;
    pad} + parametros. Se recorre como Event::CalNextPacket (p += size) hasta EndPac."""
    if evd[:5] != b'event':
        raise SystemExit('no es un archivo de evento ("event")')
    room, no = cstr(evd[0x20:0x28]), cstr(evd[0x28:0x34])
    snd_flag, = struct.unpack('>i', evd[0x34:0x38])
    pac_ofs, pac_size = struct.unpack('>II', evd[0x40:0x48])
    out = []
    p = pac_ofs
    while p < pac_ofs + pac_size:
        pid, flag, cut, frame, size = struct.unpack('>iIhhh', evd[p:p + 14])
        body = evd[p + 0x10:p + size]
        pk = dict(ofs=p, id=pid, tipo=PAQ[pid] if 0 <= pid < len(PAQ) else str(pid), flag=flag, cut=cut, frame=frame)
        if pid in (P_SETPL, P_SETEM, P_SETOM, P_MOT, P_SHP):          # mod {name[0xC], bin[0x30], tpl[0x30]}
            pk.update(nombre=cstr(body[:0xC]), bin=cstr(body[0xC:0x3C]), tpl=cstr(body[0x3C:0x6C]))
        elif pid in (P_CAM, P_LIT, P_SETEFF, P_SETMDT, P_FOG, P_FOCUS):
            pk.update(archivo=cstr(body[:0x40]))                        # pac->mod.name usado como nombre largo
        elif pid == P_SETPARTS:                                         # parts {name, oya, bin[0x30], tpl[0x30]}
            pk.update(nombre=cstr(body[:0xC]), padre=cstr(body[0xC:0x18]), bin=cstr(body[0x18:0x48]),
                      tpl=cstr(body[0x48:0x78]))
        elif pid in (P_POS, P_POSPL):                                   # pos {name, oya, s32 pos[3], rot[3], partsNo}
            pos = struct.unpack('>3i', body[0x18:0x24])
            rot = struct.unpack('>3i', body[0x24:0x30])
            parts, = struct.unpack('>i', body[0x30:0x34]) if len(body) >= 0x34 else (0,)
            pk.update(nombre=cstr(body[:0xC]), padre=cstr(body[0xC:0x18]), pos=list(pos), rot=list(rot), parte=parts)
        elif pid == P_ESP:                                              # esp {name, s32 type, pad[3], u8 parts}
            pk.update(nombre=cstr(body[:0xC]), esp_tipo=struct.unpack('>i', body[0xC:0x10])[0], parte=body[0x13])
        elif pid in (P_STR, P_SE, P_MES, P_FUNC, P_FADE, P_CAMDAMMY):   # val {s32 no, arg, time}
            pk.update(no=struct.unpack('>i', body[0:4])[0], arg=struct.unpack('>i', body[4:8])[0],
                      time=struct.unpack('>i', body[8:12])[0])
        pk['raw'] = body.hex()
        out.append(pk)
        if pid == P_ENDPAC or size <= 0:
            break
        p += size
    return dict(room=room, no=no, snd_flag=snd_flag), out


# ------------------------------------------------------------------------------------------------
# HermiteInterpolation (motion.cpp) + hermite (math_sub.cpp)
# ------------------------------------------------------------------------------------------------
def hermite(x, v, t):
    """math_sub.cpp hermite: tangentes tal cual (sin multiplicar por dt)."""
    t2 = t * t
    t3 = t * t2
    h01 = -(t3 + t3) + 3.0 * t2
    h11 = t3 - t2
    h10 = h11 - t2 + t
    h00 = -h01 + 1.0
    return x[0] * h00 + x[1] * h01 + v[0] * h10 + v[1] * h11


def _fcc(fcc_type, key):
    """Fcc_get_data_XYZ: (valor, tangente de entrada, tangente de salida) como floats del juego
    (s16 y s8 son valor / 10000). El tipo 15 (f32 sin tangentes) deja las tangentes sin tocar."""
    vf, tf = fcv.FCC_FMT[fcc_type]
    val = fcv.to_float(vf, key[0])
    if tf is None:
        return val, 0.0, 0.0
    return val, fcv.to_float(tf, key[1]), fcv.to_float(tf, key[2])


def eval_eje(axis, fcc_type, frame, max_frame, avisos=None):
    """Un eje de HermiteInterpolation con flags 2 (camara: sin loop, se clampa en maxFrame).
    El juego: frame >= maxFrame -> valor de la ultima llave; frame == llave -> su valor;
    llave[i] < frame < llave[i+1] -> hermite({v_i, v_i+1}, {out_i, in_i+1}, (frame-f0)/(f1-f0))."""
    frames = axis.frames
    n = len(frames)
    if n == 0:
        return 0.0
    keys = [_fcc(fcc_type, k) for k in axis.keys]
    if max_frame <= frame:
        return keys[n - 1][0]
    for i in range(n):
        f0 = frames[i]
        if f0 == frame:
            return keys[i][0]
        if f0 < frame:
            nx = i + 1 if i + 1 < n else 0
            f1 = frames[nx]
            if frame < f1:
                v0, _, out0 = keys[i]
                v1, in1, _ = keys[nx]
                return hermite((v0, v1), (out0, in1), (frame - f0) / (f1 - f0))
    # fuera del rango de llaves: el juego usaria val/tan sin inicializar; se sostiene la llave mas cercana
    if avisos is not None:
        avisos.add(f'frame {frame} fuera de las llaves {frames[0]}..{frames[-1]}: se sostiene la llave')
    return keys[0][0] if frame < frames[0] else keys[n - 1][0]


def eval_joint(joint, frame, max_frame, avisos=None):
    return [eval_eje(joint.axes[a], joint.fcc_type, frame, max_frame, avisos) for a in range(3)]


# ------------------------------------------------------------------------------------------------
# matrices (PSMTX: filas 3x4, v' = M v)
# ------------------------------------------------------------------------------------------------
def rot_matrix(rx, ry, rz):
    """math_sub.cpp RotMatrix: m = Rz * Ry * Rx (radianes)."""
    sx, cx, sy, cy, sz, cz = math.sin(rx), math.cos(rx), math.sin(ry), math.cos(ry), math.sin(rz), math.cos(rz)
    Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(mul(Rz, Ry), Rx)


def mtx_vec(m, t, v):
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] + t[i] for i in range(3)]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    m = math.sqrt(sum(x * x for x in a))
    return [x / m for x in a] if m else list(a)


def rot_axis(axis, ang, v):
    """PSMTXRotAxisRad + PSMTXMultVec (Rodrigues, eje normalizado)."""
    k = norm(axis)
    c, s = math.cos(ang), math.sin(ang)
    kv = cross(k, v)
    kd = sum(k[i] * v[i] for i in range(3))
    return [v[i] * c + kv[i] * s + k[i] * kd * (1 - c) for i in range(3)]


def camara_arriba(pos, at, roll):
    """cam_sys.cpp CameraSetOrientationRoll: dir = pos - at; right = up(0,1,0) x dir;
    up = dir x right; ambos rotados roll radianes sobre dir."""
    d = sub(pos, at)
    if d[0] != 0.0 or d[2] != 0.0:
        right = cross([0.0, 1.0, 0.0], d)
    else:
        right = [1.0, 0.0, 0.0]
    up = cross(d, right)
    up = rot_axis(d, roll, up)
    return norm(up)


# ------------------------------------------------------------------------------------------------
# DSP-ADPCM (streams)
# ------------------------------------------------------------------------------------------------
def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def dsp_decode(buf, nsamples, coef, yn1=0, yn2=0):
    """Decodificador DSP-ADPCM del AX (8 bytes = 1 cabecera ps + 14 muestras de 4 bits)."""
    out = array.array('h', bytes(2 * nsamples))
    h1, h2 = yn1, yn2
    # snd_str3.cpp str_ax_voice_para_set: adpcm.a[i][0] = coef[i], a[i][1] = coef[i + 8] (NO son pares seguidos)
    c = [(coef[i], coef[i + 8]) for i in range(8)]
    k = 0
    pos = 0
    nb = len(buf)
    while k < nsamples and pos + 8 <= nb:
        ps = buf[pos]
        c1, c2 = c[(ps >> 4) & 7]
        sc = 1 << (ps & 0xF)
        for j in range(7):
            b = buf[pos + 1 + j]
            for n in (b >> 4, b & 0xF):
                if n >= 8:
                    n -= 16
                v = (((n * sc) << 11) + 1024 + c1 * h1 + c2 * h2) >> 11
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                out[k] = v
                h2 = h1
                h1 = v
                k += 1
                if k >= nsamples:
                    return out
        pos += 8
    return out


def nibble_a_muestra(nbl):
    """Direccion en nibbles del AX -> indice de muestra (cada 16 nibbles: 2 de cabecera + 14)."""
    return (nbl // 16) * 14 + max(0, (nbl % 16) - 2)


def escribir_wav(path, canales, rate, loop=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = len(canales[0])
    if len(canales) == 1:
        a = canales[0]
    else:
        a = array.array('h', bytes(2 * n * len(canales)))
        for c, ch in enumerate(canales):
            a[c::len(canales)] = ch
    if sys.byteorder == 'big':
        a = array.array('h', a)
        a.byteswap()
    with wave.open(path, 'wb') as w:
        w.setnchannels(len(canales))
        w.setsampwidth(2)
        w.setframerate(int(round(rate)))
        w.writeframes(a.tobytes())
    if loop:  # chunk 'smpl' con el loop (muestras)
        ls, le = loop
        smpl = struct.pack('<9I', 0, 0, int(1e9 / rate), 60, 0, 0, 0, 1, 0) + struct.pack('<6I', 0, 0, ls, le, 0, 0)
        with open(path, 'r+b') as f:
            f.seek(0, 2)
            f.write(b'smpl' + struct.pack('<I', len(smpl)) + smpl)
            size = f.tell()
            f.seek(4)
            f.write(struct.pack('<I', size - 8))


def escribir_n95(path, canales, rate, dst=22050):
    """Copia chica para el N95: mono, 16 bit, 22050 Hz (mezcla L+R, remuestreo lineal)."""
    try:
        import numpy as np
        x = np.zeros(len(canales[0]), np.float64)
        for ch in canales:
            x += np.frombuffer(ch.tobytes(), np.int16).astype(np.float64)
        x /= len(canales)
        n = int(len(x) * dst / rate)
        t = np.arange(n) * (rate / dst)
        y = np.interp(t, np.arange(len(x)), x)
        y = np.clip(np.round(y), -32768, 32767).astype(np.int16)
        mono = array.array('h', y.tobytes())
    except ImportError:
        src = [sum(ch[i] for ch in canales) / len(canales) for i in range(len(canales[0]))]
        n = int(len(src) * dst / rate)
        step = rate / dst
        mono = array.array('h')
        for i in range(n):
            p = i * step
            j = int(p)
            f = p - j
            a = src[j] if j < len(src) else 0
            b = src[j + 1] if j + 1 < len(src) else 0
            mono.append(max(-32768, min(32767, int(round(a + (b - a) * f)))))
    escribir_wav(path, [mono], dst)


class Streams:
    """bgm/bio4str.hed: u32 ofs[2] (bloque 0, 1) -> SndStrFile {num, ofs tabla SHD, ofs RIT}
    (snd_sub3.cpp Snd_str_blk_init). RIT = 0x10 bytes (snd_drv.h SND_RIT); SHD (SND_SHD):
    flag (1 estereo, 4 loop), samples, nibbles (por canal), rate, start_nbl, lptop_nbl, lpend_nbl,
    offset (posicion en el .sbb: Snd_str_init pasa shd->offset como `aram` y
    Snd_str_dvd_read_sub lee de str->aram + read_ofs), coef[16], coefR[16], gain[2], ps[2], yn1[2], yn2[2]."""

    def __init__(self, disco):
        self.disco = disco
        self.hed = disco.archivo('bgm/bio4str.hed')
        self.blk = [struct.unpack('>I', self.hed[4 * i:4 * i + 4])[0] for i in range(2)]

    def num(self, blk):
        return struct.unpack('>I', self.hed[self.blk[blk]:self.blk[blk] + 4])[0]

    def rit(self, blk, no):
        base = self.blk[blk]
        _, _, rit_ofs = struct.unpack('>III', self.hed[base:base + 12])
        r = self.hed[base + rit_ofs + 0x10 * no:base + rit_ofs + 0x10 * no + 0x10]
        f = struct.unpack('>hbbbb2xbbbxHbb', r)
        return dict(zip(('str_no', 'ch', 'poly', 'vol', 'pan', 'aux_a', 'aux_b', 'pl_id', 'flag', 'span', 'svol'), f))

    def shd(self, blk, no):
        base = self.blk[blk]
        _, shd_ofs, _ = struct.unpack('>III', self.hed[base:base + 12])
        r = self.rit(blk, no)
        tbl = base + shd_ofs
        o = tbl + struct.unpack('>I', self.hed[tbl + 4 * r['str_no']:tbl + 4 * r['str_no'] + 4])[0]
        v = struct.unpack('>8I', self.hed[o:o + 0x20])
        h = dict(zip(('flag', 'samples', 'nibbles', 'rate', 'start_nbl', 'lptop_nbl', 'lpend_nbl', 'offset'), v))
        w = struct.unpack('>46H', self.hed[o + 0x20:o + 0x7C])
        h['coef'] = [s16(x) for x in w[0:16]]
        h['coefR'] = [s16(x) for x in w[16:32]]
        h['gain'], h['ps'] = list(w[32:34]), list(w[34:36])
        h['yn1'], h['yn2'] = [s16(x) for x in w[36:38]], [s16(x) for x in w[38:40]]
        return h

    def decodificar(self, blk, no):
        """-> (canales [array('h')], rate, info). Estereo: bloques de 0x8000 del archivo, la primera
        mitad (0x4000) izquierda y la segunda derecha (Snd_str_aram_dma_sub); mono: contiguo."""
        h = self.shd(blk, no)
        est = bool(h['flag'] & 1) and not (h['flag'] & 2)
        por_canal = (h['nibbles'] + 1) // 2
        if est:
            read_end = h['nibbles'] // 2 * 2
            size = -(-read_end // 0x8000) * 0x8000
        else:
            size = -(-por_canal // 0x8000) * 0x8000
        d = self.disco.rango(STR_ARCHIVO[blk], h['offset'], size)
        if est:
            L = bytearray()
            R = bytearray()
            for p in range(0, len(d), 0x8000):
                L += d[p:p + 0x4000]
                R += d[p + 0x4000:p + 0x8000]
            canales = [dsp_decode(bytes(L), h['samples'], h['coef'], h['yn1'][0], h['yn2'][0]),
                       dsp_decode(bytes(R), h['samples'], h['coefR'], h['yn1'][1], h['yn2'][1])]
        else:
            canales = [dsp_decode(d, h['samples'], h['coef'], h['yn1'][0], h['yn2'][0])]
        return canales, h['rate'], h


# ------------------------------------------------------------------------------------------------
# MDT (mensajes)
# ------------------------------------------------------------------------------------------------
CTRL = {0x00: 'inicio', 0x01: 'fin', 0x02: 'llamar', 0x03: 'nueva_linea', 0x04: 'nueva_pagina', 0x05: 'velocidad',
        0x06: 'color', 0x07: 'opcion', 0x08: 'esperar_boton', 0x09: 'esperar', 0x0A: 'c0a', 0x0B: 'c0b',
        0x0C: 'c0c', 0x0D: 'c0d', 0x0E: 'c0e', 0x0F: 'c0f', 0x10: 'c10', 0x11: 'c11', 0x12: 'c12'}
CTRL_ARGS = [0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1]   # mes.cpp Message::CommandArg


def mdt_mensaje(mdt, lang, no):
    """MessageData::getAddr: tbl[lang + 1] -> bloque {x0, count, ofs[count]} (ofs desde el bloque)."""
    n_lang, = struct.unpack('>I', mdt[:4])
    if lang + 1 > n_lang:
        return None
    blk, = struct.unpack('>I', mdt[4 * (lang + 1):4 * (lang + 2)])
    count, = struct.unpack('>I', mdt[blk + 4:blk + 8])
    if no < 0 or no > count - 1:     # Mes con no -1: no hay mensaje (no se lee la tabla)
        return None
    o = blk + struct.unpack('>I', mdt[blk + 8 + 4 * no:blk + 12 + 4 * no])[0]
    words = []
    while o + 2 <= len(mdt):
        w, = struct.unpack('>H', mdt[o:o + 2])
        o += 2
        words.append(w)
        if w == 0x01:          # code01 = fin del mensaje
            break
        if w < 0x80 and w < len(CTRL_ARGS):
            for _ in range(CTRL_ARGS[w]):
                words.append(struct.unpack('>H', mdt[o:o + 2])[0])
                o += 2
    return words


def texto_latino(words):
    """Palabras -> texto con la fuente common_p (glifo = w - 0x80); codigos de control como {..}."""
    s = []
    i = 0
    while i < len(words):
        w = words[i]
        if w < 0x80:
            nargs = CTRL_ARGS[w] if w < len(CTRL_ARGS) else 0
            if w == 0x03:
                s.append('\n')
            elif w not in (0x00, 0x01):
                s.append('{%s%s}' % (CTRL.get(w, hex(w)), ''.join(f' {a}' for a in words[i + 1:i + 1 + nargs])))
            i += 1 + nargs
            continue
        g = w - 0x80
        if g < len(GLIFOS_P):
            s.append(GLIFOS_P[g])
        elif g == GLIFO_PTAS:
            s.append('Ptas')
        else:
            s.append('{g%d}' % g)
        i += 1
    return ''.join(s)


# ------------------------------------------------------------------------------------------------
# EFF del evento: lista de est (para EventCutEstSet)
# ------------------------------------------------------------------------------------------------
def eff_est_ids(eff):
    """EffData @0x08 ofsEstList: {u32 num; {u16 no; u16 type; u32 flg}[num]} (ver tools/re4_eff.py)."""
    if len(eff) < 0x30:
        return []
    ofs, = struct.unpack('>I', eff[8:12])
    if ofs == 0 or ofs + 4 > len(eff):
        return []
    n, = struct.unpack('>I', eff[ofs:ofs + 4])
    return [struct.unpack('>HHI', eff[ofs + 4 + 8 * i:ofs + 12 + 8 * i]) for i in range(n)]


# ------------------------------------------------------------------------------------------------
# lo que hace el codigo del cuarto con cada evento (st1/r100.cpp)
# ------------------------------------------------------------------------------------------------
FUNCION_EVENTO = {
    'r100s03': ('st1/r100.cpp Evt_R100S03_Func: en el frame 0 de cada corte pone wep0200 (la pistola, colgada '
                'de la mano de pl0000) visible en los cortes 0-4 y 13-20 y oculta en 5-12'),
    'r100s40': ('st1/r100.cpp Evt_R100S40_Func: en cada frame prende STA_CAMERA_IN_ROOM; en el corte 0 frame 0 llama '
                'EventCarInit (st1/r120.cpp): pl0000 be_flag |= 0x100000, ot_type 1; pl0700 / pl0700a be_flag |= '
                '0x10 | 0x04000000 | 0x01000000; obm1a00 (la camioneta) be_flag |= 0x10, ot_type 4 y ESCALA 0 en sus '
                'partes 0x0F y 0x12..0x17 (no se dibujan en todo el evento); obm3000a..f (piezas colgadas de obm1a00) '
                'ot_type 1, z_mode 1, LightInfo.EnableMask 2. FuncType 3 (evento salteado) prende '
                'SCF_R120_EVENT_CANCEL.'),
}
DESPUES_DEL_EVENTO = {
    'r100s03': dict(
        nota='st1/r100.cpp r100_Sce_look: al terminar el evento el ganado va a (-79.116, 0.86, -38.89) rot Y -1.39 rad '
             'y Leon a (-82.91, 0.86, -38.48) rot Y 1.75 rad'),
    'r100s40': dict(
        nota='st1/r100.cpp r100_StartEvent: al terminar el evento (freeEvent 9) Leon queda en (-99.685, -0.484, -1.343) '
             'rot Y 2.246 rad (pPL->setPos / setAng), OpeSetOpenTerm(0) (el titulo del capitulo), SeAtSetOnOff(2, 1) '
             '(vuelven los sonidos de ambiente del area SE 2), SndBgmTblSet(0x100, 1) + SndRoomBgmStart(0, 0) / (1, 0): '
             'arranca la BGM SECUENCIADA del cuarto (slot 0 = 0xC000: secuencia 0 del archivo MIDI 0; el slot 1 esta '
             'vacio). El stream del cuarto (bio4bgm #2) NO arranca aca (no tiene el bit 0x4000 de auto-arranque): lo '
             'arranca el evento r100s03 en su corte 14.',
        leon_pos_m=[-99.685, -0.484, -1.343], leon_rot_y_rad=2.246),
}


# ------------------------------------------------------------------------------------------------
# principal
# ------------------------------------------------------------------------------------------------
def r3(v, n=5):
    return [round(x, n) for x in v]


def main():
    ap = argparse.ArgumentParser(description='Extrae la linea de tiempo de una cutscene de RE4 (GC).')
    ap.add_argument('--evento', default='r100s03', help='nombre del evento (Evd/<nombre>.evd)')
    ap.add_argument('--disc', default=DEFAULT_DISC, help='imagen del disco (.rvz/.iso/.gcm)')
    ap.add_argument('--out', default=None, help='carpeta de salida (por defecto out/evento_<no>)')
    ap.add_argument('--sin-audio', action='store_true', help='no decodificar los streams')
    ap.add_argument('--forzar-audio', action='store_true', help='volver a decodificar aunque existan los WAV')
    args = ap.parse_args()

    disco = Disco(args.disc)
    evd_local = os.path.join(CACHE, 'Evd', args.evento + '.evd')
    if os.path.isfile(evd_local):
        evd = open(evd_local, 'rb').read()
    else:
        evd = disco.archivo(f'Evd/{args.evento}.evd')
    hdr, paqs = leer_paquetes(evd)
    bins = dict(archive.parse_event(evd))
    out_dir = args.out or os.path.join(HERE, 'out', f'evento_{hdr["no"]}')
    audio_dir = os.path.join(out_dir, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    print(f'evento {hdr["room"]}{hdr["no"]}: {len(paqs)} paquetes, {len(bins)} archivos internos')

    def bin_(name):
        if name not in bins:
            raise KeyError(name)
        return bins[name]

    # ---- cortes (CalMaxCut / CalMaxFrame): Cam y CamDammy en orden de paquete ----
    cortes = []
    for pk in paqs:
        if pk['id'] == P_CAM:
            m = fcv.parse(bin_(pk['archivo']))
            cortes.append(dict(indice=len(cortes), frames=m.max_frame + 1, camara=pk['archivo'], dammy=False,
                               _mot=m, cut_paquete=pk['cut']))
        elif pk['id'] == P_CAMDAMMY:
            cortes.append(dict(indice=len(cortes), frames=pk['no'], camara=None, dammy=True, _mot=None,
                               cut_paquete=pk['cut']))
    g = 0
    for c in cortes:
        c['inicio'] = g
        g += c['frames']
    total = g

    def global_frame(cut, frame):
        if cut < 0:
            return 0                  # pre-roll (cut -1 / -2): se ejecuta todo antes del frame 0
        if cut >= len(cortes):
            return total
        return cortes[cut]['inicio'] + frame

    # ---- camara ----
    avisos = set()
    base_por_corte = {}
    for pk in paqs:
        if pk['id'] == P_POS and pk['nombre'] == 'cam0000':
            # ExePacket_Pos: RotMatrix + TransMatrix; vale hasta el siguiente paquete Cam (MotionSet -> NULL)
            rot = [x * 3.1415927 / 180.0 for x in pk['rot']]
            base_por_corte[pk['cut']] = dict(desde_frame=pk['frame'], rot_grados=pk['rot'], pos_mm=pk['pos'],
                                             _m=rot_matrix(*rot), _t=[float(x) for x in pk['pos']],
                                             relativo_oya=bool(pk['flag'] & 0x80000000))
    camara = []
    for c in cortes:
        cam = dict(corte=c['indice'], inicio=c['inicio'], frames=c['frames'], archivo=c['camara'],
                   ojo=[], objetivo=[], arriba=[], roll_grados=[], fov_grados=[])
        m = c['_mot']
        if m is None:
            cam['nota'] = 'CamDammy: el corte no mueve la camara (queda la del corte anterior)'
            camara.append(cam)
            continue
        maxf = float(m.max_frame + 1)                 # CameraMotion: maxFrame = (maxFrame & 0x3FFF) + 1
        pistas = {j.parts_no: j for j in m.joints}
        base = base_por_corte.get(c['indice'])
        for f in range(c['frames']):
            pos = eval_joint(pistas[0], f, maxf, avisos) if 0 in pistas else [0.0, 0.0, 0.0]
            at = eval_joint(pistas[1], f, maxf, avisos) if 1 in pistas else [0.0, 0.0, 0.0]
            roll = eval_joint(pistas[2], f, maxf, avisos)[1] if 2 in pistas else 0.0
            fov = eval_joint(pistas[3], f, maxf, avisos)[1] if 3 in pistas else 0.0
            up = camara_arriba(pos, at, roll)
            if base and f >= base['desde_frame']:
                pos = mtx_vec(base['_m'], base['_t'], pos)
                at = mtx_vec(base['_m'], base['_t'], at)
                up = norm(mtx_vec(base['_m'], [0, 0, 0], up))
            cam['ojo'].append(r3([x * MM for x in pos]))
            cam['objetivo'].append(r3([x * MM for x in at]))
            cam['arriba'].append(r3(up))
            cam['roll_grados'].append(round(math.degrees(roll), 4))
            cam['fov_grados'].append(round(fov * 180.0 / math.pi, 4))   # move(): fovy = fov.y * 180 / PI
        if base:
            cam['base_cam0000'] = {k: v for k, v in base.items() if not k.startswith('_')}
        camara.append(cam)

    # ---- modelos ----
    modelos = {}
    orden = []

    def modelo(nombre):
        if nombre not in modelos:
            modelos[nombre] = dict(nombre=nombre, tipo=None, bin=None, tpl=None, partes=[], posiciones=[],
                                   cortes=[])
            orden.append(nombre)
        return modelos[nombre]

    partes_de = {}
    for pk in paqs:
        if pk['id'] == P_SETOM:
            md = modelo(pk['nombre'])
            md.update(tipo='SetOm (obj18 del evento)', bin=pk['bin'], tpl=pk['tpl'], cmf_inicial=pk['flag'])
        elif pk['id'] == P_SETPL:
            md = modelo(pk['nombre'])
            md.update(tipo='SetPl (el jugador real)')
        elif pk['id'] == P_SETPARTS:
            md = modelo(pk['padre'])
            md['partes'].append(dict(nombre=pk['nombre'], bin=pk['bin'], tpl=pk['tpl']))
            partes_de[pk['nombre']] = pk['padre']
        elif pk['id'] in (P_POS, P_POSPL) and pk['nombre'] != 'cam0000':
            md = modelo(pk['nombre'])
            md['posiciones'].append(dict(
                paquete=pk['tipo'], corte=pk['cut'], frame=pk['frame'], frame_global=global_frame(pk['cut'], pk['frame']),
                pos_m=r3([x * MM for x in pk['pos']]), rot_grados=pk['rot'], padre=pk['padre'] or None,
                relativo_al_padre=bool(pk['flag'] & 0x80000000),
                emparentar_a_parte=pk['parte'] if pk['flag'] & 0x40000000 else None,
                efectivo=(pk['id'] == P_POS),
                nota=('flag 0x40000000: OyaSetObj18(modelo, padre, parte) = se cuelga de la parte '
                      f'{pk["parte"]} del padre (setPos/setAng quedan locales a esa parte)')
                if pk['flag'] & 0x40000000 else None))

    # motions / shapes por corte + visibilidad (ControlTransFlag)
    motion_por = {}
    shape_por = {}
    for pk in paqs:
        if pk['id'] == P_MOT:
            motion_por[(pk['nombre'], pk['cut'])] = pk
        elif pk['id'] == P_SHP:
            shape_por[(partes_de.get(pk['nombre'], pk['nombre']), pk['cut'])] = pk

    # funcion del cuarto (st1/r100.cpp Evt_R100S03_Func): wep0200 manual (CmfOn 5 = no lo toca ControlTransFlag)
    func_manual = {}
    if hdr['room'] == 'r100' and hdr['no'] == 's03':
        for c in range(len(cortes)):
            func_manual[('wep0200', c)] = c in (0, 1, 2, 3, 4, 13, 14, 15, 16, 17, 18, 19, 20)

    def raiz(mot, frame):
        """Raiz del modelo en metros / grados: la parte 0 con pos (kind & 4) y rot (kind & 2), que en las
        motions del evento lleva la posicion en coordenadas del cuarto (el obj18 esta en el origen,
        ExePacket_SetOm pos = 0); si no, los joints de raiz kind 1 / 0x40 (fcv.py)."""
        pos = rot = None
        mf = float(mot.max_frame + 1)
        for j in mot.joints:
            if pos is None and (j.kind == fcv.KIND_ROOT_POS or (j.parts_no == 0 and j.target() == 'pos')):
                pos = r3([x * MM for x in eval_joint(j, frame, mf)], 4)
            elif rot is None and (j.kind == fcv.KIND_ROOT_ROT or (j.parts_no == 0 and j.target() == 'rot')):
                rot = r3([math.degrees(x) for x in eval_joint(j, frame, mf)], 2)
        return pos, rot

    padres = {}
    for nm in orden:
        for p in modelos[nm]['posiciones']:
            if p['emparentar_a_parte'] is not None:
                padres[nm] = p['padre']
    raices = {}
    for nm in orden:
        md = modelos[nm]
        for c in cortes:
            ci = c['indice']
            pk = motion_por.get((nm, ci))
            ent = dict(corte=ci, inicio=c['inicio'], frames=c['frames'], motion=None, frames_motion=None, visible=False)
            if pk:
                data = bin_(pk['bin'])
                mot = fcv.parse(data)
                ent['motion'] = pk['bin']
                ent['frames_motion'] = mot.max_frame + 1
                if struct.unpack('>H', data[:2])[0] == 0:
                    # ExePacket_Mot: `if (*(u16*) dat == 0) return 1;` -> la motion NO se pone
                    ent['motion_ignorada'] = 'maxFrame 0: ExePacket_Mot no la pone'
                else:
                    ent['visible'] = True
                    if mot.max_frame + 1 < c['frames']:
                        # MotionSetCore flags 1 (sin loop): Mot_state 4 al terminar -> ControlTransFlag lo oculta
                        ent['oculto_desde_frame'] = mot.max_frame + 1
                    p0, a0 = raiz(mot, 0)
                    p1, a1 = raiz(mot, c['frames'] - 1)
                    ent['raiz_inicio_m'], ent['raiz_fin_m'] = p0, p1
                    if a0 is not None:     # las motions de personajes giran la parte 1 (pelvis), no la 0
                        ent['raiz_inicio_rot_grados'], ent['raiz_fin_rot_grados'] = a0, a1
                    raices[(nm, ci)] = (p0, mot)
            sh = shape_por.get((nm, ci))
            if sh:
                ent['cara'] = dict(parte=sh['nombre'], shape=sh['bin'])
            if (nm, ci) in func_manual:
                ent['visible'] = func_manual[(nm, ci)]
                ent['visible_por'] = 'Evt_R100S03_Func (st1/r100.cpp): be_flag bit 2 a mano en el frame 0 del corte'
            elif nm in padres and ent['visible']:
                ent['visible_por'] = f'ControlTransFlag: sigue al padre {padres[nm]}'
            md['cortes'].append(ent)
        # visibilidad de un hijo emparentado: la del padre (ControlTransFlag, obj18GetOya)
    for nm, pa in padres.items():
        if pa in modelos and not any((nm, c['indice']) in func_manual for c in cortes):
            for e, ep in zip(modelos[nm]['cortes'], modelos[pa]['cortes']):
                e['visible'] = ep['visible']

    # ---- luces / efectos / funciones / fades / niebla / foco ----
    luces = [dict(corte=pk['cut'], frame=pk['frame'], frame_global=global_frame(pk['cut'], pk['frame']),
                  lit=pk['archivo']) for pk in paqs if pk['id'] == P_LIT]
    for c in cortes:
        c['lit'] = next((l['lit'] for l in luces if l['corte'] == c['indice']), None)
    fades = [dict(corte=pk['cut'], frame=pk['frame'], frame_global=global_frame(pk['cut'], pk['frame']),
                  tipo='entrada (negro -> imagen)' if pk['no'] == 0 else 'salida (imagen -> negro)',
                  duracion_frames=pk['time'], no=pk['no']) for pk in paqs if pk['id'] == P_FADE]
    funcs = [dict(corte=pk['cut'], frame=pk['frame'], frame_global=global_frame(pk['cut'], pk['frame']),
                  entrada_tabla=pk['no'], arg=pk['arg']) for pk in paqs if pk['id'] == P_FUNC]
    niebla = [dict(corte=pk['cut'], frame=pk['frame'], archivo=pk['archivo']) for pk in paqs if pk['id'] == P_FOG]
    foco = [dict(corte=pk['cut'], frame=pk['frame'], archivo=pk['archivo']) for pk in paqs if pk['id'] == P_FOCUS]
    esp = [dict(corte=pk['cut'], frame=pk['frame'], frame_global=global_frame(pk['cut'], pk['frame']),
                modelo=pk['nombre'] or None, tipo=pk['esp_tipo'], parte=pk['parte']) for pk in paqs if pk['id'] == P_ESP]
    eff_name = next((pk['archivo'] for pk in paqs if pk['id'] == P_SETEFF), None)
    efectos_corte = []
    if eff_name and eff_name in bins:
        ids = eff_est_ids(bins[eff_name])
        idset = {i[0] for i in ids}
        for c in cortes:
            est = (c['indice'] // 10) * 16 + c['indice'] % 10     # est.cpp EventCutEstSet
            if est in idset:
                efectos_corte.append(dict(corte=c['indice'], est_id=est, frame_global=c['inicio']))

    # ---- sonidos ----
    sonidos = dict(se=[], streams=[], no_resueltos=[], notas=[])
    streams = None
    for pk in paqs:
        if pk['id'] == P_SE:
            # ExePacket_Se: SndCall(val.no = bloque, val.arg = numero, &pPL->pos)
            sonidos['se'].append(dict(frame_global=global_frame(pk['cut'], pk['frame']), corte=pk['cut'], frame=pk['frame'],
                                      bloque=pk['no'], numero=pk['arg'], raw=pk['raw']))
            sonidos['no_resueltos'].append(dict(frame_global=global_frame(pk['cut'], pk['frame']),
                                                motivo='Se: el banco depende de lo cargado en el cuarto (ver tools/re4_sonidos.py)'))
    if not sonidos['se']:
        sonidos['notas'].append('No hay paquetes Se: los efectos, voces y musica de la escena estan pre-mezclados en el '
                                'stream del evento (Str bloque 1). Las motions del evento no traen tabla SEQ '
                                '(ExePacket_Mot llama MotionSetCore con seq = 0), asi que tampoco disparan SE.')
    if not (hdr['snd_flag'] & 0x80000000):
        sonidos['notas'].append('Al empezar: SndEventInit (snd.cpp) apaga los SE del cuarto en 400 (fade) y los pausa, y baja '
                                'la BGM del cuarto (SndRoomBgmMuteAll); al terminar SndEventEnd los devuelve.')
    for pk in paqs:
        if pk['id'] != P_STR:
            continue
        gf = global_frame(pk['cut'], pk['frame'])
        blk, no = pk['no'], pk['arg']
        ent = dict(frame_global=gf, corte=pk['cut'], frame=pk['frame'], bloque_paquete=blk, numero_paquete=no,
                   flag=pk['flag'], raw=pk['raw'])
        try:
            if streams is None:
                streams = Streams(disco)
            if blk == 0:
                # EvtSndStrPlay(noTar 0) -> SndRoomStrStart(1, noStr, 1): el 2do parametro es el TIEMPO de
                # fade (segundos), el stream es el del cuarto (room_str_tbl[0], de bgm/bgmtbl.dat)
                room_no = int(hdr['room'][1:], 16)
                sblk, sno, tabla = 0, None, None
                bt = disco.archivo('bgm/bgmtbl.dat')
                ro, lo = struct.unpack('>II', bt[:8])
                i, p = 0, lo
                entradas = {}
                while True:
                    r, = struct.unpack('>H', bt[p:p + 2])
                    if r == 0xFFFF:
                        break
                    if r == room_no:
                        o = ro + struct.unpack('>I', bt[ro + 4 * i:ro + 4 * i + 4])[0]
                        n, = struct.unpack('>I', bt[o:o + 4])
                        for j in range(n):
                            e = struct.unpack('>13I', bt[o + 4 + 52 * j:o + 56 + 52 * j])
                            entradas[e[0]] = e
                    p += 2
                    i += 1
                # r100: SndBgmTblSet(0x100, 1) al final de la introduccion (st1/r100.cpp) -> tabla 1
                tabla = 1 if (hdr['room'] == 'r100' and 1 in entradas) else min(entradas) if entradas else None
                if tabla is None:
                    raise ValueError(f'el cuarto {hdr["room"]} no esta en bgmtbl.dat')
                s0 = entradas[tabla][7]
                if not (s0 & 0x8000):
                    raise ValueError('room_str_tbl[0] sin el bit 0x8000: el cuarto no tiene stream')
                sno = s0 & 0xFF
                ent.update(que='stream del cuarto (SndRoomStrStart(1, %d, 1): fade de %d s, en loop)' % (no, no),
                           bloque=sblk, numero=sno, tabla_bgm=dict(cuarto=hex(room_no), tabla=tabla, room_str_tbl0=hex(s0)),
                           fade_entrada_s=no, loop=True)
            else:
                sblk, sno = blk, no
                ent.update(que='stream del evento (voces + efectos + musica pre-mezclados)',
                           sincronizado=not (pk['flag'] & 0x20000000),
                           nota_sync=('EvtSndStrPlay(flag 1): el evento espera (TaskSleep) a que el stream este listo y '
                                      'recien ahi lo despausa -> arranca exactamente en este frame; la resincronizacion '
                                      'del juego usa segundos = frame / 29.97'),
                           loop=False)
            if sno >= streams.num(sblk):
                raise ValueError(f'numero {sno} >= {streams.num(sblk)} streams del bloque {sblk}')
            rit = streams.rit(sblk, sno)
            h = streams.shd(sblk, sno)
            est = bool(h['flag'] & 1) and not (h['flag'] & 2)
            base = f'str{sblk}_{sno:03d}'
            loop = None
            if h['flag'] & 4:
                loop = (nibble_a_muestra(h['lptop_nbl']), nibble_a_muestra(h['lpend_nbl']))
            ent.update(archivo_disco=STR_ARCHIVO[sblk], offset=h['offset'], rit=rit, str_no=rit['str_no'],
                       canales=2 if est else 1, rate=h['rate'], muestras=h['samples'],
                       duracion_s=round(h['samples'] / h['rate'], 4),
                       duracion_frames=round(h['samples'] / h['rate'] * FPS, 2),
                       volumen_rit=rit['vol'], pan_rit=rit['pan'], shd_flag=h['flag'],
                       loop_muestras=list(loop) if loop else None,
                       wav=f'audio/{base}.wav', wav_n95=f'audio/{base}_n95.wav')
            ent['loop'] = bool(h['flag'] & 4)
            wav = os.path.join(out_dir, ent['wav'])
            wn = os.path.join(out_dir, ent['wav_n95'])
            if args.sin_audio:
                ent['nota_audio'] = 'no decodificado (--sin-audio)'
            elif args.forzar_audio or not (os.path.isfile(wav) and os.path.isfile(wn)):
                print(f'  decodificando stream bloque {sblk} n {sno} ({ent["duracion_s"]} s, '
                      f'{"estereo" if est else "mono"}, {h["rate"]} Hz)...')
                canales, rate, _ = streams.decodificar(sblk, sno)
                escribir_wav(wav, canales, rate, loop)
                escribir_n95(wn, canales, rate)
            sonidos['streams'].append(ent)
        except Exception as e:  # noqa: BLE001
            ent['error'] = str(e)
            sonidos['streams'].append(ent)
            sonidos['no_resueltos'].append(dict(frame_global=gf, paquete='Str', motivo=str(e)))
    disco.limpiar()

    # ---- subtitulos ----
    subtitulos = []
    mdt_name = next((pk['archivo'] for pk in paqs if pk['id'] == P_SETMDT), None)
    mdt = bins.get(mdt_name) if mdt_name else None
    for pk in paqs:
        if pk['id'] != P_MES:
            continue
        gf = global_frame(pk['cut'], pk['frame'])
        ent = dict(frame_global=gf, corte=pk['cut'], frame=pk['frame'], mensaje_no=pk['no'],
                   duracion_frames=pk['arg'], fin_frame_global=gf + pk['arg'], raw=pk['raw'],
                   archivo=mdt_name or '(mdt del cuarto: archivo 0xF0)')
        if mdt is not None:
            w_en = mdt_mensaje(mdt, 1, pk['no'])
            ent["texto_en"] = texto_latino(w_en).strip() if w_en is not None else None
            ent['glifos_en'] = w_en
            ent['glifos_por_idioma'] = {str(l): mdt_mensaje(mdt, l, pk['no'])
                                        for l in range(struct.unpack('>I', mdt[:4])[0])}
        ent['mostrado_en_usa'] = False
        ent['nota'] = ('Event::MesSet no dibuja nada si pSys->language == 1 (USA); el bloque ingles (MesData.lang 1) '
                       'del .mdt solo tiene etiquetas de trabajo, no el dialogo. El dialogo real esta en el audio del stream.')
        caras = [nm for nm in orden for e in modelos[nm]['cortes'] if e['corte'] == pk['cut'] and e.get('cara')]
        if caras:
            ent['hablante_probable'] = caras[0]
            ent['hablante_por'] = 'modelo con animacion facial (Shp) en ese corte'
        subtitulos.append(ent)

    # ---- validacion: cada camara vs. las raices de los modelos (proyeccion 4/3, fovy de la camara) ----
    def ndc(cam, f, p):
        """Punto del mundo -> coordenadas normalizadas de la imagen completa (-1..1) y profundidad (m)."""
        eye, at, up = cam['ojo'][f], cam['objetivo'][f], cam['arriba'][f]
        fw = norm(sub(at, eye))
        r = norm(cross(fw, up))
        u = cross(r, fw)
        d = sub(p, eye)
        z = sum(d[i] * fw[i] for i in range(3))
        if z <= 0:
            return None
        t = math.tan(math.radians(cam['fov_grados'][f] / 2))
        return (sum(d[i] * r[i] for i in range(3)) / z / t / (4 / 3), sum(d[i] * u[i] for i in range(3)) / z / t, z)

    validacion = dict(
        metodo='raiz = parte 0 (cadera); se proyecta el segmento pies (raiz - 1.0 m) .. cabeza (raiz + 0.7 m) con la '
               'camara del frame del medio del corte; en_cuadro = el segmento cruza la imagen 4:3 (sin las barras)',
        cortes=[])
    for c in cortes:
        cam = camara[c['indice']]
        if not cam['ojo']:
            continue
        f = c['frames'] // 2
        fila = dict(corte=c['indice'], frame=f, modelos={})
        for nm in orden:
            key = (nm, c['indice'])
            if key not in raices or not raices[key][0]:
                continue
            mot = raices[key][1]
            p = raiz(mot, f)[0]
            pies = ndc(cam, f, [p[0], p[1] - 1.0, p[2]])
            cabeza = ndc(cam, f, [p[0], p[1] + 0.7, p[2]])
            if not pies or not cabeza:
                fila['modelos'][nm] = dict(en_cuadro=False, nota='detras de la camara')
                continue
            dentro = (min(pies[1], cabeza[1]) < 1 and max(pies[1], cabeza[1]) > -1
                      and min(pies[0], cabeza[0]) < 1 and max(pies[0], cabeza[0]) > -1)
            fila['modelos'][nm] = dict(en_cuadro=dentro, pies_ndc=r3(pies[:2], 2), cabeza_ndc=r3(cabeza[:2], 2),
                                       distancia_m=round(pies[2], 2))
        validacion['cortes'].append(fila)
    if camara and camara[0]['ojo'] and ('pl0000', 0) in raices and raices[('pl0000', 0)][0]:
        leon = raices[('pl0000', 0)][0]
        pies = ndc(camara[0], 0, [leon[0], leon[1] - 1.0, leon[2]])
        validacion['corte0_frame0'] = dict(raiz_leon_m=leon, ojo_m=camara[0]['ojo'][0], objetivo_m=camara[0]['objetivo'][0],
                                           fov_grados=camara[0]['fov_grados'][0],
                                           pies_leon_ndc=r3(pies[:2], 2) if pies else None,
                                           nota='plano bajo: la camara (a ~15 cm del piso, y = 0.86 m) encuadra las piernas/pies de Leon'
                                           if hdr['room'] == 'r100' and hdr['no'] == 's03'
                                           else 'camara del frame 0 del corte 0 contra la raiz de Leon')

    # ---- JSON ----
    for c in cortes:
        c.pop('_mot', None)
        c.pop('cut_paquete', None)
    out = dict(
        evento=f'{hdr["room"]}{hdr["no"]}',
        fuente=dict(disco=os.path.basename(args.disc), evd=f'Evd/{args.evento}.evd'),
        unidades=dict(posicion='metros (mm del juego * 0.001), coordenadas del cuarto, Y arriba',
                      angulos='grados', frames='frames de 30 fps (el juego corre a 29.97)'),
        fps=FPS, fps_ntsc=FPS_NTSC, frames_totales=total, duracion_s=round(total / FPS, 3),
        pantalla=dict(
            proyeccion='C_MTXPerspective(fovy, 4/3) (camera.cpp CameraMove): fov_grados es el vertical de la imagen completa',
            aspecto_proyeccion=round(4 / 3, 6),
            cinesco=dict(activo=True,
                         nota='cinesco.cpp: CinescoMove prende STA_CINESCO todos los frames y Draw_cinesco pinta dos '
                              'barras negras (filas 0..56 y 393..449 de 448) siempre, tambien fuera de las cutscenes',
                         barra_arriba_filas=56, barra_abajo_desde_fila=393, alto_logico=448, ancho_logico=512,
                         alto_visible_fraccion=round(337 / 448, 6),
                         aspecto_visible=round((4 / 3) / (337 / 448), 4),
                         fov_vertical_visible='2*atan(tan(fov/2) * 337/448)')),
        cortes=[{k: c[k] for k in ('indice', 'inicio', 'frames', 'camara', 'dammy', 'lit')} for c in cortes],
        camara=camara,
        modelos=[modelos[n] for n in orden],
        sonidos=sonidos,
        subtitulos=subtitulos,
        fades=fades, niebla=niebla, foco=foco, luces=luces, efectos_paquete=esp,
        efectos_por_corte=dict(archivo=eff_name, cortes=efectos_corte,
                               nota='ExePacket_Cam -> EventCutEstSet(0xC4 + effNo, corte): est id = (corte/10)*16 + corte%10 '
                                    'si existe en el EFF del evento'),
        funciones=funcs,
        funcion_evento=dict(
            nombre=f'evt_{hdr["room"]}{hdr["no"]}_func',
            descripcion=FUNCION_EVENTO.get(f'{hdr["room"]}{hdr["no"]}', 'ver el codigo del cuarto')),
        despues_del_evento=DESPUES_DEL_EVENTO.get(f'{hdr["room"]}{hdr["no"]}'),
        validacion=validacion,
        avisos=sorted(avisos),
        paquetes=[{k: v for k, v in pk.items()} | {'frame_global': global_frame(pk['cut'], pk['frame'])} for pk in paqs],
    )
    jpath = os.path.join(out_dir, 'evento.json')
    with open(jpath, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ---- resumen ----
    print()
    print(f'=== {out["evento"]}: {len(cortes)} cortes, {total} frames ({total / FPS:.2f} s a 30 fps) ===')
    for c in cortes:
        vis = [n for n in orden if modelos[n]['cortes'][c['indice']]['visible']]
        cam = camara[c['indice']]
        extra = ''
        if cam['fov_grados']:
            extra = f' fov {cam["fov_grados"][0]:.1f}->{cam["fov_grados"][-1]:.1f}'
        print(f'corte {c["indice"]:2d}  {c["inicio"]:5d}-{c["inicio"] + c["frames"] - 1:5d} ({c["frames"]:3d} f, '
              f'{c["inicio"] / FPS:6.2f}s){extra}  visibles: {", ".join(vis)}')
        for s in sonidos['streams']:
            if s['corte'] == c['indice']:
                print(f'        + audio  f{s["frame_global"]}: {s.get("que", "")} -> {s.get("wav", s.get("error"))}')
        for s in subtitulos:
            if s['corte'] == c['indice']:
                print(f'        + mensaje {s["mensaje_no"]} f{s["frame_global"]}-{s["fin_frame_global"]}: '
                      f'"{s.get("texto_en")}" (no se muestra en USA; hablante probable {s.get("hablante_probable")})')
        for fd in fades:
            if fd['corte'] == c['indice']:
                print(f'        + fade {fd["tipo"]} {fd["duracion_frames"]} f')
        for e in efectos_corte:
            if e['corte'] == c['indice']:
                print(f'        + efecto est {e["est_id"]:#x} del {os.path.basename(eff_name)}')
    if validacion.get('corte0_frame0'):
        v = validacion['corte0_frame0']
        print(f"\nvalidacion corte 0 frame 0: raiz de Leon {v['raiz_leon_m']}, ojo {v['ojo_m']}, pies de Leon en "
              f"{v['pies_leon_ndc']} (NDC, -1..1)")
    print('en cuadro (frame del medio): ' + '  '.join(
        f"c{fl['corte']}:" + ','.join(n for n, m in fl['modelos'].items() if m['en_cuadro']) for fl in validacion['cortes']))
    if sonidos['no_resueltos']:
        print('sin resolver:', sonidos['no_resueltos'])
    for a in sorted(avisos):
        print('aviso:', a)
    print(f'\n-> {jpath}')


if __name__ == '__main__':
    main()
