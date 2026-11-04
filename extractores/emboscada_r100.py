"""
emboscada_r100.py: la EMBOSCADA de r100 despues del evento del camion (r100s20). Lo usa make_r100_w3d.py.
Datos de out/r100_emboscada/ (plan.json, ia_emboscada.json, ganado_eNN.glb + clips_eNN.json, coche_barranco.glb).

  * 7 aldeanos (entradas 3, 4, 5, 0x12, 0x13, 0x26, 0x27 de la lista de enemigos del cuarto): cada uno un armature
    Ganado_eNN con SU script scripts/ganado_eNN.lua = lua/ganado.lua + su tabla RAIZ + CONF (clips de su arma,
    frames del golpe, danio, guardia). Ocultos hasta compartido "emboscada" (la pone camino.lua al terminar s20).
    En guardia (em10_R1_Keeper): quietos en su puesto hasta encontrar a Leon.
  * la camioneta de la policia en el fondo del barranco (Coche_barranco), visible con compartido "camino_libre".
  * scripts/emboscada.lua: la musica (r100_StreanChk), los tres de la casa corren hacia Leon cuando sale de la casa
    (flag 0x80) y el FIN de la demo: la salida a r101 (area AEV 0) funde a negro.
"""
import json
import math
import os

import combate_r100 as CB

HERE = os.path.dirname(os.path.abspath(__file__))
EMB = os.path.join(HERE, 'out', 'r100_emboscada')
PLAN = os.path.join(EMB, 'plan.json')
GLB_COCHE = os.path.join(EMB, 'coche_barranco.glb')

# clips del de la casa que estos no tienen (tienen los de su arma)
RENOMBRAR = {'soltar_hacha': 'golpe_antebrazo_arma', 'retroceder_hacha': 'retroceder'}
# por arma: clip de ataque, frames del golpe activo, frame del SE, distancia para atacar (ia_emboscada.json)
ARMAS = {'horca': ('ataque_horca_alto', (32, 41), 32, 2.0),
         'hacha': ('ataque', (15, 21), 15, 1.7),
         'hoz': ('ataque', (15, 21), 15, 1.7)}


def entradas():
    return json.load(open(PLAN))['emboscada']


def nombre(e):
    return 'Ganado_e%02x' % e['entrada']


def lineas_importar_aldeanos():
    """los 7 aldeanos: armature Ganado_eNN + sus mallas Ganado_eNN_<parte>"""
    out = []
    for e in entradas():
        ruta = os.path.join(HERE, e['glb'])
        base = os.path.splitext(os.path.basename(ruta))[0]
        n = nombre(e)
        out += ['importgltf ' + ruta, 'activename %s_rig' % base, 'objname ' + n]
        partes = []
        for k, m in enumerate(CB._mallas_glb(ruta)):
            partes.append(n + '_' + m.replace('Ganado_', ''))
            out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + partes[-1]]
        out += CB.lineas_unir(partes)
    return out


def lineas_importar(libreria=False):
    """la camioneta del barranco y, si los personajes NO vienen de la libreria (make_personajes_w3d.py), los 7
    aldeanos"""
    out = [] if libreria else lineas_importar_aldeanos()
    base = os.path.splitext(os.path.basename(GLB_COCHE))[0]
    out += ['importgltf ' + GLB_COCHE, 'activename %s_rig' % base, 'objname Coche_barranco',
            'activename ' + base, 'objname Coche_barranco_malla']
    return out


def _conf(e):
    ataque, golpe, se_f, alcance = ARMAS[e['arma']]
    danio = 191 if int(e['flag'], 16) & 4 else 380
    ren = ', '.join('%s = "%s"' % kv for kv in RENOMBRAR.items())
    return ('CONF = {caminar = "caminar_arma", ataque = "%s", golpe = {%d, %d}, se_f = %d, alcance = %g, danio = %d, '
            'guardia = true, guard_r = %g, renombrar = {%s}}' % (ataque, golpe[0], golpe[1], se_f, alcance, danio,
                                                                 e['Guard_r_m'], ren))


def _area(a):
    return '{piso = %g, alto = %g, pts = {%s}}' % (a['piso_m'], a['alto_m'],
                                                   ', '.join('{%g, %g}' % tuple(p) for p in a['poligono_xz_m']))


