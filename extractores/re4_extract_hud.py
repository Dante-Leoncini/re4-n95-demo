#!/usr/bin/env python3
"""
HUD de juego de Resident Evil 4 (GameCube, disco USA) -> PNG + JSON para Whisk3D.

  out/combate/hud/tex_XX_fN.png      cada textura (id XX, cuadro N) que usa el HUD, tal cual esta en el disco
  out/combate/hud/digitos_0x27.png   tira de los 15 cuadros de la fuente de digitos (comodidad)
  out/combate/hud/preview_*.png      el HUD simulado (640x480 virtual) en los tres estados de vida, para verificar
  out/combate/hud.json               elementos, rectangulos, colores, blend, orden de dibujo y reglas de animacion

COMO DIBUJA EL JUEGO EL HUD (todo es "ID system", no hay codigo de dibujo a mano):
  game/cockpit.cpp   Cockpit (Cckpt): crea las tablas de "unidades ID" del nucleo (etc/core.das) y cada frame solo
                     les cambia visibilidad (be_flag 8), rotacion z, cuadro de textura y colores.
  game/id_sys.cpp    IDSystem: arbol de quads con curvas Hermite (posicion por spline, escala, color, rotacion),
                     textura animada; move() por niveles, trans() los mete en el OT 0x13 (ultimo en dibujarse).
  game/id_tex.cpp    texturas de las unidades: un TPL con N imagenes por id (el "cuadro" = imagen N del TPL, UV 0..1).
  include/global.h   ArcFile: core.das entrada 25 (ofs_74) = texturas del HUD (formato EFF v0xB),
                     27 (ofs_7C) = medidor de vida (clase 0x21), 28 (ofs_80) = boton de accion (0x20),
                     29 (ofs_84) = cuenta regresiva (0x23), 30 (ofs_88) = barras de cine (0x30),
                     34 (ofs_98) = icono de municion (0x32).

Este script NO adivina: lee las tablas del disco y re-ejecuta la logica de cockpit.cpp + id_sys.cpp (curvas,
jerarquia, multiplicacion de color por el padre, orden LIFO del OT) para una Leon con pistola, y vuelca el
resultado. Cada numero del JSON trae su fuente (archivo:funcion:linea del decomp re4/src).

Uso:  python3 re4_extract_hud.py [--disc RUTA.rvz] [--vida 1200] [--vida-max 1200] [--balas 10]
"""
import argparse
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RE4 = os.path.normpath(os.path.join(HERE, '..', 're4'))
sys.path.insert(0, os.path.join(RE4, 'tools'))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from motion import archive  # noqa: E402
import re4_eff  # noqa: E402

DEFAULT_DISC = os.path.join(HERE, '..', 'Resident Evil 4 (USA) (Disc 1)', 'Resident Evil 4 (USA) (Disc 1).rvz')
DTK = os.path.join(HERE, 'tools', 'dtk')
CORE = os.path.join(HERE, 'extracted', 'etc', 'core.das')
OUT = os.path.join(HERE, 'out', 'combate')
OUT_HUD = os.path.join(OUT, 'hud')

# entradas de core.das (indice de Archive = (ofs - 0x10) / 4; include/global.h ArcFile)
ENT_TEX = 25        # ofs_74  IdTexDataLoad(ARC_PTR(ofs_74), TEX_OWNER_ID_COCKPIT)   cockpit.cpp:35
ENT_VIDA = 27       # ofs_7C  IdSys.set(.., IDC_LIFE_METER)                           cockpit.cpp:116
ENT_BOTON = 28      # ofs_80  IdSys.set(.., IDC_ACT_BUTTON)                           cockpit.cpp:459-460
ENT_CUENTA = 29     # ofs_84  IdSys.set(.., IDC_COUNT_DOWN)                           cockpit.cpp:716
ENT_CINE = 30       # ofs_88  IdSys.set(.., IDC_CINESCO)                              cockpit.cpp:36
ENT_BALA = 34       # ofs_98  IdSys.set(.., IDC_BLLT_ICON)                            cockpit.cpp:590

IDC_ACT_BUTTON, IDC_LIFE_METER, IDC_COUNT_DOWN, IDC_CINESCO, IDC_BLLT_ICON = 0x20, 0x21, 0x23, 0x30, 0x32

# tabla de blend de IdCommonTrans (id_sys.cpp:1115-1117): GXSetBlendMode(tipo, src, dst, op)
BLEND = {
    0: dict(gx='GX_BM_BLEND, GX_BL_SRCALPHA, GX_BL_INVSRCALPHA', gl='GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA',
            nombre='alpha'),
    1: dict(gx='GX_BM_BLEND, GX_BL_SRCALPHA, GX_BL_ONE', gl='GL_SRC_ALPHA, GL_ONE', nombre='aditivo'),
    2: dict(gx='GX_BM_BLEND, GX_BL_ONE, GX_BL_ONE', gl='GL_ONE, GL_ONE', nombre='suma'),
    3: dict(gx='GX_BM_BLEND, GX_BL_DSTCLR, GX_BL_ONE', gl='GL_DST_COLOR, GL_ONE', nombre='mod2x'),
    4: dict(gx='GX_BM_BLEND, GX_BL_DSTCLR, GX_BL_ZERO', gl='GL_DST_COLOR, GL_ZERO', nombre='multiplicar'),
}

