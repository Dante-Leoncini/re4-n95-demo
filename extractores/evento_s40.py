"""
evento_s40.py: los EVENTOS DEL CAMINO de r100 (lo usa make_r100_w3d.py). Datos de re4_extract_intro_r100.py:
  out/evento_s40/  la intro r100s40 (la camioneta de la policia llega, charlan, Leon se baja; 8 cortes, 1175 f)
  out/evento_s41/  charla con el policia de anteojos (pl0700a) junto a la camioneta (160 f)
  out/evento_s43/  charla con el otro policia (pl0700) (110 f)
  out/evento_s44/  los policias en el puente (150 f)
  out/r100_intro/  plan.json (la secuencia del juego), la camara de la VENTANA, los objetos de juego (camioneta
                   estacionada, camion viejo, policias sentados), audio

La secuencia (st1/r100.cpp):
  1. la intro r100s40 apenas arranca la partida (fundido desde negro de 30 frames). Durante un evento los objetos de
     juego que el evento reemplaza no se ven (el evento trae los suyos).
  2. Leon queda en (-99.685, -0.484, -1.343) mirando al camino (rot Y 2.246 rad) y se juega.
  3. junto a la camioneta, el BOTON DE ACCION: la primera vez la charla (s41 / s43, segun el policia); despues el
     policia dice algo corto (su motion 'hablar' + su SE).
  4. al llegar al puente: s44 (una vez).
  5. al entrar al area AEV 0x15 (una vez) la ESCENA DE LA VENTANA: el punto de vista del aldeano que espia por la
     rendija de los postigos; Leon (chico, a lo lejos) camina hacia la casa. Camara del cuarto (152 f) + Leon de
     JUEGO caminando solo (leon.lua con compartido "leon_auto") + el stream #34.
  6. r100s03 (evento_s03.py) y la pelea.

Cada evento va con UN reloj (el frame del evento): camaras y caras (animacion de escena "sNN") y los cuerpos
(animFrame de cada clip), como evento.lua de la casa. Los personajes son UN armature cada uno con los clips de todos
los eventos (tools_r100/unir_clips.py junta los glb de cada evento).
"""
import json
import math
import os
import struct

import evento_s03 as S3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
EV = os.path.join(OUT, 'evento_s40')
INTRO = os.path.join(OUT, 'r100_intro')
PLAN = os.path.join(INTRO, 'plan.json')

# modelo del evento -> (glb con los clips de todos los eventos, armature, renombre de las mallas)
MODELOS = {'pl0000': ('leon_evento_todo.glb', 'Leon_e40', ('Leon_ev_', 'Leon_e40_')),
           'pl0700': ('policia_evento_todo.glb', 'Policia_ev', None),
           'pl0700a': ('policia_a_evento_todo.glb', 'PoliciaA_ev', None),
           'obm1a00': ('obm1a00.glb', 'Camioneta_ev', None),
           'obm2d00': ('../evento_s20/obm2d00.glb', 'Camion_ev', None)}
UNIR = {'leon_evento_todo.glb': ['evento_s40/leon_evento.glb', 'evento_s41/leon_evento.glb', 'evento_s43/leon_evento.glb',
                                 'evento_s20/leon_evento.glb'],
        'policia_evento_todo.glb': ['evento_s40/policia_evento.glb', 'evento_s43/policia_evento.glb',
                                    'evento_s44/policia_evento.glb'],
        'policia_a_evento_todo.glb': ['evento_s40/policia_a_evento.glb', 'evento_s41/policia_a_evento.glb']}
# los objetos de JUEGO (fuera de los eventos): (glb, armature, clip)
JUEGO = [('coche_juego.glb', 'Coche_juego', 'juego'), ('camion_juego.glb', 'Camion_juego', 'juego'),
         ('policia_juego.glb', 'Policia_juego', 'quieto'), ('policia_a_juego.glb', 'PoliciaA_juego', 'quieto')]
OCULTAS = ('Leon_e40_pl000l',)
LEON_INICIO = (-99.685, -0.484, -1.343, 2.246)      # r100_StartEvent: pPL->setPos / setAng

