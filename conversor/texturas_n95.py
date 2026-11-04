"""El registro de las texturas del juego: cada una entra UNA vez (por su nombre) y sale en texturas.txn como un .w3dt
del Core (16 bits con sus mipmaps hechos: el N95 no decodifica PNG). El indice que devuelve agregar() es el que guardan
los binarios (mundo.bin, los modelos, los efectos, el HUD)."""
import os

import numpy as np
from PIL import Image

import binario
import w3dt


def potencia_de_dos(n, tope):
    p = 1
    while p < n and p < tope:
        p *= 2
    return p


def sangrar(a, pasos=8):
    """el color de lo opaco corrido hacia lo transparente (el RGB de un pixel invisible es negro en el disco: el filtro
    lo mezclaba en el borde -el pelo con bordes negros-). Cada paso le da a los transparentes el promedio de sus
    vecinos ya pintados"""
    rgb = a[:, :, :3].astype(np.float32)
    lleno = a[:, :, 3] >= 128
    for _ in range(pasos):
        if lleno.all():
            break
        suma = np.zeros_like(rgb)
        cuenta = np.zeros(lleno.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            m = np.roll(np.roll(lleno, dy, 0), dx, 1)
            suma += np.roll(np.roll(rgb, dy, 0), dx, 1) * m[..., None]
            cuenta += m
        nuevo = ~lleno & (cuenta > 0)
        rgb[nuevo] = suma[nuevo] / cuenta[nuevo][:, None]
        lleno = lleno | nuevo
    b = a.copy()
    b[:, :, :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    return b


class Texturas:
    def __init__(self, tope=512):
        self.lista = []          # (nombre, banderas, imagen RGBA, formato)
        self.indice = {}
        self.tope = tope

    def agregar(self, nombre, imagen, repetir=True, filtro=True, mitad=False, tope=None, formato=None):
        """imagen: ruta, PIL o arreglo. mitad: a la mitad (las de los personajes de juego). tope: lado maximo."""
        if nombre in self.indice:
            return self.indice[nombre]
        if isinstance(imagen, np.ndarray):
            img = Image.fromarray(imagen.astype(np.uint8), 'RGBA')
        elif isinstance(imagen, Image.Image):
            img = imagen.convert('RGBA')
        else:
            img = Image.open(imagen).convert('RGBA')
        w, h = img.size
        if mitad:
            w, h = max(1, w // 2), max(1, h // 2)
        t = tope or self.tope
        w2, h2 = potencia_de_dos(w, t), potencia_de_dos(h, t)
        if (w2, h2) != img.size:
            img = img.resize((w2, h2), Image.LANCZOS if w2 < img.size[0] or h2 < img.size[1] else Image.BICUBIC)
        a = np.asarray(img, np.uint8).copy()
        if (a[:, :, 3] < 250).any():
            a = sangrar(a)
        if formato is None:
            alfa = a[:, :, 3]
            if (alfa >= 250).all():
                a[:, :, 3] = 255
                formato = w3dt.RGB565
            elif np.isin(alfa, (0, 255)).mean() > 0.97:
                a[:, :, 3] = np.where(alfa >= 128, 255, 0)
                formato = w3dt.RGBA5551
            else:
                formato = w3dt.RGBA4444
        banderas = (binario.REPETIR if repetir else 0) | (binario.FILTRO if filtro else 0)
        self.indice[nombre] = len(self.lista)
        self.lista.append((nombre, banderas, a, formato))
        return self.indice[nombre]

    def formato(self, i):
        """'opaca', 'recorte' (alfa de un bit) o 'alfa'"""
        if i >= len(self.lista):
            return 'opaca'
        f = self.lista[i][3]
        return 'opaca' if f == w3dt.RGB565 else 'recorte' if f == w3dt.RGBA5551 else 'alfa'

    def guardar(self, ruta):
        texs = []
        bytes_gpu = 0
        for nombre, banderas, a, formato in self.lista:
            datos, _, w, h = w3dt.escribir(a, formato)
            texs.append((nombre[-31:], banderas, datos))
            bytes_gpu += len(datos)
        n = binario.paquete_texturas(ruta, texs)
        return len(texs), n, bytes_gpu
