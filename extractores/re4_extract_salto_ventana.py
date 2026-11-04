#!/usr/bin/env python3
"""
El SALTO POR LA VENTANA de r100 (RE4 GameCube USA): todo lo que hace el juego mientras dura, para recrearlo en Whisk3D.

  out/combate/salto_ventana.json   por ventana (ETS 0 y 1) y por direccion de salto (breakDir 0 / 1 / 2):
                                   - la secuencia del evento (cEmWindow::ExeWindowEvent) cuadro por cuadro: donde se
                                     pone Leon, el clip, el frame en que estalla el vidrio, los efectos, los sonidos
                                   - la CAMARA por frame (ojo / objetivo / fov) en el espacio LOCAL de la ventana y en
                                     el mundo: la camara de hombro normal (CameraQuasiFPS) que sigue a Leon, simulada
                                     con el codigo del juego (offsets del corte de area del cuarto, colision contra las
                                     paredes, suavizados)
                                   - los TROZOS de vidrio (obj05 = esp 0xFE de et00.eff, modelo EFM 0x10 de core.das):
                                     cuantos, desde donde, velocidad, giro, gravedad, rebote, vida, y una trayectoria de
                                     referencia por trozo (con los numeros al azar en 0)
                                   - la pantalla: franjas negras (scissor), HUD, teclas
  out/combate/vidrio_trozos_piezas.glb   los trozos SUELTOS (un nodo por parte de EFM 0x10 y 0x0E, origen = el pivote
                                   de la parte en el modelo) para animarlos uno por uno; vidrio_trozos.glb sigue igual

Fuentes (decomp ../re4/src): game/emwindow.cpp (ExeWindowEvent, SetBreakAll, SetBreakEsp, SetBreakModel, init),
game/sce_com.cpp (SceEventStart / SceEventEnd), game/main_sub.cpp (SetScissorState), game/cam_ctrl.cpp (Check,
areaHitCheck, switchCamera, Move, CameraSmooth, CameraInterpolation, cameraHitCheck), game/cam_qfps.cpp (tablas
g_transOfs, setAreaData, offsetCorrection, calcBaseMatrix, calcOffset, hitCheck, move), game/player.cpp (move ->
setPlayerLocation), game/motion.cpp (MotionGetSpeed / MotionAddSpeed: la raiz Null mueve a Leon), game/obj05.cpp +
game/esp_efm.cpp (EfmSetObj05, cObj05::move), game/est.cpp (EstSet). Disco: r100.das (ETS, CAM entrada 4, SAT, ETM
et00.eff), core.das (EFM 0x10 / 0x0E). Lee out/combate/acciones.json, leon_combate_clips.json y efectos_ventana.json
(correr antes re4_extract_leon.py --combate y re4_extract_acciones.py).

Uso:  python3 re4_extract_salto_ventana.py
"""
import json
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import re4_extract_leon as L          # noqa: E402,F401  (pone ../re4/tools en el path)
import re4_extract_r100 as R          # noqa: E402
import re4_extract_acciones as A      # noqa: E402
from motion import archive, meshbin, modelbin, gxtex  # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'tools'))
import re4_eff  # noqa: E402

OUT = os.path.join(HERE, 'out', 'combate')
EXT = os.path.join(HERE, 'extracted')
MM = 0.001
FPS = 30.0
ZNEAR = 100.0            # main.cpp: ZNEAR = 100 (mm)
PRECALENTAR = 90         # frames con Leon quieto en el arranque para asentar los suavizados de la camara


def rn(v, n=4):
    if isinstance(v, (list, tuple, np.ndarray)):
        return [rn(x, n) for x in v]
    return round(float(v), n)


# ---------------------------------------------------------------------------------------------------------------
#  matrices del juego (mm, filas; RotMatrix = Rz * Ry * Rx; aca solo hace falta yaw)
# ---------------------------------------------------------------------------------------------------------------
def mat_yaw(yaw, pos):
    """cModel::mat de Leon (ang = (0, yaw, 0)): columnas x, y, z del modelo + posicion; 4x4."""
    s, c = math.sin(yaw), math.cos(yaw)
    return np.array([[c, 0, s, pos[0]], [0, 1, 0, pos[1]], [-s, 0, c, pos[2]], [0, 0, 0, 1.0]])


def xf(m, v):
    return m[:3, :3] @ np.asarray(v, float) + m[:3, 3]


def a_local_ventana(pos_w_m, yaw_w, p_mm):
    """punto del mundo (mm) -> espacio de la ventana (m): origen = ETS pos, +Z = frente (yaw), +X = (cos, 0, -sin)."""
    d = np.asarray(p_mm, float) * MM - np.asarray(pos_w_m, float)
    s, c = math.sin(yaw_w), math.cos(yaw_w)
    return [c * d[0] - s * d[2], d[1], s * d[0] + c * d[2]]


