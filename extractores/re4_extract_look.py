#!/usr/bin/env python3
"""
El "look" original de r100 (RE4 GameCube, disco USA): filtro de pantalla, cielo, luces por area, luces de la
cinematica r100s03, el fuego de la chimenea y TODOS los emisores de efectos del cuarto.

  out/r100_look/look.json   filtro, cielo, areas_luz (CAM -> corte LIT, SAR), luces_cuarto (los 16 cortes),
                            luces_evento (s03: un .lit por corte + que cambia), fuego (parpadeo + efecto)
  out/r100_fx/emisores.json cada registro de efecto (sst del cuarto, est del cuarto, est del evento) traducido a
                            un emisor de particulas generico (metros, segundos, blend de GL) + el registro crudo
  out/r100_fx/tex/*.png     las texturas (cuadros sueltos + tiras si hay animacion)

FUENTES (decomp re4/src/game):
  light.cpp   setEnv / setBlur / setTune / hokanMove / update(cut, hokan)   cam_ctrl.cpp switchCamera (CAM -> cut)
  light01.cpp..light10.cpp (movimiento por tipo de luz: 1 = parpadeo)       light_area.cpp (SAR, solo personajes)
  filter.cpp / filter00.cpp (blur + "contraste")                             trans.cpp gxCsScale (tev_scale)
  est.cpp SstSet / eff_sys.cpp EffSetAreaState / esp_app.cpp EffAreaUpdate (efectos del cuarto por area EAR)
  st1/r100.cpp (SetSstDispFlag 0x11 auto quemado, 0x12 colgado)             event.cpp ExePacket_Lit

Uso:  python3 re4_extract_look.py
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 're4', 'tools'))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from motion import archive  # noqa: E402
import re4_eff  # noqa: E402

EXT = os.path.join(HERE, 'extracted')
DAS = os.path.join(EXT, 'St1', 'r100.das')
CORE = os.path.join(EXT, 'etc', 'core.das')
EVD = os.path.join(EXT, 'Evd', 'r100s03.evd')
EVENTO_JSON = os.path.join(HERE, 'out', 'evento_s03', 'evento.json')
MM = 0.001
FPS = 30.0


def r(v, n=4):
    if isinstance(v, (list, tuple)):
        return [r(x, n) for x in v]
    return round(float(v), n)


def c255(b):
    return [round(x / 255.0, 4) for x in b]


# ---------------------------------------------------------------------------------------------------------------
#  LIT completo (cLightEnv 0x104 + nLight x cLightWork 0x12C, include/light.h)
# ---------------------------------------------------------------------------------------------------------------
MANEJADOR = {0: 'estatica (Light00: DispCol = Col)', 1: 'PARPADEO (Light01: Col + Rnd()%(2r)-r por frame)',
             2: 'pulso seno (Light02)', 3: 'direccional que gira (Light03)', 4: 'luz de sombra de pies (Light04, nada)',
             5: 'camino de brillo (Light05)', 6: 'fundido lineal (Light06)', 7: 'direccional girando (Light07)',
             8: 'spot que sigue a un enemigo (Light08)', 0x10: 'fogonazo que se apaga (Light10)'}
ATENUACION = {0: 'constante hasta el radio (trans_lit tipo 0)', 1: 'lineal I*(R-d)/R', 2: 'cuadratica: 0.1 en el radio',
              3: 'spot (cono A0) + GX_DA_MEDIUM a 5 m', 5: 'PARALELA (direccional, usa dir)', 6: 'spot cuadratico'}


def trabajo_tipo(tipo, sub):
    """parametros del manejador por tipo (cLight::work = cLightWork+0x6C)."""
    if tipo == 1:
        rango = struct.unpack('>b', sub[4:5])[0]
        return dict(color_sub=list(sub[0:4]), rango=rango,
                    algoritmo='cada frame (30 fps): k = Rnd() %% (2*%d) - %d  (Rnd = byte 0..255, rnd.cpp); '
                              'DispCol.rgb = clamp(Col.rgb + k, 0, 255) (el MISMO k a r, g y b); la intensidad no '
                              'cambia' % (rango, rango))
    if tipo == 2:
        base, amp, freq, fase = struct.unpack('>4f', sub[0:16])
        return dict(base=base, amplitud=amp, frecuencia_hz=freq, fase=fase,
                    algoritmo='fase += freq*2pi/30; DispCol = Col * (base + amp*sin(fase))')
    if tipo == 6:
        ini, vel = struct.unpack('>2f', sub[0:8])
        return dict(inicio=ini, velocidad=vel)
    if tipo == 4:
        return dict(crudo=sub[:16].hex())
    return {}


def niebla_de(ft, fs, fe, col):
    """GX: t = (z - inicio)/(fin - inicio) (z = profundidad de ojo), cantidad de niebla f:
    LIN f = t, EXP f = 1 - 2^(-8t), EXP2 f = 1 - 2^(-8t^2) (GX_FOG_PERSP_*). color = mix(c, niebla, f)."""
    nombre = {0: 'apagada', 2: 'GX_FOG_PERSP_LIN', 4: 'GX_FOG_PERSP_EXP', 5: 'GX_FOG_PERSP_EXP2',
              6: 'GX_FOG_PERSP_REVEXP', 7: 'GX_FOG_PERSP_REVEXP2'}.get(ft, '?')
    n = dict(tipo=ft, tipo_gx=nombre, inicio_m=r(fs * MM, 3), fin_m=r(fe * MM, 3), color=c255(col[:3]),
             color_255=list(col))
    if ft == 5 and fe > fs:
        L = (fe - fs) * MM
        t = lambda f: math.sqrt(-math.log2(1 - f) / 8)
        n['cantidad'] = 'f = 1 - 2^(-8*((z - %.3f)/%.3f)^2)' % (fs * MM, L)
        n['a_distancia'] = {('%g m' % z): round(1 - 2 ** (-8 * max(0.0, (z - fs * MM) / L) ** 2), 3)
                            for z in (5, 10, 20, 30, 40, 50, 70, 100)}
        n['gl_exp2'] = dict(densidad=round(math.sqrt(8 * math.log(2)) / L, 5),
                            nota='GL EXP2 f = 1-exp(-(d*z)^2): exacto si inicio ~ 0; si inicio > 0 GL la adelanta')
        n['gl_lineal'] = dict(inicio=round(fs * MM + t(0.02) * L, 2), fin=round(fs * MM + t(0.97) * L, 2),
                              nota='recta que pasa por f=0.02 y f=0.97 de la curva EXP2 (niebla por vertice del N95)')
    return n


def lit_corte(d, o):
    e = d[o:o + 0x104]
    nl, = struct.unpack('>I', e[4:8])
    ft, fs, fe = struct.unpack('>iff', e[8:20])
    far, = struct.unpack('>f', e[0x44:0x48])
    contraste = list(struct.unpack('>3b', e[0xF5:0xF8]))
    env = dict(
        ambiente_scr=c255(e[0:3]), ambiente_em=c255(e[0xFC:0xFF]), ambiente_esp=c255(e[0x100:0x103]),
        niebla=niebla_de(ft, fs, fe, e[20:24]),
        niebla_espejo=dict(tipo=struct.unpack('>i', e[0x18:0x1C])[0], inicio_m=r(struct.unpack('>f', e[0x1C:0x20])[0] * MM, 3),
                           fin_m=r(struct.unpack('>f', e[0x20:0x24])[0] * MM, 3), color=c255(e[0x24:0x27])),
        foco=dict(z=struct.unpack('>i', e[0x28:0x2C])[0], flag=e[0x2C], nivel=e[0x2D], modo=e[0x2E]),
        far_play_ratio=r(far, 4), lejos_m=r(fe * MM * (1 - far) + 0.001, 3) if ft else None,
        hokan_frames=e[0x48],
        blur=dict(rate=e[0x2F], tipo=e[0xF0], power=struct.unpack('>b', e[0xF1:0xF2])[0]),
        contraste=dict(nivel=contraste[0] & 0xFF, pow=contraste[1] & 0xFF, bias=contraste[2] & 0xFF, crudo=contraste),
        tune=dict(on=e[0x30], colores=[list(e[0x34 + 4 * k:0x38 + 4 * k]) for k in range(3)],
                  nota='m_Tune no lo lee nadie en el decomp: ignorar'),
        tev_scale=list(e[0x40:0x42]), tev_mult=[2 ** x for x in e[0x40:0x42]],
        viento=dict(direccion=struct.unpack('>b', e[0xEC:0xED])[0], potencia=e[0xED], frecuencia=e[0xEE]),
        mipmap=dict(min_lod=e[0xF2], max_lod=e[0xF3], aniso=e[0xF4], lod_bias=r(struct.unpack('>f', e[0xF8:0xFC])[0])),
        n_luces=nl, luces=[])
    for k in range(nl):
        w = d[o + 0x104 + 0x12C * k:o + 0x104 + 0x12C * (k + 1)]
        if w[0] == 0:
            continue
        sp = w[0x2C:0x6C]
        sub = w[0x6C:0xEC]
        env['luces'].append(dict(
            n=k, encendida=bool(w[0] & 2), be_flag=w[0], tipo=w[1], atenuacion=ATENUACION.get(w[1], '?'),
            clase=w[2], manejador=MANEJADOR.get(w[2], '?'), mascara_pantalla=w[3],
            pos=r([c * MM for c in struct.unpack('>3f', w[4:16])]), radio=r(struct.unpack('>f', w[16:20])[0] * MM, 3),
            color=c255(w[20:23]), color_255=list(w[20:24]), intensidad=r(struct.unpack('>f', w[24:28])[0], 3),
            padre=w[0x1C], dir=r(struct.unpack('>3f', sp[0:12])),
            a=[r(x, 5) for x in struct.unpack('>3f', sp[0xC:0x18])], k=[r(x, 6) for x in struct.unpack('>3f', sp[0x18:0x24])],
            trabajo=trabajo_tipo(w[2], sub)))
    return env


def lit_archivo(d):
    cn, ver, nmax = struct.unpack('>HBB', d[:4])
    offs = struct.unpack('>%dI' % cn, d[4:4 + 4 * cn])
    return dict(version=ver, n_max=nmax, cortes=[lit_corte(d, o) if o else None for o in offs])


# ---------------------------------------------------------------------------------------------------------------
#  filtro (Filter00) por corte: la cuenta por pixel
# ---------------------------------------------------------------------------------------------------------------
def filtro_de(env):
    b, c = env['blur'], env['contraste']
    activo_blur = b['rate'] != 0
    activo_con = 1 <= c['nivel'] <= 3
    out = dict(blur_activo=activo_blur, contraste_activo=activo_con,
               tev_mult_modelos=env['tev_mult'][0], tev_mult_personajes=env['tev_mult'][1],
               foco_activo=env['foco']['nivel'] != 0)
    if activo_blur:
        a = b['rate'] / 255.0
        if b['tipo'] in (0, 1):
            out['blur'] = dict(formula='S = %.4f*B + %.4f*S  (B = pantalla anterior ya filtrada, 256x224 bilineal)'
                               % (a, 1 - a), gl='glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA), alfa %.4f' % a)
        else:
            p = (b['power'] & 0xFF) / 255.0
            out['blur'] = dict(formula='S += %.4f*max(B - %.4f, 0)' % (a, p), gl='SUBTRACT(TEXTURE,CONST) + (SRC_ALPHA, ONE)')
    if activo_con:
        k = [1, 2, 4][c['nivel'] - 1]
        out['contraste'] = dict(formula='S += %.4f * clamp(%d*(B - %.4f), 0, 1)' % (c['pow'] / 255, k, c['bias'] / 255),
                                gl='COMBINE SUBTRACT(TEXTURE, CONST=%.4f) RGB_SCALE %d, alfa %.4f, (SRC_ALPHA, ONE)'
                                   % (c['bias'] / 255, k, c['pow'] / 255))
    f = env['foco']
    if f['nivel']:
        tbl = [0, .6, 1.5, 2.6, 1.5, 1.6, 1.6, 2.5, 2.6, 4.5, 6.6]
        lv = min(f['nivel'], 10)
        n = 1 if lv <= 3 else (2 if lv == 4 else (3 if lv == 5 else 4))
        zp = min(max(f['z'] / 65535.0, 0.0), 0.99999)
        N, F = 0.1, 1000.0
        dist = F * N / (F - zp * (F - N))
        out['profundidad_de_campo'] = dict(
            filtro='Filter01 (filter01.cpp): copia la pantalla a 1/2 (promedio vertical + caja 2x2) y la redibuja n=%d '
                   'veces corrida +-%.1f px (diagonales), cada una S = 0.5*T + 0.5*S, con depth test %s contra '
                   'z = FocusZ/65535' % (n, tbl[lv], 'GEQUAL (borronea lo MAS CERCA que el foco)' if f['modo'] == 0
                                         else 'LEQUAL (borronea lo MAS LEJOS que el foco)'),
            nivel=lv, pasadas=n, corrimiento_px=tbl[lv], modo='cerca' if f['modo'] == 0 else 'lejos',
            foco_z=f['z'], foco_distancia_m=round(dist, 3),
            gl='glCopyTexSubImage2D a T; n quads corridos +-d px, textura T, alfa 0.5, (SRC_ALPHA, ONE_MINUS_SRC_ALPHA), '
               'glDepthMask(0), glDepthFunc(%s), quad a profundidad de ventana %.5f (near 0.1, far 1000)'
               % ('GL_GEQUAL' if f['modo'] == 0 else 'GL_LEQUAL', zp))
    return out


# ---------------------------------------------------------------------------------------------------------------
#  CAM (areas de camara: cada una elige el corte del LIT) / EAR (areas de efectos) / SAR
# ---------------------------------------------------------------------------------------------------------------
def cam_areas(d):
    nc, na, nl = d[4], d[5], d[6]
    out = []
    for i in range(na):
        rr = d[0x10 + 0x10 * i:0x20 + 0x10 * i]
        ao, co = struct.unpack('>II', rr[8:16])
        A = d[ao:ao + 0x30]
        an, cn, attr = struct.unpack('b', A[1:2])[0], struct.unpack('b', A[2:3])[0], A[3]
        h, by = struct.unpack('>ff', A[0x20:0x28])
        n, po = struct.unpack('>iI', A[0x28:0x30])
        pts = [struct.unpack('>3f', d[po + 12 * k:po + 12 * k + 12]) for k in range(n)]
        C = d[co:co + 0x34]
        automatica = not (attr & 4)
        out.append(dict(registro=i, area_no=an, corte_lit=an if automatica else None, habilitada=bool(A[0] & 1),
                        attr=attr, prioridad=('primero (attr 0x20)' if attr & 0x20 else 'normal') if automatica else
                        'NUNCA por posicion (attr 4): camara de guion', tipo_camara=C[2],
                        piso_m=r(by * MM, 3), alto_m=r(h * MM, 3),
                        poligono_xz=[[r(p[0] * MM, 3), r(p[2] * MM, 3)] for p in pts]))
    return out


def ear_areas(d):
    import re4_extract_r100 as R
    n, = struct.unpack('>I', d[:4])
    out = []
    for i in range(n):
        rr = d[0x10 + 0x98 * i:0x10 + 0x98 * (i + 1)]
        a = R.area_data(rr[4:0x34])
        a.update(no=rr[0], area_no=rr[2], en_cuarto=bool(struct.unpack('>I', rr[0x34:0x38])[0] & 1))
        out.append(a)
    return out


# ---------------------------------------------------------------------------------------------------------------
#  efectos
# ---------------------------------------------------------------------------------------------------------------
TEX_QUE = {0x72: 'ruido (grano de pantalla)', 0x32: 'cuadrado blanco suave (parche de luz / sombra)',
           0x51: 'voluta de humo tenue', 0x53: 'humo', 0x1E: 'nube de humo/polvo', 0x1F: 'nube de humo/niebla',
           0xC4: 'niebla', 0xCA: 'niebla', 0xCB: 'mata de pasto', 0xD0: 'helecho/planta', 0xD8: 'ramitas',
           0xF1: 'hoja', 0xF3: 'pino joven', 0xF4: 'mosca (4 cuadros)', 0xD9: 'gusanos (12 cuadros)', 0xF6: 'arbusto',
           0x26: 'llama', 0x2E: 'bola de fuego / llama', 0x08: 'brillo radial', 0xE9: 'haz de luz vertical',
           0xE2: 'rocio / gotitas', 0x03: 'sangre', 0x04: 'sangre', 0x06: 'sangre', 0x07: 'sangre', 0x09: 'sangre',
           0x16: 'sangre', 0xFC: 'nube (mancha)', 0x1B: 'onda (anillo)', 0x57: 'salpicadura (puntos)', 0xCD: 'gota',
           0x12: 'mancha de hollin'}

SST_QUE = {  # (no de sst) -> que es, a mano mirando posiciones/texturas
    0: 'GRANO de pantalla (esp04 ruido, alfa 15) + parche de luz en el piso de la casa (MOD2X)',
    1: 'tres TELAS colgando (esp4E: tela con resortes y viento, tex 51) en el camino/casas',
    2: 'follaje falso (impostores de arbustos/pasto) cerca del puente oeste',
    3: 'NEBLINA/polvo en el aire dentro y alrededor de la casa (nubes grandes lentas)',
    4: 'MOSCAS y GUSANOS (carne podrida) en la casa',
    5: 'NIEBLA atmosferica alrededor de la camara (esp15 clima, 60 nubes)',
    6: 'esp46 -> Filter03 BRILLO (glow) de lo que escribe alfa en el EFB (las llamas, tool 0x8000): '
       'suma (40,25,12)/255 * alfa_borroso a la pantalla',
    7: 'CHIMENEA: fuego (llamas + humo + resplandor) y haces de luz por las ventanas de la casa',
    8: 'follaje falso alrededor de la casa (pinos, pasto, helechos, arbustos)',
    9: 'vapor/neblina del barranco (debajo del puente)',
    10: 'follaje falso (camino este)',
    11: 'follaje falso (zona del arroyo)',
    12: 'follaje falso (camino central)',
    13: 'follaje falso (arroyo)',
    14: 'neblina y rocio del arroyo/cascada',
    15: 'AUTO QUEMADO en el barranco: fuego + humo negro (bandera 0x11: solo despues de s40)',
    16: 'CADAVER colgado: sangre que gotea (bandera 0x12; no en Japon)',
}

BLEND_GL = {0: ['GL_SRC_ALPHA', 'GL_ONE_MINUS_SRC_ALPHA'], 1: ['GL_SRC_ALPHA', 'GL_ONE'], 2: ['GL_ONE', 'GL_ONE'],
            3: ['GL_DST_COLOR', 'GL_ONE'], 4: ['GL_DST_COLOR', 'GL_ZERO'], 5: ['GL_SRC_ALPHA', 'GL_ONE_MINUS_SRC_COLOR']}
BLEND_NOMBRE = {0: 'alfa', 1: 'aditivo', 2: 'suma', 3: 'mod2x (src*dst + dst)', 4: 'multiplicar', 5: 'pantalla'}


ESP_DESC = {   # esp*.cpp: que es cada id y que hace ademas de CommonMove
    0x00: 'sprite animado comun (billboard que solo rota en Z; orientado con tool bit0)',
    0x04: 'OVERLAY de pantalla en mosaico (512x448): cada frame pos = base + azar(+-Work8[1], +-Work8[2]) '
          'envuelto; mosaico de Size_x x Size_y pixeles; Work8[0] bit0/1 repite en x/y',
    0x05: 'aleteo (hoja/ceniza): x += P sin(th), z += P cos(1.7th), y += 0.3P cos(1.9th); th += S(rand+0.2)',
    0x06: 'sprite que recorre un CAMINO (path Work8[0]/[1]) a velocidad Work32[0] (+-Work32[2]); '
          'Work8[2] bit0 loop con espera WorkSp8[0]+azar WorkSp8[1]; path = Rot(Vec1 grados) * Escala(1+Vec0/10)',
    0x08: 'quad en mosaico con UV que se desplaza: du,dv por frame = Work32[0,1]*0.001; Work8[0..1] repeticiones',
    0x0A: 'estela / haz: 50 copias del sprite sobre la trayectoria simulada (vel, acel, arrastre) = haz de luz con polvo',
    0x0B: 'sprite con TEMBLOR: cada frame offset nuevo = lado*Vec0.x*azar + arriba*Vec0.y*azar - frente*Vec0.z '
          '(ejes de camara)',
    0x0E: 'destello de lente (pantalla, sin profundidad), alfa por distancia al centro, cono y oclusion por Z',
    0x10: 'calcomania en el piso (y = piso + 65 mm + Vec0.y)',
    0x11: 'LUZ dinamica (no se dibuja): copia la luz Work8[2] del corte Work8[1] del LIT (Work8[0]: 0 core, 1 cuarto)',
    0x12: 'estela texturizada', 0x15: 'CLIMA: particulas en una caja alrededor de la CAMARA (ver clima)',
    0x40: 'sobre la superficie del agua (y = agua + Pos.y + vaiven)',
    0x46: 'NO se dibuja: Filter03 (glow del alfa del EFB) con color rgb*alfa/255, prioridad Work8[1]',
    0x47: 'sprite de pantalla que se envuelve en los bordes', 0x4A: 'temblor de camara',
    0x48: 'sprite que se BALANCEA (pasto, colgados): ang += A*sin(t*F), t += 0.01/frame (t0 azar +-2pi); '
          '(A, F) = (Vec0.x/10 rad, Vec0.y) en x, Vec1 en y, Vec2 en z; con tool 0x80000 = billboard eje Y',
    0x4E: 'TELA colgante (resortes K 7.5, gravedad 0.5, amortiguacion 0.98, fila de arriba fija) con viento seno',
    0xFE: 'modelo de escombros (obj05)',
}


def especificos(q):
    """parametros propios de cada id (ver ESP_DESC)."""
    i, w8, v0 = q['Id'], q['Work8'], q['Vec0']
    if i == 0x15:
        R = q['R_pos'][2]
        k = 1 - w8[2] / 100.0
        return dict(caja_radio_m=r(R * MM), caja='a los lados y arriba +-0.6R, adelante 0..R desde la camara; al salir se '
                    'envuelve al otro lado', desvanecer_lejos='alfa *= 1 - (d - R*%.2f)/(R*%.2f) si d > %.2f m'
                    % (k, 1 - k, R * k * MM), borrar_lejos_cerca_m=[w8[0] * 0.1, w8[1] * 0.1],
                    frames_fundido_interior=w8[3], y_minima_m=r(v0[0] * MM))
    if i == 0x04:
        return dict(temblor_px=[w8[1], w8[2]], repetir_xy=[bool(w8[0] & 1), bool(w8[0] & 2)],
                    mosaico_px=[q['Size_base_x'], q['Size_base_y']],
                    gl='quad a pantalla, textura repetida cada %gx%g px (de 512x448), uv + azar(+-%d, +-%d px) cada frame'
                       % (q['Size_base_x'], q['Size_base_y'], w8[1], w8[2]))
    if i == 0x48:
        return dict(balanceo={'x': [r(v0[0] / 10.0), r(v0[1])], 'y': [r(q['Vec1'][0] / 10.0), r(q['Vec1'][1])],
                              'z': [r(q['Vec2'][0] / 10.0), r(q['Vec2'][1])]},
                    nota='[amplitud rad, frecuencia]; t += 0.01 por frame')
    if i == 0x0B:
        return dict(temblor_m=[r(v0[0] * MM), r(v0[1] * MM)], hacia_camara_m=r(v0[2] * MM))
    if i == 0x06:
        return dict(camino=[w8[0], w8[1]], flags=w8[2], velocidad=q['Work32'][0], espera=q['WorkSp8'][:2],
                    escala=r([1 + x / 10.0 for x in v0]), rot_grados=r(q['Vec1']))
    if i == 0x08:
        return dict(uv_por_frame=[q['Work32'][0] * 0.001, q['Work32'][1] * 0.001], repeticiones=[w8[0] / 10 + 1, w8[1] / 10 + 1])
    if i == 0x46:
        a = q['Col_start'][3] / 255.0
        return dict(filter03_color_255=[int(c * a) for c in q['Col_start'][:3]], nivel=struct.unpack('b', bytes([w8[0]]))[0],
                    prioridad=w8[1])
    if i == 0x0A:
        return dict(modo=w8[2], vida_copias=struct.unpack('b', bytes([w8[0]]))[0], copias=50)
    return None


def tool_bits(f):
    return [n for b, n in re4_eff.TOOL_BITS.items() if f & (1 << b)]


def emisor_de(rec, tex_arch, texlookup):
    """registro EspGenWork -> emisor generico. Unidades: m, s (30 fps), por-frame guardado tal cual + convertido."""
    q = rec
    esgen = q['Kind'] == 1
    w8, w16 = q['Espgen_work8'], q['Espgen_work16']
    tx = texlookup(q['Tex_id'])
    texinfo = None
    if q['Id'] not in re4_eff.NO_TEX_IDS and tx is not None:
        a = tx['anm']
        texinfo = dict(id='0x%02X' % q['Tex_id'], que=TEX_QUE.get(q['Tex_id'], '?'), archivos=tex_arch.get(q['Tex_id'], []),
                       cuadros=a['Frames'], loop=a['Loop'], W=a['W'], H=a['H'], Cx=a['Cx'], Cy=a['Cy'],
                       tiempos=a['times'], cuadros_por_frame=((q['Anm_rate'] + 0x20) & 0xFF) / 32.0,
                       cuadro_inicial=q['Ptn_no'])
    sim = re4_eff.simulate(q, 400)
    muerte = sim[-1] if len(sim[-1]) == 2 else None
    vida_sim = muerte[0] if muerte else None
    e = dict(
        esp_id='0x%02X' % q['Id'], esp_nombre=re4_eff.ESP_NAMES.get(q['Id'], 'esp%02X' % q['Id']),
        retardo_frames=q['Set_time'],
        generador=dict(espgen_id='0x%02X' % q['Espgen_id'], vida_frames=w16[0], espera_frames=w8[0],
                       por_emision=w8[1] + 1, espera_azar=q['Espgen_work8_3'][0], flags=q['Espgen_flg'],
                       reparto_360_y=bool(q['Espgen_flg'] & 1), curvas_D=q['Espgen_work8_2'],
                       vec0=r(q['Espgen_vec0'])) if esgen else None,
        pos_m=r([x * MM for x in q['Pos']]), pos_azar_m=r([x * MM for x in q['R_pos']]),
        vel_m_s=r([x * MM * FPS for x in q['Speed']]), vel_azar_m_s=r([x * MM * FPS for x in q['R_speed']]),
        arrastre_por_frame=r(q['D_speed'], 5), arrastre_por_s=r(q['D_speed'] ** FPS, 5) if q['D_speed'] > 0 else 0,
        acel_m_s2=r([x * MM * FPS * FPS for x in q['Speed_plus']]),
        acel_azar_m_s2=r([x * MM * FPS * FPS for x in q['R_speed_plus']]),
        ang_grados=r(q['Ang'], 3), ang_azar_grados=r(q['R_ang'], 3),
        vel_ang_grados_s=r([x * FPS for x in q['Ang_plus']], 3), vel_ang_azar_grados_s=r([x * FPS for x in q['R_ang_plus']], 3),
        tamano_m=[r(q['Size_base_x'] * MM), r(q['Size_base_y'] * MM)], tamano_azar_m=r(q['R_size_base'] * MM),
        crecimiento_por_frame=r(q['Size_plus'], 6), freno_crecimiento_por_frame=r(q['D_size_plus'], 5),
        color=c255(q['Col_start'][:3]), alfa=r(q['Col_start'][3] / 255.0),
        color_mult_por_frame=r(q['Col_d'], 5), alfa_mult_por_s=r(q['Col_d'][3] ** FPS, 5),
        aparicion_frames=q['Col_max_cnt'], sostener_frames=q['Col_start_cnt'],
        vida_max_frames=q['Life_max'], vida_simulada_frames=vida_sim,
        muere_por=muerte[1] if muerte else ('fin de la animacion (no loop)' if re4_eff.anim_life(q, tx) else
                                            'no muere (permanente)'),
        vida_anim_frames=re4_eff.anim_life(q, tx),
        blend=q['Blend_type'], blend_nombre=BLEND_NOMBRE.get(q['Blend_type'], '?'), blend_gl=BLEND_GL.get(q['Blend_type']),
        tool_flg='0x%X' % q['Tool_flg'], tool_bits=tool_bits(q['Tool_flg']),
        billboard=('orientado (no mira a la camara)' if q['Tool_flg'] & 1 else
                   ('billboard eje Y' if q['Tool_flg'] & 0x80000 else 'billboard')),
        parte=q['Parts_no'], borrar_lejos_cerca=[q['Del_far'], q['Del_near']],
        textura=texinfo, que_hace=ESP_DESC.get(q['Id'], '?'), especificos=especificos(q),
        dibujo='sin cull, Z test LEQUAL sin escritura (tool 0x200000 escribe Z), alpha test > 0, CON niebla de escena, '
               'color = textura * color' + (', iluminado' if q['Tool_flg'] & 0x40 else ''))
    return e


def exportar_texturas(effs, ids_por_eff, carpeta):
    """PNG por cuadro + tira horizontal si hay animacion. -> {tex_id: [archivos]}"""
    from PIL import Image
    os.makedirs(carpeta, exist_ok=True)
    out = {}
    for pref, eff in effs:
        for tid in sorted(ids_por_eff.get(pref, ())):
            if tid not in eff.tex:
                continue
            arch = []
            imgs = []
            for k, fr in enumerate(eff.tex[tid]['frames']):
                img = re4_eff.decode_tex(fr['fmt'], fr['w'], fr['h'], fr['data'], fr['pal'])
                nombre = '%s_tex%02X_f%d.png' % (pref, tid, k)
                with open(os.path.join(carpeta, nombre), 'wb') as fh:
                    fh.write(re4_eff.png_bytes(img))
                arch.append(nombre)
                imgs.append(Image.open(os.path.join(carpeta, nombre)).convert('RGBA'))
            if len(imgs) > 1:
                w, h = imgs[0].size
                tira = Image.new('RGBA', (w * len(imgs), h))
                for k, im in enumerate(imgs):
                    tira.paste(im, (k * w, 0))
                nombre = '%s_tex%02X_tira%d.png' % (pref, tid, len(imgs))
                tira.save(os.path.join(carpeta, nombre))
                arch.append(nombre)
            out[tid] = arch
    return out


def secuencias(eff, lista, datos):
    d = eff.d
    if not lista or not datos:
        return []
    n, = struct.unpack_from('>I', d, lista)
    out = []
    for i in range(n):
        no, typ, flg = struct.unpack_from('>HHI', d, lista + 4 + 8 * i)
        s = eff._seq(datos + struct.unpack_from('>I', d, datos + 4 + 4 * i)[0])
        out.append((i, no, typ, flg, s))
    return out


# ---------------------------------------------------------------------------------------------------------------
def main():
    das = archive.Archive(DAS)
    ent = {e.index: e for e in das.entries()}
    por_tag = {}
    for i in sorted(ent):
        por_tag.setdefault(ent[i].tag, []).append(ent[i].data)
    lit_cuarto = lit_archivo(por_tag['LIT'][0])
    lit_tercero = lit_archivo(por_tag['LIT'][1])
    cams = cam_areas(por_tag['CAM'][0])
    ears = ear_areas(por_tag['EAR'][0])
    sar_num, = struct.unpack('>I', por_tag['SAR'][0][:4])
    evd = dict(archive.parse_event(open(EVD, 'rb').read()))
    ev = json.load(open(EVENTO_JSON)) if os.path.isfile(EVENTO_JSON) else None

    out_look = os.path.join(HERE, 'out', 'r100_look')
    out_fx = os.path.join(HERE, 'out', 'r100_fx')
    os.makedirs(out_look, exist_ok=True)
    os.makedirs(out_fx, exist_ok=True)

    # ---- luces del evento: un .lit por corte (se usa su corte 0: ExePacket_Lit -> roomLitSet + update(0, -1)) ----
    luces_evento = []
    prev = None
    cortes_ev = ev['cortes'] if ev else [dict(indice=i, lit='event/r100/s03/etc/s03_%03d.lit' % i) for i in range(21)]
    for c in cortes_ev:
        if not c.get('lit') or c['lit'] not in evd:
            continue
        la = lit_archivo(evd[c['lit']])
        env = la['cortes'][0]
        cambios = []
        if prev:
            for k in ('ambiente_em', 'ambiente_esp', 'far_play_ratio', 'tev_scale'):
                if env[k] != prev[k]:
                    cambios.append('%s %s -> %s' % (k, prev[k], env[k]))
            if env['niebla'] != prev['niebla']:
                cambios.append('niebla %s..%s -> %s..%s m' % (prev['niebla']['inicio_m'], prev['niebla']['fin_m'],
                                                             env['niebla']['inicio_m'], env['niebla']['fin_m']))
            pl = {(l['n']): l for l in prev['luces'] if l['encendida']}
            el = {(l['n']): l for l in env['luces'] if l['encendida']}
            for n in sorted(set(pl) | set(el)):
                a, b = pl.get(n), el.get(n)
                if a is None:
                    cambios.append('luz %d PRENDE %s tipo %d en %s' % (n, b['color_255'][:3], b['tipo'], b['pos']))
                elif b is None:
                    cambios.append('luz %d se apaga' % n)
                else:
                    dif = [k for k in ('pos', 'radio', 'color', 'intensidad', 'tipo', 'dir') if a[k] != b[k]]
                    if dif:
                        cambios.append('luz %d cambia %s' % (n, ', '.join('%s %s->%s' % (k, a[k], b[k]) for k in dif)))
        luces_evento.append(dict(corte=c['indice'], frame_inicio=c.get('inicio'), archivo=c['lit'],
                                 version=la['version'], n_cortes_archivo=len(la['cortes']),
                                 filtro=filtro_de(env), cambios_vs_anterior=cambios, env=env))
        prev = env

    # ---- efectos ----
    eff_room = re4_eff.Eff(por_tag['EFF'][0], 'r100')
    core = re4_eff.load_effs(CORE, 1)[0]
    eff_ev = re4_eff.Eff(evd['event/r100/s03/etc/r100s03.eff'], 'r100s03')

    def texlookup_de(eff):
        return lambda t: eff.tex.get(t) or core.tex.get(t)
    grupos = []   # (fuente, eff, i, no, tipo, flg, seq)
    for i, no, typ, flg, s in secuencias(eff_room, eff_room.h[3], eff_room.h[9]):
        grupos.append(('sst_cuarto', eff_room, i, no, typ, flg, s))
    for i, no, typ, flg, s in secuencias(eff_room, eff_room.h[2], eff_room.h[8]):
        grupos.append(('est_cuarto', eff_room, i, no, typ, flg, s))
    for i, no, typ, flg, s in secuencias(eff_ev, eff_ev.h[2], eff_ev.h[8]):
        grupos.append(('est_evento', eff_ev, i, no, typ, flg, s))
    usados = {'r100': set(), 'core': set(), 'r100s03': set()}
    for fuente, eff, i, no, typ, flg, s in grupos:
        for q in s['records']:
            ids = set()
            if q['Id'] not in re4_eff.NO_TEX_IDS:
                ids.add(q['Tex_id'])
            if q['Tool_flg'] & 0x4000:
                ids.add(q['MaskTex_id'])
            for t in ids:
                (usados[eff.name] if t in eff.tex else usados['core']).add(t)
    carpeta_tex = os.path.join(out_fx, 'tex')
    tex_arch = {}
    for pref, eff in (('core', core), ('r100', eff_room), ('r100s03', eff_ev)):
        tex_arch.update(exportar_texturas([(pref, eff)], {pref: usados.get(pref, set())}, carpeta_tex))

    ear_por_no = {a['area_no']: a for a in ears}
    em_grupos = []
    for fuente, eff, i, no, typ, flg, s in grupos:
        if fuente == 'sst_cuarto':
            if typ == 0xFFFF:
                cuando = 'siempre (SstSet al entrar al cuarto, pre-corrido 200 frames: game.cpp)'
            else:
                cuando = 'mientras Leon (pos + 0.1 m) esta dentro del area EAR %d; al salir se BORRA todo (EffSetAreaState)' % typ
            bandera = no & 0xFF
            nota_bandera = {0x11: 'r100.cpp: apagada hasta que cae el auto (Room_flg 10)',
                            0x12: 'r100.cpp: apagada en la version japonesa'}.get(bandera, 'encendida')
            que = SST_QUE.get(i, '?')
        elif fuente == 'est_cuarto':
            cuando = 'solo si el codigo llama EstSet(EFF_ROOM, 0x%02X) (r100.cpp: est 0 = estanque, TexRender)' % no
            que = 'est 0x%02X del cuarto (disparado por codigo/golpes)' % no
            bandera, nota_bandera = None, None
        else:
            corte = next((c['corte'] for c in (ev or {}).get('efectos_por_corte', {}).get('cortes', []) if c['est_id'] == no), None)
            cuando = 'cinematica s03, corte %s' % corte
            que = 'polvo/humo del evento (patadas, caidas) cerca de (-80.6, 0.85, -38.6)' if no else 'polvo del evento (colgado de partes del modelo)'
            bandera, nota_bandera = None, None
        tl = texlookup_de(eff)
        recs = [emisor_de(q, tex_arch, tl) for q in s['records']]
        crudo = [{k: (list(v) if isinstance(v, tuple) else v) for k, v in q.items()} for q in s['records']]
        em_grupos.append(dict(fuente=fuente, indice=i, no=no, tipo_lista=typ, que=que, cuando=cuando,
                              area_ear=ear_por_no.get(typ) if fuente == 'sst_cuarto' and typ != 0xFFFF else None,
                              bandera_visible=bandera, bandera_nota=nota_bandera,
                              cabeza=dict(pos_m=r([x * MM for x in s['pos']]), rot_grados=r(s['rot_deg']), parte=s['parts']),
                              emisores=recs, crudo=crudo))
    fx = dict(
        fuente='r100.das EFF (sst = efectos del cuarto, est = por codigo) + core.das EFF (texturas comunes) + r100s03.eff',
        unidades='metros, segundos (30 fps); *_por_frame = valor del juego por frame; colores 0..1',
        semantica=dict(
            por_frame='pos += vel; vel = (vel + acel) * arrastre; tam_mult += crec; crec *= freno (muere si tam_mult<=0); '
                      'ang += vel_ang; t<=aparicion: alfa = alfa0*t/aparicion; t >= aparicion+sostener: rgba *= color_mult '
                      '(muere si alfa < 4/255); muere en vida_max si != 0',
            tamano='cuadrado completo = tamano_m * tam_mult (centrado salvo Cx/Cy de la textura: Cy=H -> ancla abajo)',
            generador='espgen: cada espera_frames (+azar) emite por_emision particulas durante vida_frames (0 = siempre)'
                      '; pos = pos + azar uniforme en +-pos_azar',
            blend='ver blend_gl (glBlendFunc). mod2x: src*dst + dst', texturas='out/r100_fx/tex'),
        areas_ear=ears,
        grupos=em_grupos)
    with open(os.path.join(out_fx, 'emisores.json'), 'w') as f:
        json.dump(fx, f, indent=1, ensure_ascii=False)

    # ---- fuego de la chimenea ----
    luz_fuego = []
    for ci, env in enumerate(lit_cuarto['cortes']):
        if env:
            for l in env['luces']:
                if l['clase'] == 1:
                    luz_fuego.append(dict(corte=ci, **{k: l[k] for k in ('n', 'encendida', 'pos', 'radio', 'color_255',
                                                                        'intensidad', 'tipo', 'trabajo')}))
    for le in luces_evento:
        for l in le['env']['luces']:
            if l['clase'] == 1 and l['encendida']:
                luz_fuego.append(dict(corte_evento=le['corte'], **{k: l[k] for k in ('n', 'pos', 'radio', 'color_255',
                                                                                     'intensidad', 'tipo', 'trabajo')}))
    fuego_sst = next(g for g in em_grupos if g['fuente'] == 'sst_cuarto' and g['no'] == 9)
    fuego = dict(
        luz=dict(resumen='luz n=2, tipo 2 (cuadratica, 0.1 en el radio), clase 1 = Light01_Move (light01.cpp)',
                 parpadeo='cada frame a 30 fps: k = Rnd() % (2*rango) - rango, rango = 12 -> k en [-12, 11]; '
                          'DispCol.rgb = clamp(Col.rgb + k, 0, 255) con el MISMO k en r,g,b; intensidad y radio fijos. '
                          'Rnd = LCG de 16 bits (rnd.cpp) ~ uniforme 0..255 -> ruido blanco, sin suavizado ni periodo.',
                 rango=12, color_base_255=[128, 113, 60], variacion_relativa='r +-9%, g +-11%, b +-20% (el azul cambia mas)',
                 por_corte=luz_fuego),
        efecto=dict(sst_no=9, area='EAR 2 (interior de la casa: -85.6..-68 x, -44.9..-22.1 z)',
                    registros={'0': 'humo que sube (tex 1E) cada 10 frames', '1': 'llamas (tex 2E) cada 8 frames, aditivo',
                               '2-4': 'tres llamas fijas (tex 26), aditivo', '10-12': 'resplandor naranja (tex 08, 255,165,70) MOD2X',
                               '5,8,13': 'polvo en los haces de luz de las ventanas', '6,7': 'haces de luz (tex E9)',
                               '9': 'parche de luz (tex 32) MOD2X', '14': 'mancha de hollin (tex 12)'},
                    posicion_m=[-76.4, 1.0, -36.4], nota='el fuego es del CUARTO (sst), no del evento: el evento solo trae polvo'),
    )

    # ---- look.json ----
    cortes_usados = sorted({a['corte_lit'] for a in cams if a['corte_lit'] is not None} | {0})
    look = dict(
        fuente='r100.das (LIT #0 = cuarto 16 cortes, LIT #1 = tercero, CAM, EAR, SAR, EFF) + Evd/r100s03.evd',
        filtro=dict(
            resumen='En r100 el filtro de pantalla (Filter00) NO hace nada: blur_rate = 0 y contraste nivel 0 en todos '
                    'los cortes del cuarto y del evento (ver por_corte). Lo que SI da el look: tev_scale 1 (x2 en el TEV), '
                    'niebla EXP2 color (141,135,117), grano de pantalla (sst 0: esp04 tex 72 alfa 15/255) y la '
                    'niebla de particulas (sst 5).',
            formula_filter00=dict(
                blur='tipos 0/1: S = a*B + (1-a)*S, a = blur_rate/255, B = copia 256x224 del frame ANTERIOR ya filtrado '
                     '(realimentacion). Tipo 1: uv inset p = blur_power/1024 (zoom radial). Tipo 2: S += a*max(B - P, 0)',
                contraste='campos contrast[0..2] = (nivel, pow, bias): si nivel 1..3: S += (pow/255)*clamp(k*(B - bias/255), 0, 1),'
                          ' k = 1/2/4 (es un bloom sobre umbral, no una curva)',
                tune='m_Tune: nadie lo lee (ignorar)', gamma='GXSetDispCopyGamma(0) = 1.0; brillo de opciones b: salida *= b/64',
                tev_scale='ultimo TEV de cada modelo: out = clamp(prev * 2^tev_scale[grupo]); grupo 0 mapa/objetos/enemigos, '
                          'grupo 1 Leon/Ashley/NPC. r100: [1, 1] -> x2'),
            filter03_glow=dict(
                fuente='sst 6 (esp46, siempre): Filter03SetParam(nivel 0 -> 2 pasadas, color (40,25,12)) cada frame',
                formula='A = alfa del EFB (solo lo escriben los sprites con tool 0x8000: las LLAMAS de la chimenea y del '
                        'auto; el fondo tiene alfa 0) copiado a 1/2, 1/4 y borroneado 2x2 veces con offsets 0.008 uv; '
                        'S += (40,25,12)/255 * A_borroso  (blend ONE, ONE; sin niebla)',
                gl='dibujar cada llama OTRA VEZ como halo: quad 2-3x mas grande, textura suave (tex 08 brillo radial), '
                   'color (40,25,12)/255 * alfa_llama, glBlendFunc(GL_ONE, GL_ONE), sin niebla, sin escribir Z'),
            gl='nada de pantalla completa para r100. Grano: quad a pantalla con la textura de ruido 0x72 repetida, '
               'color (1,1,1,15/255), glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA), uv desplazado al azar cada frame.',
            por_corte_cuarto=[dict(corte=i, **filtro_de(e)) for i, e in enumerate(lit_cuarto['cortes']) if e],
            por_corte_evento=[dict(corte=l['corte'], **l['filtro']) for l in luces_evento]),
        cielo=None,   # lo completa el bloque de abajo
        areas_luz=dict(
            regla='cam_ctrl.cpp areaHitCheck/switchCamera: el corte del LIT = area_no de la AREA DE CAMARA (CAM) donde '
                  'esta Leon (pos.y + 0.1 m entre piso y piso+alto, punto en poligono XZ). Primero las de attr 0x20, '
                  'despues en orden; se mantiene la actual mientras siga adentro. Fuera de toda area: corte 0. '
                  'Las de attr 4 son camaras de guion (nunca por posicion).',
            mezcla='update(cut, -1): las LUCES y el ambiente cambian AL INSTANTE (deleteScr + loadLit); solo la NIEBLA '
                   '(inicio, fin, color) se interpola en hokan frames (hokanMove: x = (x*h + nuevo)/(h+1), h-- cada frame,'
                   ' = lerp lineal en h frames; r100 hokan = 50 frames = 1.67 s)',
            sar=dict(num=sar_num, nota='SAR vacio (0 areas). Ademas el SAR solo escala la luz de PERSONAJES '
                                       '(light_area.cpp), no del mapa'),
            areas_camara=cams,
            casa='interior de la casa = area de camara 4 -> corte LIT 4 (niebla 9.8..62.4 m, luces interiores 6-12, '
                 'far 0.603)',
            cortes_usados=cortes_usados),
        luces_cuarto=dict(lit=dict(version=lit_cuarto['version'], n_max=lit_cuarto['n_max']),
                          cortes=lit_cuarto['cortes'], tercer_lit=lit_tercero),
        luces_evento=dict(regla='event.cpp ExePacket_Lit: al empezar cada corte roomLitSet(s03_NNN.lit) + update(0, -1): '
                                'se usa el corte 0 del archivo; niebla interpolada hokan frames, luces al instante. '
                                'Al terminar el evento vuelve el LIT del cuarto (corte 0 hasta que cambie el area).',
                          cortes=luces_evento),
        fuego=fuego,
        correcciones_horneado=dict(
            nota='diferencias entre re4_extract_r100.py (Luces) y el juego (light.cpp setModel2, trans_lit.cpp '
                 'LightSetModel, scroll.cpp) para las piezas del mapa:',
            mascara='SelectMask bit i = 1 -> la luz i SI ilumina (light.cpp:539 saltea si el bit es 0). El extractor '
                    'lo usa al reves.',
            xF='solo luces con (xF & 0x10) (EnableMask de SMD = 0x10, scroll.cpp:226/662): en el corte 0 NO iluminan '
               'el mapa las luces 1 (xF 0x47) y 5 (xF 0x06), que son para personajes',
            ambiente='mapa: AmbientScr (corte 0 = 2,2,2 casi negro), no AmbientEm (26,26,24)',
            material='color de material = tinte SMX (info->color); modelos self-lit (bin flag 0x40000000): ambiente = '
                     'color de vertice, material = tinte',
            maximo='8 luces por objeto, en orden del pool, y solo si el volumen de la luz toca la caja del objeto '
                   '(lightHitCheck)'),
        )
    look['cielo'] = cielo_info(ent, lit_cuarto)
    with open(os.path.join(out_look, 'look.json'), 'w') as f:
        json.dump(look, f, indent=1, ensure_ascii=False)
    n_em = sum(len(g['emisores']) for g in em_grupos)
    print('look.json: %d cortes del cuarto, %d areas de camara, %d cortes del evento' %
          (sum(1 for c in lit_cuarto['cortes'] if c), len(cams), len(luces_evento)))
    print('emisores.json: %d grupos, %d registros, %d texturas -> %s' % (len(em_grupos), n_em, len(tex_arch), out_fx))


def cielo_info(ent, lit_cuarto):
    """datos del cielo (SMD #0, work con la textura 8 del comun). La explicacion va en CIELO_NOTAS."""
    import re4_extract_r100 as R
    smds = [ent[i] for i in sorted(ent) if ent[i].tag == 'SMD']
    raiz, comun = R.Smd(smds[0].data, 'raiz'), R.Smd(smds[1].data, 'comun')
    smx = R.smx([ent[i] for i in sorted(ent) if ent[i].tag == 'SMX'][0].data)
    works = []
    for wi, w in enumerate(raiz.works):
        if w['bin'] == 0xFF or max(w['sc']) < 5:
            continue
        src = comun if (w['flags'] & R.FLAG_BIN_COMUN) else raiz
        m = src.malla(w['bin'])
        texs = sorted({p.tex_id for p in m.parts})
        if 8 not in texs:
            continue
        rec = smx.get(w['id'])
        works.append(dict(work=wi, id=w['id'], pos_m=r([c * MM for c in w['pos']]), escala=r(w['sc']), texturas=texs,
                          flags='0x%X' % w['flags'],
                          smx=dict(rec, color='0x%08X' % rec['color'], mascara='0x%08X' % rec['mascara'],
                                   flags='0x%08X' % rec['flags']) if rec else None))
    import numpy as np
    img = comun.texturas(0)[8].decode()
    media = (img[..., :3].reshape(-1, 3).astype(float).mean(0) / 255).round(4).tolist()
    c0 = lit_cuarto['cortes'][0]
    info = dict(works=works, textura8_color_medio=media, niebla_corte0=c0['niebla'], tev_scale=c0['tev_scale'])
    info.update(CIELO_NOTAS)
    return info


CIELO_NOTAS = dict(
    como_se_dibuja='SMD #0 work 2 (id 2, bin 0 propio, 1 parte, tex 8 CMPR 256x256). SMX: ot_type 2 (SCROLL PRE) -> '
                   'tabla 0xB cubeta 4: se dibuja ANTES que el resto del escenario (trans.cpp ModelTrans / AddOtDirect). '
                   'Z test LEQUAL y Z write ON. Proyeccion GX normal: ZNEAR 0.1 m, ZFAR 1000 m; View.setFarPlane solo '
                   'recorta en CPU (esfera enorme -> siempre pasa). Blend 0 (alfa normal), alfa 1.',
    iluminacion='modelo "self-lit" (bin flag 0x40000000): canal 0 con luz, ambiente = color de vertice (0.502), '
                'material = tinte SMX 0xF0F0F0 (0.941). Luces permitidas (SelectMask 0xFFFFFF11 y xF & 0x10): 0 y 4 '
                '(paralelas) -> 0.502 + 0.65 + 0.24 satura -> rasterizado = 0.941',
    tev='color = tex * 0.941 * 2^tev_scale[0] = tex * 1.88 (tev_scale 1)',
    niebla='SI: GX_FOG_PERSP_EXP2 del corte (-1.09..106.9 m, color 141,135,117). Casi todo el anillo esta a 50-214 m '
           '-> f 0.73..1: el cielo es practicamente el COLOR DE LA NIEBLA. Por eso se ve amarillo palido.',
    fondo='bio4_AddBgColor (gx_sub.cpp): antes de todo se pinta un quad a pantalla con el COLOR DE LA NIEBLA (alfa 0)',
    scroll_uv='(-0.001212, 0.000001) por frame (30 fps) sumado a la matriz de textura',
    receta_gl='1) glClearColor = color de niebla. 2) cielo primero, depth test LEQUAL + write, far >= 250 m. '
              '3) sin luces; color de vertice (1.88,1.88,1.88) via GL_COMBINE MODULATE + GL_RGB_SCALE 2 con color 0.941. '
              '4) niebla ENCENDIDA igual que el mapa (EXP2 densidad 0.0218/m o lineal). 5) glMatrixMode(GL_TEXTURE) '
              'translate(-0.001212*frame, 0.000001*frame).',
    nota_extractor='re4_extract_r100.py pinta el cielo solo con el tinte 0.941 (sin x2 y sin niebla, porque va antes '
                   'de la Niebla) -> hay que ponerlo DESPUES del objeto Niebla o darle el color de la niebla.')


if __name__ == '__main__':
    main()