LUA = '''-- emboscada.lua: despues del evento del camion (generado por emboscada_r100.py; out/r100_emboscada/plan.json)
--   * la camioneta queda en el barranco (compartido "camino_libre")
--   * la MUSICA (r100_StreanChk): suena apenas termina el evento; cuando alguno de la emboscada encontro a Leon y
--     esta a menos de 30 m, o Leon salio de la casa, queda "armada": desde ahi suena solo mientras haya uno asi; si
--     no hay ninguno se corta y no se vuelve a revisar por 5 s
--   * Leon sale de la casa: los tres de la puerta (%s) dejan la guardia y corren hacia el
--   * el FIN de la demo: la salida a r101 (area AEV 0) funde a negro

local ENEMIGOS = {%s}
local PUERTA = {%s}
local CASA = %s
local SALIDA = %s
local MUSICA_VOL = 0.8

local coche, leon
local cocheListo = false
local musicaH = nil
local armada, espera = false, 0
local salio = false
local fin, finT = false, 0
local despiertos = false

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

function inicio()
    coche = buscar("Coche_barranco")
    leon = buscar("Leon")
    if coche then setVisible(coche, false) end
    cocheListo, musicaH, armada, espera, salio, fin, finT = false, nil, false, 0, false, false, 0
    despiertos = false
end

function actualizar(dt)
    if not cocheListo and compartido("camino_libre") and coche then
        cocheListo = true
        setVisible(coche, true); animClip(coche, "barranco", true, true)
    end
    if not compartido("emboscada") or not leon then return end
    -- los aldeanos: un objeto oculto no corre su script -> se muestran y ganado.lua arranca (su clave ya esta)
    if not despiertos then
        despiertos = true
        for _, n in ipairs(ENEMIGOS) do local o = buscar(n); if o then setVisible(o, true) end end
    end
    if fin then
        finT = finT + dt
        setCompartido("cinematica", true)
        return
    end
    local x, y, z = posicion(leon)
    -- Leon salio de la casa (area 9): los de la puerta lo persiguen
    if not salio and not dentro(CASA, x, y + 0.2, z) then
        salio = true
        for _, n in ipairs(PUERTA) do setCompartido(n .. "_despertar", true) end
    end
    -- la musica
    local alguno = false
    for _, n in ipairs(ENEMIGOS) do if compartido(n .. "_ganado_alerta") then alguno = true end end
    if alguno or salio then armada = true end
    espera = math.max(0, espera - dt)
    local quiere = (not armada) or alguno
    if quiere and not musicaH and espera <= 0 then
        musicaH = sonido("sonidos/r100_musica.wav", MUSICA_VOL, 1.0, true)
    elseif not quiere and musicaH then
        pararSonido(musicaH, 1.0); musicaH = nil; espera = 5
    end
    -- el FIN: la salida del cuarto
    if dentro(SALIDA, x, y + 0.2, z) then
        fin = true
        if musicaH then pararSonido(musicaH, 2.0); musicaH = nil end
        setCompartido("cinematica", true); setCompartido("hud_visible", false)
        setCompartido("fundido_seg", 2.0); setCompartido("fundido", 1)
        info("emboscada: fin de la demo")
    end
end
'''


def lua():
    p = json.load(open(PLAN))
    es = entradas()
    puerta = [nombre(e) for e in es if e['entrada'] in (3, 4, 5)]
    return LUA % (', '.join(puerta), ', '.join('"%s"' % nombre(e) for e in es), ', '.join('"%s"' % n for n in puerta),
                  _area(p['areas']['casa_flag_leon_adentro']), _area(p['areas']['salida_r101']))


PROPS_PLANTILLA = 'propiedades = {activar = "ganado_activo", vida = 500}'


def ruta_lua(e):
    return 'scripts/%s.lua' % nombre(e).lower()


def lua_aldeano(e):
    """scripts/ganado_eNN.lua = lua/ganado.lua + su RAIZ (sus clips) + VOL + CONF (su arma). Las propiedades quedan
    las de la plantilla (activar = "ganado_activo", vida = 500): el NIVEL las cambia (override del proxy, o el texto
    en el armado sin libreria)"""
    clips = json.load(open(os.path.join(HERE, e['clips'])))['clips']
    txt = CB.lua_con_raiz(os.path.join(HERE, 'lua', 'ganado.lua'),
                          CB._pistas(clips) + '\n' + CB.volumenes() + '\n' + _conf(e))
    assert PROPS_PLANTILLA in txt
    return txt


def aplicar(proy, datos, extra, libreria=None):
    """los aldeanos (ocultos, con su script), la camioneta del barranco y el Empty Emboscada con emboscada.lua.
    libreria: cada aldeano es un PROXY de su prefab (Ganado_eNN de re4_personajes.w3d) oculto, con las propiedades
    de su script por override: lo despierta "emboscada" y su vida es la de la entrada del cuarto"""
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    por_nombre = {o.get('nombre'): o for o in col['hijos']}
    if libreria:
        # los proxies van donde iban los armatures: despues de los policias de juego (orden de dibujo)
        k = next((i + 1 for i, o in enumerate(col['hijos']) if o.get('nombre') == 'PoliciaA_juego'),
                 len(col['hijos']))
        nuevos = []
        for e in entradas():
            s = e['escala']['valor']
            nuevos.append(libreria.proxy(nombre(e), e['pos_m'], [0, round(math.degrees(e['rot_y_rad']), 3), 0],
                                         [s, s, s], visible={'.': False},
                                         props={'activar': 'emboscada', 'vida': e['hp']}))
        col['hijos'][k:k] = nuevos
    for e in entradas():
        n = nombre(e)
        o = por_nombre.get(n)
        if not o or o.get('tipo') != 'armature':
            continue
        o['pos'] = list(e['pos_m'])
        o['rot'] = [0, round(math.degrees(e['rot_y_rad']), 3), 0]
        s = e['escala']['valor']
        o['escala'] = [s, s, s]
        o['visible'] = False
        ruta = ruta_lua(e)
        o['scripts'] = [{'archivo': ruta}]
        txt = lua_aldeano(e).replace(PROPS_PLANTILLA, 'propiedades = {activar = "emboscada", vida = %d}' % e['hp'])
        datos[ruta] = txt.encode('utf-8')
    coche = por_nombre.get('Coche_barranco')
    if coche:
        coche['pos'], coche['rot'], coche['visible'] = [0, 0, 0], [0, 0, 0], False
    col['hijos'].append({'tipo': 'objeto', 'nombre': 'Emboscada', 'pos': [-77.0, 1.0, -26.0], 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'scripts': [{'archivo': 'scripts/emboscada.lua'}]})
    datos['scripts/emboscada.lua'] = lua().encode('utf-8')