# ---------------------------------------------------------------------------------------------------------------
#  colision de la camara: cameraHitCheck -> SatMgr.hitCheck(from, to, ..., 0x8000, 0x1C2810) contra las PAREDES del
#  SAT del cuarto (+ el quad de colision de cada ventana intacta: setSat attr 0x40, x +-850, y -200..1600, hasta que
#  SetAtariOff lo saca al romperse). Los personajes (EmHitCheck) y objetos (ObjHitCheck) no se simulan.
# ---------------------------------------------------------------------------------------------------------------
class Colision:
    def __init__(self, V, tris, ventanas):
        T = [(V[a], V[b], V[c]) for a, b, c, attr, cl in tris if cl == 2 and not (attr & 0x1C2810)]
        self.fijo = np.array(T, float) / MM          # mm
        self.ventanas = {}
        for w in ventanas:
            p, yaw = w['pos_m'], w['yaw_rad']
            q = [A.a_mundo(p, yaw, (x, y, 0.0)) for x, y in ((-0.85, -0.2), (0.85, -0.2), (0.85, 1.6), (-0.85, 1.6))]
            q = np.array(q) / MM
            self.ventanas[w['etc_no']] = np.array([[q[0], q[1], q[2]], [q[0], q[2], q[3]]])

    def rayo(self, a, b, intactas):
        """primer impacto del segmento a -> b (mm) o None: (punto, normal)."""
        tri = self.fijo
        extra = [self.ventanas[n] for n in intactas]
        if extra:
            tri = np.concatenate([tri] + extra)
        a = np.asarray(a, float)
        d = np.asarray(b, float) - a
        v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
        e1, e2 = v1 - v0, v2 - v0
        h = np.cross(d, e2)
        det = np.einsum('ij,ij->i', e1, h)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = a - v0
        u = inv * np.einsum('ij,ij->i', s, h)
        q = np.cross(s, e1)
        v = inv * (q @ d)
        t = inv * np.einsum('ij,ij->i', e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= 1)
        if not hit.any():
            return None
        i = np.argmin(np.where(hit, t, np.inf))
        n = np.cross(e1[i], e2[i])
        n /= np.linalg.norm(n) or 1.0
        if n @ d > 0:
            n = -n
        return a + d * t[i], n


# ---------------------------------------------------------------------------------------------------------------
#  CAMARA de hombro (cam_qfps.cpp) con las tablas del corte de area (setAreaData) del cuarto
# ---------------------------------------------------------------------------------------------------------------
def leer_cam(cam):
    """B404: areas (CameraAreaRec + CameraAreaInfo) y cortes; solo lo que usa areaHitCheck / setAreaData."""
    ncut, narea = cam[4], cam[5]
    areas = []
    for i in range(narea):
        ai, ci = struct.unpack_from('>II', cam, 0x10 + 16 * i + 8)
        en, ano, cno, attr = struct.unpack_from('>BbbB', cam, ai)
        d, = struct.unpack_from('>f', cam, ai + 4)
        attr2 = cam[ai + 8]
        h, by, num, pp = struct.unpack_from('>ffiI', cam, ai + 0x20)
        pts = [struct.unpack_from('>3f', cam, pp + 12 * j) for j in range(num)]
        _, ccno, ctyp, cfl = struct.unpack_from('>BbbB', cam, ci)
        fr, = struct.unpack_from('>f', cam, ci + 0x14)
        cnum, cpos, cat, croll, cfov = struct.unpack_from('>iIIII', cam, ci + 0x20)
        corte = dict(camera_no=ccno, tipo=ctyp, flags=cfl, floor_ratio=fr, num=cnum)
        if ctyp == 8 and cnum == 24:
            corte['pos'] = [struct.unpack_from('>3f', cam, cpos + 12 * k) for k in range(cnum)]
            corte['at'] = [struct.unpack_from('>3f', cam, cat + 12 * k) for k in range(cnum)]
            corte['roll'] = [struct.unpack_from('>f', cam, croll + 4 * k)[0] for k in range(cnum)]
            corte['fovy'] = [struct.unpack_from('>f', cam, cfov + 4 * k)[0] for k in range(cnum)]
        areas.append(dict(i=i, enable=en, area_no=ano, camera_no=cno, attr=attr, dir=d, attr2=attr2, height=h,
                          base_y=by, pts=[(p[0], p[2]) for p in pts], corte=corte))
    return areas


def area_hit(a, pos, yaw):
    """areaHit: banda de altura (pos.y + 100 en [base_y, base_y + height)) + poligono XZ; attr 4 = nunca."""
    if a['attr'] & 4:
        return False
    if a['attr'] & 0x40:
        d = (yaw - a['dir'] + math.pi) % (2 * math.pi) - math.pi
        if abs(d) > 2.3561945:
            return False
    y = pos[1] + 100.0
    if y < a['base_y'] or y >= a['base_y'] + a['height']:
        return False
    x, z = pos[0], pos[2]
    c = False
    n = len(a['pts'])
    for k in range(n):
        x1, z1 = a['pts'][k]
        x2, z2 = a['pts'][(k + 1) % n]
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            c = not c
    return c


# g_transOfs[TRANS_DATA_LEON][0] (Leon sin apuntar; lado 0 = hombro por defecto): (Campos, campos2, Target, fov)
TRANS_LEON = [((-500.0, 885.0, -1050.0), (-240.0, 1550.0, -150.0), (0.0, 2585.0, 1390.0), 50.0),
              ((-500.0, 1765.0, -1190.0), (-180.0, 1700.0, -110.0), (0.0, 1340.0, 1480.0), 50.0),
              ((-500.0, 2420.0, -680.0), (-200.0, 1870.0, -185.0), (0.0, 780.0, 1250.0), 50.0)]


def offset_correction(campos, campos2):
    """cam_qfps offsetCorrection: el punto cercano queda >= 320 mm detras de Leon a lo largo de la camara."""
    campos, campos2 = np.array(campos, float), np.array(campos2, float)
    d = campos2 - campos
    ln = np.linalg.norm(d)
    d /= ln
    t = (-0.8 * 400.0 - campos[2]) / d[2]
    if t > ln:
        campos2 = campos + d * t
    return campos2


