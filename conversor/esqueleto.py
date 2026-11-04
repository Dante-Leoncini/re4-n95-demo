"""El esqueleto de un armature de Whisk3D (rigs glTF) evaluado como el Core (animation/SkeletalAnimation.cpp):
local = T * R * S con R = Rz * Ry * Rx (euler en grados, orden XYZ), mundo = cadena de padres, skin = mundo * invBind.
Las curvas de los clips (.w3da) son lineales o escalones (lo horneado del juego); cada componente tiene la suya y el que
no tiene curva queda en su reposo. Aca los clips salen MUESTREADOS por cuadro: por hueso, la rotacion local como
cuaternion y la traslacion (el N95 interpola entre dos cuadros y arma las matrices)."""
import numpy as np


def _mat_json(m16):
    return np.array(m16, float).reshape(4, 4).T


def quat_de_euler(deg):
    """deg (..., 3) en grados, R = Rz*Ry*Rx -> cuaternion (..., 4) x y z w"""
    r = np.radians(np.asarray(deg, float)) * 0.5
    cx, sx = np.cos(r[..., 0]), np.sin(r[..., 0])
    cy, sy = np.cos(r[..., 1]), np.sin(r[..., 1])
    cz, sz = np.cos(r[..., 2]), np.sin(r[..., 2])
    # q = qz * qy * qx
    w = cz * cy * cx + sz * sy * sx
    x = cz * cy * sx - sz * sy * cx
    y = cz * sy * cx + sz * cy * sx
    z = sz * cy * cx - cz * sy * sx
    return np.stack([x, y, z, w], -1)


def mat_de_quat(q):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    m = np.zeros(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z)
    m[..., 0, 1] = 2 * (x * y - z * w)
    m[..., 0, 2] = 2 * (x * z + y * w)
    m[..., 1, 0] = 2 * (x * y + z * w)
    m[..., 1, 1] = 1 - 2 * (x * x + z * z)
    m[..., 1, 2] = 2 * (y * z - x * w)
    m[..., 2, 0] = 2 * (x * z - y * w)
    m[..., 2, 1] = 2 * (y * z + x * w)
    m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def _curva(c, frames):
    """la curva evaluada en los cuadros (enteros): lineal o escalon, constante afuera"""
    fr = np.asarray(c.frames, float)
    v = np.asarray(c.valores, float)
    if len(fr) == 1:
        return np.full(len(frames), v[0])
    out = np.interp(frames, fr, v)
    esc = np.asarray(c.interp) == 0
    if esc.any():
        k = np.searchsorted(fr, frames, side='right') - 1
        k = np.clip(k, 0, len(fr) - 1)
        m = esc[k] & (frames < fr[-1])
        out[m] = v[k[m]]
    return out


class Esqueleto:
    def __init__(self, arm_json, animset):
        self.huesos = arm_json['bones']
        self.nombres = [b['nombre'] for b in self.huesos]
        self.padres = [b['padre'] for b in self.huesos]
        self.inv_bind = [_mat_json(b['invBind']) for b in self.huesos]
        self.rest_t = np.array([b['restT'] for b in self.huesos], float)
        self.rest_r = np.array([b['restR'] for b in self.huesos], float)
        self.rest_s = np.array([b.get('restS', [1, 1, 1]) for b in self.huesos], float)
        self.rest_q = quat_de_euler(self.rest_r)
        for b in self.huesos:
            if any(abs(x) > 1e-6 for x in b.get('preRot', [0, 0, 0])):
                raise ValueError('%s: hueso con preRot (no es un rig glTF)' % b['nombre'])
        tabla, clips = animset
        mapa = {i: self.nombres.index(n) for i, n in enumerate(tabla) if n in self.nombres}
        self.clips = []
        for c in clips:
            pistas = {mapa[h]: cs for h, cs in c.pistas.items() if h in mapa}
            self.clips.append((c, pistas))
        # el orden de evaluacion: padres antes que hijos
        self.orden = []
        hecho = set()
        while len(self.orden) < len(self.huesos):
            for i, p in enumerate(self.padres):
                if i not in hecho and (p < 0 or p in hecho):
                    self.orden.append(i)
                    hecho.add(i)

    def muestrear(self, k, primero=None, ultimo=None):
        """el clip k cuadro a cuadro: (cuadros, t (nf, nh, 3), q (nf, nh, 4), animados_r, animados_t)"""
        c, pistas = self.clips[k]
        f0 = c.ini if primero is None else primero
        f1 = c.fin if ultimo is None else ultimo
        frames = np.arange(f0, f1 + 1, dtype=float)
        nf, nh = len(frames), len(self.huesos)
        T = np.repeat(self.rest_t[None], nf, 0)
        R = np.repeat(self.rest_r[None], nf, 0)
        anim_r, anim_t = set(), set()
        for h, curvas in pistas.items():
            for cv in curvas:
                if cv.prop == 0 and cv.comp < 3:
                    T[:, h, cv.comp] = _curva(cv, frames)
                elif cv.prop == 1 and cv.comp < 3:
                    R[:, h, cv.comp] = _curva(cv, frames)
            if np.abs(T[:, h] - self.rest_t[h]).max() > 1e-5:
                anim_t.add(h)
            if np.abs(R[:, h] - self.rest_r[h]).max() > 1e-4:
                anim_r.add(h)
        Q = quat_de_euler(R)
        # (el signo de cada cuaternion: que dos cuadros seguidos no esten en hemisferios opuestos)
        for f in range(1, nf):
            neg = (Q[f] * Q[f - 1]).sum(-1) < 0
            Q[f][neg] *= -1
        return frames, T, Q, sorted(anim_r), sorted(anim_t)

    def mundos(self, T, Q):
        """para UN cuadro (T (nh,3), Q (nh,4)): las matrices de mundo 4x4 de cada hueso"""
        loc = np.zeros((len(self.huesos), 4, 4))
        loc[:, :3, :3] = mat_de_quat(Q) * self.rest_s[:, None, :]
        loc[:, :3, 3] = T
        loc[:, 3, 3] = 1
        mundo = [None] * len(loc)
        for i in self.orden:
            p = self.padres[i]
            mundo[i] = loc[i] if p < 0 else mundo[p] @ loc[i]
        return mundo

    def reposo(self):
        return self.mundos(self.rest_t, self.rest_q)
