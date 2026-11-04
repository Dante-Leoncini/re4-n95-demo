"""Las texturas de la demo para el N95: el .w3dt del Core de Whisk3D (gfx/w3dTexture.cpp), los pixeles ya en el formato
que recibe glTexImage2D con todos los niveles de mipmap hechos (cargar es leer y subir: el N95 no decodifica PNG).

    cabecera (16 B): "W3DT" | u16 version (1) | u16 formato | u16 ancho | u16 alto | u8 niveles | u8 0 | u16 0
    niveles:         el 0 (ancho x alto) y cada mitad hasta 1x1, filas apretadas, cada nivel alineado a 4
    formato:         1 RGB565 | 2 RGBA5551 | 3 RGBA4444 | 5 RGBA8888 (little-endian, como GL)

El formato sale de la imagen: opaca, 565; con alfa de un bit (los recortes: plantas, arboles), 5551; con alfa de varios
niveles (los efectos, el HUD, las olas), 8888 (como la version N95 de dbz2w3d: las de alfa con niveles quedan en 8
bits). Ancho y alto potencia de dos (lo unico que acepta el MBX del N95; las texturas de la PS2 ya lo son)."""
import struct

import numpy as np
from PIL import Image

RGB565, RGBA5551, RGBA4444, RGBA8888 = 1, 2, 3, 5
NOMBRE = {RGB565: '565', RGBA5551: '5551', RGBA4444: '4444', RGBA8888: '8888'}
BPP = {RGB565: 2, RGBA5551: 2, RGBA4444: 2, RGBA8888: 4}


def rgba(img):
    """una ruta, una Image o un arreglo (alto, ancho, 4) -> uint8 (alto, ancho, 4)"""
    if isinstance(img, np.ndarray):
        return np.ascontiguousarray(img, np.uint8)
    if not isinstance(img, Image.Image):
        img = Image.open(img)
    return np.asarray(img.convert('RGBA'), np.uint8)


def formato_de(a):
    alfa = a[:, :, 3]
    if (alfa == 255).all():
        return RGB565
    if np.isin(alfa, (0, 255)).all():
        return RGBA5551
    return RGBA8888


def mitad(a, formato):
    """el nivel que sigue (cada 2x2 promediado; en 5551 el alfa vuelve a ser de un bit)"""
    h, w = a.shape[:2]
    f = a.astype(np.float32).reshape(max(1, h // 2), 2 if h > 1 else 1, max(1, w // 2), 2 if w > 1 else 1, 4)
    m = f.mean((1, 3))
    if formato == RGBA5551:
        m[:, :, 3] = np.where(m[:, :, 3] >= 127.5, 255, 0)
    return np.clip(m + 0.5, 0, 255).astype(np.uint8)


def empacar(a, formato):
    c = a.astype(np.uint32)
    r, g, b, al = c[:, :, 0], c[:, :, 1], c[:, :, 2], c[:, :, 3]
    if formato == RGB565:
        v = ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
    elif formato == RGBA5551:
        v = ((r * 31 + 127) // 255) << 11 | ((g * 31 + 127) // 255) << 6 | ((b * 31 + 127) // 255) << 1 | (al >= 128)
    elif formato == RGBA4444:
        v = ((r * 15 + 127) // 255) << 12 | ((g * 15 + 127) // 255) << 8 | ((b * 15 + 127) // 255) << 4 | \
            ((al * 15 + 127) // 255)
    else:
        return a.tobytes()
    return v.astype('<u2').tobytes()


def escribir(img, formato=None, mips=True):
    """-> (bytes del .w3dt, formato, ancho, alto)"""
    a = rgba(img)
    h, w = a.shape[:2]
    assert w & (w - 1) == 0 and h & (h - 1) == 0, 'textura de %dx%d: el N95 solo acepta potencias de dos' % (w, h)
    if formato is None:
        formato = formato_de(a)
    niveles = [a]
    while mips and (niveles[-1].shape[0] > 1 or niveles[-1].shape[1] > 1):
        niveles.append(mitad(niveles[-1], formato))
    partes = [struct.pack('<4sHHHHBBH', b'W3DT', 1, formato, w, h, len(niveles), 0, 0)]
    for n in niveles:
        d = empacar(n, formato)
        partes.append(d + b'\0' * ((-len(d)) % 4))
    return b''.join(partes), formato, w, h