def tabla_area(area):
    """setAreaData + bindAreaCamera (attr2 & 0x5D): la tabla de transicion (sin apuntar) del lado 0 del corte."""
    c = area['corte'] if area else None
    if not c or c['tipo'] != 8 or c['num'] == 0 or 'pos' not in c:
        return [(np.array(a), offset_correction(a, b), np.array(t), f) for a, b, t, f in TRANS_LEON]
    out = []
    for j in range(3):
        k = 6 + j                     # i = 2 (transicion, lado 0), j = arriba / medio / abajo
        campos = c['pos'][k] if not (c['flags'] & 0x20) else TRANS_LEON[j][0]
        campos2 = c['pos'][18 + j] if not (c['flags'] & 0x20) else TRANS_LEON[j][1]
        out.append((np.array(campos), offset_correction(campos, campos2), np.array(c['at'][k]), c['fovy'][k]))
    return out


class CamaraHombro:
    """CameraControl (r0 = 0xA) + CameraQuasiFPS + CamSmth, un frame por llamada."""

    def __init__(self, areas, col):
        self.areas, self.col = areas, col
        self.area = None
        self.tabla = tabla_area(None)
        self.viejo = None
        self.blend_n = 0
        self.eff_pos = self.eff_at = None
        self.smooth = None
        self.inter = None

    def elegir_area(self, pos, yaw, cut_attr=1):
        """areaHitCheck: primero las areas attr 0x20, despues la actual si sigue valiendo, despues la primera."""
        for a in self.areas:
            if a['enable'] & 1 and a['attr'] & 0x20 and a['attr2'] & 1 and area_hit(a, pos, yaw):
                return a
        if self.area is not None and self.area['attr'] & cut_attr and area_hit(self.area, pos, yaw):
            return self.area
        for a in self.areas:
            if a['enable'] & 1 and a['attr'] & cut_attr and a['attr2'] & 1 and area_hit(a, pos, yaw):
                return a
        return None

    def frame(self, pos, yaw, intactas):
        a = self.elegir_area(pos, yaw)
        if a is not self.area:
            if a is not None and a['corte']['tipo'] == 8:
                # switchCamera tipo 8: setBlendData (la tabla vieja pasa a BLEND) + setAreaData + setBlendCount(10)
                self.viejo = self.tabla
                self.tabla = tabla_area(a)
                self.blend_n = 10
            elif a is None:
                self.viejo = self.tabla
                self.tabla = tabla_area(None)
                self.blend_n = 10
            self.area = a
        # calcOffset: blend viejo -> actual (m_blend_count-- antes de usarlo) y el sitio MEDIO (sin palanca C: la
        # inclinacion m_depression_ratio decae *0.9 por frame y queda en 0)
        if self.blend_n > 0:
            self.blend_n -= 1
        r = self.blend_n / 10.0
        cam, cam2, tgt, fov = self.tabla[1]
        if r > 0:
            o = self.viejo[1]
            cam, cam2, tgt, fov = (o[0] * r + cam * (1 - r), o[1] * r + cam2 * (1 - r), o[2] * r + tgt * (1 - r),
                                   o[3] * r + fov * (1 - r))
        m = mat_yaw(yaw, pos)     # calcBaseMatrix: la matriz de Leon (pisos planos: sin inclinacion por la normal)
        salida_pos = self.hit_check(m, cam, cam2, tgt, fov, intactas)
        # lr_rate 0.6: suavizado de la X local (el cambio de hombro)
        p2x, t2x = salida_pos[0] * 0.4, tgt[0] * 0.4
        if self.eff_pos is None:
            self.eff_pos, self.eff_at = np.array(salida_pos, float), np.array(tgt, float)
        else:
            self.eff_pos = np.array([self.eff_pos[0] * 0.6 + p2x, salida_pos[1], salida_pos[2]])
            self.eff_at = np.array([self.eff_at[0] * 0.6 + t2x, tgt[1], tgt[2]])
        ojo, obj = xf(m, self.eff_pos), xf(m, self.eff_at)
        # CamSmth: param = 0.8 * viejo + 0.2 * nuevo (m_walk_ratio 0.8)
        if self.smooth is None:
            self.smooth = [ojo, obj, fov]
        else:
            s = self.smooth
            self.smooth = [s[0] * 0.8 + ojo * 0.2, s[1] * 0.8 + obj * 0.2, s[2] * 0.8 + fov * 0.2]
        return self.smooth[0].copy(), self.smooth[1].copy(), float(self.smooth[2]), (a['i'] if a else None)

    def hit_check(self, m, campos, campos2, target, fov, intactas):
        """CameraQuasiFPS::hitCheck: rayo cercano -> camara y dos rayos corridos +-w (medio ancho del plano cercano)."""
        up = np.array([0.0, 1.0, 0.0])
        w = ZNEAR * math.tan(math.radians(fov) / 2) * 1.3333334
        vv1 = np.cross(campos2 - target, up)
        vv1 = vv1 / np.linalg.norm(vv1) * w
        vv0 = np.cross(campos - target, up)
        vv0 = vv0 / np.linalg.norm(vv0) * w
        diff = vv1 - vv0
        dr = campos2 - campos
        dr /= np.linalg.norm(dr)
        near = dr * ZNEAR
        inv = np.linalg.inv(m)
        hits = []
        hA = self.col.rayo(xf(m, campos2), xf(m, campos), intactas)
        if hA is not None:
            hits.append(xf(inv, hA[0]))
        for sg in (-1.0, 1.0):
            wa, wb = xf(m, campos2 + sg * vv1), xf(m, campos + sg * vv0)
            h = self.col.rayo(wa, wb, intactas)
            if h is not None:
                d = np.linalg.norm(h[0] - wb) / np.linalg.norm(wa - wb)
                sc = diff * d + vv0
                hits.append(xf(inv, h[0]) - sg * sc + near)
        out = np.array(campos, float)
        if hits:
            dmin = np.linalg.norm(out - campos2)
            for hpt in hits:
                d = np.linalg.norm(hpt - campos2)
                if d < dmin:
                    dmin, out = d, hpt
        else:
            wb = xf(m, campos)
            if (self.col.rayo(wb, xf(m, campos - vv0), intactas) is not None or
                    self.col.rayo(wb, xf(m, campos + vv0), intactas) is not None):
                out = campos + near
        return out