# nombres legibles por (clase, markNo) o (clase, 'no', unitNo) para las unidades sin id (markNo 0xFF)
NOMBRES = {
    (0x30, 'no', 1): 'barra_cine_inferior', (0x30, 'no', 2): 'barra_cine_superior',
    (0x21, 0x00): 'raiz_hud', (0x21, 0x01): 'grupo_ashley', (0x21, 0x02): 'aguja_vida_max_ashley',
    (0x21, 0x03): 'grupo_anillo_ashley', (0x21, 0x04): 'cuarto_ashley_1', (0x21, 0x05): 'cuarto_ashley_2',
    (0x21, 0x06): 'grupo_vacio_2f', (0x21, 0x07): 'cuarto_vida_1', (0x21, 0x08): 'cuarto_vida_2',
    (0x21, 0x09): 'cuarto_vida_3', (0x21, 0x0A): 'digito_decenas', (0x21, 0x0B): 'digito_unidades',
    (0x21, 0x17): 'digito_centenas', (0x21, 0x0C): 'plantilla_color_0c', (0x21, 0x0D): 'plantilla_color_0d',
    (0x21, 0x0E): 'plantilla_color_0e', (0x21, 0x0F): 'plantilla_PELIGRO', (0x21, 0x10): 'plantilla_PRECAUCION',
    (0x21, 0x11): 'plantilla_BIEN', (0x21, 0x12): 'grupo_color_vida', (0x21, 0x13): 'destello_precaucion',
    (0x21, 0x14): 'destello_peligro', (0x21, 0x15): 'grupo_efecto_15', (0x21, 0x16): 'plantilla_blanca_16',
    (0x21, 0x18): 'destello_precaucion_ashley', (0x21, 0x19): 'destello_peligro_ashley',
    (0x21, 0x1A): 'estado_ashley_1a', (0x21, 0x1B): 'estado_ashley_1b', (0x21, 0x1C): 'estado_ashley_1c',
    (0x21, 0x1D): 'estado_ashley_1d', (0x21, 0x1E): 'estado_ashley_1e', (0x21, 0x30): 'grupo_icono_municion',
    (0x21, 0x3F): 'cartel_EMPTY', (0x21, 0x40): 'nombre_Leon', (0x21, 0x41): 'nombre_Ashley',
    (0x21, 0x42): 'nombre_Ada', (0x21, 0x43): 'nombre_43', (0x21, 0x44): 'nombre_44', (0x21, 0x45): 'nombre_45',
    (0x21, 0xFE): 'grupo_marca_vida_max',
    (0x21, 'no', 0x07): 'grupo_marco', (0x21, 'no', 0x0F): 'marco_medidor', (0x21, 'no', 0x1A): 'brillo_medidor',
    (0x21, 'no', 0x02): 'disco_fondo', (0x21, 'no', 0x28): 'grupo_destellos', (0x21, 'no', 0x31): 'marca_vida_max',
    (0x21, 'no', 0x17): 'marca_vida_max_ashley', (0x21, 'no', 0x08): 'marco_ashley',
    (0x21, 'no', 0x30): 'brillo_ashley', (0x21, 'no', 0x36): 'grupo_estado_ashley',
    (0x21, 'no', 0x32): 'cuarto_ashley_sombra_1', (0x21, 'no', 0x33): 'cuarto_ashley_sombra_2',
    (0x21, 'no', 0x2D): 'efecto_15_a', (0x21, 'no', 0x2B): 'efecto_15_b',
    (0x32, 0x31): 'icono_municion_pistola',
}


# ---------------------------------------------------------------------------------------------------------------
#  disco / archivos
# ---------------------------------------------------------------------------------------------------------------
def asegurar_core(disc):
    """extracted/etc/core.das; si falta lo copia del disco con dtk (read.cpp CoreDataRead lee 'etc/core.das')."""
    if not os.path.isfile(CORE):
        os.makedirs(os.path.dirname(CORE), exist_ok=True)
        subprocess.check_call([DTK, 'vfs', 'cp', f'{os.path.abspath(disc)}:files/etc/core.das', CORE])
    return archive.Archive(CORE)


# ---------------------------------------------------------------------------------------------------------------
#  tablas ID (include/id_sys.h IdDataHeader / IdData2, version "2.00", registros de 0x8C bytes)
# ---------------------------------------------------------------------------------------------------------------
def curva(d, o):
    """Hermite1 {s32 num; {f32 t, v, out, in}[num]} (include/hermite.h)."""
    if not o:
        return None
    n = struct.unpack_from('>i', d, o)[0]
    return [list(struct.unpack_from('>4f', d, o + 4 + 16 * i)) for i in range(n)]


def camino(d, o0, o1):
    """FuncPathData {s8 k; pad; s8 n@7; Vec pos[n]} (include/path.h). Devuelve los puntos de control."""
    if not o0:
        return None
    n = struct.unpack_from('>b', d, o0 + 7)[0]
    return dict(k=struct.unpack_from('>b', d, o0)[0],
                puntos=[list(struct.unpack_from('>3f', d, o0 + 8 + 12 * i)) for i in range(n)])


def leer_tabla(d):
    ver = d[:5].split(b'\0')[0].decode()
    assert ver == '2.00', ver
    num = d[5]
    out = []
    for i in range(num):
        o = 8 + 0x8C * i
        r = d[o:o + 0x8C]
        ofs = struct.unpack_from('>6I', r, 0x74)
        out.append(dict(
            fila=i, flags=r[3], id=r[4], no=r[5], nivel=r[6], padre=r[7], kind=r[9], tex=r[11], ancla=r[12] & 0xF,
            loop=r[13], escala_tipo=r[14], rot_eje=r[15], dir=r[16],
            pos=list(struct.unpack_from('>3f', r, 0x14)), tam=list(struct.unpack_from('>2f', r, 0x50)),
            col0=list(r[0x58:0x5C]), col1=list(r[0x5C:0x60]), rot=list(struct.unpack_from('>3f', r, 0x60)),
            blend=r[0x6C], trans=r[0x6D], mascara=r[0x6E], tex_flag=r[0x6F], pow=r[0x70],
            camino=camino(d, ofs[0], ofs[1]), curvas=[curva(d, x) for x in ofs[2:]]))
    return out


# ---------------------------------------------------------------------------------------------------------------
#  Hermite / spline (game/hermite.cpp, game/path.cpp)
# ---------------------------------------------------------------------------------------------------------------
def hermite(keys, t):
    """Hermite_1CurveCalc (hermite.cpp:48-71) + Hermite_1 (hermite.cpp:131-143): 0 fuera de rango."""
    for k0, k1 in zip(keys, keys[1:]):
        if k0[0] <= t <= k1[0]:
            dt = k1[0] - k0[0]
            s = (t - k0[0]) / dt
            s2, s3 = s * s, s * s * s
            h01 = -(s3 + s3) + 3.0 * s2
            h11 = s3 - s2
            h10 = h11 - s2 + s
            h00 = 1.0 - h01
            return h00 * k0[1] + h01 * k1[1] + dt * (h10 * k0[2] + h11 * k1[3])
    return 0.0


def punto_camino(cam, t):
    """FuncPathCalc (path.cpp:431-456). Solo hacen falta n=1 (constante) y n=2 (orden recortado a 1 = recta,
    FuncPathParametrize path.cpp:340-341), que son los unicos casos en las tablas del HUD."""
    p = cam['puntos']
    if len(p) <= 1:
        return [0.0, 0.0, 0.0]
    if len(p) != 2:
        raise NotImplementedError('camino B-spline de %d puntos' % len(p))
    return [a + (b - a) * t for a, b in zip(p[0], p[1])]