# los eventos del camino. disparo: 'inicio' | ('accion', area AEV) | ('area', area AEV). ocultar: los objetos de
# juego que el evento reemplaza mientras dura. leon: donde queda despues (None = donde lo deja su modelo del evento)
EVENTOS = [
    {'ev': 's40', 'disparo': 'inicio', 'ocultar': [a for _, a, _ in JUEGO], 'leon': LEON_INICIO,
     'fundido_entrada': 30},
    {'ev': 's41', 'disparo': ('accion', 25), 'ocultar': ['PoliciaA_juego'], 'leon': None,
     'despues': ('PoliciaA_juego', 'hablar', 'sonidos/policia_a_hablar.wav')},
    {'ev': 's43', 'disparo': ('accion', 26), 'ocultar': ['Policia_juego'], 'leon': None,
     'despues': ('Policia_juego', 'hablar', 'sonidos/policia_hablar.wav')},
    {'ev': 's44', 'disparo': ('area', 27), 'ocultar': [], 'leon': (-112.251, -0.193, -4.42, None)},
    # el CAMION (r100_Sce_zombi_dead): muerto el ganado de la casa, el camion viejo rueda camino abajo, se lleva la
    # camioneta y el puente. Leon queda donde estaba (EvtStfPlPosNoSet); los vehiculos y los policias no vuelven
    # (quedan en el barranco) y empieza la emboscada
    {'ev': 's20', 'disparo': ('flag', 'ganado_muerto', 3.5), 'leon': False, 'camino_libre': True,
     'ocultar': ['Camion_juego', 'Coche_juego', 'Policia_juego', 'PoliciaA_juego']},
]


def _doc_glb(ruta):
    g = open(ruta, 'rb').read()
    jl = struct.unpack('<I', g[12:16])[0]
    return json.loads(g[20:20 + jl])


def _nodos_malla(ruta):
    doc = _doc_glb(ruta)
    return [n.get('name', '') for n in doc['nodes'] if 'mesh' in n], [a.get('name') for a in doc.get('animations', [])]


def _ruta(glb):
    return os.path.normpath(os.path.join(EV, glb))


def _renombrar(m, pref):
    return m.replace(pref[0], pref[1]) if pref else m


def preparar():
    """arma los glb _todo (si faltan o son viejos) juntando los clips de todos los eventos"""
    import sys
    sys.path.insert(0, os.path.join(HERE, 'tools_r100'))
    import unir_clips
    for dst, fuentes in UNIR.items():
        rutas = [os.path.join(OUT, f) for f in fuentes]
        out = os.path.join(EV, dst)
        if os.path.isfile(out) and os.path.getmtime(out) >= max(os.path.getmtime(r) for r in rutas):
            continue
        unir_clips.unir(out, rutas)


def lineas_importar():
    import combate_r100
    preparar()
    out = []
    for cod, (glb, arm, pref) in MODELOS.items():
        ruta = _ruta(glb)
        base = os.path.splitext(os.path.basename(glb))[0]
        out += ['importgltf ' + ruta, 'activename %s_rig' % base, 'objname ' + arm]
        mallas, _ = _nodos_malla(ruta)
        noms = [_renombrar(m, pref) for m in mallas]
        for k, nom in enumerate(noms):
            out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + nom]
        out += combate_r100.lineas_unir(noms, combate_r100.sueltas_de(noms))   # (menos dibujos: ver lineas_unir)
    for glb, arm, _ in JUEGO:
        ruta = os.path.join(INTRO, glb)
        base = os.path.splitext(glb)[0]
        out += ['importgltf ' + ruta, 'activename %s_rig' % base, 'objname ' + arm]
        mallas, _ = _nodos_malla(ruta)
        for k, m in enumerate(mallas):
            out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + arm + '_malla']
    return out