# ---------------------------------------------------------------------------------------------------------------
#  TROZOS de vidrio (obj05)
# ---------------------------------------------------------------------------------------------------------------
def rot_xyz_deg(a):
    """RotMatrix (Rz * Ry * Rx) de angulos en grados -> 3x3."""
    x, y, z = (math.radians(v) for v in a)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def trozos_de_registro(q, partes, piso_local_mm=None, frames=None):
    """EfmSetObj05 + cObj05::move con los numeros al azar (fRandSeed1_1) en 0, en el espacio de la VENTANA (mm; EstSet
    con pos = origen de la ventana y rot = la de la ventana -> la matriz m del registro es la de la ventana).
    Devuelve (parametros, [trayectoria por parte: pos (m) y ang (rad) por frame])."""
    flags = q['Tool_flg']
    R0 = rot_xyz_deg(q['Ang'])                      # ang del cuerpo (grados -> rad); rotSpd = Ang_plus = 0 aca
    pos = np.array(q['Pos'], float)                 # + R_pos * azar
    esc = np.array([q['Size_base_x'] * 0.005, q['Size_base_y'] * 0.005, q['Size_base_x'] * 0.005])
    centro = R0 @ np.array(q['Vec0'], float)        # Efm05RotMatrix: el centro gira con el cuerpo
    rebote = np.array(q['Vec1'], float) * 0.1
    pow_, paso, rnd, rot_amp = q['Work8']
    grav = q['Work32'][0] * -0.1                    # prm.w.xCC (mm / frame^2)
    freno = 1.0 - q['Work32'][1] * 0.001            # prm.w.xD0
    suelo_ofs = q['Work32'][2]                      # xD4
    vida = q['Life_max']
    M = np.eye(4)
    M[:3, :3] = R0 @ np.diag(esc)
    M[:3, 3] = pos
    params = dict(
        registro_pos_mm=rn(q['Pos'], 2), pos_azar_mm=rn(q['R_pos'], 2),
        cuerpo_ang_grados=rn(q['Ang'], 2), ang_azar_grados=rn(q['R_ang'], 2),
        escala_xz_y=[rn(esc[0]), rn(esc[1])],
        centro_de_la_explosion_mm=rn(centro, 2), centro_azar_mm=rn(q['Vec2'], 2),
        rango_por_frame_mm=2 * paso + 1, velocidad_mm_frame='%d * 4096 / rango (el rango cuando la alcanza)' % pow_,
        azar_velocidad=rnd / 32.0, giro_azar_rad_frame=rn(rot_amp * 0.005),
        gravedad_mm_frame2=grav, gravedad_m_s2=rn(grav * MM * FPS * FPS, 3), freno_por_frame=rn(freno),
        rebote=rn(rebote), rebota_en_el_piso=bool(flags & 1), rebota_en_paredes=bool(flags & 2),
        queda_plano=bool(flags & 8), suelo_ofs_mm=suelo_ofs, vida_frames=vida,
        alfa_inicial=rn(q['Col_start'][3] / 255.0), color=rn([c / 255.0 for c in q['Col_start'][:3]]),
        alfa_mult_por_frame_desde=q['Col_max_cnt'] + q['Col_start_cnt'], alfa_mult=rn(q['Col_d'][3]),
        muere='a los %d frames o con alfa < 4/255' % vida, iluminado=bool(flags & 0x40))
    trayect = []
    rango_f = lambda f: (f + 1) * (paso * 2 + 1) + 1.0      # noqa: E731
    for p in partes:
        lp = np.array(p['pivote_mm'], float)
        world = xf(M, lp)
        spd = None
        ang = np.zeros(3)
        rot_spd = np.zeros(3)
        estado = 0
        fr_sale = None
        pts, angs = [], []
        for f in range(frames or vida):
            if f >= vida:
                break
            fr = f + 1                                  # w->frame++ antes de calcular el rango
            rango = rango_f(fr)
            powf = pow_ * 4096.0 / rango
            if estado == 0:
                d = world - (pos + centro)
                if np.linalg.norm(d) < rango or paso == 0xFF:
                    estado = 1
                    fr_sale = f
                    if not d.any():
                        d = np.array([0.0, 1.0, 0.0])
                    spd = d / np.linalg.norm(d) * powf
                    rot_spd = np.zeros(3)             # rotAmp * azar(-1..1) por eje
            if estado == 1:
                world = world + spd
                spd = spd * freno
                spd[1] += grav
                ang = ang + rot_spd
                if flags & 1 and piso_local_mm is not None and world[1] - suelo_ofs < piso_local_mm:
                    spd = spd * np.array([rebote[0], -rebote[1], rebote[0]])
                    world[1] = piso_local_mm + suelo_ofs
                    if np.linalg.norm(spd) < 15.0:
                        estado = 2
            pts.append(rn(world * MM))
            angs.append(rn(ang))
        trayect.append(dict(parte=p['parte'], sale_en_frame=fr_sale,
                            velocidad_inicial_m_s=rn(np.array(spd_ini(p, M, pos, centro, pow_, paso)) * MM * FPS),
                            ang_rad_por_frame=angs,
                            pos_m_por_frame=pts))
    return params, trayect


