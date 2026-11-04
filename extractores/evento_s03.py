"""
evento_s03.py: arma la CINEMATICA r100s03 (Leon entra a la casa, el ganado lo ataca) adentro de re4_r100.w3d.
Lo usa make_r100_w3d.py. Datos:
  out/evento_s03/evento.json   (re4_extract_evento.py) camara por frame de cada corte, cortes, sonido, subtitulos
  out/ganado/clips.json        (re4_extract_ganado.py) que clip toca cada modelo en cada corte
  out/leon/leon.glb            (re4_extract_leon.py --evento r100s03.evd) los clips s03_cNN de Leon

Lo que agrega al proyecto:
  * 21 camaras s03_cam_NN, cada una con curvas POR FRAME de su corte (posicion, rotacion y fov) en la animacion de
    escena "s03", que ademas trae la pista "Camara activa" con los 21 CORTES (el editor y el juego cambian de camara
    solos al pasar por cada corte). Aspecto 1.77 (las barras negras del juego: cinesco.cpp las dibuja siempre).
  * Ganado + utileria (hacha, foto de Ashley, palo): armatures en el ORIGEN (sus clips llevan la posicion de mundo).
  * Evento_s03_entrada_N: HITBOX (hijos del Empty Evento_s03) que cubren el area del evento (AEV 10), filtro
    "jugador"; Leon lleva el suyo (Leon_hitbox, etiqueta "jugador": hitbox_leon(), en su prefab de la libreria).
  * scripts/evento.lua: espera a que Leon entre al area del evento (alEntrar del hitbox), y ahi reproduce todo: la animacion de
    escena (camaras), el clip de cada personaje por corte (visible solo en los cortes donde el juego lo mueve), el
    audio del evento (voces + efectos + musica ya mezclados en el stream del juego) y la musica del cuarto desde el
    corte 14. Al terminar devuelve el control (compartido "cinematica") y deja a Leon donde lo deja el juego.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTO = os.path.join(HERE, 'out', 'evento_s03', 'evento.json')
CLIPS = os.path.join(HERE, 'out', 'ganado', 'clips.json')
GANADO = os.path.join(HERE, 'out', 'ganado')

# modelo del evento -> objeto en Whisk3D (el armature). Leon de la cinematica es OTRO armature (Leon_ev): el
# personaje como lo arma el EVENTO (cara con formas, chaqueta y manos del evento, detalle completo); el Leon de juego
# (simplificado para el N95, se le ve la nuca) se oculta mientras dura.
OBJETOS = {'pl0000': 'Leon_ev', 'em1000': 'Ganado', 'obm0300': 'Evento_hacha', 'obm1000': 'Evento_foto',
           'obm0500': 'Evento_palo'}
EV = os.path.join(HERE, 'out', 'evento_s03')
CARAS = os.path.join(EV, 'caras.json')
# (glb completo, glb con el atlas a la mitad, nombre del armature)
IMPORTAR = [('leon_evento.glb', 'leon_evento_mitad.glb', 'Leon_ev'), ('ganado_evento.glb', 'ganado_evento_mitad.glb', 'Ganado'),
            (os.path.join(GANADO, 'obm0300.glb'), None, 'Evento_hacha'),
            (os.path.join(GANADO, 'obm1000.glb'), None, 'Evento_foto'),
            (os.path.join(GANADO, 'obm0500.glb'), None, 'Evento_palo')]
OCULTAS = ('Leon_ev_pl000l',)   # una varilla de 31 cm pesada al hueso 0 que el evento carga (marcador, no se ve)
ASPECTO = 1.7725                  # el area visible entre las barras del cinesco (337/448 de alto en 4:3)
LEON_DESPUES = (-82.910, 0.860, -38.480)   # donde el juego deja a Leon al terminar (r100.cpp)
MIRAR_DESPUES = (-79.116, -38.890)          # ...mirando al ganado


def _mallas_glb(ruta):
    import struct
    g = open(ruta, 'rb').read()
    jl = struct.unpack('<I', g[12:16])[0]
    doc = json.loads(g[20:20 + jl])
    return [n.get('name', '') for n in doc['nodes'] if 'mesh' in n]


def lineas_importar(mitad=True):
    """importa los personajes del evento y renombra: armature -> nombre, mallas -> los nombres de los nodos del glb
    (el importador las llama <archivo>, <archivo>.001, ... en el orden de los nodos)."""
    import combate_r100
    out = []
    for full, med, nombre in IMPORTAR:
        ruta = full if os.path.isabs(full) else os.path.join(EV, med if (mitad and med) else full)
        base = os.path.splitext(os.path.basename(ruta))[0]
        out += ['importgltf ' + ruta, 'activename %s_rig' % base, 'objname ' + nombre]
        mallas = _mallas_glb(ruta)
        noms = []
        for k, m in enumerate(mallas):
            nom = m if (m and len(mallas) > 1) else '%s_malla' % nombre
            noms.append(nom)
            out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + nom]
        out += combate_r100.lineas_unir(noms, combate_r100.sueltas_de(noms))   # (menos dibujos: ver lineas_unir)
    return out


def _reducir(keys, tol):
    """Ramer-Douglas-Peucker sobre (frame, valor): saca los keys que la interpolacion lineal ya reproduce."""
    if len(keys) <= 2:
        return keys
    f0, v0 = keys[0]
    f1, v1 = keys[-1]
    peor, ip = -1.0, -1
    for i in range(1, len(keys) - 1):
        f, v = keys[i]
        d = abs(v - (v0 + (v1 - v0) * (f - f0) / float(f1 - f0)))
        if d > peor:
            peor, ip = d, i
    if peor <= tol:
        return [keys[0], keys[-1]]
    return _reducir(keys[:ip + 1], tol)[:-1] + _reducir(keys[ip:], tol)


def curvas_caras():
    """las caras que hablan: una curva AnimShape (p 15) por forma, con el peso POR FRAME del evento (caras.json)."""
    c = json.load(open(CARAS))
    objs = []
    for malla in ('Leon_ev_cara', 'Ganado_ev_cara'):
        if malla not in c:
            continue
        pesos = c[malla]['pesos']
        curvas = []
        for k in range(len(c[malla]['shapes'])):
            keys = [(f + 1, float(pesos[f][k])) for f in range(len(pesos))]
            if max(abs(v) for _, v in keys) < 1e-4:
                continue
            keys = _reducir(keys, 0.003)
            curvas.append({'p': 15, 'c': k, 'k': [[f, round(v, 4), 1, 3, 0, 0, 0, 0] for f, v in keys]})
        if curvas:
            objs.append({'objeto': malla, 'curvas': curvas})
    return objs


def _euler_xyz(eye, tgt, up):
    """rot euler XYZ (grados) de Whisk3D (Qx*Qy*Qz -> R = Rx Ry Rz) para una camara que mira de eye a tgt: la
    camara mira por -Z local con +Y arriba."""
    f = [t - e for t, e in zip(tgt, eye)]
    n = math.sqrt(sum(c * c for c in f)) or 1.0
    f = [c / n for c in f]
    r = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]]
    n = math.sqrt(sum(c * c for c in r)) or 1.0
    r = [c / n for c in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    z = [-c for c in f]
    R = [[r[0], u[0], z[0]], [r[1], u[1], z[1]], [r[2], u[2], z[2]]]   # columnas: derecha, arriba, atras
    b = math.asin(max(-1.0, min(1.0, R[0][2])))
    a = math.atan2(-R[1][2], R[2][2])
    c = math.atan2(-R[0][1], R[0][0])
    return [math.degrees(a), math.degrees(b), math.degrees(c)]


def _continuo(prev, ang):
    if prev is None:
        return ang
    return [x + round((p - x) / 360.0) * 360.0 for x, p in zip(ang, prev)]


def _curva(p, c, keys):
    return {'p': p, 'c': c, 'k': [[f, round(v, 5), 1, 3, 0, 0, 0, 0] for f, v in keys]}   # lineal


def camaras_y_escena(ev):
    """(objetos camara, escena de animacion "s03")"""
    camaras, objs_anim = [], []
    corte_cam = []
    for cam in ev['camara']:
        k = cam['corte']
        nom = 's03_cam_%02d' % k
        pos, rot, fov = [], [], []
        prev = None
        for i in range(cam['frames']):
            frame = cam['inicio'] + i + 1                      # el frame global 0 es el 1 de la escena
            e = _continuo(prev, _euler_xyz(cam['ojo'][i], cam['objetivo'][i], cam['arriba'][i]))
            prev = e
            pos.append((frame, cam['ojo'][i]))
            rot.append((frame, e))
            # fov VISIBLE entre las barras (la proyeccion del juego es 4:3 con el fov de la imagen completa)
            fv = 2 * math.degrees(math.atan(math.tan(math.radians(cam['fov_grados'][i]) / 2) * 337.0 / 448.0))
            fov.append((frame, fv))
        curvas = []
        for comp in range(3):
            curvas.append(_curva(0, comp, [(f, v[comp]) for f, v in pos]))
            curvas.append(_curva(1, comp, [(f, v[comp]) for f, v in rot]))
        curvas.append(_curva(6, 0, fov))                          # AnimFov
        objs_anim.append({'objeto': nom, 'curvas': curvas})
        camaras.append({'tipo': 'camara', 'nombre': nom, 'pos': cam['ojo'][0], 'rot': rot[0][1],
                        'escala': [1, 1, 1], 'fov': round(fov[0][1], 3), 'orto': False, 'near': 0.02, 'far': 300,
                        'aspecto': ASPECTO})
        corte_cam.append({'frame': cam['inicio'] + 1, 'camara': nom})
    escena = {'nombre': 's03', 'inicio': 1, 'fin': ev['frames_totales'], 'fps': 30,
              'camaraActiva': corte_cam, 'objetos': objs_anim + curvas_caras()}
    return camaras, escena


LOOK = os.path.join(HERE, 'out', 'r100_look', 'look.json')


def luces_cortes():
    """las luces de cada corte del evento (look.json luces_evento) en el idioma de las luces de make_r100_w3d:
    paralela -> brillo min(1, max(color) * I * 2); el fuego (n 2) -> tono + brillo relativo a la I del juego (la I base
    va en la atenuacion de la luz, k0 = 1/I)."""
    L = json.load(open(LOOK))
    base = next(l for l in L['luces_cuarto']['cortes'][4]['luces'] if l['n'] == 2)['intensidad']
    out = []
    for c in L['luces_evento']['cortes']:
        por_n = {l['n']: l for l in c['env']['luces']}
        esc = 2.0 ** (c['env']['tev_scale'][0] if c['env'].get('tev_scale') else 1)

        def sol(n):
            l = por_n.get(n)
            if not l or not l.get('encendida', True) or l['tipo'] == 0:
                return 0.0
            return min(1.0, max(l['color']) * l['intensidad'] * esc)
        f = por_n.get(2)
        if f and f.get('encendida', True) and f['tipo'] in (2, 6):
            m = max(f['color']) or 1.0
            e = min(1.0, m * esc * f['intensidad'] / base)
            fs = 'f = {%g, %g, %g, %.4f, %.4f, %.4f, %.3f}' % (tuple(f['pos']) + tuple(x / m for x in f['color']) + (e,))
        else:
            fs = 'f = nil'
        out.append('    {s0 = %.3f, s1 = %.3f, %s},   -- corte %d' % (sol(0), sol(1), fs, c['corte']))
    return '\n'.join(out)


# el HITBOX de Leon (va en su prefab, make_personajes_w3d.py; sin libreria, en el armature del nivel): el cuerpo,
# 0.6 x 1.8 x 0.6 m desde los pies. Etiqueta "jugador": la entrada a la casa solo reacciona a el.
LEON_HITBOX_TAM = (0.6, 1.8, 0.6)
ENTRADA_POS = (-83.3, 1.5, -34.7)     # el Empty Evento_s03 (el padre del hitbox de la entrada)


def hitbox_leon():
    return {'tipo': 'hitbox', 'nombre': 'Leon_hitbox', 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
            'activo': True, 'tam': list(LEON_HITBOX_TAM), 'centro': [0, LEON_HITBOX_TAM[1] / 2.0, 0],
            'etiqueta': 'jugador', 'filtro': '', 'detectarCuerpos': False}


def area_aev10():
    info = json.load(open(os.path.join(HERE, 'out', 'r100', 'r100.json')))
    return next(a for a in info['aev'] if a['no'] == 10)


def caja_area(pts):
    """la caja ORIENTADA (giro en Y) de menor area que contiene el poligono convexo (x, z): (centro x, centro z,
    ancho en su X local, largo en su Z local, giro Y en grados de Whisk3D)"""
    mejor = None
    for k in range(1800):
        t = math.radians(k / 10.0)
        a = [x * math.cos(t) + z * math.sin(t) for x, z in pts]
        b = [-x * math.sin(t) + z * math.cos(t) for x, z in pts]
        ar = (max(a) - min(a)) * (max(b) - min(b))
        if mejor is None or ar < mejor[0] - 1e-9:
            mejor = (ar, t, min(a), max(a), min(b), max(b))
    _, t, a0, a1, b0, b1 = mejor
    ac, bc = (a0 + a1) / 2.0, (b0 + b1) / 2.0
    # su X local es (cos t, sin t) en (x, z): un giro de -t alrededor de +Y (R_y(g) lleva X a (cos g, -sin g))
    return (ac * math.cos(t) - bc * math.sin(t), ac * math.sin(t) + bc * math.cos(t), a1 - a0, b1 - b0,
            -math.degrees(t))


def adentro(pts, d):
    """el cuadrilatero convexo (x, z) con cada lado corrido hacia adentro lo que sobresale de el una caja de medio lado
    'd' alineada a los ejes (el soporte de la caja en la normal del lado: d * (|nx| + |nz|)): una caja asi centrada en
    el poligono achicado toca el lado justo cuando su centro llega al lado original"""
    n = len(pts)
    sx = sum(p[0] for p in pts) / n
    sz = sum(p[1] for p in pts) / n
    rectas = []
    for i in range(n):
        (x0, z0), (x1, z1) = pts[i], pts[(i + 1) % n]
        nx, nz = z1 - z0, -(x1 - x0)
        ln = math.hypot(nx, nz)
        nx, nz = nx / ln, nz / ln
        if (sx - x0) * nx + (sz - z0) * nz < 0:      # la normal hacia el centro
            nx, nz = -nx, -nz
        dd = d * (abs(nx) + abs(nz))
        rectas.append((x0 + nx * dd, z0 + nz * dd, x1 - x0, z1 - z0))
    out = []
    for i in range(n):
        ax, az, adx, adz = rectas[i - 1]
        bx, bz, bdx, bdz = rectas[i]
        den = adx * bdz - adz * bdx
        u = ((bx - ax) * bdz - (bz - az) * bdx) / den
        out.append((ax + adx * u, az + adz * u))
    return out


ENTRADA_TIRAS = 12     # cajas en que se parte el area (el cuadrilatero no es un rectangulo: una sola caja sobraba)


def hitbox_entrada():
    """los HITBOX de la entrada (hijos de Evento_s03): el area AEV 10 del juego. El juego prueba UN punto (los pies de
    Leon + 20 cm) contra un cuadrilatero; un hitbox es una caja, y el de Leon es su CUERPO (LEON_HITBOX_TAM). Asi:
      * el cuadrilatero se achica lo que sobresale medio cuerpo de Leon por lado (adentro()): el cuerpo lo toca cuando
        el CENTRO entra al original (exacto con Leon mirando por los ejes; girado, hasta ~10 cm antes);
      * se parte en ENTRADA_TIRAS tiras (cortes de su lado sur al norte) y cada tira va en la caja orientada mas chica
        que la contiene (sobra a lo sumo un triangulito del lado inclinado, unos centimetros).
    En alto, del piso del area a piso + alto (el juego: pies + 20 cm en [piso - 0.1, piso + alto))."""
    a = area_aev10()
    p = adentro([tuple(v) for v in a['pts']], LEON_HITBOX_TAM[0] / 2.0)
    A, B, C, D = p          # A-B el lado sur, D-C el norte (r100.json: el orden del AEV)
    cy = a['piso'] + a['alto'] / 2.0
    out = []
    for i in range(ENTRADA_TIRAS):
        t0, t1 = i / float(ENTRADA_TIRAS), (i + 1) / float(ENTRADA_TIRAS)
        tira = [(A[0] + (B[0] - A[0]) * t0, A[1] + (B[1] - A[1]) * t0), (A[0] + (B[0] - A[0]) * t1, A[1] + (B[1] - A[1]) * t1),
                (D[0] + (C[0] - D[0]) * t1, D[1] + (C[1] - D[1]) * t1), (D[0] + (C[0] - D[0]) * t0, D[1] + (C[1] - D[1]) * t0)]
        cx, cz, ancho, largo, giro = caja_area(tira)
        out.append({'tipo': 'hitbox', 'nombre': 'Evento_s03_entrada_%d' % i,
                    'pos': [round(cx - ENTRADA_POS[0], 4), round(cy - ENTRADA_POS[1], 4), round(cz - ENTRADA_POS[2], 4)],
                    'rot': [0, round(giro, 3), 0], 'escala': [1, 1, 1], 'activo': True,
                    'tam': [round(ancho, 4), round(a['alto'], 4), round(largo, 4)], 'centro': [0, 0, 0],
                    'etiqueta': 'evento', 'filtro': 'jugador', 'detectarCuerpos': False})
    return out


def lua(ev, clips):
    cortes = []
    for c in ev['cortes']:
        cc = next((x for x in clips['cortes'] if x['corte'] == c['indice']), {'modelos': {}})
        mods = ', '.join('%s = "%s"' % (OBJETOS[m], v['clip']) for m, v in sorted(cc['modelos'].items())
                         if m in OBJETOS)
        cortes.append('    {inicio = %d, frames = %d, clips = {%s}},' % (c['indice'] and c['inicio'] or 0, c['frames'],
                                                                         mods))
    pist = next((m for m in ev['modelos'] if m['nombre'] == 'wep0200'), None)
    pist_cortes = sorted({c['corte'] for c in pist['cortes'] if c.get('visible')}) if pist else []
    streams = ev['sonidos']['streams']
    musica = next((s for s in streams if s.get('loop')), None)
    luces = luces_cortes()
    return '''-- evento.lua: la CINEMATICA r100s03 (Leon entra a la casa y el ganado lo ataca). Generado por evento_s03.py.
--
-- El juego la dispara con el area AEV 10 (adentro de la casa): aca son los HITBOX "Evento_s03_entrada_N" (hijos de
-- este objeto, filtro "jugador", el area partida en tiras): el motor llama alEntrar() cuando entra el de Leon.
-- Todo va con el reloj del evento (30 fps):
--   * las CAMARAS: la animacion de escena "s03" (curvas por frame de cada camara + la pista "Camara activa" con los
--     21 cortes: el motor cambia de camara solo);
--   * los PERSONAJES: en cada corte cada modelo toca SU clip (s03_cNN); un modelo sin motion en un corte no se ve
--     (el juego hace MotClear al empezar cada corte y oculta lo que no se mueve);
--   * el SONIDO: el stream del evento (voces + efectos + musica ya mezclados) desde el frame 0 y la musica del
--     cuarto desde el frame %d.
-- Mientras dura, compartido("cinematica") = true: leon.lua y r100.lua no tocan nada.

local CORTES = {
%s
}
local TOTAL = %d
local PISTOLA_CORTES = {%s}          -- cortes donde se ve la pistola en la mano de Leon (el resto la guarda)
local MUSICA_FRAME = %d
local LEON_DESPUES = {%g, %g, %g}
local MIRAR_DESPUES = {%g, %g}
local MODELOS = {"Leon_ev", "Ganado", "Evento_hacha", "Evento_foto", "Evento_palo"}
-- LUCES por corte (s03_NNN.lit: el juego las cambia AL INSTANTE en cada corte): brillo de las dos paralelas
-- (0 = apagada) y la luz del fuego {x, y, z, r, g, b, brillo}. fx.lua hace parpadear el fuego alrededor de eso.
local LUCES = {
%s
}

local obj = {}
local estado = "espera"      -- espera | cine | fin
local t, corte, musica = 0, -1, false
local vozH                  -- el audio de la cinematica: su reloj (relojCine)
local entro = false          -- alEntrar: Leon entro al area (los hitbox de la entrada)
local musicaH = nil

-- el clip del corte, QUIETO: el frame lo pone actualizar() cada tick (un solo reloj para todo)
local function tocar(nombre, clip)
    local o = obj[nombre]
    if not o then return end
    animClip(o, clip, false, true)
    animVelocidad(o, 0)
end

local function aplicarCorte(k)
    local c = CORTES[k + 1]
    for _, nombre in ipairs(MODELOS) do
        local clip = c.clips[nombre]
        if obj[nombre] then
            setVisible(obj[nombre], clip ~= nil)
            if clip then tocar(nombre, clip) end
        end
    end
    local pist = false
    for _, n in ipairs(PISTOLA_CORTES) do if n == k then pist = true end end
    if obj.pistola then setVisible(obj.pistola, pist) end
    local l = LUCES[k + 1]
    if l then
        if obj.sol0 then setEnergia(obj.sol0, l.s0) end
        if obj.sol1 then setEnergia(obj.sol1, l.s1) end
        if obj.fuego and l.f then
            setPosicion(obj.fuego, l.f[1], l.f[2], l.f[3])
            setCompartido("fuego_r", l.f[4]); setCompartido("fuego_g", l.f[5])
            setCompartido("fuego_b", l.f[6]); setCompartido("fuego_e", l.f[7])
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

-- las luces vuelven a las del juego (corte 4 del cuarto)
local function lucesJuego()
    if obj.sol0 then setEnergia(obj.sol0, obj.base.s0) end
    if obj.sol1 then setEnergia(obj.sol1, obj.base.s1) end
    if obj.fuego then setPosicion(obj.fuego, obj.base.fx, obj.base.fy, obj.base.fz) end
    for _, n in ipairs({"fuego_r", "fuego_g", "fuego_b", "fuego_e"}) do setCompartido(n, nil) end
end

local function empezar()
    estado, t, corte, musica = "cine", 0, -1, false
    vozH = nil
    setCompartido("cinematica", true)
    setCompartido("cine_interior", true)   -- r100.lua: se ve solo lo de adentro de la casa
    setCompartido("hud_visible", false)
    -- el Leon de JUEGO se va; actua el Leon del EVENTO (armature en el origen: los clips llevan la posicion de mundo)
    if obj.Leon then setVisible(obj.Leon, false) end
    animEscena("s03", false)                   -- camaras + cortes + las caras (formas)
    vozH = sonido("sonidos/evento_s03.wav", 1.0)
    info("evento s03: empieza")
end

local function terminar()
    estado = "fin"
    if obj.Leon_ev then setVisible(obj.Leon_ev, false) end
    local leon = obj.Leon
    setVisible(leon, true)
    local dx, dz = MIRAR_DESPUES[1] - LEON_DESPUES[1], MIRAR_DESPUES[2] - LEON_DESPUES[3]
    setPosicion(leon, LEON_DESPUES[1], LEON_DESPUES[2], LEON_DESPUES[3])
    setRotacion(leon, 0, math.deg(math.atan(dx, dz)), 0)   -- (Lua 5.4: math.atan2 ya no existe)
    pararEscena()                              -- la pista de cortes deja de mandar la camara
    lucesJuego()
    -- el ganado del EVENTO se va y aparece el de JUEGO (Ganado_juego, ganado.lua: mismo modelo, con la IA) donde lo
    -- pone el juego (r100_Sce_look), caminando hacia Leon con el hacha
    for _, n in ipairs({"Ganado", "Evento_hacha", "Evento_foto", "Evento_palo"}) do
        if obj[n] then setVisible(obj[n], false) end
    end
    setCompartido("ganado_activo", true)
    -- (visible: Whisk3D no corre los scripts de los objetos ocultos, ganado.lua arranca recien ahora)
    local gj = buscar("Ganado_juego")
    if gj then setVisible(gj, true) end
    if obj.camara then setCamaraActiva(obj.camara) end
    setCompartido("leon_resync", true)         -- leon.lua relee posicion y rumbo (estuvo oculto: no vio nada)
    setCompartido("cinematica", false)         -- leon.lua retoma desde aca
    setCompartido("cine_interior", false)
    setCompartido("hud_visible", true)
    info("evento s03: fin")
end

function inicio()
    for _, n in ipairs(MODELOS) do obj[n] = buscar(n) end
    obj.Leon = buscar("Leon")
    obj.pistola = buscar("Leon_ev_pistola")
    obj.camara = buscar("Cámara")
    obj.sol0, obj.sol1, obj.fuego = buscar("r100_luz_00"), buscar("r100_luz_01"), buscar("r100_luzcasa_02")
    obj.base = {s0 = obj.sol0 and energia(obj.sol0) or 1, s1 = obj.sol1 and energia(obj.sol1) or 1}
    if obj.fuego then obj.base.fx, obj.base.fy, obj.base.fz = posicion(obj.fuego) end
    if obj.Leon_ev then setVisible(obj.Leon_ev, false) end
    -- antes del evento: el ganado espera en su primera pose (la del corte 1), la utileria no se ve
    if obj.Ganado then animClip(obj.Ganado, "s03_c01", false, true); animVelocidad(obj.Ganado, 0) end
    for _, n in ipairs({"Evento_hacha", "Evento_foto", "Evento_palo"}) do
        if obj[n] then setVisible(obj[n], false) end
    end
    estado, entro = "espera", false
    setCompartido("cinematica", false)
end

-- la ENTRADA a la casa: los hitbox Evento_s03_entrada_N (hijos de este objeto: sus eventos llegan a este script)
-- avisan cuando entra el de Leon (filtro "jugador"). Leon oculto (otra cinematica) no participa.
function alEntrar(otro, miHitbox, suHitbox)
    if estado == "espera" and not entro and otro ~= nil and (otro == obj.Leon or nombre(otro) == "Leon") then
        info("evento s03: Leon entra a la casa (hitbox " .. nombre(miHitbox) .. ")")
        entro = true    -- (puede entrar a varias tiras en el mismo tick: cuenta la primera)
    end
end

function actualizar(dt)
    -- el ganado muere: la musica se corta seca (r100_Sce_zombi_dead: SndRoomStrStop); si Leon muere y se
    -- reinicia vuelve a sonar
    if musicaH and compartido("ganado_muerto") then pararSonido(musicaH); musicaH = nil end
    if estado == "fin" and not musicaH and not compartido("ganado_muerto") and compartido("ganado_activo") then
        musicaH = sonido("sonidos/r100_musica.wav", 0.8, 1.0, true)
    end
    if estado == "espera" then
        -- (la dispara alEntrar: el evento llega en el paso de hitbox, ANTES de los actualizar() del tick; empieza
        --  aca, en el mismo tick, como cuando la prueba del area estaba en este actualizar)
        if entro then entro = false; empezar() end
        return
    end
    if estado ~= "cine" then return end
    t = relojCine(vozH, 0, t, dt)
    -- frame CONTINUO (con fraccion): floor(t * 30) con t acumulado en flotante a veces repetia un frame y saltaba
    -- el siguiente (1/30 no es exacto): eso era un micro salto. Con la fraccion los cuerpos y las camaras se
    -- interpolan igual entre dos frames del juego; el corte se decide por el frame entero (+ epsilon).
    local ft = t * 30 + 1e-4
    local f = math.floor(ft)
    if f >= TOTAL then terminar() return end
    local k = corte
    while k + 1 < #CORTES and CORTES[k + 2].inicio <= f do k = k + 1 end
    if k ~= corte then corte = k; aplicarCorte(k) end
    -- UN SOLO RELOJ: camaras, cortes y caras (la animacion de escena) y los cuerpos, todos en el MISMO frame. Con
    -- relojes separados uno se adelantaba un frame: micro saltos del cuerpo contra la camara, y en un corte la
    -- camara nueva llegaba antes que el personaje que aparece en ella.
    animEscenaFrame(ft + 1)
    local c = CORTES[corte + 1]
    for nombre, _ in pairs(c.clips) do
        if obj[nombre] then animFrame(obj[nombre], ft - c.inicio) end
    end
    if not musica and f >= MUSICA_FRAME then
        musica = true
        -- la musica del cuarto en LOOP (bio4bgm #2 con sus puntos de loop) hasta que muere el ganado
        musicaH = sonido("sonidos/r100_musica.wav", 0.8, 1.0, true)
    end
end
''' % (musica['frame_global'] if musica else 10 ** 6, '\n'.join(cortes), ev['frames_totales'],
       ', '.join(str(x) for x in pist_cortes),
       musica['frame_global'] if musica else 10 ** 6, LEON_DESPUES[0], LEON_DESPUES[1], LEON_DESPUES[2],
       MIRAR_DESPUES[0], MIRAR_DESPUES[1], luces)


def aplicar(proy, datos, full=False, libreria=None):
    """agrega camaras, escena de animacion y evento.lua al proyecto (proyecto.json ya cargado en 'proy').
    libreria: Leon viene de la libreria de personajes (libreria_r100.py): la pistola del evento usa la MALLA de la
    libreria (el recurso "<libreria>/Leon_pistola": una sola copia en memoria) y el hitbox de Leon ya esta en su
    prefab. Sin libreria el hitbox se le agrega al armature Leon del nivel."""
    ev = json.load(open(EVENTO))
    clips = json.load(open(CLIPS))
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    camaras, escena = camaras_y_escena(ev)
    col['hijos'].extend(camaras)
    # el script del evento va en un objeto VACIO propio: Whisk3D solo corre los scripts de objetos VISIBLES y el
    # evento oculta a los personajes en los cortes donde no actuan (colgado del Ganado se frenaba en el corte 0)
    # (con el HITBOX de la entrada como hijo: sus eventos le llegan a evento.lua, el script de su padre)
    col['hijos'].append({'tipo': 'objeto', 'nombre': 'Evento_s03', 'pos': list(ENTRADA_POS), 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'scripts': [{'archivo': 'scripts/evento.lua'}],
                         'hijos': hitbox_entrada()})
    anim = proy.get('animaciones') or {'activa': 0, 'escenas': [{'nombre': 'Scene', 'inicio': 1, 'fin': 250,
                                                                  'fps': 30}]}
    anim['escenas'] = [e for e in anim['escenas'] if e.get('nombre') != 's03'] + [escena]
    proy['animaciones'] = anim

    def todos(lista):
        for o in lista:
            yield o
            yield from todos(o.get('hijos', []))
    import make_re4_w3d as base
    for o in list(todos(col['hijos'])):
        if o.get('nombre') in OCULTAS:
            o['visible'] = False
        if o.get('nombre') == 'Leon' and o.get('tipo') == 'armature' and not libreria:
            o['hijos'] = [h for h in o.get('hijos', []) if h.get('nombre') != 'Leon_hitbox'] + [hitbox_leon()]
        if o.get('nombre') == 'Leon_ev' and o.get('tipo') == 'armature':
            # la pistola del evento es la MISMA malla que la de juego (wep0200 = wep02:2): otra instancia con su
            # Child Of a la mano derecha del Leon del evento (hueso_010)
            pist = next((h for h in todos(col['hijos']) if h.get('nombre') == 'Leon_pistola'), None)
            if libreria:
                # la malla es un recurso de la LIBRERIA: el nivel guarda solo su nombre con el prefijo
                o.setdefault('hijos', []).append({
                    'tipo': 'malla', 'nombre': 'Leon_ev_pistola', 'pos': [0, 0, 0], 'rot': [0, 0, 0],
                    'escala': [1, 1, 1], 'malla': libreria.nombre + '/Leon_pistola',
                    'constraints': [base.child_of('Leon_ev')]})
            elif pist:
                cp = json.loads(json.dumps(pist))
                cp['nombre'] = 'Leon_ev_pistola'
                cp['constraints'] = [base.child_of('Leon_ev')]
                cp.pop('hijos', None)
                o.setdefault('hijos', []).append(cp)
        # los personajes del evento van al ORIGEN (sus clips llevan la posicion de mundo). LEON NO: es el jugador y
        # arranca en su spawn; evento.lua lo lleva al origen solo mientras dura la cinematica
        if o.get('nombre') in OBJETOS.values() and o.get('tipo') == 'armature' and o['nombre'] != 'Leon':
            o['pos'], o['rot'] = [0, 0, 0], [0, 0, 0]

        if o.get('tipo') == 'camara' and o.get('nombre') == 'Cámara':
            o['aspecto'] = ASPECTO           # el juego tiene las barras negras siempre (cinesco.cpp)
    datos['scripts/evento.lua'] = lua(ev, clips).encode('utf-8')
    audio = os.path.join(HERE, 'out', 'evento_s03', 'audio')
    extra = {}
    for s in ev['sonidos']['streams']:
        destino = 'sonidos/r100_musica.wav' if s.get('loop') else 'sonidos/evento_s03.wav'
        # FULL: el WAV original (el de la musica trae el chunk smpl con el loop del stream: la intro suena una vez y
        # despues repite 11.6 s .. 51.7 s, sin corte)
        extra[destino] = os.path.join(HERE, 'out', 'evento_s03', s['wav'] if full else s['wav_n95'])
    return extra
