"""EL SONIDO para el N95 (datos/sonidos/): todo a la frecuencia del mezclador del Core (22050 Hz) y mono.

  *.wav      los efectos (16 bits), con el volumen de cada uno ya aplicado (la tabla VOL de los scripts)
  *.ima      las pistas largas (la musica del cuarto, el audio de cada cinematica, la voz del codec): IMA ADPCM, 4 bits
             por muestra (un cuarto de la memoria). 'IMA2', u32 frecuencia, u32 muestras, u32 desde donde vuelve el
             lazo; los nibbles (el bajo primero)
  lista.txt  los nombres de los efectos (el juego no puede listar una carpeta del telefono)
"""
import io
import os
import struct
import wave

import numpy as np

RATE = 22050
PISTAS = ('r100_bgm', 'r100_musica', 'evento_s03', 'evento_s40', 'evento_s20', 'evento_s41', 'evento_s43',
          'evento_s44', 'codec_voz', 'codec_tono', 'ventana')
PASOS = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97,
         107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
         876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871,
         5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
         24623, 27086, 29794, 32767]
INDICE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def leer_wav(datos):
    w = wave.open(io.BytesIO(datos))
    n, ch, rate, ancho = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
    b = w.readframes(n)
    if ancho == 2:
        a = np.frombuffer(b, '<i2').astype(np.float64)
    elif ancho == 1:
        a = (np.frombuffer(b, np.uint8).astype(np.float64) - 128) * 256
    else:
        raise ValueError('wav de %d bits' % (ancho * 8))
    a = a.reshape(-1, ch).mean(1)
    return a, rate


def a_rate(a, rate):
    if rate == RATE or len(a) < 2:
        return a
    n = int(round(len(a) * RATE / rate))
    t = np.arange(n) * (rate / RATE)
    return np.interp(t, np.arange(len(a)), a)


def guardar_wav(ruta, a):
    s = np.clip(np.round(a), -32768, 32767).astype('<i2')
    with wave.open(ruta, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(s.tobytes())


def ima(a):
    """IMA ADPCM (el mismo decodificador que sonido.cpp)"""
    s = np.clip(np.round(a), -32768, 32767).astype(np.int32)
    pred, indice = 0, 0
    nib = np.zeros(len(s), np.uint8)
    pasos, ind = PASOS, INDICE
    for i, x in enumerate(s.tolist()):
        paso = pasos[indice]
        dif = x - pred
        n = 0
        if dif < 0:
            n = 8
            dif = -dif
        d = paso >> 3
        if dif >= paso:
            n |= 4
            dif -= paso
            d += paso
        if dif >= paso >> 1:
            n |= 2
            dif -= paso >> 1
            d += paso >> 1
        if dif >= paso >> 2:
            n |= 1
            d += paso >> 2
        pred += -d if n & 8 else d
        pred = -32768 if pred < -32768 else 32767 if pred > 32767 else pred
        indice += ind[n]
        indice = 0 if indice < 0 else 88 if indice > 88 else indice
        nib[i] = n
    if len(nib) % 2:
        nib = np.append(nib, 0)
    return (nib[0::2] | (nib[1::2] << 4)).astype(np.uint8).tobytes()


def armar(proyectos, vol, salida, log=print):
    """proyectos: los .w3d (fuentes.Proyecto) de donde salen los sonidos; vol: nombre -> volumen"""
    os.makedirs(salida, exist_ok=True)
    hechos = set()
    efectos = []
    kb_ef = kb_pi = 0
    for p in proyectos:
        for entrada in sorted(p.nombres):
            if not entrada.startswith('sonidos/') or not entrada.endswith('.wav'):
                continue
            nombre = os.path.basename(entrada)[:-4]
            if nombre in hechos:
                continue
            hechos.add(nombre)
            a, rate = leer_wav(p.leer(entrada))
            a = a_rate(a, rate)
            if nombre in PISTAS:
                ruta = os.path.join(salida, nombre + '.ima')
                datos = ima(a)
                with open(ruta, 'wb') as f:
                    f.write(b'IMA2' + struct.pack('<III', RATE, len(a), 0) + datos)
                kb_pi += os.path.getsize(ruta) // 1024
            else:
                a = a * vol.get(nombre, 1.0)
                ruta = os.path.join(salida, nombre + '.wav')
                guardar_wav(ruta, a)
                efectos.append(nombre)
                kb_ef += os.path.getsize(ruta) // 1024
    with open(os.path.join(salida, 'lista.txt'), 'w', newline='\n') as f:
        f.write('\n'.join(efectos) + '\n')
    log('sonidos: %d efectos (%d KB), %d pistas IMA (%d KB)' % (len(efectos), kb_ef, len(hechos) - len(efectos), kb_pi))