def _camara(nom, ojo, obj, arriba, fov_img, frame0):
    """curvas de una camara del juego (ojo / objetivo / arriba / fov por frame, proyeccion 4:3) -> (objeto, anim)"""
    pos, rot, fov = [], [], []
    prev = None
    for i in range(len(ojo)):
        f = frame0 + i
        e = S3._continuo(prev, S3._euler_xyz(ojo[i], obj[i], arriba[i]))
        prev = e
        pos.append((f, ojo[i]))
        rot.append((f, e))
        fov.append((f, 2 * math.degrees(math.atan(math.tan(math.radians(fov_img[i]) / 2) * 337.0 / 448.0))))
    curvas = []
    for c in range(3):
        curvas.append(S3._curva(0, c, [(f, v[c]) for f, v in pos]))
        curvas.append(S3._curva(1, c, [(f, v[c]) for f, v in rot]))
    curvas.append(S3._curva(6, 0, fov))
    cam = {'tipo': 'camara', 'nombre': nom, 'pos': ojo[0], 'rot': rot[0][1], 'escala': [1, 1, 1],
           'fov': round(fov[0][1], 3), 'orto': False, 'near': 0.02, 'far': 300, 'aspecto': S3.ASPECTO}
    return cam, {'objeto': nom, 'curvas': curvas}


def _caras(ev):
    c = json.load(open(os.path.join(OUT, 'evento_' + ev, 'caras.json')))
    objs = []
    for malla, pref in (('Leon_ev_cara', MODELOS['pl0000'][2]), ('Policia_ev_cara', None), ('PoliciaA_ev_cara', None)):
        if malla not in c:
            continue
        pesos = c[malla]['pesos']
        curvas = []
        for k in range(len(c[malla]['shapes'])):
            keys = [(f + 1, float(pesos[f][k])) for f in range(len(pesos))]
            if max(abs(v) for _, v in keys) < 1e-4:
                continue
            keys = S3._reducir(keys, 0.003)
            curvas.append({'p': 15, 'c': k, 'k': [[f, round(v, 4), 1, 3, 0, 0, 0, 0] for f, v in keys]})
        if curvas:
            objs.append({'objeto': _renombrar(malla, pref), 'curvas': curvas})
    return objs


def _evento(ev):
    return json.load(open(os.path.join(OUT, 'evento_' + ev, 'evento.json')))


def escenas():
    """camaras + animaciones de escena de cada evento y "ventana" (la camara del aldeano)"""
    camaras, escs = [], []
    for e in EVENTOS:
        d = _evento(e['ev'])
        anim, cortes = [], []
        for cam in d['camara']:
            nom = '%s_cam_%02d' % (e['ev'], cam['corte'])
            o, a = _camara(nom, cam['ojo'], cam['objetivo'], cam['arriba'], cam['fov_grados'], cam['inicio'] + 1)
            camaras.append(o); anim.append(a)
            cortes.append({'frame': cam['inicio'] + 1, 'camara': nom})
        escs.append({'nombre': e['ev'], 'inicio': 1, 'fin': d['frames_totales'], 'fps': 30, 'camaraActiva': cortes,
                     'objetos': anim + _caras(e['ev'])})
    cv = json.load(open(os.path.join(INTRO, 'camara_ventana.json')))
    o, a = _camara('ventana_cam', cv['ojo'], cv['objetivo'], cv['arriba'], cv['fov_grados'], 1)
    camaras.append(o)
    escs.append({'nombre': 'ventana', 'inicio': 1, 'fin': cv['frames'], 'fps': 30,
                 'camaraActiva': [{'frame': 1, 'camara': 'ventana_cam'}], 'objetos': [a]})
    return camaras, escs


def _visibles(ev, d):
    """{corte: modelos visibles} (plan.json para s40; para las charlas, 'cortes' de cada modelo del evento.json)"""
    if ev == 's40':
        plan = json.load(open(PLAN))
        for paso in plan['secuencia']:
            if paso.get('paso') == 2:
                return {c['corte']: set(c['visibles']) for c in paso['cortes']}
    vis = {}
    for m in d.get('modelos', []):
        for c in m.get('cortes', []):
            if c.get('visible'):
                vis.setdefault(c['corte'], set()).add(m.get('nombre'))
    return vis


def _cortes_lua(ev, d):
    vis = _visibles(ev, d)
    clips = {cod: set(_nodos_malla(_ruta(glb))[1]) for cod, (glb, _, _) in MODELOS.items()}
    out = []
    for c in d['cortes']:
        clip = '%s_c%02d' % (ev, c['indice'])
        mods = ', '.join('%s = "%s"' % (arm, clip) for cod, (_, arm, _) in MODELOS.items()
                         if clip in clips[cod] and (not vis or cod in vis.get(c['indice'], set())))
        out.append('{inicio = %d, frames = %d, clips = {%s}}' % (c['inicio'], c['frames'], mods))
    return ', '.join(out)


