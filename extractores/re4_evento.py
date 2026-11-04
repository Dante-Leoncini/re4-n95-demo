#!/usr/bin/env python3
"""
Eventos (cutscenes en motor) de Resident Evil 4 GameCube: files/Evd/rNNNsMM.evd.

Un .evd es un bloque "event" (include/event.h EvtHeader) con una tabla de archivos por nombre (modelos .bin/.tpl,
motions .fcv, luces, efectos) y un STREAM DE PAQUETES (EvtPacket: id, flag, cut, frame, size, ...) que
game/event.cpp ejecuta frame a frame:

  SetOm    (3)   crea un modelo del evento (obj18) desde bin/tpl: "pl0000" = Leon, "em1000" = el ganado, obmNNNN ...
                 Los "em/pl00/pl000a.bin" & co. NO estan en el .evd: ExeBeginEvt registra con esos nombres los modelos
                 del propio Leon (pl000a.bin = PL_ARC 4 = pl00:0 el cuerpo, pl000a.tpl = pl00:1, pl000d.bin = pl00:5,
                 pl000b.tpl = pl00:3, pl000e.bin = pl00:6, pl000l.bin = pl00:12).
  SetParts (4)   cuelga un modelo de piezas (cabeza, manos) del modelo `oya`; ev0002/ev0102/... ademas pisan las
                 posiciones de reposo del padre (cModel::setPartsOffset).
  Cam      (6)   = COMIENZO DE UN CORTE: camara del corte (largo del corte = maxFrame de la camara + 1) y
                 MotClear() de todos los modelos (cada corte arranca sus motions de cero).
  CamDammy (8)   corte sin camara (largo = val.no).
  Pos      (9)   ubica un modelo (pos mm / rot grados); flag 0x40000000 = lo cuelga de la parte `partsNo` de `oya`
                 (OyaSetObj18: asi el arma va en la mano de Leon).
  Mot      (0xB) MotionSetCore(m, dat, 0, 0, flags 1, frame 0): la motion del modelo en ese corte. Mot_attr bit 0 =
                 la velocidad de las claves raiz ("Null" pos/rot) mueve al modelo (MotionGetSpeed/MotionAddSpeed,
                 empezando de Pos = 0): mundo = Pos del paquete * raiz(f) * partes. En r100s03 no hay claves raiz
                 ni paquetes Pos para los personajes: la parte 0 trae directamente la posicion en el MUNDO del cuarto.
  Shp      (0xC) animacion de caras (ShapeData, <modelo>/face/*.fcv).

Aca: la lista de cortes con su largo, que motion toca cada modelo en cada corte, y la evaluacion de un corte con el
codigo del juego (evalhost) devolviendo poses de largo = largo del corte (la motion se sostiene en su ultimo frame si
es mas corta, como MotionSetCore sin loop; se corta si es mas larga: el corte siguiente hace MotClear).
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
from motion import archive, fcv  # noqa: E402

PAQUETES = ('BeginEvt SetPl SetEm SetOm SetParts SetList Cam CamPos CamDammy Pos PosPl Mot Shp Esp Lit Str Se Mes '
            'Func ParentOn ParentOff EndPl EndEm EndOm EndParts EndList EndEvt EndPac SetEff Fade Fog Focus SetMdt').split()

# ExeBeginEvt: los modelos del jugador que el evento pide por nombre -> (archivo, entrada)
BINS_LEON = {'em/pl00/pl000a.bin': ('pl00', 0), 'em/pl00/pl000a.tpl': ('pl00', 1), 'em/pl00/pl000d.bin': ('pl00', 5),
             'em/pl00/pl000b.tpl': ('pl00', 3), 'em/pl00/pl000e.bin': ('pl00', 6), 'em/pl00/pl000l.bin': ('pl00', 12)}


def _txt(b):
    return b.split(b'\0')[0].decode('ascii', 'replace')


def resolver_evd(nombre, disc):
    """Ruta de un .evd: tal cual, o extracted/Evd/<nombre>, o sacado del disco (files/Evd/) con dtk la primera vez."""
    if os.path.isfile(nombre):
        return nombre
    base = os.path.basename(nombre)
    if not base.lower().endswith('.evd'):
        base += '.evd'
    out = os.path.join(HERE, 'extracted', 'Evd', base)
    if not os.path.isfile(out):
        import re4_extract_leon as L
        L.ensure_dtk()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        subprocess.check_call([L.DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/Evd/{base}', out])
    return out


class Paquete:
    def __init__(self, d, p):
        self.id, self.flag, self.cut, self.frame, self.size = struct.unpack('>iIhhh', d[p:p + 14])
        self.tipo = PAQUETES[self.id] if 0 <= self.id < len(PAQUETES) else f'id{self.id}'
        c = d[p + 0x10:p + self.size]
        self.cuerpo = c
        if self.tipo == 'SetParts':
            self.nombre, self.oya, self.bin, self.tpl = _txt(c[:0xC]), _txt(c[0xC:0x18]), _txt(c[0x18:0x48]), _txt(c[0x48:0x78])
        elif self.tipo in ('Pos', 'ParentOn', 'ParentOff'):
            self.nombre, self.oya = _txt(c[:0xC]), _txt(c[0xC:0x18])
            v = struct.unpack('>7i', c[0x18:0x34])
            self.pos, self.rot, self.parte = v[0:3], v[3:6], v[6]
        elif self.tipo == 'CamDammy':
            self.no = struct.unpack('>i', c[:4])[0]
        else:
            # mod: name[0xC] bin[0x30] tpl[0x30]; Cam / Lit / SetEff / SetMdt guardan el archivo en name+bin (0x3C)
            self.nombre, self.bin, self.tpl = _txt(c[:0xC]), _txt(c[0xC:0x3C]), _txt(c[0x3C:0x6C])
            self.archivo = _txt(c[:0x3C])


class Evento:
    def __init__(self, ruta):
        d = open(ruta, 'rb').read()
        self.nombre = os.path.splitext(os.path.basename(ruta))[0]   # r100s03
        self.bins = dict(archive.parse_event(d))
        pac_ofs, pac_size = struct.unpack('>II', d[0x40:0x48])
        self.paquetes = []
        p = pac_ofs
        while p < pac_ofs + pac_size:
            k = Paquete(d, p)
            self.paquetes.append(k)
            if k.tipo == 'EndPac':
                break
            p += k.size
        # cortes (CalMaxCut / CalMaxFrame)
        self.cortes = []
        for k in self.paquetes:
            if k.tipo == 'Cam':
                self.cortes.append(struct.unpack('>H', self.bins[k.archivo][:2])[0] + 1)
            elif k.tipo == 'CamDammy':
                self.cortes.append(k.no)
        self.modelos = {k.nombre: (k.bin, k.tpl) for k in self.paquetes if k.tipo == 'SetOm'}
        self.piezas = [(k.nombre, k.oya, k.bin, k.tpl) for k in self.paquetes if k.tipo == 'SetParts']
        self.posiciones = [k for k in self.paquetes if k.tipo == 'Pos']
        self.mots = {}   # (corte, modelo) -> nombre del .fcv
        for k in self.paquetes:
            if k.tipo == 'Mot':
                self.mots[(k.cut, k.nombre)] = k.bin

    @property
    def sufijo(self):
        """'r100s03' -> 's03' (prefijo de los clips)."""
        i = self.nombre.rfind('s')
        return self.nombre[i:] if i > 0 else self.nombre

    def clip(self, corte):
        return f'{self.sufijo}_c{corte:02d}'

    def motion(self, corte, modelo):
        """fcv.Motion que el evento pone en `modelo` en ese corte, o None (sin paquete Mot, o motion vacia: el juego
        la ignora si su u16 maxFrame es 0)."""
        nombre = self.mots.get((corte, modelo))
        if nombre is None:
            return None
        dat = self.bins[nombre]
        if struct.unpack('>H', dat[:2])[0] == 0:
            return None
        return fcv.parse(dat)

    def cortes_de(self, modelo):
        return [c for c in range(len(self.cortes)) if self.motion(c, modelo) is not None]

    def piezas_de(self, modelo):
        return [(n, b, t) for n, oya, b, t in self.piezas if oya == modelo]

    def lugar(self, modelo):
        """(pos mm, rot grados) del ultimo paquete Pos sin padre para el modelo, o None (queda en el origen)."""
        r = None
        for k in self.posiciones:
            if k.nombre == modelo and not k.oya and not (k.flag & 0x40000000):
                r = (k.pos, k.rot)
        return r

    def adjuntos(self):
        """[(modelo, padre, parte)] de los Pos con flag 0x40000000 (OyaSetObj18)."""
        vistos = []
        for k in self.posiciones:
            if k.flag & 0x40000000 and (k.nombre, k.oya, k.parte) not in vistos:
                vistos.append((k.nombre, k.oya, k.parte))
        return vistos


def poses_corte(skel, motion, largo, ik=True, lugar=None):
    """Poses (evalhost, el codigo del juego) de los frames 0..largo-1 del corte; mas alla del final de la motion se
    sostiene el ultimo frame (MotionSetCore sin loop). Devuelve (poses, raiz): raiz = None si el modelo queda en el
    origen (sin claves raiz "Null" pos/rot ni paquete Pos `lugar`); si no, por frame la matriz 3x4 del modelo en el
    mundo = Pos(lugar) * (RotMatrix(rot raiz) + pos raiz), que va delante del l_mat de las partes raiz."""
    import re4_extract_leon as L
    from motion import evalhost
    player = evalhost.Player(skel, motion, ik=ik)
    ultimo = motion.n_frames - 1
    poses = [player.frame(min(f, ultimo)) for f in range(largo)]
    raiz = None
    if any(p.root_pos != (0.0, 0.0, 0.0) or p.root_rot != (0.0, 0.0, 0.0) for p in poses):
        raiz = []
        for p in poses:
            m = list(p.root_mat)
            m[3], m[7], m[11] = p.root_pos
            raiz.append(tuple(m))
    if lugar is not None:
        pos, rot = lugar
        m = list(player.rot_matrix([r * 3.1415927 / 180.0 for r in rot]))
        m[3], m[7], m[11] = (float(c) for c in pos)
        raiz = [tuple(m)] * len(poses) if raiz is None else [L.mat34_mul(tuple(m), r) for r in raiz]
    return poses, raiz


def raiz_mundo(pose, raiz_f=None):
    """Posicion en el mundo (mm) de la parte 0 en una pose."""
    lm = pose.l_mat[0]
    if raiz_f is not None:
        import re4_extract_leon as L
        lm = L.mat34_mul(raiz_f, lm)
    return (lm[3], lm[7], lm[11])


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='lista los paquetes y los cortes de un .evd')
    ap.add_argument('evd')
    ap.add_argument('--disc', default=os.path.join(HERE, '..', 'Resident Evil 4 (USA) (Disc 1)', 'Resident Evil 4 (USA) (Disc 1).rvz'))
    a = ap.parse_args()
    ev = Evento(resolver_evd(a.evd, a.disc))
    print(f'{ev.nombre}: {len(ev.cortes)} cortes, {sum(ev.cortes)} frames')
    for c, largo in enumerate(ev.cortes):
        mods = [m for (cc, m) in ev.mots if cc == c]
        print(f'  corte {c:2d}: {largo:4d} frames  {" ".join(mods)}')
    print('modelos:', ev.modelos)
    print('piezas:', ev.piezas)
    print('adjuntos:', ev.adjuntos())