def spd_ini(p, M, pos, centro, pow_, paso):
    """la velocidad (mm/frame) con que sale la parte: radial desde el centro, pow * 4096 / rango del frame en que el
    rango la alcanza (sin el azar)."""
    world = xf(M, np.array(p['pivote_mm'], float))
    d = world - (pos + centro)
    dist = np.linalg.norm(d)
    f = 0
    while True:
        rango = (f + 2) * (paso * 2 + 1) + 1.0
        if dist < rango or paso == 0xFF:
            break
        f += 1
    if not d.any():
        d = np.array([0.0, 1.0, 0.0])
    return d / np.linalg.norm(d) * (pow_ * 4096.0 / rango)


def partes_efm(core, ids=(0x10, 0x0E)):
    """los modelos EFM de core.das -> {id: (meshbin, tpl, [partes con su pivote])}."""
    d, h = core.d, core.h
    n = struct.unpack_from('>I', d, h[5])[0]
    lista = [struct.unpack_from('>H', d, h[5] + 4 + 8 * i)[0] for i in range(n)]
    out = {}
    for i, idn in enumerate(lista):
        if idn not in ids:
            continue
        eo = h[11] + struct.unpack_from('>I', d, h[11] + 4 + 4 * i)[0]
        _, om, ot, _, _ = struct.unpack_from('>5I', d, eo)
        m = meshbin.parse(d[eo + om:eo + ot])
        sk = modelbin.parse(d[eo + om:eo + ot])
        tpl = gxtex.parse_tpl(d[eo + ot:])
        partes = []
        for p in sk.parts:
            vs = {v[0] for part in m.parts for t in part.triangles() for v in t if m.skin(v[0])[0][0] == p.no}
            P = np.array([m.position(k) for k in vs])
            partes.append(dict(parte=p.no, pivote_mm=list(p.pos), vertices=len(vs),
                               caja_mm=[rn(P.min(0), 1), rn(P.max(0), 1)] if len(P) else None))
        out[idn] = (m, tpl, partes)
    return out


class _Pieza:
    """una parte del meshbin como malla suelta: solo sus triangulos, vertices relativos a su pivote."""

    def __init__(self, m, parte, pivote):
        self._m = m
        self._p = parte
        self._piv = pivote
        self.parts = []
        for part in m.parts:
            tris = [t for t in part.triangles() if all(m.skin(v[0])[0][0] == parte for v in t)]
            self.parts.append(_Parte(part, tris))

    def position(self, i):
        p = self._m.position(i)
        return tuple(p[k] - self._piv[k] for k in range(3))

    def __getattr__(self, k):
        return getattr(self._m, k)


class _Parte:
    def __init__(self, part, tris):
        self._part = part
        self._tris = tris

    def triangles(self):
        return self._tris

    def __getattr__(self, k):
        return getattr(self._part, k)


