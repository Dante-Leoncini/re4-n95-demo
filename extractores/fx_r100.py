"""
fx_r100.py: el LOOK del juego en r100 (lo usa make_r100_w3d.py). Datos de re4_extract_look.py:
  out/r100_fx/emisores.json   los efectos del cuarto (sst): fuego de la chimenea, neblina, niebla de clima...
  out/r100_look/look.json     cortes de luz (LIT) por area de camara, niebla por corte, la luz del fuego

Lo que agrega:
  * EMISORES (particulas de Whisk3D) traducidos 1:1 de los records del juego (unidades ya en m / s):
      - CHIMENEA (sst 7): humo, llamas (flipbook de 30 cuadros, aditivo), 3 llamas fijas, resplandor naranja y los
        haces de luz de las ventanas.
      - NEBLINA de adentro de la casa (sst 3): nubes grandes y lentas.
      - NIEBLA DE CLIMA (sst 5, esp15): 60 nubes en una caja que acompania a la camara de juego (el emisor es hijo de
        la Camara; las particulas viven en el mundo). Adentro de la casa se apaga (el juego la funde en 30 frames).
  * LUCES para los PERSONAJES por zona (el mapa ya trae la luz horneada): afuera el corte 0, adentro de la casa el
    corte 4 (con la luz del fuego). fx.lua prende un grupo u otro.
  * NIEBLA por zona: afuera la del corte 0, adentro la del corte 4 (empieza a 9.8 m y termina a 62 m).
  * fx.lua: el parpadeo de la luz del fuego como Light01_Move del juego (cada frame k = azar(-12..11)/255 sumado a
    los tres canales del color base), las llamas fijas (se emiten una vez al arrancar), y el cambio de zona.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, 'out', 'r100_fx')
TEX = os.path.join(FX, 'tex')
LOOK = os.path.join(HERE, 'out', 'r100_look', 'look.json')
F = 30.0

# grupos sst que se traducen (indice en emisores.json['grupos'] con fuente sst_cuarto) y su prefijo de nombre
GRUPOS = {7: 'fx_chimenea', 3: 'fx_neblina_casa'}
CLIMA = 5          # la niebla de clima (esp15), va colgada de la camara
SALTEAR = ('0x0A',)   # 'motion-trail sprites': sin equivalente barato
# los sprites ORIENTADOS (no miran a la camara) solo se usan si son un brillo radial (se ve igual de frente):
# los haces de luz (E9), el parche de luz (32) y el hollin del piso (12) quedarian parados mirando a la camara.
ORIENTADOS_OK = ('0x08',)


def _textura(t, tex_dir=None):
    """(archivo, cuadros) de la textura de un emisor: la tira si es animada."""
    tex_dir = tex_dir or TEX
    if not t:
        return None, 1
    tid = t['id'][2:].upper().zfill(2)
    n = t.get('cuadros', 1)
    if n > 1:
        a0 = (t.get('archivos') or ['core_tex%s_f0.png' % tid])[0]   # <eff>_texXX_f0.png -> <eff>_texXX_tiraN.png
        tira = a0.replace('_f0.png', '_tira%d.png' % n)
        if os.path.isfile(os.path.join(tex_dir, tira)):
            return tira, n
    f = t['archivos'][0] if t.get('archivos') else None
    return f, 1


def _mezcla(e):
    b = tuple(e.get('blend_gl') or ())
    if b == ('GL_SRC_ALPHA', 'GL_ONE'):
        return 3, 1.0              # aditiva ponderada por alfa (el "aditivo" del juego)
    if b == ('GL_ONE', 'GL_ONE'):
        return 2, 1.0
    if 'mod2x' in (e.get('blend_nombre') or ''):
        return 3, 0.35             # MOD2X (src*dst + dst) no existe en GL fijo: aditiva suave que aclara igual
    return 1, 1.0


def particula(e, nombre, pos=None, tex_dir=None, ruta='texturas/fx/'):
    """un record del juego -> objeto particulas de Whisk3D. Estatico (sin generador) = 1 particula eterna que emite
    fx.lua una vez al arrancar (las llamas fijas, el resplandor)."""
    tex, cuadros = _textura(e.get('textura'), tex_dir)
    mez, kalfa = _mezcla(e)
    gen = e.get('generador')
    estatico = gen is None
    tam = sum(e['tamano_m']) / 2.0
    plus = e.get('crecimiento_por_frame', 0.0) or 0.0
    D = e.get('freno_crecimiento_por_frame', 1.0) or 1.0
    if abs(plus) < 1e-5:
        crec, freno = 0.0, 1.0
    elif D >= 0.9999:
        crec, freno = plus * F, 1.0
    else:
        crec, freno = plus * F * (-math.log(D)) / (1.0 - D), D ** F
    t = e.get('textura') or {}
    una_vez = 'fin de la animacion' in (e.get('muere_por') or '')
    if e.get('vida_max_frames'):
        vida = e['vida_max_frames'] / F
    elif una_vez and cuadros > 1:
        vida = cuadros / (F * max(1e-3, t.get('cuadros_por_frame', 1.0)))
    elif e.get('vida_simulada_frames'):
        vida = e['vida_simulada_frames'] / F
    else:
        vida = 3600.0              # permanente
    cantidad = 0.0
    if gen and gen.get('espera_frames', 0) > 0:
        cantidad = gen.get('por_emision', 1) * F / gen['espera_frames']
    o = {'tipo': 'particulas', 'nombre': nombre, 'rot': [0, 0, 0], 'escala': [1, 1, 1],
         'pos': [round(c, 4) for c in (pos or e['pos_m'])],
         'textura': (ruta + tex) if tex else '',
         'cantidad': round(cantidad, 4), 'vida': round(vida, 3), 'tam': round(tam, 4),
         'vel': 0, 'dispersion': 0, 'gravedad': 0, 'mezcla': mez,
         'color': [round(c, 4) for c in e['color']] + [round(min(1.0, e['alfa'] * kalfa), 4)],
         'desvanecer': False, 'activo': True, 'variacion': 0, 'turbulencia': 0,
         'velLocal': [round(c, 5) for c in e['vel_m_s']], 'velAzar': [round(c, 5) for c in e['vel_azar_m_s']],
         'posAzar': [round(c, 5) for c in e['pos_azar_m']], 'aceleracion': [round(c, 5) for c in e['acel_m_s2']],
         'arrastre': round(e.get('arrastre_por_s', 1.0), 6), 'crecimiento': round(crec, 5),
         'frenoCrecimiento': round(freno, 6), 'alphaDecae': round(e.get('alfa_mult_por_s', 1.0), 8),
         'alphaMuerte': round(4 / 255.0, 5), 'rotInicial': e['ang_grados'][2], 'rotAzar': e['ang_azar_grados'][2],
         'velRotacion': e['vel_ang_grados_s'][2], 'velRotAzar': e['vel_ang_azar_grados_s'][2],
         'giroSignoAzar': False, 'radioEmision': 30}
    if cuadros > 1:
        o.update(flipCuadros=cuadros, flipCols=cuadros, flipFilas=1,
                 flipFps=round(F * t.get('cuadros_por_frame', 1.0), 3), flipUnaVez=una_vez)
    return o, estatico, tex


def emisores():
    """-> (objetos particulas sueltos, emisor de clima (hijo de la camara), nombres estaticos, texturas usadas)"""
    E = json.load(open(os.path.join(FX, 'emisores.json')))
    sst = [g for g in E['grupos'] if g.get('fuente') == 'sst_cuarto']
    objs, estaticos, texs = [], [], set()
    for gi, pref in GRUPOS.items():
        g = sst[gi]
        for k, e in enumerate(g['emisores']):
            if e['esp_id'] in SALTEAR:
                continue
            tid = (e.get('textura') or {}).get('id')
            if 'orientado' in (e.get('billboard') or '') and tid not in ORIENTADOS_OK:
                continue
            pos = list(e['pos_m'])
            t = e.get('textura') or {}
            if t.get('H') and t.get('Cy'):   # el pivote del sprite (Cx, Cy en pixeles) -> el centro del quad
                pos[1] += (t['H'] / 2.0 - t['Cy']) / t['H'] * -e['tamano_m'][1]
            o, est, tex = particula(e, '%s_%02d' % (pref, k), pos=pos)
            if not est and tid in ('0x1E', '0x1F'):
                # humo / neblina: nacen fundiendo (el juego las hace aparecer en Col_max_cnt frames) y se funden al
                # pasar pegadas a la camara (una nube de 1.8 m atravesada por la camara llenaba la pantalla de golpe)
                o.update(aparecer=1.0 if tid == '0x1F' else 0.3, fundeCerca=[0.3, 1.5])
            objs.append(o)
            if est:
                estaticos.append(o['nombre'])
            if tex:
                texs.add(tex)
    # NIEBLA DE CLIMA (esp15): 60 nubes en una caja frente a la camara (a los lados y arriba +-0.6R, adelante
    # 0..R). El emisor va COLGADO de la camara (hijo): nace adelante, las particulas quedan en el mundo.
    e = sst[CLIMA]['emisores'][0]
    R = e['especificos']['caja_radio_m']
    clima, _, tex = particula(e, 'fx_clima', pos=[0, 0, -R / 2.0])
    # sin pops: nace fundiendo, se apaga a lo largo de la vida y, como en el juego, se funde con la distancia a la
    # camara (entera hasta R/2, nada en R) y se borra pegada a ella (1 m)
    vida = 6.0
    clima.update(cantidad=round(60 / vida, 3), vida=vida, desvanecer=True, posAzar=[0.6 * R, 0.6 * R, R / 2.0],
                 radioEmision=0, aparecer=1.5, fundeCerca=[1.0, 2.0], fundeLejos=[round(R * 0.5, 3), round(R, 3)])
    clima['color'][3] = round(min(1.0, clima['color'][3] * 1.6), 4)   # el apagado por vida baja el promedio
    if tex:
        texs.add(tex)
    return objs, clima, estaticos, sorted(texs)


def _niebla(nombre, n, visible, z50=None):
    # GX EXP2 del juego: f = 1 - 2^(-8 t^2), t = (z - inicio) / (fin - inicio). GL EXP2 no tiene inicio: se ajusta
    # la densidad para que las dos lleguen a MITAD de niebla a la misma distancia (z50); con inicio ~0 (afuera) es
    # casi igual a la exacta, y adentro de la casa (inicio 9.8 m) no llena de niebla los primeros metros.
    # (z50 dado: el N95, que corta el mapa mas cerca, la pide mas espesa)
    z50 = z50 or max(1.0, n['inicio_m'] + math.sqrt(1 / 8.0) * (n['fin_m'] - n['inicio_m']))
    dens = math.sqrt(math.log(2)) / z50
    return {'tipo': 'niebla', 'nombre': nombre, 'pos': [-77.0, 3.0, -30.0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
            'visible': visible, 'activa': True, 'modo': 'exp2', 'inicio': max(0.0, n['inicio_m']),
            'fin': n['fin_m'], 'densidad': round(dens, 5), 'color': n['color'], 'fondo': True}


def nieblas(z50=None):
    """UNA niebla (la de afuera, corte 0); fx.lua la funde a la de adentro de la casa (corte 4) en 50 frames, como el
    hokan del LIT del juego (con dos objetos Niebla el cambio era de golpe). z50: la distancia de mitad de niebla (el
    N95 la quiere mas cerca; None = la del juego)."""
    L = json.load(open(LOOK))
    c = L['luces_cuarto']['cortes']
    return [_niebla('r100_niebla', c[0]['niebla'], True, z50)]


def niebla_casa():
    """(densidad, r, g, b) de la niebla de adentro de la casa"""
    L = json.load(open(LOOK))
    n = _niebla('x', L['luces_cuarto']['cortes'][4]['niebla'], False)
    return [n['densidad']] + list(n['color'])


def luces_interior(luces_lit_fn):
    """las luces de PERSONAJES adentro de la casa (corte 4): las puntuales de adentro, con la del fuego (n 2). Las
    paralelas (n 0, 1) son las mismas afuera y adentro: quedan siempre (tope de 8 luces de GL). Mismo traductor que las de afuera (make_r100_w3d.luces_lit)."""
    L = json.load(open(LOOK))
    c4 = L['luces_cuarto']['cortes'][4]
    sel = [l for l in c4['luces'] if l['n'] in (2, 6, 12)]
    info = {'luz': {'tev_scale': c4['tev_scale'], 'luces': sel}}
    out = luces_lit_fn(info, ns=[l['n'] for l in sel], prefijo='r100_luzcasa_')
    for o in out:
        o['visible'] = False
    return out


LUA = '''-- fx.lua: el LOOK del cuarto (generado por fx_r100.py).
--  * zona: adentro de la casa (camara adentro o cinematica, lo decide r100.lua -> compartido "r100_interior")
--    cambia la NIEBLA (corte 4: mas cerca) y las LUCES de los personajes (corte 4, con el fuego), y apaga la
--    niebla de clima (el juego la funde al entrar);
--  * la luz del FUEGO parpadea como Light01_Move: cada frame k = azar(-12..11)/255 sumado a los 3 canales;
--  * las llamas y el resplandor FIJOS de la chimenea (una particula eterna cada uno) se emiten al arrancar.
local ESTATICOS = {%s}
local AFUERA = {%s}
local ADENTRO = {%s}
local FUEGO = "r100_luzcasa_02"
local NIEBLA_CASA = {%s}          -- densidad, r, g, b (corte 4)
local HOKAN = 50 / 30                 -- el LIT funde la niebla en 50 frames

local obj = {}
local interior = nil
local fuego, fuegoBase = nil, nil
local nieblaAfuera, nieblaT = nil, 0   -- nieblaT: 0 afuera .. 1 adentro

local function lista(nombres)
    local t = {}
    for _, n in ipairs(nombres) do local o = buscar(n); if o then t[#t + 1] = o end end
    return t
end

function inicio()
    obj.afuera, obj.adentro = lista(AFUERA), lista(ADENTRO)
    obj.niebla = buscar("r100_niebla")
    if obj.niebla then nieblaAfuera = {niebla(obj.niebla)} end
    obj.clima = buscar("fx_clima")
    for _, n in ipairs(ESTATICOS) do local o = buscar(n); if o then emitir(o, 1) end end
    fuego = buscar(FUEGO)
    if fuego then local r, g, b = color(fuego); fuegoBase = {r, g, b, energia(fuego)} end
    interior = nil
end

function actualizar(dt)
    local adentro = compartido("r100_interior") == true
    if adentro ~= interior then
        interior = adentro
        for _, o in ipairs(obj.afuera) do setVisible(o, not adentro) end
        for _, o in ipairs(obj.adentro) do setVisible(o, adentro) end
        -- la niebla de clima deja de NACER (las que estan en el aire se funden solas: sin pop)
        if obj.clima then setEmitiendo(obj.clima, not adentro) end
    end
    -- la niebla se FUNDE entre la de afuera y la de adentro
    local obj_t = adentro and 1 or 0
    if obj.niebla and nieblaAfuera and nieblaT ~= obj_t then
        local paso = dt / HOKAN
        if math.abs(obj_t - nieblaT) <= paso then nieblaT = obj_t
        elseif obj_t > nieblaT then nieblaT = nieblaT + paso else nieblaT = nieblaT - paso end
        local a, b, k = nieblaAfuera, NIEBLA_CASA, nieblaT
        setNiebla(obj.niebla, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k,
                  a[4] + (b[4] - a[4]) * k)
    end
    if fuego and fuegoBase and adentro then
        -- la base: la del juego, o la del corte de la cinematica (evento.lua la publica en fuego_r/g/b/e)
        local br, bg, bb, e = fuegoBase[1], fuegoBase[2], fuegoBase[3], fuegoBase[4]
        local ce = compartido("fuego_e")
        if ce then br, bg, bb, e = compartido("fuego_r"), compartido("fuego_g"), compartido("fuego_b"), ce end
        local k = (math.random(0, 23) - 12) / 255
        local r = math.max(0, math.min(1, br * e + k))
        local g = math.max(0, math.min(1, bg * e + k))
        local b = math.max(0, math.min(1, bb * e + k))
        local m = math.max(r, g, b, 1e-4)
        setColor(fuego, r / m, g / m, b / m)
        setEnergia(fuego, m)
    end
end
'''


def lua(estaticos, afuera, adentro):
    q = lambda l: ', '.join('"%s"' % n for n in l)
    return LUA % (q(estaticos), q(afuera), q(adentro), ', '.join('%g' % v for v in niebla_casa()))
