#!/usr/bin/env python3
"""
Arma re4_r100.w3d: Leon (el de re4.w3d, con sus armas, efectos y leon.lua) parado frente a la casa del primer
ganado, en el escenario r100 del juego, caminando con la colision del juego.

  Coleccion
    Camara, Light (sol direccional)
    Leon ...                          (make_re4_w3d.py: armature + armas + efectos + scripts/leon.lua)
    r100_raiz        Culling          las 13 piezas SIEMPRE cargadas (SMD #0) + scripts/r100.lua
    r100_bloque_0..4 Culling          los 5 bloques del juego (r100_0N.dat); r100.lua los prende/apaga
    r100_col_suelo / r100_col_pared   la colision (SAT) oculta: la usa leon.lua (colSuelo / colPared / colRayo)

LA OCLUSION COMO EN EL JUEGO (block.cpp): el mapa esta partido en 5 bloques; segun el AREA del BLK en la que esta
Leon se dibujan su bloque y los vecinos por link (el resto se descarga). Aca: r100.lua prueba las mismas areas
(areaHitCheck_xz4, en metros) y hace setVisible de cada Culling. Adentro de cada bloque, el Culling (frustum por
AABB = el ModelTrans del juego, esfera contra el frustum) recorta lo que la camara no ve. Los Culling miran SOLO
la camara activa: el viewport libre de la derecha muestra lo que la camara de juego dibuja (se ve aparecer y
desaparecer).

LOS PERSONAJES (Leon con sus armas / efectos / leon.lua, el ganado de la casa y los 7 aldeanos de la emboscada) NO se
importan adentro del nivel: son PROXIES W3D de los prefabs de la libreria re4_personajes.w3d (make_personajes_w3d.py;
si falta, se arma primero). Ver libreria_r100.py. Con --sin-libreria se arma como antes (todo adentro del nivel).

MODO AVANZADO (por defecto): al final el escenario estatico se hornea en mallas unidas que dibujan RUTINAS de Whisk3D
(avanzado_r100.py: muchas menos llamadas GL). --clasico lo deja con los Culling y los LOD de siempre (para comparar, o
para editar el mapa: en el modo avanzado el mundo lo dibujan memorias que escribe r100.lua, se ve al darle Play).

Uso:  python3 make_r100_w3d.py [-o re4_r100.w3d] [--full] [--libreria re4_personajes.w3d | --sin-libreria]
                               [--clasico] [--whisk3d RUTA]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_re4_w3d as base  # noqa: E402
import evento_s03  # noqa: E402
import pvs_interior  # noqa: E402  que se ve desde adentro de la casa
import fx_r100  # noqa: E402  particulas, niebla y luces por zona (el look del juego)
import hud_r100  # noqa: E402  el HUD (Whisk3DUI)
import codec_r100  # noqa: E402  la llamada de radio (Recortes con su camara + UI)
import evento_s40  # noqa: E402  la intro (camioneta) y la escena de la ventana
import combate_r100  # noqa: E402  el ganado de juego (IA), la sangre, el laser, leon.lua con sus tablas
import emboscada_r100  # noqa: E402  despues del camion (r100s20): los aldeanos en guardia y el fin de la demo
import libreria_r100  # noqa: E402  los personajes como proxies de la libreria re4_personajes.w3d
import avanzado_r100  # noqa: E402  el modo avanzado: el escenario horneado en rutinas
import n95_r100  # noqa: E402  el perfil del telefono (texturas, sonidos)
import claves_r100  # noqa: E402  sin las claves redundantes de las cinematicas (memoria al abrir)
CASA = pvs_interior.CASA   # la caja del interior (evento_s03: la cinematica de la casa)

GLB_MAPA = os.path.join(HERE, 'out', 'r100', 'r100.glb')
JSON_MAPA = os.path.join(HERE, 'out', 'r100', 'r100.json')

# Leon afuera de la casa, frente a la puerta (et0d00: bisagra en (-77.04, 0.87, -30.32), 1.3 m de ancho hacia -X),
# mirando hacia ella (-Z)
# donde el juego deja a Leon al terminar la intro r100s40 (r100_StartEvent: setPos / setAng 2.246 rad)
SPAWN = (-99.685, -0.484, -1.343)
SPAWN_YAW = 128.686
LOD_DIST = [8, 20]   # el LOD mide al AABB del chunk: L0 hasta 8 m, L1 hasta 20 m, despues L2
# EL N95 A 30 FPS: el mapa con el nivel cercano tambien simplificado (35 % del juego SIN cruzar las costuras de UV: al 20
# % y cruzandolas los tablones del puente quedaban chatos y con la textura corrida), L1 10 % y L2 3 % (el follaje 30 %
# y 12 %: mas bajo poda las ramas de los arboles a pocos metros), cambios de LOD a 6 y 14 m, el corte lejano a 30 m
# (el juego: ~43) y la niebla mas espesa para que no se vea el corte (mitad de niebla a 21 m; la del juego: 37 m).
# Lo ESTATICO cuesta poco por triangulo en el N95 (sin skinning ni luces por vertice: los colores vienen horneados);
# lo que se deforma es lo caro (n95_glb.py). El FONDO (cerros, siluetas, el
# terreno de abajo) tambien: al 45 %, partido en celdas de 16 m y con la misma distancia maxima (a 40 m ya es 98 %
# niebla; entero, cada pieza era una caja gigante que siempre contenia a la camara: nunca se descartaba)
N95_MAPA = ['--l0-prop', '0.35', '--l0-costuras', '--lod', '0.1,0.03', '--lod-alfa', '0.3,0.12',
            '--lod-error', '0.03,0.08', '--lado', '6,10,20', '--fondo-prop', '0.45', '--fondo-lado', '10',
            '--fondo-celda', '16']
N95_LOD_DIST = [6, 14]
N95_LEJOS = 30.0
N95_NIEBLA_Z50 = 21.0


def lua_mapa(info):
    """scripts/r100.lua: el streaming de bloques del juego con los datos del BLK."""
    areas = []
    for a in info['bloques']['areas']:
        if not a['activa'] or 'pts' not in a:
            continue
        pts = ', '.join('{%g, %g}' % (x, z) for x, z in a['pts'])
        vis = ', '.join(str(v) for v in a['visibles'])
        areas.append('    {area = %d, pri = %d, piso = %g, alto = %g, pts = {%s}, visibles = {%s}},'
                     % (a['area'], a['prioridad'], a['piso'], a['alto'], pts, vis))
    return '''-- r100.lua: STREAMING DE BLOQUES de RE4 (block.cpp cBlock::check), generado por make_r100_w3d.py.
--
-- El juego parte el mapa en bloques (r100_00..04.dat). Cada frame busca el AREA del BLK en la que esta el jugador
-- (pos + 20 cm, la de mayor prioridad) y deja cargados SU bloque y los vecinos por link; el resto se descarga
-- (no se dibuja). Adentro de lo cargado cada pieza se recorta por frustum (aca: el Culling de cada bloque).
-- Las areas y los conjuntos visibles salen del BLK de r100.das (re4_extract_r100.py).

local AREAS = {
%s
}
local NBLOQUES = %d
-- los objetos del mapa: {nombre, bloque (-1 = siempre: raiz / fondo), se ve desde ADENTRO de la casa, puente}
-- puente: "sano" (hasta que el camion lo tira, compartido "camino_libre") o "roto" (despues)
local MAPA = {
%s
}
-- el INTERIOR de la casa: con la camara adentro (o en la cinematica, que pasa toda adentro) solo se dibuja lo que se
-- VE desde adentro (pvs_interior.py: rayos por la puerta y las rendijas de los postigos). RE4 no tiene oclusion:
-- adentro seguia dibujando el pasto y los arboles de afuera, tapados por las paredes.
local CASA = {x0 = %g, x1 = %g, z0 = %g, z1 = %g, y1 = %g}

local leon, camara
local objetos = {}
local interior = false
local roto = false

-- LA PUERTA de la casa (ETS 2, et0d00): se abre hacia adentro con F (el boton de accion del juego) si Leon esta
-- cerca. Es pared para leon.lua (colPared contra la malla de la puerta): cerrada no deja pasar. La colision de una
-- malla se lee UNA vez: al moverla se descarta (colOlvidar) y se relee en la proxima consulta.
local puerta
local PUERTA_CENTRO = {%g, %g}   -- mitad de la hoja (la bisagra esta en el origen de la malla)
local puertaAng, puertaObjetivo = 0, 0
local PUERTA_VEL = 180            -- grados por segundo (medio segundo en abrirse)
local PUERTA_ABIERTA = 90   -- abierta hacia AFUERA (emDoor setOpenLock: base_dir + pi/2)
local area = -1

-- MODO AVANZADO (avanzado_r100.py le pone MUNDO al principio): el mapa esta horneado en mallas unidas que dibujan rutinas.
-- Cada chunk tiene un PERMISO (@perm: la rutina saltea sus tests si es 0) y cada pieza (un nivel de LOD) una bandera
-- (@vp) que escribe el test de la rutina; al quitarle el permiso a un chunk se apagan sus banderas (la rutina ya no las
-- prueba). Al empezar se escriben los rangos de triangulos de cada dibujo (@rg) y las cajas de las piezas (@cj)
local fondoV
local function mundoIniciar()
    if not MUNDO or not setMemorias then return end
    for _, r in ipairs(MUNDO.rangos) do setMemorias("rg" .. r[1], r[2], table.unpack(r, 3)) end
    for j, c in ipairs(MUNDO.cajas) do setMemorias("cj" .. (j - 1), 0, table.unpack(c)) end
    setMemorias("lejos", 0, 1e9, 1e9, 1e9, 1e9, 1e9, 1e9)
    -- (las variantes del fondo, todas apagadas: una partida anterior pudo dejar otra prendida)
    if MUNDO.fondo then for v = 0, 255 do setMemoria("fo", v, 0) end end
    fondoV = nil
end

-- el FONDO translucido (las capas enormes alrededor del mapa) va capa por capa en el orden del Culling clasico, que
-- cambia a lo largo del camino: una variante por franja de MUNDO.fondo.zona metros en x; se prende la de la camara
local function mundoFondo()
    local F = MUNDO and MUNDO.fondo
    if not F or not camara then return end
    local x = posicion(camara)
    local z = math.floor((x - F.x0) / F.zona) + 1
    if z < 1 then z = 1 elseif z > #F.v then z = #F.v end
    local v = F.v[z]
    if v ~= fondoV then
        if fondoV then setMemoria("fo", fondoV, 0) end
        setMemoria("fo", v, 1)
        fondoV = v
    end
end

local function mundoPermitir(e, v)
    if e.perm == v then return end
    e.perm = v
    local g = e.g
    setMemoria("perm" .. (g.p // 256), g.p %% 256, v and 1 or 0)
    if not v then
        for _, i in ipairs(g.s) do setMemoria("vp" .. (i // 256), i %% 256, 0) end
    end
end

-- areaHitCheck_xz4 (area.cpp), en metros: banda de altura y los dos pares de lados del cuadrilatero
local function dentro(a, x, y, z)
    if y + 0.1 < a.piso or y >= a.piso + a.alto then return false end
    local p = a.pts
    if (p[4][1] - p[1][1]) * (z - p[1][2]) > (p[4][2] - p[1][2]) * (x - p[1][1]) or
       (p[2][1] - p[1][1]) * (z - p[1][2]) < (p[2][2] - p[1][2]) * (x - p[1][1]) then return false end
    if (p[4][1] - p[3][1]) * (z - p[3][2]) < (p[4][2] - p[3][2]) * (x - p[3][1]) or
       (p[2][1] - p[3][1]) * (z - p[3][2]) > (p[2][2] - p[3][2]) * (x - p[3][1]) then return false end
    return true
end

-- checkBlockArea: la de mayor prioridad; si empata, se queda con la actual; si no hay ninguna, la actual
local function areaDe(x, y, z, actual)
    local mejor, pri = actual, -1
    for _, a in ipairs(AREAS) do
        if dentro(a, x, y, z) and a.pri >= pri then
            if a.pri > pri or a.area == actual or mejor == actual then mejor, pri = a.area, a.pri end
        end
    end
    return mejor
end

local function aplicar(n)
    local vis = {}
    for _, a in ipairs(AREAS) do
        if a.area == n then for _, b in ipairs(a.visibles) do vis[b] = true end end
    end
    for _, e in ipairs(objetos) do
        local v = (e.bloque < 0 or vis[e.bloque] == true) and (not interior or e.adentro) and
                  (e.puente == nil or (e.puente == "roto") == roto)
        if e.o then setVisible(e.o, v) else mundoPermitir(e, v) end
    end
end

local function camaraAdentro()
    if compartido("cine_interior") then return true end   -- la cinematica de la casa (s03)
    if not camara then return false end
    local x, y, z = posicion(camara)
    return x > CASA.x0 and x < CASA.x1 and z > CASA.z0 and z < CASA.z1 and y < CASA.y1
end

local function actualizarPuerta(dt)
    if not puerta then return end
    local x, y, z = posicion(leon)
    local dx, dz = x - PUERTA_CENTRO[1], z - PUERTA_CENTRO[2]
    -- la puerta esta TRABADA ABIERTA (el juego la deja asi hasta la emboscada): F es el boton de accion de Leon
    if puertaAng ~= puertaObjetivo then
        local paso = PUERTA_VEL * dt
        if math.abs(puertaObjetivo - puertaAng) <= paso then puertaAng = puertaObjetivo
        elseif puertaObjetivo < puertaAng then puertaAng = puertaAng - paso
        else puertaAng = puertaAng + paso end
        setRotacion(puerta, 0, puertaAng, 0)
        colOlvidar(puerta)
    end
end

function inicio()
    leon = buscar("Leon")
    puerta = buscar("r100_puerta")
    -- al empezar la partida la puerta de la casa ya esta ABIERTA (como en el juego original)
    puertaAng, puertaObjetivo = PUERTA_ABIERTA, PUERTA_ABIERTA
    if puerta then setRotacion(puerta, 0, puertaAng, 0); colOlvidar(puerta) end
    camara = buscar("Cámara")
    objetos = {}
    for _, m in ipairs(MAPA) do
        local g = MUNDO and MUNDO.grupos[m[1]]
        if g then
            objetos[#objetos + 1] = {g = g, bloque = m[2], adentro = m[3], puente = m[4]}
        else
            local o = buscar(m[1])
            if o then objetos[#objetos + 1] = {o = o, bloque = m[2], adentro = m[3], puente = m[4]} end
        end
    end
    mundoIniciar()
    area, interior, roto = -1, false, false
end

function actualizar(dt)
    if not leon then return end
    mundoFondo()
    local adentro = camaraAdentro()
    local cambio = adentro ~= interior
    interior = adentro
    -- el area (los bloques) sale de donde esta Leon (en la cinematica de la casa queda quieto, oculto)
    if not compartido("cinematica") then actualizarPuerta(dt) end
    do
        local x, y, z = posicion(leon)
        local n = areaDe(x, y + 0.2, z, area)
        if n ~= area and n >= 0 then area = n; cambio = true; info("r100: area " .. n) end
    end
    if (compartido("camino_libre") and true or false) ~= roto then roto = not roto; cambio = true end
    if cambio then setCompartido("r100_interior", interior) end
    if cambio and area >= 0 then
        aplicar(area)
        info("r100: " .. (interior and "interior (solo lo que se ve desde adentro)" or "exterior"))
    end
end
''' % ('\n'.join(areas), len(info['bloques']['links']),
       '\n'.join('    {"%s", %d, %s, %s},' % (n, b, 'true' if v else 'false', '"%s"' % pu if pu else 'nil')
                 for n, b, v, pu in info.get('objetos_mapa', [])),
       CASA['x0'], CASA['x1'], CASA['z0'], CASA['z1'], CASA['y1'], (info['puerta']['pos'][0] - 0.65 if info.get('puerta') else 0), (info['puerta']['pos'][2] if info.get('puerta') else 0))


def quat_vista(yaw_deg, pitch_deg):
    """quaternion (x, y, z, w) de una vista orbital: yaw alrededor de +Y y despues pitch alrededor de X local."""
    y, p = math.radians(yaw_deg) / 2, math.radians(pitch_deg) / 2
    qy = (0.0, math.sin(y), 0.0, math.cos(y))
    qx = (math.sin(p), 0.0, 0.0, math.cos(p))
    ax, ay, az, aw = qy
    bx, by, bz, bw = qx
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def vista3d(pivote, dist, yaw, pitch, extra):
    q = quat_vista(yaw, pitch)
    # el layout guarda el pivote con el cruce historico posY<->pivot.z / posZ<->pivot.y (GuardarW3D.cpp)
    lineas = ['posX: %g' % pivote[0], 'posY: %g' % pivote[2], 'posZ: %g' % pivote[1], 'orbitDistance: %g' % dist,
              'rotQX: %g' % q[0], 'rotQY: %g' % q[1], 'rotQZ: %g' % q[2], 'rotQW: %g' % q[3],
              'showArmature: false', 'ShowRelantionshipsLines: false'] + extra
    return 'Viewport3D {\n' + ''.join('  ' + l + '\n' for l in lineas) + '}'


def indentar(txt, n):
    return '\n'.join(('  ' * n + l) if l else l for l in txt.split('\n'))


def layout():
    # UN solo viewport: la CAMARA del juego (Rendered), sin overlays; abajo el timeline, a la derecha outliner +
    # propiedades
    # (showHitbox: false = Overlays > Objects > Hitbox apagado: el alambre del cuerpo de Leon y de la entrada a la casa no
    #  se dibujan en la vista del juego; el layout lo guarda)
    cam = vista3d(SPAWN, 4.0, 0, -20, ['ViewFromCameraActive: true', 'view: Rendered', 'showOverlays: false', 'showLights: false', 'showCamera: false', 'showHitbox: false'])
    return ('Layout {\n'
            '  ViewportRow {\n'
            '    ViewportColumn {\n' + indentar(cam, 3) + '\n'
            '      Timeline {\n        modo: dope\n      }\n'
            '      Split: 0.86\n'
            '    }\n'
            '    ViewportColumn {\n      Outliner\n      Properties\n      Split: 0.45\n    }\n'
            '    Split: 0.8\n'
            '  }\n'
            '}\n')


# luces del LIT (corte 0) para LEON: el escenario ya trae la luz HORNEADA en el vertex color (la misma cuenta de GX,
# re4_extract_r100.py), asi que las luces de GL solo iluminan al personaje. En el N95 cada luz de GL cuesta por
# vertice: afuera las 2 paralelas principales; adentro de la casa fx_r100 suma las 3 puntuales del corte 4 (fuego).
LUCES_LIT = (0, 1)


def rot_desde_y(s):
    """rot euler XYZ (grados) de una lampara direccional cuya luz VIENE de la direccion s (Whisk3D: el +Y local
    rotado; Quaternion::FromEulerXYZ = Qx*Qy*Qz, con ry = 0: y = cos rx cos rz, z = sin rx cos rz, x = -sin rz)."""
    n = math.sqrt(sum(c * c for c in s)) or 1.0
    x, y, z = (c / n for c in s)
    rz = math.asin(max(-1.0, min(1.0, -x)))
    rx = math.atan2(z, y)
    return [round(math.degrees(rx), 3), 0.0, round(math.degrees(rz), 3)]


def luces_lit(info, ns=LUCES_LIT, prefijo='r100_luz_'):
    """las luces del juego como luces de GL, con la atenuacion de trans_lit.cpp pasada a metros."""
    lit = info['luz']
    escala = 2.0 ** (lit['tev_scale'][0] if lit['tev_scale'] else 0)
    por_n = {l['n']: l for l in lit['luces']}
    out = []
    for n in ns:
        l = por_n.get(n)
        if not l:
            continue
        I, r = l['intensidad'], max(0.01, l['radio'])
        o = {'tipo': 'luz', 'nombre': '%s%02d' % (prefijo, n), 'rot': [0, 0, 0], 'escala': [1, 1, 1]}
        if l['tipo'] == 5:             # paralela: 'dir' es la posicion lejana de la fuente
            o['direccional'] = True
            o['pos'] = [SPAWN[0], SPAWN[1] + 8, SPAWN[2]]
            o['rot'] = rot_desde_y(l['dir'])
            br = I
            att = None
        elif l['tipo'] in (2, 6):      # cuadratica: I / (1 + k2 d^2), llega a 0.1 en el radio
            # la I va en la ATENUACION (k0 = 1/I), no en el color: asi el color queda en 0..1 con su tono
            # (clampeado a 2 salia blanco) y el parpadeo del fuego (setColor/setEnergia) no se satura
            br = 1.0
            k2 = (I - 0.1) / 0.1 / (r * r)
            att = [round(1.0 / I, 5), 0.0, round(k2 / I, 6)]
        else:                          # spot (3): GX_DA_MEDIUM con referencia 5 m y brillo I (sin cono en GL)
            br = min(I, 0.999)
            k1 = 0.5 * (1 - br) / (br * 5.0)
            att = [1.0, round(k1, 5), round(k1 / 5.0, 5)]
            br = I
        o['color'] = [round(min(2.0, c * br * escala), 4) for c in l['color']]
        if att:
            o['pos'] = l['pos']
            o['atenuacion'] = att
        out.append(o)
    return out


def editar_mapa(w3d, info, libreria=None):
    with zipfile.ZipFile(w3d) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    datos = dict((i.filename, d) for i, d in entradas)
    proy = json.loads(datos['proyecto.json'])
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    # (un proyecto nuevo de Whisk3D trae un Constructor y "Limpiar pantalla": con ellos la pantalla se limpia con SU
    # color y no con el fondo de la niebla. Afuera: el viewport limpia como siempre, con el color de la niebla)
    proy['escena']['objetos'] = [o for o in proy['escena']['objetos']
                                 if not (o.get('tipo') == 'rutina' and o.get('nombre') in ('Constructor', 'Limpiar pantalla'))]
    piezas = info['piezas']
    lejos = info['lejos']              # el far del juego (fog.End * (1 - far_play_ratio) + 1): ~44 m
    lod_dist = LOD_DIST
    if not info.get('full'):
        lejos, lod_dist = min(lejos, N95_LEJOS), N95_LOD_DIST

    # las mallas importadas del mapa: r100, r100.001, ... en el orden de los nodos del glb
    def indice(nom):
        if nom == 'r100':
            return 0
        if nom.startswith('r100.') and nom[5:].isdigit():
            return int(nom[5:])
        return None
    mapa, resto = {}, []
    for o in col['hijos']:
        i = indice(o.get('nombre', '')) if o.get('tipo') == 'malla' else None
        if i is None:
            resto.append(o)
        else:
            mapa[i] = o
    if len(mapa) != len(piezas):
        sys.exit('el mapa importo %d mallas y r100.json tiene %d piezas' % (len(mapa), len(piezas)))

    def culling(nombre, hijos, scripts=None, alfa=False, distancia=True):
        c = {'tipo': 'culling', 'nombre': nombre, 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
             'soloCamaraActiva': True, 'hijos': hijos}
        if distancia:
            c['distanciaMax'] = lejos      # lo que el juego ya no dibuja (el far de la niebla)
        if alfa:
            c['ordenAlpha'] = True          # translucidos de atras hacia adelante
        if scripts:
            c['scripts'] = scripts
        return c

    # chunk -> LOD con sus niveles (L0 cerca, L1, L2 lejos); los chunks de un solo nivel quedan como malla suelta
    por_chunk = {}
    sueltos, cielo = [], []
    for i, p in enumerate(piezas):
        o = mapa[i]
        o['nombre'] = p['nombre']
        if p['grupo'] == 'colision':
            o['visible'] = False
            sueltos.append(o)
        elif p['grupo'] == 'cielo':
            cielo.append(o)
        elif p['nombre'] == 'r100_puerta':
            por_chunk[('b1', 'opaco', 'r100_puerta')] = [o]
        else:
            por_chunk.setdefault((p['grupo'], p['capa'], p['chunk']), []).append(o)
    grupos = {}
    por_bloque = {}                    # bloque -> nombres de sus objetos (r100.lua los prende/apaga)
    for (grupo, capa, chunk), objs in sorted(por_chunk.items()):
        if len(objs) == 1:
            nodo = objs[0]
        else:
            # el LOD mide la distancia al AABB del hijo: L0 hasta 12 m, L1 hasta 28 m, despues L2
            nodo = {'tipo': 'lod', 'nombre': chunk, 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
                    'distancias': lod_dist, 'soloCamaraActiva': True, 'hijos': objs}
        grupos.setdefault((capa, grupo), []).append(nodo)
        if grupo.startswith('b'):
            por_bloque.setdefault(int(grupo[1:]), []).append(nodo['nombre'])
    info['por_bloque'] = por_bloque
    pvs = set(info.get('pvs_interior', []))
    objs_mapa = []
    for (grupo, capa, chunk), objs in sorted(por_chunk.items()):
        nombre = chunk if len(objs) > 1 else objs[0]['nombre']
        bloque = int(grupo[1:]) if grupo.startswith('b') else -1
        adentro = (chunk in pvs) or chunk == 'r100_puerta' or not pvs
        objs_mapa.append((nombre, bloque, adentro, grupo[len('puente_'):] if grupo.startswith('puente_') else None))
    info['objetos_mapa'] = objs_mapa

    # ORDEN DEL ARBOL = orden de dibujo:
    #   r100_cielo (sin niebla) -> r100_niebla -> Leon, camara, luces -> fondo, raiz, bloques (opacos)
    #   -> translucidos (fondo, raiz, bloques _alfa) -> colision (oculta)
    # el CIELO va DESPUES de la niebla (el juego lo dibuja con niebla: el anillo esta a 50-214 m y sale casi del
    # color de la niebla, amarillo palido); primero en el arbol igual (antes del mapa, escribe z)
    antes = fx_r100.nieblas(z50=None if info.get('full') else N95_NIEBLA_Z50)
    if cielo:
        antes.append({'tipo': 'culling', 'nombre': 'r100_cielo', 'pos': [0, 0, 0], 'rot': [0, 0, 0],
                      'escala': [1, 1, 1], 'soloCamaraActiva': True, 'hijos': cielo})
    # UN Culling para TODO lo opaco del mapa (adelante->atras puro: el z-buffer descarta lo tapado sin pintarlo) y
    # UNO para todo lo translucido (atras->adelante, para que el alpha mezcle bien). Con un Culling por bloque el
    # orden era solo DENTRO de cada bloque: el follaje de un bloque lejano se dibujaba encima del de uno cercano.
    # El streaming de bloques del juego sigue: r100.lua prende/apaga los objetos de cada bloque (por nombre).
    nuevos = []
    if ('opaco', 'fondo') in grupos:
        nuevos.append(culling('r100_fondo', grupos[('opaco', 'fondo')], distancia=not info.get('full')))
    opacos = [n for (c, g), l in sorted(grupos.items()) if c == 'opaco' and g != 'fondo' for n in l]
    c = culling('r100_opaco', opacos, scripts=[{'archivo': 'scripts/r100.lua'}])
    c['ordenCercania'] = True
    nuevos.append(c)
    # (el N95: el fondo viene partido en celdas; su translucido va con el resto, adelante: sin las variantes de orden
    # por zona, que con cientos de celdas harian enorme la rutina)
    fondo_aparte = info.get('full')
    if ('alfa', 'fondo') in grupos and fondo_aparte:
        nuevos.append(culling('r100_fondo_alfa', grupos[('alfa', 'fondo')], alfa=True, distancia=False))
    alfas = [] if fondo_aparte else list(grupos.get(('alfa', 'fondo'), []))
    alfas += [n for (c2, g), l in sorted(grupos.items()) if c2 == 'alfa' and g != 'fondo' for n in l]
    nuevos.append(culling('r100_alfa', alfas, alfa=True))

    for o in resto:
        if o.get('nombre') == 'Leon' and o.get('tipo') == 'armature':
            o['pos'] = list(SPAWN)
            o['rot'] = [0, SPAWN_YAW, 0]
        if o.get('tipo') == 'camara':
            r = math.radians(SPAWN_YAW)
            o['pos'] = [SPAWN[0] - math.sin(r) * 2.3, SPAWN[1] + 1.65, SPAWN[2] - math.cos(r) * 2.3]
            o['far'] = 300      # el cielo y el fondo estan lejos; el mapa lo corta la distancia de cada Culling
    # la Light por defecto se reemplaza por las luces del juego (LIT de r100, corte 0)
    resto = [o for o in resto if not (o.get('tipo') == 'luz' and o.get('nombre') == 'Light')]
    # Leon va DESPUES del mapa opaco y ANTES de los translucidos: su parte transparente (pelo, pestanias) escribe
    # z; dibujado antes que el mapa, los bordes semitransparentes del pelo dejaban ver el fondo (el mapa de atras
    # perdia el z-test). Mismo orden que la tabla OT del juego: opacos, personajes, translucidos.
    personajes = [o for o in resto if o.get('tipo') == 'armature']
    # los VEHICULOS antes que las personas: el pelo semitransparente de Leon (escribe z) dibujado antes que la
    # camioneta le abria huecos al auto; dibujado despues se mezcla sobre el auto ya pintado (adentro o afuera)
    vehiculos = ('Camioneta_ev', 'Coche_juego', 'Camion_juego')
    personajes = ([o for o in personajes if o.get('nombre') in vehiculos] +
                  [o for o in personajes if o.get('nombre') not in vehiculos])
    if libreria:
        # LEON es un proxy del prefab "Leon" de la libreria, en su spawn (el lugar del armature: primera persona)
        nv = sum(1 for o in personajes if o.get('nombre') in vehiculos)
        personajes.insert(nv, libreria.proxy('Leon', SPAWN, [0, SPAWN_YAW, 0]))
    resto = [o for o in resto if o.get('tipo') != 'armature']
    opacos_n = [c for c in nuevos if not c.get('ordenAlpha')]
    alfas_n = [c for c in nuevos if c.get('ordenAlpha')]
    # EFECTOS del cuarto (fuego de la chimenea, neblina, niebla de clima) + las luces de adentro de la casa; fx.lua
    # (en el Empty r100_fx) cambia de zona con compartido("r100_interior") que pone r100.lua
    fx_objs, clima, estaticos, fx_tex = fx_r100.emisores()
    luces_casa = fx_r100.luces_interior(luces_lit)
    luces_afuera = luces_lit(info)
    for o in resto:
        if o.get('tipo') == 'camara' and o.get('nombre') == 'Cámara':
            o.setdefault('hijos', []).append(clima)
    fx = {'tipo': 'objeto', 'nombre': 'r100_fx', 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
          'scripts': [{'archivo': 'scripts/fx.lua'}], 'hijos': fx_objs}
    col['hijos'] = (antes + resto + luces_afuera + luces_casa + opacos_n + personajes + alfas_n + [fx] + sueltos)
    # translucidos MEZCLADOS (sombras / tierra suaves, follaje): no escriben z (la regla de la tabla translucida)
    for m in proy.get('materiales', []):
        if m.get('nombre', '').startswith('r100_') and '_b' in m.get('nombre', '')[9:]:
            m.setdefault('flags', {})['escribeProfundidad'] = False
    proy['layout'] = layout()
    extra = evento_s03.aplicar(proy, datos, full=info.get('full', False), libreria=libreria)     # camaras + animacion "s03" + evento.lua (datos) + sonidos (extra)
    extra.update(evento_s40.aplicar(proy, datos, full=info.get('full', False)))   # intro + ventana (intro.lua)
    combate_r100.aplicar(proy, datos, extra, libreria=libreria)    # Ganado_juego + ganado.lua, efectos de impacto, leon.lua con tablas
    emboscada_r100.aplicar(proy, datos, extra, libreria=libreria)  # los 7 aldeanos de la emboscada, la camioneta en el barranco
    hud_r100.agregar(proy, datos, extra)        # el HUD del juego (vida + balas) y el grano de pantalla: Whisk3DUI
    # la LLAMADA DE RADIO: despues del HUD (su 2D va adentro del .w3dui del HUD) y ULTIMA en el arbol (su Recorte de
    # pantalla completa tapa el mundo): no se agrega nada a la coleccion despues de esto
    codec_r100.aplicar(proy, datos, extra, libreria=libreria)
    if libreria:
        # la libreria en el registro del nivel y colocar.lua PRIMERO en el arbol (corre antes que todos los scripts:
        # le pasa el transform de cada proxy a su personaje, ver libreria_r100.py)
        proy['librerias'] = [libreria.registro(w3d)]
        emp, txt = libreria.colocar()
        col['hijos'].insert(0, emp)
        datos['scripts/colocar.lua'] = txt.encode('utf-8')
        # (lo que hacia make_re4_w3d.editar_proyecto con el nivel: sin cache de juego y sin nada elegido)
        proy['cacheJuego'] = False
        if isinstance(proy.get('sesion'), dict):
            proy['sesion']['activo'] = ''
            proy['sesion']['seleccion'] = []
    datos['proyecto.json'] = json.dumps(proy, ensure_ascii=False).encode('utf-8')
    datos['scripts/r100.lua'] = lua_mapa(info).encode('utf-8')
    datos['scripts/fx.lua'] = fx_r100.lua(estaticos, [],
                                          [o['nombre'] for o in luces_casa]).encode('utf-8')
    for t in fx_tex:
        extra['texturas/fx/' + t] = os.path.join(fx_r100.TEX, t)

    tmp = w3d + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        nombres = [i.filename for i, _ in entradas]
        for info_z, _ in entradas:
            zi = zipfile.ZipInfo(info_z.filename, date_time=info_z.date_time)
            zi.compress_type = info_z.compress_type
            zi.external_attr = info_z.external_attr
            z.writestr(zi, datos[info_z.filename])
        for nombre in sorted(k for k in datos if k.startswith('scripts/')):
            if nombre not in nombres:
                z.writestr(nombre, datos[nombre], zipfile.ZIP_DEFLATED)
        for nombre, ruta in extra.items():
            if nombre not in nombres:
                z.write(ruta, nombre, zipfile.ZIP_DEFLATED)
    os.replace(tmp, w3d)


def comprimir_mallas(w3d):
    """las .w3dm son TEXTO y Whisk3D las guarda sin comprimir (STORED): 62 MB. El lector acepta deflate igual (se
    probo: abre y dibuja lo mismo) -> ~14 MB. Menos para copiar al N95 y menos lectura de la memoria del telefono."""
    tmp = w3d + '.tmp'
    with zipfile.ZipFile(w3d) as zi, zipfile.ZipFile(tmp, 'w') as zo:
        for i in zi.infolist():
            n = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            n.external_attr = i.external_attr
            n.compress_type = zipfile.ZIP_DEFLATED if i.filename.endswith('.w3dm') else i.compress_type
            zo.writestr(n, zi.read(i.filename))
    os.replace(tmp, w3d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--output', default=None,
                    help='default: re4_r100.w3d (texturas a la mitad, N95) o re4_r100_full.w3d (con --full)')
    ap.add_argument('--full', action='store_true',
                    help='version FULL: todas las texturas a su tamanio original (mapa, Leon y los del evento)')
    ap.add_argument('--libreria', default=libreria_r100.ARCHIVO,
                    help='la libreria de personajes (default: re4_personajes.w3d; si falta se arma con '
                         'make_personajes_w3d.py)')
    ap.add_argument('--sin-libreria', action='store_true',
                    help='como antes de la libreria: Leon, el ganado y los aldeanos importados adentro del nivel')
    ap.add_argument('--mapa', default=None,
                    help='la carpeta del mapa extraido (r100.glb + r100.json; default: out/r100 o out/r100_full)')
    ap.add_argument('--clasico', action='store_true',
                    help='sin el modo avanzado: el escenario con sus Culling y LOD (objetos malla clasicos)')
    ap.add_argument('--whisk3d', default=base.WHISK3D_LOCAL if os.path.isfile(base.WHISK3D_LOCAL) else 'whisk3d')
    args = ap.parse_args()
    suf = '_full' if args.full else ''
    out = os.path.abspath(args.output or os.path.join(HERE, 're4_r100%s.w3d' % suf))
    # la version FULL (PC) usa a Leon con los clips de combate (dano, muerte, herido: out/combate, atlas completo)
    glb_leon = combate_r100.GLB_LEON if args.full else os.path.join(HERE, 'out', 'leon', 'leon.glb')
    if args.full:
        # + el clip "radio" (sacar la radio para la llamada): mismo esqueleto, se junta por nombre de nodo
        sys.path.insert(0, os.path.join(HERE, 'tools_r100'))
        import unir_clips
        radio = os.path.join(HERE, 'out', 'r100_intro', 'leon_radio.glb')
        con_radio = os.path.join(os.path.dirname(glb_leon), 'leon_combate_radio.glb')
        if not os.path.isfile(con_radio) or os.path.getmtime(con_radio) < max(os.path.getmtime(glb_leon),
                                                                              os.path.getmtime(radio)):
            unir_clips.unir(con_radio, [glb_leon, radio])
        glb_leon = con_radio
    # el N95: el mapa del perfil de 30 fps (N95_MAPA, arriba)
    MAPA_N95 = N95_MAPA
    dir_mapa = os.path.abspath(args.mapa) if args.mapa else os.path.join(HERE, 'out', 'r100_full' if args.full else 'r100_n95')
    glb_mapa, json_mapa = os.path.join(dir_mapa, 'r100.glb'), os.path.join(dir_mapa, 'r100.json')

    if not os.path.isfile(glb_leon):
        subprocess.check_call([sys.executable, os.path.join(HERE, 're4_extract_leon.py'), '-o', glb_leon] +
                              (['--atlas-completo'] if args.full else []))
    opciones_mapa = ['--full'] if args.full else MAPA_N95
    sello = os.path.join(dir_mapa, 'opciones.txt')        # (otras opciones del extractor -> se vuelve a extraer)
    if not os.path.isfile(glb_mapa) or (not args.mapa and (not os.path.isfile(sello) or
                                                          open(sello).read().split() != opciones_mapa)):
        subprocess.check_call([sys.executable, os.path.join(HERE, 're4_extract_r100.py'), '-o', dir_mapa] + opciones_mapa)
        open(sello, 'w').write(' '.join(opciones_mapa))
    info = json.load(open(json_mapa))
    info['full'] = args.full
    # PVS del interior (rayos, ~4 min): se guarda al lado del mapa y solo se rehace si el glb cambio
    cache = os.path.join(dir_mapa, 'pvs_interior.json')
    firma = '%d-%d' % (os.path.getsize(glb_mapa), int(os.path.getmtime(glb_mapa)))
    pvs = json.load(open(cache)) if os.path.isfile(cache) else {}
    if pvs.get('firma') != firma:
        print('calculando lo que se ve desde adentro de la casa (rayos)...')
        vis, n, _ = pvs_interior.calcular(glb_mapa, info['piezas'])
        pvs = {'firma': firma, 'visibles': sorted(vis), 'total': n}
        json.dump(pvs, open(cache, 'w'), indent=1)
    info['pvs_interior'] = pvs['visibles']
    print('interior: %d de %d chunks se ven desde adentro' % (len(pvs['visibles']), pvs['total']))

    libreria = None
    if not args.sin_libreria:
        libreria = libreria_r100.Libreria(args.libreria)
        if not os.path.isfile(libreria.archivo):
            print('falta la libreria de personajes: make_personajes_w3d.py -> %s' % libreria.archivo)
            subprocess.check_call([sys.executable, os.path.join(HERE, 'make_personajes_w3d.py'), '-o',
                                   libreria.archivo, '--whisk3d', args.whisk3d])
        if not args.full:
            # el N95: su propia libreria (re4_personajes_n95.w3d, al lado del nivel en la tarjeta), armada con el Leon
            # de combate SIMPLIFICADO (5.400 triangulos en vez de 9.100, se ve igual) y con el perfil del telefono
            # (la original de cada textura y sonido: la libreria de PC). Mismo NOMBRE de libreria: las referencias
            # "lib:re4_personajes/..." no cambian
            n95 = os.path.splitext(libreria.archivo)[0] + '_n95.w3d'
            leon_n95 = os.path.join(HERE, 'out', 'combate_n95', 'leon_combate.glb')
            if not os.path.isfile(leon_n95):
                subprocess.check_call([sys.executable, os.path.join(HERE, 're4_extract_leon.py'), '--combate',
                                       '--reducir', '0.006', '-o', leon_n95])
            base_n95 = os.path.join(HERE, 'out', 're4_personajes_n95_base.w3d')
            subprocess.check_call([sys.executable, os.path.join(HERE, 'make_personajes_w3d.py'), '-o', base_n95,
                                   '--leon', leon_n95, '--n95', '--whisk3d', args.whisk3d], stdout=subprocess.DEVNULL)
            n95_r100.convertir(base_n95, n95, originales=[libreria.archivo])
            libreria = libreria_r100.Libreria(n95)
    lineas = ['selobj Cubo', 'delete']
    if not libreria:
        bl = os.path.splitext(os.path.basename(glb_leon))[0]
        lineas += [f'importgltf {glb_leon}', f'activename {bl}_rig', 'objname Leon']
        for k, nom in enumerate(base.MALLAS):
            lineas += [f'activename {bl if k == 0 else f"{bl}.{k:03d}"}', f'objname {nom}']
    lineas += evento_s03.lineas_importar(mitad=not args.full)   # los personajes del evento y la utileria
    lineas += combate_r100.lineas_importar(libreria=bool(libreria))   # ventanas, vidrio (+ el ganado de juego)
    lineas += evento_s40.lineas_importar()                      # la intro: camioneta, policias; objetos de juego
    lineas += emboscada_r100.lineas_importar(libreria=bool(libreria))   # la camioneta caida (+ los aldeanos)
    lineas += codec_r100.lineas_importar(radio=not libreria)    # la llamada de radio: Leon y Hunnigan (+ la radio)
    lineas += [f'importgltf {glb_mapa}', f'guardarw3d {out}']
    if not args.full:
        # el N95 a 30 fps: los personajes y los vehiculos con menos triangulos (n95_glb.REGLAS)
        import n95_glb
        lineas = n95_glb.simplificadas(lineas)
    base.correr_script(args.whisk3d, lineas)
    if not libreria:
        base.editar_proyecto(out)      # Leon: constraints, efectos, luz del disparo, leon.lua, sonidos
    editar_mapa(out, info, libreria)
    base.correr_script(args.whisk3d, [f'abrirw3d {out}', f'guardarw3d {out}'])
    comprimir_mallas(out)
    if not args.clasico:
        avanzado_r100.avanzar(out)
    # las cinematicas vienen horneadas a una clave por frame: las que caen sobre la recta de sus vecinas sobran (dos
    # tercios). El JSON entero vive en memoria mientras abre: en el N95 es lo que mas pesa de la carga
    claves_r100.reducir(out)
    if not args.full:
        # (la ORIGINAL de cada textura / sonido: la version de PC; el mapa del N95 ya viene a la mitad)
        original = os.path.join(HERE, 're4_r100_full.w3d')
        if not os.path.isfile(original):
            print('AVISO: falta %s (la version de PC): las texturas que el armado ya achico se achican otra vez'
                  % original)
        n95_r100.convertir(out, out, proyecto=True, originales=[original])
    print(f'-> {out} ({os.path.getsize(out) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