def _areas(plan):
    """{numero de area AEV: (piso, alto, poligono)} del plan"""
    out = {}
    for paso in plan['secuencia']:
        for op in paso.get('opcionales', []) or []:
            a = op.get('area')
            if a:
                out[a['area']] = (a['piso_m'], a['alto_m'], a['poligono_xz_m'])
        if paso.get('paso') == 5:
            a = paso['disparo']['area']
            out[a['area']] = (a['piso_m'], a['alto_m'], a['poligono_xz_m'])
    return out


def _area_lua(a):
    return '{piso = %g, alto = %g, pts = {%s}}' % (a[0], a[1], ', '.join('{%g, %g}' % tuple(p) for p in a[2]))


LUA = '''-- camino.lua: los EVENTOS DEL CAMINO de r100 (generado por evento_s40.py; out/r100_intro/plan.json).
--   * la intro (s40) al empezar; las charlas con los policias (s41 / s43) con el BOTON DE ACCION junto a la
--     camioneta (despues, el policia dice algo corto); los policias en el puente (s44) al llegar;
--   * la ESCENA DE LA VENTANA (area AEV 0x15, una vez): la camara del aldeano espiando por la rendija de los
--     postigos; Leon camina solo hacia la casa (leon.lua: compartido "leon_auto") con su stream.
-- Cada evento: UN reloj (su frame) para la animacion de escena "sNN" (camaras + caras) y animFrame de cada cuerpo.
-- Mientras corre algo, compartido("cinematica") = true (leon.lua quieto, HUD oculto).

local EVENTOS = {
%s
}
local MODELOS = {%s}
local JUEGO = {%s}
local VENTANA = {area = %s, frames = %d, leon = {%g, %g, %g, %g}}
local BGM_VOL = 0.35

local obj = {}
local visto = {}
local actual = nil          -- el evento que corre (su tabla)
local t, corte = 0, -1
local ventana = "espera"    -- espera | corre | listo
local tv = 0
local audioH, ventanaH       -- los audios de la cinematica y de la ventana: su reloj (relojCine)
local hablaT = {}
local arranque = true
local reaccionVista = 0
local reaccionCual = 1
local bgmH = nil            -- la musica del camino (secuenciada en el juego; aca renderizada, con su loop)
local bgmListo = false

local function dentro(a, x, y, z)
    if y + 0.1 < a.piso or y >= a.piso + a.alto then return false end
    local pts, c = a.pts, false
    local j = #pts
    for i = 1, #pts do
        local xi, zi, xj, zj = pts[i][1], pts[i][2], pts[j][1], pts[j][2]
        if ((zi > z) ~= (zj > z)) and (x < (xj - xi) * (z - zi) / (zj - zi) + xi) then c = not c end
        j = i
    end
    return c
end

local function aplicarCorte(k)
    local c = actual.cortes[k + 1]
    for _, n in ipairs(MODELOS) do
        local o = obj[n]
        if o then
            local clip = c.clips[n]
            setVisible(o, clip ~= nil)
            if clip then animClip(o, clip, false, true); animVelocidad(o, 0) end
        end
    end
end

-- RELOJ de la cinematica: avanza con dt, pero si el AUDIO va mas adelante salta hasta el (el mixer va en tiempo real
-- aunque el cuadro tarde; en el N95 la logica topa el dt a 0.1 s y a menos de 10 fps la animacion se iba quedando
-- atras de la voz): la animacion saltea los frames que haga falta para quedar donde va el sonido (sonidoPosicion, el
-- frameskip del motor). t0 = donde estaba t cuando arranco el sonido. Sin sonido (todavia no, ya termino) solo dt.
-- (Con dt y no SOLO el audio: el harness simula mas rapido que el tiempo real y ahi manda dt, como siempre.)
local function relojCine(h, t0, t, dt)
    local nt = t + dt
    local s = h and sonidoPosicion and sonidoPosicion(h)
    if s and t0 + s > nt then nt = t0 + s end
    return nt
end

local function empezar(e)
    actual, t, corte = e, 0, -1
    visto[e.nombre] = true
    setCompartido("cinematica", true); setCompartido("hud_visible", false)
    if obj.Leon then setVisible(obj.Leon, false) end
    for _, n in ipairs(e.ocultar) do if obj[n] then setVisible(obj[n], false) end end
    if e.fundido > 0 then
        -- fundido DESDE NEGRO (hud.lua: compartido "fundido" = objetivo 1 negro .. 0 nada, en "fundido_seg")
        setCompartido("fundido_ya", 1); setCompartido("fundido", 0); setCompartido("fundido_seg", e.fundido / 30)
    end
    animEscena(e.nombre, false)
    audioH = sonido(e.audio, 1.0)
    info("camino: evento " .. e.nombre)
end

local function terminar()
    local e = actual
    actual = nil
    pararEscena()
    -- donde queda Leon: el lugar fijo del evento o la raiz de su modelo del evento en el ultimo frame
    local l = obj.Leon
    local x, y, z = posicion(l)
    local _, yaw = rotacion(l)
    if e.leon then
        x, y, z = e.leon[1], e.leon[2], e.leon[3]
        if e.leon[4] then yaw = math.deg(e.leon[4]) end
    elseif e.leon == nil and obj.Leon_e40 and visible(obj.Leon_e40) then
        local hx, _, hz = huesoPunto(obj.Leon_e40, "hueso_000")
        local fx, _, fz = huesoPunto(obj.Leon_e40, "hueso_000", 0, 0, 1)
        if hx then x, z = hx, hz; yaw = math.deg(math.atan(fx - hx, fz - hz)) end
    end
    for _, n in ipairs(MODELOS) do if obj[n] then setVisible(obj[n], false) end end
    for _, n in ipairs(e.ocultar) do if obj[n] then setVisible(obj[n], true) end end
    setVisible(l, true)
    setPosicion(l, x, y, z)
    setRotacion(l, 0, yaw or 0, 0)
    if obj.camara then setCamaraActiva(obj.camara) end
    setCompartido("leon_resync", true)
    setCompartido("cinematica", false); setCompartido("hud_visible", true)
    -- despues de la intro, la LLAMADA DE RADIO a Hunnigan (codec.lua)
    if e.nombre == "s40" then setCompartido("codec_llamar", true) end
    -- el camion se fue al barranco: queda ahi (con la camioneta), el camino libre y la emboscada
    if e.camino_libre then
        for _, n in ipairs(e.ocultar) do if obj[n] then setVisible(obj[n], false) end end
        if obj.Camion_ev then setVisible(obj.Camion_ev, true); animClip(obj.Camion_ev, "barranco", true, true) end
        setCompartido("camino_libre", true)
        setCompartido("emboscada", true)
    end
    -- la BGM del cuarto arranca al terminar la intro (SndRoomBgmStart) y sigue en loop
    if not bgmListo then bgmListo = true; bgmH = sonido("sonidos/r100_bgm.wav", BGM_VOL, 1.0, true) end
end

local function empezarVentana()
    ventana, tv = "corre", 0
    setCompartido("hud_visible", false)
    setCompartido("leon_auto_x", VENTANA.leon[1]); setCompartido("leon_auto_y", VENTANA.leon[2])
    setCompartido("leon_auto_z", VENTANA.leon[3]); setCompartido("leon_auto_yaw", math.deg(VENTANA.leon[4]))
    setCompartido("leon_auto", true)
    animEscena("ventana", false)
    ventanaH = sonido("sonidos/ventana.wav", 1.0)
end

local function terminarVentana()
    ventana = "listo"
    pararEscena()
    setCompartido("leon_auto", false)
    if obj.camara then setCamaraActiva(obj.camara) end
    setCompartido("hud_visible", true)
end

function inicio()
    for _, n in ipairs(MODELOS) do obj[n] = buscar(n); if obj[n] then setVisible(obj[n], false) end end
    for _, n in ipairs(JUEGO) do
        local o = buscar(n[1]); obj[n[1]] = o
        if o then animClip(o, n[2], true, true) end
    end
    obj.Leon = buscar("Leon")
    obj.camara = buscar("Cámara")
    actual, visto, ventana, hablaT = nil, {}, "espera", {}
    arranque = true
end

function actualizar(dt)
    -- la cinematica de la casa tiene su propia musica: la del camino se funde
    if bgmH and compartido("cine_interior") then pararSonido(bgmH, 2.0); bgmH = nil end
    if arranque then
        arranque = false
        for _, e in ipairs(EVENTOS) do if e.disparo == "inicio" then empezar(e) return end end
    end
    if actual then
        setCompartido("cinematica", true)
        t = relojCine(audioH, 0, t, dt)
        local ft = t * 30 + 1e-4
        local f = math.floor(ft)
        if f >= actual.total then terminar() return end
        local k = corte
        while k + 1 < #actual.cortes and actual.cortes[k + 2].inicio <= f do k = k + 1 end
        if k ~= corte then corte = k; aplicarCorte(k) end
        animEscenaFrame(ft + 1)
        local c = actual.cortes[corte + 1]
        for nombre, _ in pairs(c.clips) do
            if obj[nombre] then animFrame(obj[nombre], ft - c.inicio) end
        end
        return
    end
    if ventana == "corre" then
        tv = relojCine(ventanaH, 0, tv, dt)
        animEscenaFrame(tv * 30 + 1)
        if tv * 30 >= VENTANA.frames then terminarVentana() end
        return
    end
    -- le APUNTARON y "dispararon" a la camioneta: un policia reacciona (su motion 'hablar' + su voz), alternando
    local rn = compartido("policia_reaccion_n") or 0
    if rn ~= reaccionVista then
        reaccionVista = rn
        for _, e in ipairs(EVENTOS) do
            if e.despues and obj[e.despues[1]] and not hablaT[e.despues[1]] then
                reaccionCual = reaccionCual - 1
                if reaccionCual <= 0 then
                    reaccionCual = 2
                    animClip(obj[e.despues[1]], e.despues[2], false, true)
                    sonido(e.despues[3], 1.0)
                    hablaT[e.despues[1]] = true
                    break
                end
            end
        end
    end
    -- los policias vuelven a su pose de sentados cuando terminan de hablar
    for n, _ in pairs(hablaT) do
        if obj[n] and animTermino(obj[n]) then animClip(obj[n], "quieto", true, true); hablaT[n] = nil end
    end
    if compartido("cinematica") or not obj.Leon then return end
    -- los eventos por FLAG: un tiempo despues de que se prende (el ganado muere y el cuerpo termina de caer)
    for _, e in ipairs(EVENTOS) do
        if e.disparo == "flag" and not visto[e.nombre] and compartido(e.flag) and (compartido("leon_vida") or 1) > 0 then
            e.t = (e.t or 0) + dt
            if e.t >= e.espera then empezar(e) return end
        end
    end
    local x, y, z = posicion(obj.Leon)
    local accion = compartido("leon_accion")
    -- el juego prueba un punto 0.55 m ADELANTE de Leon (a +0.25 m) contra las areas del boton de accion
    local _, ry = rotacion(obj.Leon)
    local r = math.rad(ry or 0)
    local ax_, az_ = x + math.sin(r) * 0.55, z + math.cos(r) * 0.55
    local cartel = nil
    for _, e in ipairs(EVENTOS) do
        if e.area and e.disparo == "area" and dentro(e.area, x, y, z) and not visto[e.nombre] then empezar(e) return end
        if e.area and e.disparo == "accion" and dentro(e.area, ax_, y + 0.25, az_) then
            cartel = "TALK"
            -- cada vez que se aprieta: la charla (el juego la repite)
            if accion then setCompartido("cartel_camino", nil); empezar(e) return end
        end
    end
    setCompartido("cartel_camino", cartel)
    if ventana == "espera" and dentro(VENTANA.area, x, y, z) then empezarVentana() end
end
'''