# ---------------------------------------------------------------------------------------------------------------
#  IDSystem (game/id_sys.cpp) re-implementado en 2D
# ---------------------------------------------------------------------------------------------------------------
class Unidad:
    def __init__(self, rec, clase):
        self.rec = rec
        self.clase = clase
        self.be_flag = rec['flags'] | 0xD            # set(): be_flag = flags; |= 0xD (id_sys.cpp:347,419)
        self.mark = rec['id']
        self.no = rec['no']
        self.kind = rec['kind']
        self.tex = rec['tex']
        self.tex_no = 0
        self.tex_ptn = 0
        self.tex_flag = rec['tex_flag']
        self.loop = rec['loop']
        self.rev = rec['dir']
        self.pos0 = list(rec['pos'])
        self.tam = list(rec['tam'])
        self.col0 = list(rec['col0'])
        self.col1 = list(rec['col1'])
        self.rot0 = list(rec['rot'])
        self.curvas = list(rec['curvas'])
        self.timer = [0, 0, 0, 0]
        self.padre = None
        self.nivel = rec['nivel']
        self.col = [0.0] * 4
        self.mat = np.eye(3)
        self.ver = None

    @property
    def nombre(self):
        k = NOMBRES.get((self.clase, self.mark)) if self.mark != 0xFF else None
        return k or NOMBRES.get((self.clase, 'no', self.no)) or 'c%02X_id%02X_no%02X' % (self.clase, self.mark, self.no)

    # --- timers: cuerpo comun de idSysMove00..03 (id_sys.cpp:659-680, 783-804, 865-886, 914-935)
    def _paso(self, n):
        keys = self.curvas[n]
        v = hermite(keys, float(self.timer[n]))
        fin = keys[-1][0]
        bit = 1 << n
        if not (self.rev & bit):
            self.timer[n] += 1
            if self.timer[n] >= fin:
                self.timer[n] = 0 if (self.loop & bit) else int(fin)
        else:
            self.timer[n] -= 1
            if self.timer[n] <= 0:
                self.timer[n] = int(fin) if (self.loop & bit) else 0
        return v

    def mover(self, texturas):
        r = self.rec
        # idSysMove00: posicion = pos0 + (camino(t) - camino(0))  (id_sys.cpp:649-699)
        pos = [0.0, 0.0, 0.0]
        if r['camino'] and len(r['camino']['puntos']) > 0:
            t = self._paso(0) if self.curvas[0] else 0.0
            a, b = punto_camino(r['camino'], t), punto_camino(r['camino'], 0.0)
            pos = [x - y for x, y in zip(a, b)]
        self.pos = [p + q for p, q in zip(pos, self.pos0)]
        if self.kind != 1:
            self.ver = vertices(self.rec['ancla'], self.tam[0], self.tam[1])
        # idSysMove01: escala por curva 1 (id_sys.cpp:772-818)
        if self.curvas[1]:
            s = self._paso(1)
            if self.ver is not None:
                if self.rec['escala_tipo'] & 0x10:
                    self.ver[:, 0] *= s
                elif self.rec['escala_tipo'] & 0x20:
                    self.ver[:, 1] *= s
                else:
                    self.ver *= s
        # idSysMove02: color (id_sys.cpp:822-900)
        if self.curvas[2]:
            rr = self._paso(2)
            if any(self.col1):
                self.col = [min(255.0, max(0.0, (1 - rr) * a + rr * b)) for a, b in zip(self.col0, self.col1)]
            else:
                self.col = [float(self.col0[0]), float(self.col0[1]), float(self.col0[2]), rr]
        else:
            self.col = [float(c) for c in self.col0]
        if self.padre is not None:
            self.col = [float(int(c * p / 255.0) & 0xFF) for c, p in zip(self.col, self.padre.col)]
        # idSysMove03: rotacion (grados) + traslacion; hijo de grupo concatena la matriz del padre (id_sys.cpp:904-958)
        rot = list(self.rot0)
        if self.curvas[3]:
            a = self._paso(3)
            rot[self.rec['rot_eje']] = a
        self.rot = rot
        z = math.radians(rot[2])
        c, s = math.cos(z), math.sin(z)
        lm = np.array([[c, -s, self.pos[0]], [s, c, self.pos[1]], [0, 0, 1.0]])
        if self.padre is not None and self.padre.kind == 1:
            self.mat = self.padre.mat @ lm
        else:
            self.mat = lm
        # idSysMove04: animacion de textura (id_sys.cpp:962-997)
        if self.tex != 0xFF:
            if self.tex not in texturas:
                self.be_flag &= ~8
            elif not (self.tex_flag & 2):
                self.tex_no = self.tex_ptn
                self.tex_ptn = (self.tex_ptn + 1) % texturas[self.tex]['anm']['Frames']


def vertices(ancla, w, h):
    """IdCalcVertex (id_sys.cpp:703-769): v0 arriba-izq, v1 arriba-der, v2 abajo-der, v3 abajo-izq (y hacia arriba)."""
    if ancla == 0:
        v = [(-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2), (-w / 2, -h / 2)]
    elif ancla == 1:
        v = [(0, 0), (w, 0), (w, -h), (0, -h)]
    elif ancla == 2:
        v = [(-w, 0), (0, 0), (0, -h), (-w, -h)]
    elif ancla == 3:
        v = [(-w, h), (0, h), (0, 0), (-w, 0)]
    else:
        v = [(0, h), (w, h), (w, 0), (0, 0)]
    return np.array(v, dtype=float)