# ---------------------------------------------------------------------------------------------------------------
def main():
    acc = json.load(open(os.path.join(OUT, 'acciones.json')))
    clips = {c['clip']: c for c in json.load(open(os.path.join(OUT, 'leon_combate_clips.json')))['clips']}
    efx = {g['est']: g for g in json.load(open(os.path.join(OUT, 'efectos_ventana.json')))['grupos']}
    das = archive.Archive(os.path.join(EXT, 'St1', 'r100.das'))
    ent = list(das.entries())
    V, tris = R.sat(next(e for e in ent if e.tag == 'SAT').data)
    import re4_extract_intro_r100 as I
    cam_d = I.arc_room(das, 4).data
    areas = leer_cam(cam_d)
    ventanas = acc['ventanas']['lista']
    col = Colision(V, tris, ventanas)
    core = re4_eff.load_effs(os.path.join(EXT, 'etc', 'core.das'), 1)[0]
    efm = partes_efm(core)

    # ---- los trozos sueltos ----
    modelos = []
    for idn in (0x10, 0x0E):
        m, tpl, partes = efm[idn]
        for p in partes:
            modelos.append(('efm_%02x_parte_%d' % (idn, p['parte']), _Pieza(m, p['parte'], p['pivote_mm']), tpl, True))
    A.glb_estatico(os.path.join(OUT, 'vidrio_trozos_piezas.glb'), modelos, 'vidrio_pieza')

    # ---- cada ventana / salto ----
    EST_LEON = {0: 8, 1: 2, 2: 4}
    SND = {0: {3: (1, 0x29), 4: (1, 0x34), 5: (1, 0x43), 0x23: (5, 5), 0x29: (5, 0x12), 0x2C: (5, 0x13)},
           1: {3: (1, 0x29), 4: (1, 0x34), 5: (1, 0x43), 0x2D: (5, 5), 0x33: (5, 0x12), 0x37: (5, 0x13)},
           2: {3: (1, 0x29), 4: (1, 0x34), 5: (1, 0x43), 0x28: (5, 5), 0x37: (5, 0x12), 0x39: (5, 0x13)}}
    WAV = {(1, 0x29): 'ventana_leon_1.wav', (1, 0x34): 'ventana_leon_2.wav', (1, 0x43): 'ventana_leon_3.wav',
           (5, 5): 'ventana_cae_cuerpo.wav', (5, 0x12): 'ventana_paso_1.wav', (5, 0x13): 'ventana_paso_2.wav'}
    salida_v = []
    resumen = []
    for w in ventanas:
        pos_w = w['pos_m']
        yaw_w = w['yaw_rad']
        saltos = []
        for sj in w['saltos']:
            bd = sj['break_dir']
            c = clips[sj['clip']]
            pista = c['raiz']['pista_x_z_rotY']
            py = c['raiz']['pista_y']
            n = c['frames']
            yaw_l = sj['leon_yaw_rad']
            ini = np.array(sj['leon_inicio_mundo_m']) / MM
            f_rompe = sj['vidrio_rompe_frame']
            cam = CamaraHombro(areas, col)
            leon_mundo = []
            for f in range(n):
                x, z, ry = pista[f]
                s, cc = math.sin(yaw_l), math.cos(yaw_l)
                p = ini + np.array([cc * x + s * z, py[f], -s * x + cc * z]) / MM
                leon_mundo.append((p, yaw_l + ry))
            intactas_ini = [v['etc_no'] for v in ventanas]
            for _ in range(PRECALENTAR):              # Leon quieto en el arranque: suavizados asentados
                cam.frame(leon_mundo[0][0], leon_mundo[0][1], intactas_ini)
            ojo_l, obj_l, ojo_w, obj_w, fovs, area_f = [], [], [], [], [], []
            for f in range(n):
                intactas = [v['etc_no'] for v in ventanas if not (v['etc_no'] == w['etc_no'] and f >= f_rompe)]
                o, t, fov, ai = cam.frame(leon_mundo[f][0], leon_mundo[f][1], intactas)
                ojo_w.append(rn(o * MM))
                obj_w.append(rn(t * MM))
                ojo_l.append(rn(a_local_ventana(pos_w, yaw_w, o)))
                obj_l.append(rn(a_local_ventana(pos_w, yaw_w, t)))
                fovs.append(rn(fov, 3))
                area_f.append(ai)
            fov_vis = [rn(2 * math.degrees(math.atan(math.tan(math.radians(f) / 2) * 337.0 / 448.0)), 3) for f in fovs]
            leon_l = [rn(a_local_ventana(pos_w, yaw_w, p)) for p, _ in leon_mundo]
            # trozos del est de rotura del salto (tblB[breakDir][1])
            est = sj['est_rotura']
            g = efx[est]
            piso_l = None
            h = A.piso_bajo(V, tris, pos_w[0] + math.sin(yaw_w) * 0.3, pos_w[1] + 0.5, pos_w[2] + math.cos(yaw_w) * 0.3)
            if bd == 2:
                fr_ = A.a_mundo(pos_w, yaw_w, (0, 0, 1.0))
                h = A.piso_bajo(V, tris, fr_[0], pos_w[1] - 0.5, fr_[2])
            if h is not None:
                piso_l = (h - pos_w[1]) / MM
            trozos = []
            for k, q in enumerate(g['crudo']):
                if q['Id'] != 0xFE:
                    continue
                m, _, partes = efm[q['Tex_id']]
                params, tray = trozos_de_registro(q, partes, piso_l, frames=q['Life_max'])
                trozos.append(dict(registro=k, modelo_efm='0x%02X' % q['Tex_id'],
                                   nodos_glb=['efm_%02x_parte_%d' % (q['Tex_id'], p['parte']) for p in partes],
                                   parametros=params, trozos=tray))
            efectos = [dict(frame=0, grupo=efx[EST_LEON[bd]]['nombre'], est=EST_LEON[bd], donde='sobre Leon',
                            llamada='EstSet(pPL, -1, 0, 0, eff 0x54, %d, 1): pos = NULL -> la cabeza del est (pos / '
                                    'rot / parte del est) relativa a Leon' % EST_LEON[bd]),
                       dict(frame=f_rompe, grupo=g['nombre'], est=est, donde='origen de la ventana, con su rotacion',
                            llamada='SetBreakAll(plPos, 1, 1) -> SetBreakEsp(ChkBreakDir(plPos), 1, 1) = tblB[%d][1] '
                                    '-> EstSet(0, -1, origen ventana, ang ventana, eff, %d, 0x801): con pos explicita la '
                                    'cabeza del est NO se usa; los pos de los registros son del espacio de la ventana'
                                    % (bd, est))]
            sonidos = [dict(frame=f_rompe, banco='ROOM', id='0x3B', wav='vidrio_rompe.wav', donde='en la ventana',
                            que='SetBreakAll: SndCall(6, 0x3B, &pos)')]
            for fr_s, (bank, sid) in sorted(SND[bd].items()):
                sonidos.append(dict(frame=fr_s, banco='PL' if bank == 1 else 'FOOT', id='0x%02X' % sid, wav=WAV[(bank, sid)],
                                    donde='Leon', que='SndCall(%d, 0x%02X, &pPL->pos)' % (bank, sid)))
            saltos.append(dict(
                break_dir=bd, clip=sj['clip'], cartel=sj['cartel'], frames=n, duracion_s=rn(n / FPS, 3),
                leon=dict(inicio_local_m=rn([v * MM for v in sj['leon_inicio_local_mm']]),
                          yaw_local_rad=rn(yaw_l - yaw_w, 5), inicio_mundo_m=sj['leon_inicio_mundo_m'],
                          yaw_mundo_rad=yaw_l, raiz_local_m_por_frame=leon_l,
                          nota='pPL->pos / ang puestos de golpe en el frame 0 (PSMTXMultVec(ventana.mat, pos local)); '
                               'la raiz Null del clip lo mueve (MotionSetCore 0x201: MotionGetSpeed/AddSpeed); '
                               'colision apagada (beginEvent); cara 2 (setFace(2)) todo el salto'),
                vidrio=dict(rompe_en_frame=f_rompe, est=est, modelo_roto='et0001.bin (Ventana_rota)',
                            colision='SetAtariOff: sin SAT 0x40 ni EAT desde ese frame; etc flag bit 0 = rota'),
                efectos=efectos, sonidos=sonidos,
                camara=dict(
                    tipo='camara de HOMBRO normal (CameraQuasiFPS, r0 0xA) siguiendo a Leon: el evento NO pone camara '
                         'propia (SceEventStart(0) solo hace PlEndCamera; LadderEventTrans esconde escaleras)',
                    area_por_frame=area_f,
                    local_ventana=dict(ojo_m=ojo_l, objetivo_m=obj_l),
                    mundo=dict(ojo_m=ojo_w, objetivo_m=obj_w),
                    arriba=[0, 1, 0], roll_grados=0.0,
                    fov_grados=fovs, fov_visible_grados=fov_vis,
                    nota='frame f = frame f del clip (Leon ya movido por su raiz ese frame). Arranque: Leon quieto %d '
                         'frames en el lugar de inicio (los suavizados asentados); en el juego la camara viene de '
                         'donde estaba el jugador -> los primeros frames pueden diferir' % PRECALENTAR),
                trozos=trozos))
            resumen.append('ventana %d breakDir %d: %d frames, camara ojo %s -> %s (local), area %s, trozos %d' % (
                w['etc_no'], bd, n, ojo_l[0], ojo_l[-1], sorted({a for a in area_f if a is not None}),
                sum(len(t['trozos']) for t in trozos)))
        salida_v.append(dict(etc_no=w['etc_no'], pos_m=pos_w, yaw_rad=yaw_w, frente_mundo=w['frente_mundo'],
                             glb='out/combate/ventana_%d.glb' % w['etc_no'], saltos=saltos))

    area_doc = []
    for a in areas:
        c = a['corte']
        e = dict(indice=a['i'], area_no=a['area_no'], attr='0x%02X' % a['attr'], base_y_m=rn(a['base_y'] * MM),
                 alto_m=rn(a['height'] * MM), poligono_xz_m=[rn([x * MM, z * MM]) for x, z in a['pts']],
                 corte_tipo=c['tipo'], floor_ratio=rn(c['floor_ratio']))
        if 'pos' in c:
            t = tabla_area(a)
            e['hombro_sin_apuntar'] = [dict(sitio=s, ojo_m=rn(t[j][0] * MM), cercano_m=rn(t[j][1] * MM),
                                            objetivo_m=rn(t[j][2] * MM), fov_grados=rn(t[j][3], 3))
                                       for j, s in enumerate(('arriba', 'medio', 'abajo'))]
        area_doc.append(e)

    doc = dict(
        titulo='Salto por la ventana en r100 (RE4 GameCube USA): evento, camara, trozos de vidrio, efectos y sonidos',
        unidades='metros, segundos, 30 fps; angulos en radianes salvo *_grados. Espacio LOCAL de la ventana: origen = '
                 'pos_m de la ventana (centro del borde de abajo del vidrio), +Y arriba, +Z = frente de la ventana '
                 '(yaw_rad: frente = (sin yaw, 0, cos yaw)), +X = (cos yaw, 0, -sin yaw). mundo = pos_m + '
                 'x * (cos yaw, 0, -sin yaw) + y * (0, 1, 0) + z * (sin yaw, 0, cos yaw)',
        fuentes=__doc__.split('Fuentes')[1].split('Uso:')[0].strip(),
        evento=dict(
            funcion='cEmWindow::ExeWindowEvent (emwindow.cpp), llamado por el boton de accion (windowOn)',
            pasos=[
                'SceEventStart(0): el juego entra en modo evento: enemigos / objetos en modo evento, efectos de evento '
                'borrados, PlEndCamera (sale de apuntar), STA_EVENT + STA_SUSPEND, teclas bloqueadas (KeyStop '
                '0xEFCF0000), SE de bloque 2 parados, medidor de vida OCULTO, Leon invulnerable (dmg.set(0, 0x80)), '
                'SYS_SCISSOR_ON = FRANJAS NEGRAS (scissor y 56..392 de 448: se ven 337 lineas, como las cinematicas)',
                'SetStatus(2) en la ventana; LadderEventTrans(0) esconde las escaleras de mano; pPL->beginEvent(0) '
                '(sin colision), setNoSuspend(1), setFace(2)',
                'breakDir = ChkBreakDir(pos del jugador): 1 si esta DELANTE (+Z local, Front_check 90 grados), si no 2 '
                'si del otro lado no hay piso (CalFloor: > 3 m de caida a 2 m), si no 0',
                'Leon se pone EN EL LUGAR del salto (espacio de la ventana, mm): breakDir 0 (90, -1000, -1610) yaw 0; '
                '1 (-210, -1000, 1990) yaw pi; 2 (0, -1000, -980) yaw 0; + la rotacion de la ventana. Motion '
                'pl00537 / pl00538 / pl00536 (MotionSetCore attr 0x201: la raiz mueve a Leon)',
                'cada frame i hasta que termina la motion: efectos / sonidos / rotura (ver saltos[].efectos, '
                '.sonidos, .vidrio)',
                'al terminar: setFace(0), LadderEventTrans(1), SceEventEnd(0): CamCtrl.Comeback(0), vuelven HUD, '
                'teclas, danio, SIN franjas (salvo que estuvieran antes), sub pantalla cerrada 10 frames'],
            pantalla=dict(franjas='GXSetScissor(0, 56, ancho, alto - 111): 56 px arriba, 55 abajo en 448 (se ve '
                                  'y 56..392); el resto queda con el color de borrado (negro)',
                          hud='medidor de vida oculto (Cckpt.lifeMeterDisp(0), IdSys IDC_LIFE_METER) y sin carteles '
                              'del boton de accion (SPF_ACTBTN)',
                          temblor='NINGUNO: el evento no usa quake (pG->quake_ofs); SetShake de la ventana es solo '
                                  'cuando alguien la golpea',
                          fundido='ninguno'),
            otros='r11f (room 0x11F) agrega el est 6 del cuarto en el frame 25 de breakDir 0; no aplica a r100'),
        camara=dict(
            que=('NO hay camara de evento: sigue la camara de HOMBRO de siempre (CameraControl r0 = 0xA, '
                 'CameraQuasiFPS). Durante STA_EVENT CameraControl::Check igual corre areaHitCheck (elige el corte de '
                 'area por la posicion de Leon) pero no el cambio a la camara de caida (0xB); Move corre r0 0xA. '
                 'player.cpp le pasa la matriz de Leon (setPlayerLocation) cada frame que se mueve, y la raiz del clip lo '
                 'mueve -> la camara lo sigue desde atras, CRUZA la ventana detras de el'),
            formula=dict(
                base='m = matriz de Leon (RotY(yaw) + pos); pisos planos (la inclinacion por la normal del piso '
                     'floor_ratio no se simula)',
                offsets='sin palanca C / sin apuntar: sitio MEDIO de la tabla de TRANSICION (lado 0) del corte de area '
                        '(setAreaData tipo 8; attr2 & 0x5D -> reemplaza la de Leon). Las dos areas de la casa '
                        '(indices 1 = afuera, 3 = adentro) tienen el mismo sitio medio: ojo (-0.500, 1.765, -1.190), '
                        'cercano (0, 1.800, -0.090), objetivo (0, 1.340, 1.480) m en el espacio de Leon (+Z adelante), '
                        'fov 50 grados (vertical de la imagen 4:3 COMPLETA). Al cambiar de area: blend lineal de 10 '
                        'frames entre las tablas',
                colision='hitCheck: rayo cercano -> ojo y dos rayos corridos +-w (w = ZNEAR 100 mm * tan(fov/2) * 4/3) '
                         'contra las paredes del SAT (+ el quad de la ventana intacta); el ojo pasa al impacto mas '
                         'cercano al punto cercano (+ ZNEAR hacia adentro en los laterales)',
                suavizado='X local del ojo y del objetivo: x = 0.6 * x_anterior + 0.4 * x (lr_rate); despues '
                          'CamSmth: ojo / objetivo / fov = 0.8 * anterior + 0.2 * nuevo cada frame (m_walk_ratio)',
                proyeccion='C_MTXPerspective(fov, 4/3), near 0.1 m; con las franjas se ve fov_visible_grados '
                           '(= 2 atan(tan(fov / 2) * 337 / 448))'),
            areas_del_cuarto=area_doc),
        trozos=dict(
            que='obj05 (esp 0xFE "effect model" de et00.eff): cada registro 0xFE crea UN modelo EFM 0x10 de core.das '
                '(3 partes = 3 trozos) en su lugar; las partes salen volando del centro de la explosion cuando el rango '
                '(que crece rango_por_frame_mm cada frame) las alcanza',
            modelo='out/combate/vidrio_trozos_piezas.glb: nodos efm_10_parte_N / efm_0e_parte_N con el origen en el '
                   'pivote de la parte; el cuerpo lleva ang (grados) y escala (x, y, z) = (Size_base_x, Size_base_y, '
                   'Size_base_x) * 0.005; la parte N arranca en cuerpo * pivote_N',
            formula=('por frame: w.frame++; rango = (frame + 1) * (2 * paso + 1) + 1 mm; la parte en espera (estado 0) '
                     'sale si |pos_mundo_parte - (pos_cuerpo + centro)| < rango: vel = dir_radial * pow * 4096 / '
                     'rango + pow*rnd*azar(-1..1) por eje, velGiro = giro_azar * azar(-1..1) por eje. Volando: pos += '
                     'vel; vel *= freno; vel.y += gravedad; ang += velGiro. Rebote (Tool_flg 1): bajo el piso '
                     '(EatMgr.getFloor) -> vel.xz *= rebote.x, vel.y *= -rebote.y, velGiro *= 0.8; se queda si |vel| < '
                     '15 mm/frame. Color: alfa constante los primeros (Col_max_cnt + Col_start_cnt) frames, despues '
                     '* alfa_mult por frame; muere a vida_frames o alfa < 4'),
            azar='pos del cuerpo + R_pos * azar(-1..1) (x +-0.285 m en todos los registros de rotura), y el giro '
                 '(+-0.07 rad / frame por eje): las trayectorias de abajo tienen el azar en 0',
            partes={('0x%02X' % k): v[2] for k, v in efm.items()}),
        efectos_json='out/combate/efectos_ventana.json (grupos por nombre; mismo formato que efectos.json)',
        ventanas=salida_v)
    ruta = os.path.join(OUT, 'salto_ventana.json')
    with open(ruta, 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    for s in resumen:
        print(' ', s)
    print('-> out/combate/salto_ventana.json, out/combate/vidrio_trozos_piezas.glb')


if __name__ == '__main__':
    main()