def lua(plan):
    areas = _areas(plan)
    evs = []
    for e in EVENTOS:
        d = _evento(e['ev'])
        disparo, area, flag = (e['disparo'], None, None) if isinstance(e['disparo'], str) else (e['disparo'] + (None,))[:3]
        if disparo == 'flag':
            area, flag = None, e['disparo'][1:]
        leon = 'false' if e['leon'] is False else 'nil'
        if e['leon']:
            leon = '{%g, %g, %g, %s}' % (e['leon'][0], e['leon'][1], e['leon'][2],
                                         'nil' if e['leon'][3] is None else '%g' % e['leon'][3])
        desp = 'nil' if not e.get('despues') else '{"%s", "%s", "%s"}' % e['despues']
        evs.append('    {nombre = "%s", disparo = "%s", area = %s, total = %d, audio = "sonidos/evento_%s.wav", '
                   'ocultar = {%s}, leon = %s, despues = %s, fundido = %d,%s%s\n     cortes = {%s}},'
                   % (e['ev'], disparo, _area_lua(areas[area]) if area else 'nil', d['frames_totales'], e['ev'],
                      ', '.join('"%s"' % n for n in e['ocultar']), leon, desp, e.get('fundido_entrada', 0),
                      ' flag = "%s", espera = %g,' % flag if flag else '',
                      ' camino_libre = true,' if e.get('camino_libre') else '',
                      _cortes_lua(e['ev'], d)))
    lp = [p for p in plan['secuencia'] if p.get('paso') == 5][0]
    leon = [-80.54, -0.008, -12.073, 2.99]
    for linea in lp['al_empezar']:
        if linea.startswith('Leon a ['):
            nums = linea[len('Leon a ['):].split(']')[0].split(',')
            leon = [float(v) for v in nums] + [float(linea.split('rot Y')[1].split()[0])]
    frames = json.load(open(os.path.join(INTRO, 'camara_ventana.json')))['frames']
    return LUA % ('\n'.join(evs), ', '.join('"%s"' % arm for _, arm, _ in MODELOS.values()),
                  ', '.join('{"%s", "%s"}' % (arm, clip) for _, arm, clip in JUEGO),
                  _area_lua(areas[lp['disparo']['area']['area']]), frames, leon[0], leon[1], leon[2], leon[3])