class IdSys:
    """Pool de unidades en orden de creacion (unitPull toma el primer hueco libre, id_sys.cpp:125-143)."""

    def __init__(self, texturas):
        self.pool = []
        self.texturas = texturas

    def set(self, tabla, ident, clase, modo=0, nuevos=None):
        """IDSystem::set v2 (id_sys.cpp:341-462): ident 0xFF = todas; si no, la unidad con ese id y (recursivo,
        modo 1) las que tienen ese padre. El padre se busca entre las creadas en esta misma llamada."""
        raiz = nuevos is None
        if raiz:
            nuevos = []
        for rec in tabla:
            clave = rec['padre'] if modo == 1 else rec['id']
            if ident == 0xFF or clave == ident:
                u = Unidad(rec, clase)
                if rec['padre'] != 0xFF:
                    for c in self.vivas():
                        if c in nuevos and c.no == rec['padre']:
                            u.padre = c
                            break
                if None in self.pool:                       # primer hueco libre (unitPull)
                    self.pool[self.pool.index(None)] = u
                else:
                    self.pool.append(u)
                nuevos.append(u)
                if ident != 0xFF:
                    self.set(tabla, rec['no'], clase, 1, nuevos)
        return nuevos

    def vivas(self):
        return [u for u in self.pool if u is not None]

    def kill(self, clase, ident=0xFF):
        """IDSystem::kill (id_sys.cpp:467-487): libera el hueco (be_flag 0xFF) sin compactar el pool."""
        for i, u in enumerate(self.pool):
            if u is not None and u.clase == clase and (ident == 0xFF or u.mark == ident):
                self.pool[i] = None
        for u in self.vivas():
            if u.padre is not None and u.padre not in self.pool:
                u.padre = None

    def ptr(self, ident, clase):
        for u in self.vivas():
            if u.mark == ident and u.clase == clase:
                return u
        raise KeyError('unidad %02X clase %02X' % (ident, clase))

    def mover(self):
        """IDSystem::move (id_sys.cpp:528-559): por nivel de arbol, cada unidad con be_flag 4."""
        vivas = self.vivas()
        for u in vivas:
            u.nivel = 0 if u.padre is None else None
        cambio = True
        while cambio:
            cambio = False
            for u in vivas:
                if u.nivel is None and u.padre.nivel is not None:
                    u.nivel = u.padre.nivel + 1
                    cambio = True
        for lv in range(max(u.nivel for u in vivas) + 1):
            for u in vivas:
                if u.nivel == lv and (u.be_flag & 4):
                    u.mover(self.texturas)

    def orden_dibujo(self):
        """IDSystem::trans + unitTrans (id_sys.cpp:1001-1063) meten los hijos antes que el padre en el mismo balde
        (OT 0x13, prioridad 5); AddOtDirect inserta al frente (trans_ot.cpp:268-273) y ExecOt recorre la lista
        (trans_ot.cpp:287-296): se dibuja en orden INVERSO al de insercion."""
        ins = []

        def trans(u):
            for c in self.vivas():
                if (c.be_flag & 8) and u.kind == 1 and c.padre is u:
                    trans(c)
            ins.append(u)
        for u in self.vivas():
            if (u.be_flag & 8) and u.padre is None:
                trans(u)
        return [u for u in reversed(ins) if u.tex != 0xFF]


