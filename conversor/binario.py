"""Los archivos de la demo para el N95: little endian (como el ARM11), todo alineado a 4 bytes.

  paquete de texturas (.txn): 'TXN1', u32 cantidad; por textura: char nombre[32], u16 banderas (1 repetir, 2 filtro
  lineal), u16 0, u32 desde, u32 bytes; despues cada textura entera, un .w3dt (w3dt.py) alineado a 4."""
import struct


class Escritor:
    def __init__(self):
        self.partes = []
        self.largo = 0

    def b(self, datos):
        self.partes.append(datos)
        self.largo += len(datos)
        return self

    def s(self, fmt, *v):
        return self.b(struct.pack('<' + fmt, *v))

    def nombre(self, n, largo=32):
        e = n.encode('utf-8')[:largo - 1]
        return self.b(e + b'\0' * (largo - len(e)))

    def alinear(self, a=4):
        if self.largo % a:
            self.b(b'\0' * (a - self.largo % a))
        return self

    def guardar(self, ruta):
        self.alinear()
        with open(ruta, 'wb') as f:
            f.write(b''.join(self.partes))
        return self.largo


REPETIR, FILTRO = 1, 2


def paquete_texturas(ruta, texturas):
    """texturas: [(nombre, banderas, w3dt)] (w3dt: los bytes de un .w3dt)"""
    w = Escritor().b(b'TXN1').s('I', len(texturas))
    desde = 8 + len(texturas) * 44
    for nombre, banderas, datos in texturas:
        w.nombre(nombre).s('HHII', banderas, 0, desde, len(datos))
        desde += (len(datos) + 3) // 4 * 4
    for t in texturas:
        w.b(t[2]).alinear()
    return w.guardar(ruta)