def aplicar(proy, datos, full=True):
    """camaras, escenas de los eventos y "ventana", el Empty Eventos_camino con camino.lua; -> extra (sonidos)"""
    plan = json.load(open(PLAN))
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    camaras, esc = escenas()
    col['hijos'].extend(camaras)
    col['hijos'].append({'tipo': 'objeto', 'nombre': 'Eventos_camino', 'pos': [-99.7, 1.0, -1.3], 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'scripts': [{'archivo': 'scripts/camino.lua'}]})
    anim = proy.get('animaciones') or {'activa': 0, 'escenas': []}
    nombres = {e['nombre'] for e in esc}
    anim['escenas'] = [e for e in anim['escenas'] if e.get('nombre') not in nombres] + esc
    proy['animaciones'] = anim

    def todos(lista):
        for o in lista:
            yield o
            yield from todos(o.get('hijos', []))
    arms = {a for _, a, _ in MODELOS.values()} | {a for _, a, _ in JUEGO}
    for o in todos(col['hijos']):
        if o.get('nombre') in OCULTAS:
            o['visible'] = False
        if o.get('tipo') == 'armature' and o.get('nombre') in arms:
            o['pos'], o['rot'] = [0, 0, 0], [0, 0, 0]      # los clips llevan la posicion de mundo
    # los vidrios de la camioneta y el camion: mezclados SIN escribir z (sino tapan a lo que se dibuja despues:
    # Leon adentro de la camioneta quedaba detras de un vidrio negro). El pelo de los personajes sigue escribiendo z.
    for m in proy.get('materiales', []):
        n = m.get('nombre', '')
        if 'transparente' in n and n.startswith(('obm1a00', 'obm2d00', 'Coche', 'Camion')):
            m.setdefault('flags', {})['escribeProfundidad'] = False
    datos['scripts/camino.lua'] = lua(plan).encode('utf-8')
    extra = {}
    k = 'wav' if full else 'wav_n95'
    for e in EVENTOS:
        s = _evento(e['ev'])['sonidos']['streams'][0]
        extra['sonidos/evento_%s.wav' % e['ev']] = os.path.join(OUT, 'evento_' + e['ev'], s[k])
    extra['sonidos/ventana.wav'] = os.path.join(INTRO, 'audio', 'str1_034%s.wav' % ('' if full else '_n95'))
    extra['sonidos/r100_bgm.wav'] = os.path.join(OUT, 'bgm', 'r100_bgm.wav')
    extra['sonidos/policia_hablar.wav'] = os.path.join(INTRO, 'audio', 'se_policia_hablar.wav')
    extra['sonidos/policia_a_hablar.wav'] = os.path.join(INTRO, 'audio', 'se_policia_a_hablar.wav')
    return extra