# ---------------------------------------------------------------------------------------------------------------
#  logica de cockpit.cpp para Leon (pl_type 0), sin Ashley, arma = pistola (weapon_no 1)
# ---------------------------------------------------------------------------------------------------------------
class Cockpit:
    A_RATIO = 0.9                                          # cockpit.cpp:97

    def __init__(self, ids, tablas, vida, vida_max, balas, boton=0):
        self.ids, self.tab = ids, tablas
        self.vida, self.vida_max, self.balas, self.boton = vida, vida_max, balas, boton
        # Cockpit::roomInit (cockpit.cpp:31-42), en el mismo orden (define el orden del pool = orden de dibujo)
        ids.set(tablas['cine'], 0xFF, IDC_CINESCO)
        ids.set(tablas['boton'], 1, IDC_ACT_BUTTON)
        ids.set(tablas['boton'], 0xF0, IDC_ACT_BUTTON)
        # LifeMeter::roomInit (cockpit.cpp:112-163)
        ids.set(tablas['vida'], 0xFF, IDC_LIFE_METER)
        for m in (0x40, 0x41, 0x42):
            ids.ptr(m, IDC_LIFE_METER).be_flag &= ~8
        ids.ptr(0x40, IDC_LIFE_METER).be_flag |= 8        # pl_type 0 = Leon
        # SUPUESTO: los nombres de Mercenarios (43 Krauser, 44 Wesker, 45 HUNK) no los toca ningun codigo del
        # decomp y quedarian encima de "Leon"; en el juego real no se ven, asi que se ocultan aca.
        for m in (0x43, 0x44, 0x45):
            ids.ptr(m, IDC_LIFE_METER).be_flag &= ~8
        raiz = ids.ptr(0, IDC_LIFE_METER)                  # disp(1): rev_flag |= 0xF (cockpit.cpp:425-427)
        raiz.rev |= 0xF
        raiz.be_flag |= 8
        self.m_life = float(vida)
        self.plantillas = [ids.ptr(m, IDC_LIFE_METER) for m in (0x11, 0x10, 0x0F)]   # bien / precaucion / peligro
        self.color0 = [0.0] * 4                            # m_color0/1: objeto global, arranca en 0
        self.color1 = [0.0] * 4
        self.mark_old = -1                                 # BulletInfo::roomInit (cockpit.cpp:531-534)
        # CountDown::roomInit (cockpit.cpp:714-723): se crea y se oculta
        ids.set(tablas['cuenta'], 0xFF, IDC_COUNT_DOWN)
        ids.ptr(0x10, IDC_COUNT_DOWN).be_flag &= ~8
        self.boton_old = 0

    @staticmethod
    def nivel_vida(vida):
        """cPlayer::getLifeLevel (pl_class.cpp:1029-1067): tope FIJO 1200 para Leon, no pl_life_max."""
        if vida > 1200 * 2 // 3:
            return 0
        return 1 if vida > 1200 // 3 else 2

    def mover(self):
        ids = self.ids
        U = lambda m: ids.ptr(m, IDC_LIFE_METER)  # noqa: E731
        # LifeMeter::move (cockpit.cpp:172-398)
        U(1).be_flag &= ~8                                 # sin Ashley (cockpit.cpp:194-199)
        U(3).be_flag &= ~8
        nivel = int(20 * (self.vida_max - 1200) / 1200.0 + 0.5)       # lifeLevel (item.cpp:218-221)
        U(0xFE).rot0[2] = nivel * -135.0 / 20.0 - 45.0                # cockpit.cpp:202-203
        self.m_life = self.A_RATIO * self.m_life + (1 - self.A_RATIO) * self.vida      # cockpit.cpp:207
        u7, u8, u9 = U(7), U(8), U(9)
        for u in (u7, u8, u9):
            u.be_flag &= ~8
        rate = self.m_life / 400.0                                    # cockpit.cpp:216-232
        if rate > 4:
            for u in (u7, u8, u9):
                u.be_flag |= 8
            u7.rot0[2], u8.rot0[2], u9.rot0[2] = 90.0, 0.0, 0.0 - (rate - 4) * 45.0
        elif rate > 2:
            u7.be_flag |= 8
            u8.be_flag |= 8
            u7.rot0[2], u8.rot0[2] = 90.0, 90.0 - (rate - 2) * 45.0
        elif rate >= 0:
            u7.be_flag |= 8
            u7.rot0[2] = 180.0 - rate * 45.0
        lv = self.nivel_vida(self.vida)
        src = self.plantillas[lv]
        for i in range(4):                                            # cockpit.cpp:269-272
            self.color0[i] = self.A_RATIO * self.color0[i] + (1 - self.A_RATIO) * src.col0[i]
            self.color1[i] = self.A_RATIO * self.color1[i] + (1 - self.A_RATIO) * src.col1[i]
        p = U(0x12)                                                   # cockpit.cpp:306-319
        p.col0 = [int(self.color0[0]), int(self.color0[1]), int(self.color0[2]), 255]
        p.col1 = [int(self.color1[0]), int(self.color1[1]), int(self.color1[2]), 255]
        p.curvas[2] = src.curvas[2]
        p.loop |= 4
        u13, u14 = U(0x13), U(0x14)                                   # cockpit.cpp:343-358
        u13.be_flag = (u13.be_flag | 8) if lv == 1 else (u13.be_flag & ~8)
        u14.be_flag = (u14.be_flag | 8) if lv == 2 else (u14.be_flag & ~8)
        # BulletInfo::move (cockpit.cpp:539-616), pistola: dispBulletDigit = 1, icono 0x31
        num = self.balas
        dig = [num % 10, num // 10 % 10, num // 100 % 10]
        vacio = U(0x3F)
        vacio.be_flag &= ~8
        uds = [U(0x0B), U(0x0A), U(0x17)]
        for u, d in zip(uds, dig):
            u.tex_flag |= 2
            u.tex_no = d
        mark = 0x31
        if self.mark_old != mark:
            ids.kill(IDC_BLLT_ICON)
            nuevos = ids.set(self.tab['bala'], mark, IDC_BLLT_ICON)
            nuevos[0].padre = U(0x30)                                 # unitParent (cockpit.cpp:591-592)
        self.mark_old = mark
        sin_reserva = False                   # noBullet: ItemMgr.search(balas) == 0 (cockpit.cpp:553-564)
        for u in uds:
            if num == 0 and sin_reserva:
                u.be_flag &= ~8
            else:
                u.be_flag |= 8
        if num == 0 and sin_reserva:
            vacio.be_flag |= 8
        if dig[2] == 0:
            uds[2].be_flag &= ~8
        # ActionButton::move (cockpit.cpp:467-527)
        if self.boton != self.boton_old:
            ident = {6: 9, 2: 2, 3: 3, 4: 4, 0xC: 5, 0xB: 6, 5: 7, 9: 0xA, 0xA: 0xB, 0xD: 0xC, 0xE: 8, 0xF: 0xD,
                     0x10: 0xE, 1: 0}.get(self.boton, 0)
            ids.kill(IDC_ACT_BUTTON)
            ids.set(self.tab['boton'], 1, IDC_ACT_BUTTON)
            ids.set(self.tab['boton'], 0xF0, IDC_ACT_BUTTON)
            if self.boton:
                ids.set(self.tab['boton'], ident, IDC_ACT_BUTTON)
        self.boton_old = self.boton


# ---------------------------------------------------------------------------------------------------------------
#  texturas
# ---------------------------------------------------------------------------------------------------------------
def imagen(tex, n):
    fr = tex['frames'][n]
    img = re4_eff.decode_tex(fr['fmt'], fr['w'], fr['h'], fr['data'], fr['pal'])
    return np.array(img, dtype=np.uint8).reshape(fr['h'], fr['w'], 4)


def guardar_png(arr, path):
    Image.fromarray(arr, 'RGBA').save(path)


# ---------------------------------------------------------------------------------------------------------------
#  render de verificacion (reproduce IdCommonTrans id_sys.cpp:1113-1183 en software)
# ---------------------------------------------------------------------------------------------------------------
def a_pantalla(mat, v):
    """unidad -> pixel de la pantalla virtual 640x480 (origen arriba-izq). m_scrn_mat pone el plano a
    dist = 240/tan(fovy/2) (id_sys.cpp:536-542) y la proyeccion es perspectiva 4:3 (camera.cpp:104): x = 320 + X,
    y = 240 - Y, sin importar el fovy."""
    p = mat @ np.array([v[0], v[1], 1.0])
    return 320.0 + p[0], 240.0 - p[1]


def render(dibujo, cache, escala=2, fondo=(70, 80, 95)):
    W, H = 640 * escala, 480 * escala
    dst = np.zeros((H, W, 3), dtype=np.float32)
    dst[:] = np.array(fondo, dtype=np.float32) / 255.0
    for u in dibujo:
        tex = cache(u.tex, u.tex_no)
        esq = np.array([a_pantalla(u.mat, v) for v in u.ver]) * escala
        o, ex, ey = esq[0], esq[1] - esq[0], esq[3] - esq[0]
        x0, y0 = np.floor(esq.min(0)).astype(int)
        x1, y1 = np.ceil(esq.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if x1 <= x0 or y1 <= y0:
            continue
        ys, xs = np.mgrid[y0:y1, x0:x1] + 0.5
        M = np.array([[ex[0], ey[0]], [ex[1], ey[1]]])
        inv = np.linalg.inv(M)
        du = inv[0, 0] * (xs - o[0]) + inv[0, 1] * (ys - o[1])
        dv = inv[1, 0] * (xs - o[0]) + inv[1, 1] * (ys - o[1])
        dentro = (du >= 0) & (du < 1) & (dv >= 0) & (dv < 1)
        th, tw = tex.shape[:2]
        tx = np.clip((du * tw).astype(int), 0, tw - 1)
        ty = np.clip((dv * th).astype(int), 0, th - 1)
        t = tex[ty, tx].astype(np.float32) / 255.0
        col = np.array(u.col, dtype=np.float32) / 255.0
        rgb = t[..., :3] * col[:3]                                   # GXSetTevOp MODULATE (id_tex.cpp:105)
        if u.tex_flag & 1:                                           # mascara: alpha = mask.a * ras.a (1132-1160)
            m = cache(u.rec['mascara'], 0)
            mh, mw = m.shape[:2]
            ma = m[np.clip((dv * mh).astype(int), 0, mh - 1), np.clip((du * mw).astype(int), 0, mw - 1), 3] / 255.0
            a = ma * col[3]
        else:
            a = t[..., 3] * col[3]
        ok = dentro & (a * 255.0 > 1.0)                              # GXSetAlphaCompare(GREATER, 1) (1130)
        region = dst[y0:y1, x0:x1]
        a3 = a[..., None]
        b = u.rec['blend']
        if b == 0:
            nuevo = rgb * a3 + region * (1 - a3)
        elif b == 1:
            nuevo = region + rgb * a3
        elif b == 2:
            nuevo = region + rgb
        elif b == 3:
            nuevo = region * rgb + region
        else:
            nuevo = region * rgb
        region[ok] = np.clip(nuevo, 0, 1)[ok]
    return Image.fromarray((dst * 255).astype(np.uint8), 'RGB')


# ---------------------------------------------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=DEFAULT_DISC)
    ap.add_argument('--vida', type=int, default=1200)
    ap.add_argument('--vida-max', type=int, default=1200)
    ap.add_argument('--balas', type=int, default=10)
    args = ap.parse_args()

    core = asegurar_core(args.disc)
    eff = re4_eff.Eff(core.entry(ENT_TEX).data, 'core#25')
    tablas = dict(vida=leer_tabla(core.entry(ENT_VIDA).data), boton=leer_tabla(core.entry(ENT_BOTON).data),
                  cuenta=leer_tabla(core.entry(ENT_CUENTA).data), cine=leer_tabla(core.entry(ENT_CINE).data),
                  bala=leer_tabla(core.entry(ENT_BALA).data))
    os.makedirs(OUT_HUD, exist_ok=True)

    imgs = {}

    def cache(tid, n):
        if (tid, n) not in imgs:
            imgs[(tid, n)] = imagen(eff.tex[tid], n)
        return imgs[(tid, n)]

    # --- simulacion: 3 estados de vida (cada uno arranca de cero como un roomInit)
    def simular(vida, frames, boton=0):
        ids = IdSys(eff.tex)
        ck = Cockpit(ids, tablas, vida, args.vida_max, args.balas, boton)
        ck.mover()                                  # roomInit llama move() una vez (cockpit.cpp:162)
        cuadros = []
        for f in range(frames):
            ck.mover()                              # Cckpt.move (game.cpp:719) antes de IdSys.move (main.cpp:174)
            ids.mover()
            cuadros.append([(u, dict(col=list(u.col), mat=u.mat.copy(), ver=None if u.ver is None else u.ver.copy(),
                                     tex_no=u.tex_no)) for u in ids.orden_dibujo()])
        return ids, ck, cuadros

    class Foto:
        def __init__(self, u, st):
            self.__dict__.update(u.__dict__)
            self.col, self.mat, self.ver, self.tex_no = st['col'], st['mat'], st['ver'], st['tex_no']

    estados = [('bien', max(args.vida, 801)), ('precaucion', 600), ('peligro', 300)]
    previews = []
    sims = {}
    for nombre, vida in estados:
        ids, ck, cuadros = simular(vida, 180)
        sims[nombre] = (ids, ck, cuadros)
        # cuadro del latido mas brillante (maximo verde/rojo del grupo 0x12) en el ultimo ciclo
        g = ids.ptr(0x12, IDC_LIFE_METER)
        periodo = int(math.ceil(g.curvas[2][-1][0]))
        mejor = max(range(len(cuadros) - periodo, len(cuadros)),
                    key=lambda f: sum(dict((u.mark, st) for u, st in cuadros[f] if u.clase == 0x21)
                                      .get(7, {'col': [0] * 4})['col'][:3]))
        dib = [Foto(u, st) for u, st in cuadros[mejor]]
        img = render(dib, cache)
        img.save(os.path.join(OUT_HUD, 'preview_%s.png' % nombre))
        previews.append(img.crop((380 * 2, 280 * 2, 640 * 2, 480 * 2)))
    # tira de detalle (esquina inferior derecha, x2) de los tres estados
    tira = Image.new('RGB', (sum(p.width for p in previews), previews[0].height))
    x = 0
    for p in previews:
        tira.paste(p, (x, 0))
        x += p.width
    tira.save(os.path.join(OUT_HUD, 'preview_estados_detalle.png'))
    # prompt de accion 'A' (DISP_A_NORMAL = 1 -> id 0), opcional
    ids_a, _, cuadros_a = simular(1200, 40, boton=1)
    render([Foto(u, st) for u, st in cuadros_a[-1]], cache).save(os.path.join(OUT_HUD, 'preview_boton_A.png'))

    # --- texturas usadas por lo que se dibuja (y sus mascaras) + fuente de digitos completa
    usadas = set()
    for ids, _, _ in list(sims.values()) + [(ids_a, None, None)]:
        for u in ids.vivas():
            if u.tex != 0xFF and u.tex in eff.tex:
                usadas.add(u.tex)
            if u.tex_flag & 1:
                usadas.add(u.rec['mascara'])
    archivos_tex = {}
    for tid in sorted(usadas):
        t = eff.tex[tid]
        fr = []
        for n in range(len(t['frames'])):
            nombre = 'tex_%02X_f%d.png' % (tid, n)
            guardar_png(cache(tid, n), os.path.join(OUT_HUD, nombre))
            fr.append('hud/' + nombre)
        f0 = t['frames'][0]
        archivos_tex['%02X' % tid] = dict(archivos=fr, ancho=f0['w'], alto=f0['h'],
                                          formato=re4_eff.TF_NAMES[f0['fmt']], cuadros=len(fr))
    dig = np.concatenate([cache(0x27, n) for n in range(len(eff.tex[0x27]['frames']))], axis=1)
    guardar_png(dig, os.path.join(OUT_HUD, 'digitos_0x27.png'))

    # --- elementos (estado nominal = 'bien', cuadro en el pico del latido)
    ids, ck, cuadros = sims['bien']
    g = ids.ptr(0x12, IDC_LIFE_METER)

    def elemento(orden, u, st):
        tw, th = eff.tex[u.tex]['frames'][u.tex_no if u.tex_no < len(eff.tex[u.tex]['frames']) else 0]['w'], \
            eff.tex[u.tex]['frames'][0]['h']
        esq = [list(map(lambda v: round(v, 2), a_pantalla(st['mat'], v))) for v in st['ver']]
        xs, ys = [p[0] for p in esq], [p[1] for p in esq]
        ang = math.degrees(math.atan2(st['mat'][1, 0], st['mat'][0, 0]))
        cadena = []
        p = u.padre
        while p is not None:
            cadena.append(p.nombre)
            p = p.padre
        return dict(
            orden=orden, nombre=u.nombre, clase='%02X' % u.clase, id='%02X' % u.mark, no='%02X' % u.no,
            padres=cadena, textura='%02X' % u.tex, archivo='hud/tex_%02X_f%d.png' % (u.tex, st['tex_no']),
            cuadro=st['tex_no'],
            uv_px=[0, 0, tw, th], uv_norm=[0.0, 0.0, 1.0, 1.0],
            mascara=('hud/tex_%02X_f0.png' % u.rec['mascara']) if u.tex_flag & 1 else None,
            pantalla_esquinas_v0v1v2v3=esq,
            pantalla_rect_xywh=[round(min(xs), 2), round(min(ys), 2), round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)],
            centro_pivote=[round(320 + st['mat'][0, 2], 2), round(240 - st['mat'][1, 2], 2)],
            tamano=[u.tam[0], u.tam[1]], ancla=u.rec['ancla'], rotacion_z_grados=round(ang, 3),
            color_rgba=[int(c) for c in st['col']], color_propio_col0=u.col0, color_propio_col1=u.col1,
            blend=u.rec['blend'], blend_gx=BLEND[u.rec['blend']]['gx'], blend_gl=BLEND[u.rec['blend']]['gl'],
            visible=st['col'][3] > 1.0,
            curvas={k: v for k, v in zip(('camino_t', 'escala', 'color', 'rotacion'), u.curvas) if v},
            loop_bits=u.loop)

    def en_pantalla(e):
        x, y, w, h = e['pantalla_rect_xywh']
        return x < 640 and y < 480 and x + w > 0 and y + h > 0

    def lista(cs, canal):
        pk = max(range(len(cs) - 60, len(cs)),
                 key=lambda f: dict((uu.mark, st) for uu, st in cs[f] if uu.clase == 0x21)[7]['col'][canal])
        return pk, [elemento(i, u, st) for i, (u, st) in enumerate(cs[pk])]

    pico, todos = lista(cuadros, 1)
    elementos = [e for e in todos if en_pantalla(e)]
    fuera = [dict(nombre=e['nombre'], rect=e['pantalla_rect_xywh'], color_rgba=e['color_rgba']) for e in todos
             if not en_pantalla(e)]
    nombres_bien = {e['nombre'] for e in elementos}
    por_estado = {}
    for est, canal in (('precaucion', 0), ('peligro', 0)):
        _, ls = lista(sims[est][2], canal)
        por_estado[est] = [e for e in ls if en_pantalla(e) and e['nombre'] not in nombres_bien]
    _, ls = lista(cuadros_a, 1)
    boton_a = [e for e in ls if e['clase'] == '20']

    def unidades(tabla, clase):
        return [dict(r, nombre=(NOMBRES.get((clase, r['id'])) if r['id'] != 0xFF else None)
                     or NOMBRES.get((clase, 'no', r['no'])) or '') for r in tabla]

    plantillas = {}
    for nombre, m in (('bien', 0x11), ('precaucion', 0x10), ('peligro', 0x0F)):
        t = ids.ptr(m, IDC_LIFE_METER)
        k = t.curvas[2]
        plantillas[nombre] = dict(col0=t.col0, col1=t.col1, curva_pulso=k, periodo_frames=int(math.ceil(k[-1][0])),
                                  periodo_seg=round(math.ceil(k[-1][0]) / 30.0, 3))

    doc = dict(
        fuente='Resident Evil 4 (USA) GameCube, files/etc/core.das (entradas 25/27/28/29/30/34), decomp re4/src',
        pantalla=dict(
            virtual='640x480, origen del HUD en el CENTRO con y hacia ARRIBA (pos de las unidades); los '
                    'rectangulos de este JSON ya estan convertidos a pixeles con origen arriba-izquierda (x=320+X, '
                    'y=240-Y)',
            proyeccion='perspectiva de la camara (C_MTXPerspective fovy, aspecto 4/3; camera.cpp:104) con el plano '
                       'del HUD en z = -240/tan(fovy/2) (IDSystem::move id_sys.cpp:536-542): equivale EXACTAMENTE a '
                       'una ortho 640x480 porque todas las unidades tienen z=0 y solo rotan en z',
            ot='OT 0x13, prioridad 5, ejecutado despues de toda la escena y con el scissor apagado (trans.cpp:968); '
               'sin z (GXSetZMode(0) id_tex.cpp:103), sin niebla (id_sys.cpp:1075), cull off (1119)',
            tev='color = textura.rgb * col.rgb/255, alpha = textura.a * col.a/255 (GXSetTevOp MODULATE + color '
                'material, id_tex.cpp:105/120-130); con mascara (tex_flag 1): alpha = mascara.a * col.a y se ignora '
                'el alpha de la textura base (id_sys.cpp:1132-1160, TevAlphaIn(1, ZERO, TEXA, RASA, ZERO))',
            alpha_test='pasa si alpha > 1/255 (GXSetAlphaCompare(GREATER,1,OR,GREATER,1) id_sys.cpp:1130)',
            blend={str(k): v for k, v in BLEND.items()},
            color_heredado='col_final = floor(col_propio * col_padre / 255) por canal, recursivo (id_sys.cpp:893-899)',
            fps='la logica y los timers de las curvas avanzan 1 por frame de juego (30 fps)'),
        estado_simulado=dict(personaje='Leon (pl_type 0)', vida=args.vida, vida_max=args.vida_max,
                             balas_cargadas=args.balas, arma='pistola (weapon_no 1, item 0x21; item.cpp:117)',
                             ashley=False, cuadro_elegido='pico del latido (frame %d de 180)' % pico),
        texturas=archivos_tex,
        elementos_en_orden_de_dibujo=elementos,
        elementos_extra_por_estado=dict(
            nota='se dibujan ademas de los de arriba solo en ese estado; su "orden" es el del cuadro completo de ese '
                 'estado (misma numeracion que la lista principal +/- los elementos que cambian); valores en el pico '
                 'del latido',
            **por_estado),
        boton_accion_A=boton_a,
        dibujadas_fuera_de_pantalla=dict(
            nota='unidades que el juego SI dibuja pero fuera de los 640x480 (y=-280 o +260 en coordenadas del HUD): '
                 'son plantillas de color que cockpit.cpp lee (unidades 0F/10/11) o de la cuenta regresiva; no '
                 'hace falta dibujarlas', lista=fuera),
        medidor_vida=dict(
            descripcion='NO es un electrocardiograma: es un anillo circular (marco 0x1d) cuyo relleno son hasta 3 '
                        '"cuartos de anillo" (tex 0x20, ancla 2 = pivote en su esquina arriba-derecha = centro del '
                        'anillo) que giran; el color del relleno late (pulso tipo corazon) con un periodo que depende '
                        'del estado Bien/Precaucion/Peligro',
            vida_suavizada='m_life = 0.9*m_life + 0.1*pl_life cada frame (cockpit.cpp:97,207)',
            cuartos='rate = m_life/400 (cockpit.cpp:216). rate<=2: solo cuarto_vida_1 (id 07) visible, rot = 180 - '
                    'rate*45. 2<rate<=4: 07 a 90 y cuarto_vida_2 (id 08) rot = 90 - (rate-2)*45. rate>4: 07=90, '
                    '08=0, cuarto_vida_3 (id 09) rot = -(rate-4)*45 (cockpit.cpp:217-232). Es decir 45 grados cada '
                    '400 PV; el borde visible del relleno barre sentido horario.',
            marca_vida_max='grupo 0xFE rot = nivel*(-135)/20 - 45, nivel = lifeLevel(20, pl_life_max, 1200) = '
                           'round(20*(max-1200)/1200) (cockpit.cpp:200-203, item.cpp:218-221): gira la rayita '
                           '"marca_vida_max" (2x10 px) hasta donde llega la vida maxima',
            estado='cPlayer::getLifeLevel (pl_class.cpp:1058-1066): BIEN si pl_life > 800, PRECAUCION si > 400, '
                   'PELIGRO si <= 400 (tope fijo 1200 para Leon, NO usa pl_life_max)',
            color='el grupo 0x12 (padre de los 3 cuartos) toma col0/col1 = color de la plantilla del estado suavizado '
                  '0.9/0.1 por frame, y la curva 2 de la plantilla con loop (cockpit.cpp:249-272, 306-319); '
                  'IdSysMove02 hace col = lerp(col0, col1, curva(t)) (id_sys.cpp:828-857) y los cuartos (blancos) '
                  'lo heredan multiplicando',
            plantillas=plantillas,
            destellos='PRECAUCION: destello_precaucion (id 13) visible; PELIGRO: destello_peligro (id 14) visible '
                      '(cockpit.cpp:343-358). Son quads blancos con mascara 0x17 (circulo), blend aditivo y solo el '
                      'alpha animado (col1 = 0 -> col.a = curva) : precaucion alpha 0->255->0 en 18.5 frames '
                      '(periodo 19), peligro 0->255->0 en 5.05 frames (periodo 6)',
            aparicion='raiz_hud: camino recto (217,-130)->(392,-130) = +175 px a la derecha, curva 0..1 en 8 frames '
                      'con tangentes 0 (ease in/out). Visible: timer baja a 0 = en su sitio (LifeMeter::disp(1) y '
                      'frameIn: rev_flag |= 0xF). frameOut: sale deslizando 8 frames; disp(0): se oculta de golpe '
                      '(cockpit.cpp:419-453)'),
        municion=dict(
            que_muestra='SOLO las balas cargadas en el arma (cItemMgr::bulletNum -> bulletNumCurrent, '
                        'item.cpp:2757-2769). La version GameCube NO muestra la reserva',
            digitos='tex 0x27 (16x24 CI8, 15 cuadros; cuadro = digito 0..9) en quads de 16x20, color propio '
                    '(105,205,205); unidades id 0B / decenas id 0A / centenas id 17 en x = +11 / -2 / -15 respecto de '
                    'la raiz (paso 13 px, centrados, y = -12) (cockpit.cpp:565-579)',
            ceros='solo se oculta la CENTENA cuando es 0; la decena se ve siempre (7 balas -> "07") '
                  '(cockpit.cpp:613-615)',
            vacio='sin balas cargadas y sin cajas de esa municion en el maletin: se ocultan los digitos y se muestra '
                  'cartel_EMPTY (id 3F, tex 0x17) (cockpit.cpp:553-564, 597-607)',
            icono='icono de la municion del arma (clase 0x32 id 31 = balas de pistola, tex 0x29) colgado del '
                  'grupo 0x30 (cockpit.cpp:581-595, 661-710)',
            cuando='siempre que el HUD este visible y el arma tenga contador (dispBulletDigit, cockpit.cpp:620-657); '
                   'NO depende de apuntar'),
        visibilidad=dict(
            hud='siempre en juego normal (Cckpt.move cockpit.cpp:46-59, IdSys.trans id_sys.cpp:1001-1027); lo apagan '
                'eventos/menus: IdSys.dispSw(IDC_LIFE_METER,0) en sub-pantalla, cinematicas (sce_com.cpp:143-144), '
                'opciones, mapa, etc. y DPF_ID_SYSTEM / DPF_COCKPIT',
            barras_cine='la clase 0x30 (2 quads negros 640x60 arriba y abajo, tex 0x0a) se crea en Cockpit::roomInit '
                        '(cockpit.cpp:36) y queda visible: el juego de GameCube es letterbox tambien en gameplay; el '
                        'medidor queda justo encima de la barra inferior (y 420..480)'),
        mira=dict(
            hay_reticula_2d=False,
            detalle='con pistola no hay mira en el HUD: el apuntado es la mira laser 3D. cObjWep::drawLaserSight '
                    '(objWep.cpp:226-306): linea EspDrawLaserLine = efecto est 3 del EFF del nucleo (esp_app.cpp:464-490) '
                    'y el punto drawPoint = est 0x50 (objWep.cpp:310-322), escalado con la distancia a la camara. Solo '
                    'las miras telescopicas usan la clase ID 0x25 IDC_SCOPE (cam_extra.cpp).'),
        otros=dict(
            boton_accion='clase 0x20 (core entrada 28): al acercarse a algo, ActBtn fija m_disp_flag y '
                         'ActionButton::move crea el grupo del boton (A normal = id 0: tex 0x28 boton A verde + halo '
                         '0xf2) (cockpit.cpp:467-527); el texto ("OPEN", "TALK"...) va aparte con la fuente de mensajes '
                         '(act_btn.cpp:100-145). Ver preview_boton_A.png',
            ashley='con Ashley: segundo medidor (grupo_ashley id 01 / anillo id 03, cuartos id 04/05, 30 grados cada '
                   '200 PV) e iconos de estado id 1A..1E (cockpit.cpp:189-247, 274-397)',
            cuenta_regresiva='clase 0x23, oculta salvo en secciones con tiempo (cockpit.cpp:714-844)'),
        unidades_crudas=dict(vida=unidades(tablas['vida'], 0x21), cine=unidades(tablas['cine'], 0x30),
                             icono_municion=unidades(tablas['bala'], 0x32)),
    )
    with open(os.path.join(OUT, 'hud.json'), 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print('out/combate/hud.json: %d elementos dibujados, %d texturas' % (len(elementos), len(archivos_tex)))
    for e in elementos:
        print('  %2d %-26s tex %s rect %s rot %7.2f col %s blend %d' % (
            e['orden'], e['nombre'], e['textura'], e['pantalla_rect_xywh'], e['rotacion_z_grados'],
            e['color_rgba'], e['blend']))


if __name__ == '__main__':
    main()
