"""Lectura de las bibliotecas de clips de esqueleto de Whisk3D (.w3da, libs/Whisk3DCore/animation/W3dAnimSet.h):
la tabla de huesos y los clips con sus curvas (propiedad, componente, keyframes)."""
import struct


class Curva:
    def __init__(self, prop, comp, frames, valores, interp):
        self.prop, self.comp = prop, comp
        self.frames, self.valores, self.interp = frames, valores, interp

    def valor(self, f):
        """el valor en el frame f (con fraccion): constante afuera, lineal adentro (salvo interpolacion constante)"""
        fr, v = self.frames, self.valores
        if f <= fr[0]:
            return v[0]
        if f >= fr[-1]:
            return v[-1]
        lo, hi = 0, len(fr) - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if fr[m] <= f:
                lo = m
            else:
                hi = m
        if self.interp[lo] == 0:      # constante
            return v[lo]
        t = (f - fr[lo]) / float(fr[hi] - fr[lo])
        return v[lo] + (v[hi] - v[lo]) * t


class Clip:
    def __init__(self, nombre, fps, ini, fin):
        self.nombre, self.fps, self.ini, self.fin = nombre, fps, ini, fin
        self.pistas = {}    # hueso -> [Curva]


class Cursor:
    def __init__(self, d, p=0):
        self.d, self.p = d, p

    def u32(self):
        v, = struct.unpack_from('<I', self.d, self.p); self.p += 4; return v

    def i32(self):
        v, = struct.unpack_from('<i', self.d, self.p); self.p += 4; return v

    def f32(self):
        v, = struct.unpack_from('<f', self.d, self.p); self.p += 4; return v

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def txt(self):
        n = self.u32(); s = self.d[self.p:self.p + n].decode('utf8'); self.p += n; return s


def _curva(c):
    prop, comp, n = c.i32(), c.i32(), c.u32()
    mF, mI, mT, mH = c.u8(), c.u8(), c.u8(), c.u8()
    if n == 0:
        return Curva(prop, comp, [0], [0.0], [1])
    if mF == 1:     # regulares
        f0, paso = c.i32(), c.i32()
        frames = [f0 + paso * i for i in range(n)]
    else:
        frames = [c.i32() for _ in range(n)]
    valores = [c.f32() for _ in range(n)]
    interp = [c.i32()] * n if mI == 1 else [c.i32() for _ in range(n)]
    if mT == 1:
        c.i32()
    else:
        [c.i32() for _ in range(n)]
    if mH == 1:
        c.p += 16 * n
    return Curva(prop, comp, frames, valores, interp)


def leer(datos):
    if datos[:4] != b'W3DA':
        raise ValueError('no es un .w3da')
    nb, = struct.unpack_from('<I', datos, 12)
    p = 20
    huesos, clips = [], []
    for _ in range(nb):
        cc, dom, cant, nbytes = struct.unpack_from('<4sIII', datos, p)
        p += 16
        c = Cursor(datos[p:p + nbytes])
        if cc == b'HUES':
            huesos = [c.txt() for _ in range(cant)]
        elif cc == b'CLIP':
            k = Clip(c.txt(), c.i32(), c.i32(), c.i32())
            for _ in range(cant):
                hueso, ncur = c.i32(), c.u32()
                curvas = [_curva(c) for _ in range(ncur)]
                if hueso >= 0:
                    k.pistas[hueso] = curvas
            clips.append(k)
        p += (nbytes + 3) & ~3
    return huesos, clips
