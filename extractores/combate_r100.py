"""
combate_r100.py: el COMBATE de la demo r100 (lo usa make_r100_w3d.py). Datos:
  out/ganado_juego/ganado_juego_lugar.glb + clips.json + ia.json   el ganado de juego (57 clips EN EL LUGAR: la raiz la
                                                                  mueve ganado.lua con la pista de cada clip)
  out/combate/leon_combate.glb + leon_combate_clips.json          Leon con los clips de dano / muerte / herido
  out/combate/efectos.json + tex/                                 sangre, polvo de la bala, punto del laser
  out/combate/armas.json                                          cargador, danio, tiempos

Agrega al proyecto:
  * Ganado_juego: el aldeano de juego (mismo esqueleto y mallas que el de la cinematica, con el hacha en la mano
    IZQUIERDA). Oculto hasta que termina la cinematica (evento.lua pone compartido "ganado_activo"); ganado.lua = la IA.
  * fx_combate: un Empty por efecto (fx_sangre, fx_polvo, fx_cuchillo, fx_sangre_leon) con sus emisores (rafagas:
    cantidad 0). Lua lleva el Empty al punto del impacto, lo gira hacia el tirador (+Z del efecto) y emite.
  * Leon_laser_punto: el punto rojo del laser (una particula por frame en el choque del rayo, siempre mira a camara).
  * Las tablas de RAIZ de los clips (x, z, giro por frame) dentro de leon.lua y ganado.lua (marca --@@RAIZ@@).
"""
import json
import math
import os

import fx_r100

HERE = os.path.dirname(os.path.abspath(__file__))
COMB = os.path.join(HERE, 'out', 'combate')
TEX = os.path.join(COMB, 'tex')
GJ = os.path.join(HERE, 'out', 'ganado_juego')
GLB_GANADO = os.path.join(GJ, 'ganado_juego_lugar.glb')
GLB_LEON = os.path.join(COMB, 'leon_combate.glb')
GLB_PISTOLA = os.path.join(COMB, 'pistola.glb')   # la pistola con esqueleto: corredera y cargador animados
RUTA_TEX = 'texturas/fxc/'

# grupo de efectos.json -> (Empty, que es)
EFECTOS = {'bala_ganado': 'fx_sangre', 'bala_pared': 'fx_polvo', 'cuchillo_ganado': 'fx_cuchillo',
           'sangre_leon_golpe': 'fx_sangre_leon',
           # out/combate/efectos_ventana.json: el vidrio que estalla cuando Leon salta por una ventana
           'vidrio_estalla_evento_afuera': 'fx_vidrio_afuera', 'vidrio_estalla_evento_adentro': 'fx_vidrio_adentro',
           'vidrio_estalla_evento_abajo': 'fx_vidrio_abajo',
           # el polvo / las astillas sobre Leon al arrancar el salto (frame 0)
           'leon_ventana_afuera': 'fx_leon_ventana_afuera', 'leon_ventana_adentro': 'fx_leon_ventana_adentro',
           'leon_ventana_abajo': 'fx_leon_ventana_abajo'}
GLB_VENTANA = os.path.join(COMB, 'ventana.glb')     # Ventana_intacta / Ventana_rota (espacio de la ventana)
ACCIONES = os.path.join(COMB, 'acciones.json')
# out/combate/salto_ventana.json: la camara por frame de cada salto y los TROZOS de vidrio (vidrio_trozos_piezas.glb:
# un nodo por pieza, con el origen en su pivote)
SALTO = os.path.join(COMB, 'salto_ventana.json')
GLB_TROZOS = os.path.join(COMB, 'vidrio_trozos_piezas.glb')
ESP_OK = ('0x00', '0x01', '0x0B')   # sprites comunes / con temblor (sin estelas, luces ni calcomanias)


def _mallas_glb(ruta):
    import struct
    g = open(ruta, 'rb').read()
    jl = struct.unpack('<I', g[12:16])[0]
    doc = json.loads(g[20:20 + jl])
    return [n.get('name', '') for n in doc['nodes'] if 'mesh' in n]


def nombre_malla_ganado(m):
    return m.replace('Ganado_ev_', 'Ganado_j_').replace('Ganado_hacha', 'Ganado_j_hacha')


def lineas_importar_pistola():
    """la pistola con esqueleto (Pistola + Pistola_malla): va en la mano de Leon"""
    return ['importgltf ' + GLB_PISTOLA, 'activename pistola_rig', 'objname Pistola',
            'activename pistola', 'objname Pistola_malla']


def lineas_unir(partes, sueltas=()):
    """las PARTES de un personaje (mismo esqueleto) en UNA malla por TRAMO (Ctrl+J: los grupos de vertices y las
    normales se conservan). Cada malla es un dibujo aparte con sus punteros, su matriz y su skinning: un aldeano de 5
    partes costaba ~110 llamadas GL por cuadro. 'sueltas' quedan aparte (las caras con shape keys, que animan las
    escenas por nombre; lo que un script prende y apaga) y cortan los tramos: el orden de dibujo se conserva (el pelo
    semitransparente, que escribe z, sigue despues de la cara)"""
    out, tramo = [], []

    def cerrar():
        if len(tramo) >= 2:
            # (la principal, la primera del tramo, se elige ULTIMA: queda activa y la union conserva su nombre)
            out.extend(['selobj ' + tramo[1]] + ['selname ' + p for p in tramo[2:]] + ['selname ' + tramo[0], 'join'])
        del tramo[:]
    for p in partes:
        if p in sueltas:
            cerrar()
        else:
            tramo.append(p)
    cerrar()
    return out


def sueltas_de(partes):
    """las partes que quedan aparte al unir: las caras / cabezas (shape keys) y las armas que un script prende"""
    return [p for p in partes if p.endswith(('_cara', '_cabeza', '_pistola'))]


def lineas_importar_ganado():
    """el ganado de juego: armature Ganado_juego + sus mallas (Ganado_j_*: el cuerpo, las manos, los ojos y el hacha
    en una; la cara con sus shape keys aparte)"""
    base = os.path.splitext(os.path.basename(GLB_GANADO))[0]
    out = ['importgltf ' + GLB_GANADO, 'activename %s_rig' % base, 'objname Ganado_juego']
    partes = []
    for k, m in enumerate(_mallas_glb(GLB_GANADO)):
        partes.append(nombre_malla_ganado(m))
        out += ['activename ' + (base if k == 0 else '%s.%03d' % (base, k)), 'objname ' + partes[-1]]
    out += lineas_unir(partes, sueltas=sueltas_de(partes))
    return out


def lineas_importar(libreria=False):
    """las ventanas y los trozos de vidrio (del nivel) y, si los personajes NO vienen de la libreria
    (re4_personajes.w3d, make_personajes_w3d.py), el ganado de juego y la pistola con esqueleto"""
    out = [] if libreria else lineas_importar_pistola()
    out += ['importgltf ' + GLB_VENTANA, 'activename ventana', 'objname Ventana_intacta_0',
            'activename ventana.001', 'objname Ventana_rota_0']
    bt = os.path.splitext(os.path.basename(GLB_TROZOS))[0]
    out += ['importgltf ' + GLB_TROZOS]
    for k, m in enumerate(_mallas_glb(GLB_TROZOS)):
        out += ['activename ' + (bt if k == 0 else '%s.%03d' % (bt, k)), 'objname Vidrio_' + m]
    if not libreria:
        out += lineas_importar_ganado()
    return out


def _rafaga(e):
    """cuantas particulas suelta el record de una vez (el generador del juego las reparte en unos frames)"""
    g = e.get('generador')
    if not g:
        return 1
    vida = max(1, g.get('vida_frames') or 1)
    cada = (g.get('espera_frames') or 0) + 1
    return max(1, int(round(g.get('por_emision', 1) * max(1, vida / float(cada)))))


def efectos():
    """-> (Empties con sus emisores, {Empty: [(emisor, rafaga)]}, texturas usadas)"""
    E = json.load(open(os.path.join(COMB, 'efectos.json')))
    EV = json.load(open(os.path.join(COMB, 'efectos_ventana.json')))
    objs, tabla, texs = [], {}, set()
    for g in E['grupos'] + EV['grupos']:
        emp = EFECTOS.get(g.get('nombre'))
        if not emp:
            continue
        hijos, lista = [], []
        for k, e in enumerate(g['emisores']):
            if e['esp_id'] not in ESP_OK or 'orientado' in (e.get('billboard') or ''):
                continue
            if not e.get('textura'):
                continue
            nom = '%s_%02d' % (emp, k)
            o, _, tex = fx_r100.particula(e, nom, pos=e['pos_m'], tex_dir=TEX, ruta=RUTA_TEX)
            o['cantidad'] = 0.0                     # solo rafagas (Lua)
            if o['vida'] > 60:
                o['vida'] = 3.0                     # 'permanente' en un efecto de impacto = hasta que se apaga
            o['radioEmision'] = 0
            hijos.append(o)
            lista.append((nom, _rafaga(e)))
            if tex:
                texs.add(tex)
        objs.append({'tipo': 'objeto', 'nombre': emp, 'pos': [0, -50, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
                     'hijos': hijos})
        tabla[emp] = lista
    # el PUNTO del laser: textura de brillo radial, aditivo, (250, 30, 50); una particula por frame (vida 2 frames)
    L = E.get('laser', {})
    punto = L.get('punto', {}) if isinstance(L, dict) else {}
    col = punto.get('color') or [250 / 255.0, 30 / 255.0, 50 / 255.0]
    objs.append({'tipo': 'particulas', 'nombre': 'Leon_laser_punto', 'pos': [0, -50, 0], 'rot': [0, 0, 0],
                 'escala': [1, 1, 1], 'textura': RUTA_TEX + 'core_tex08_f0.png', 'cantidad': 0.0, 'vida': 0.07,
                 'tam': 0.1, 'vel': 0, 'dispersion': 0, 'gravedad': 0, 'mezcla': 2,
                 'color': [round(c, 4) for c in col[:3]] + [1.0], 'desvanecer': False, 'activo': True,
                 'variacion': 0, 'turbulencia': 0, 'radioEmision': 0})
    texs.add('core_tex08_f0.png')
    return objs, tabla, sorted(texs)


def _pistas(clips, filtro=None):
    """{clip: {x0, z0, r0, x1, z1, r1, ...}} de las pistas de raiz (solo los clips que se mueven)"""
    out = []
    for c in clips:
        nom = c.get('clip') or c.get('nombre')
        r = c.get('raiz') or {}
        p = r.get('pista_x_z_rotY')
        if not p or not r.get('se_mueve', True):
            continue
        if filtro and nom not in filtro:
            continue
        if all(abs(v) < 1e-4 for f in p for v in f):
            continue
        out.append('    %s = {%s},' % (nom, ', '.join('%.4f, %.4f, %.4f' % tuple(f) for f in p)))
    return 'local RAIZ = {\n%s\n}' % '\n'.join(out)


def raiz_leon():
    """RAIZ (x, z, giro) de todos los clips + RAIZY (la altura: los saltos por la ventana suben / bajan)"""
    c = json.load(open(os.path.join(COMB, 'leon_combate_clips.json')))
    ys = []
    for x in c['clips']:
        py = (x.get('raiz') or {}).get('pista_y')
        if py and any(abs(v) > 1e-4 for v in py):
            ys.append('    %s = {%s},' % (x['clip'], ', '.join('%.4f' % v for v in py)))
    return _pistas(c['clips']) + '\nlocal RAIZY = {\n%s\n}' % '\n'.join(ys)


def ventanas_lua():
    """VENTANAS: las ventanas que se pueden saltar (out/combate/acciones.json): posicion, frente, saltos con el lugar
    donde arranca Leon, el clip, el frame en que rompe el vidrio y su efecto; SEQV: sonidos por frame de esos clips"""
    A = json.load(open(ACCIONES))
    fx = {0: 'fx_vidrio_afuera', 1: 'fx_vidrio_adentro', 3: 'fx_vidrio_abajo'}
    fxl = {0: 'fx_leon_ventana_afuera', 1: 'fx_leon_ventana_adentro', 2: 'fx_leon_ventana_abajo'}
    filas = []
    for w in A['ventanas']['lista']:
        saltos = []
        for sj in w['saltos']:
            saltos.append('{lado = %d, clip = "%s", cartel = "%s", x = %g, y = %g, z = %g, yaw = %g, rompe = %d, fx = "%s", '
                          'fxl = "%s"}'
                          % (1 if sj['break_dir'] == 1 else -1, sj['clip'], sj['cartel'].replace('_', ' '),
                             sj['leon_inicio_mundo_m'][0], sj['leon_inicio_mundo_m'][1], sj['leon_inicio_mundo_m'][2],
                             sj['leon_yaw_rad'], sj['vidrio_rompe_frame'], fx.get(sj.get('est_rotura'), 'fx_vidrio_afuera'),
                             fxl.get(sj['break_dir'], 'fx_leon_ventana_afuera')))
        filas.append('    {n = %d, x = %g, y = %g, z = %g, yaw = %g, saltos = {%s}},'
                     % (w['etc_no'], w['pos_m'][0], w['pos_m'][1], w['pos_m'][2], w['yaw_rad'], ', '.join(saltos)))
    # sonidos de los clips: (frame, banco, id) -> archivo (1 = voz de Leon, 5 = pisadas / cuerpo)
    mapa = {(1, 0x29): 'ventana_leon_1', (1, 0x34): 'ventana_leon_2', (1, 0x43): 'ventana_leon_3',
            (5, 5): 'ventana_cae_cuerpo', (5, 0x12): 'ventana_paso_1', (5, 0x13): 'ventana_paso_2',
            (5, 0x0e): 'valla_pie_1', (5, 0x0d): 'valla_pie_2'}
    seq = []
    for nom, c in A['clips'].items():
        ev = [(f, mapa.get((b, i))) for f, b, i in (c.get('eventos') or {}).get('sonidos', []) if mapa.get((b, i))]
        if ev:
            seq.append('    %s = {%s},' % (nom, ', '.join('[%d] = "%s"' % e for e in ev)))
    return 'local VENTANAS = {\n%s\n}\nlocal SEQV = {\n%s\n}\n%s' % ('\n'.join(filas), '\n'.join(seq), salto_lua()[0])


def trozos_salto():
    """[(clip, nodo del glb, escala, yaw de la ventana, [(x, y, z) de mundo por frame desde la rotura])]"""
    S = json.load(open(SALTO))
    out = []
    for w in S['ventanas']:
        wx, wy, wz = w['pos_m']
        c, sn = math.cos(w['yaw_rad']), math.sin(w['yaw_rad'])
        for sj in w['saltos']:
            for reg in sj['trozos']:
                pr = reg['parametros']
                esc = pr['escala_xz_y']
                for k, t in enumerate(reg['trozos']):
                    pos = [(wx + lx * c + lz * sn, wy + ly, wz - lx * sn + lz * c) for lx, ly, lz in t['pos_m_por_frame']]
                    out.append((sj['clip'], reg['nodos_glb'][t['parte']], (esc[0], esc[1], esc[0]),
                                w['yaw_rad'], pos))
    return out


def salto_lua():
    """CAMV: la camara de hombro del juego por frame de cada salto (ojo, objetivo); TROZOS: por clip, los objetos de
    los trozos de vidrio con su posicion por frame (desde el frame en que se rompe)"""
    S = json.load(open(SALTO))
    cams = []
    for w in S['ventanas']:
        for sj in w['saltos']:
            m = sj['camara']['mundo']
            vals = ', '.join('%.3f, %.3f, %.3f, %.3f, %.3f, %.3f' % (tuple(o) + tuple(t))
                             for o, t in zip(m['ojo_m'], m['objetivo_m']))
            cams.append('    %s = {%s},' % (sj['clip'], vals))
    por_clip = {}
    nombres = []
    for i, (clip, nodo, esc, yaw, pos) in enumerate(trozos_salto()):
        nom = 'VT_%02d' % i
        nombres.append((nom, nodo, esc, yaw))
        por_clip.setdefault(clip, []).append('{"%s", {%s}}' % (nom, ', '.join('%.3f, %.3f, %.3f' % p for p in pos)))
    tro = '\n'.join('    %s = {%s},' % (c, ',\n        '.join(l)) for c, l in por_clip.items())
    return 'local CAMV = {\n%s\n}\nlocal TROZOS = {\n%s\n}' % ('\n'.join(cams), tro), nombres


def raiz_ganado():
    c = json.load(open(os.path.join(GJ, 'clips.json')))
    return _pistas(c['clips'])


def volumenes():
    """local VOL = {nombre = volumen} de out/sonidos/combate/sonidos.json (el volumen del juego, 0..1)"""
    ruta = os.path.join(HERE, 'out', 'sonidos', 'combate', 'sonidos.json')
    if not os.path.isfile(ruta):
        return 'local VOL = {}'
    S = json.load(open(ruta))['sonidos']
    it = S.items() if isinstance(S, dict) else [(e.get('archivo'), e) for e in S]
    return 'local VOL = {%s}' % ', '.join('%s = %.3f' % (os.path.splitext(k)[0], v.get('volumen', 1.0))
                                          for k, v in it if k and v.get('volumen') is not None)


def lua_con_raiz(ruta, tabla):
    txt = open(ruta, encoding='utf-8').read()
    assert '--@@RAIZ@@' in txt, ruta
    return txt.replace('--@@RAIZ@@', tabla)


def lua_fxc(tabla):
    """local FXC = {Empty = {{emisor, rafaga}, ...}}: los efectos de impacto (los Empties fx_* del nivel)"""
    return 'local FXC = {\n%s\n}' % '\n'.join(
        '    %s = {%s},' % (emp, ', '.join('{"%s", %d}' % (n, k) for n, k in lista)) for emp, lista in tabla.items())


def lua_leon(tabla=None):
    """leon.lua con sus tablas (RAIZ, FXC, VOL, VENTANAS, CAMV, TROZOS) en la marca --@@RAIZ@@"""
    if tabla is None:
        tabla = efectos()[1]
    return lua_con_raiz(os.path.join(HERE, 'lua', 'leon.lua'),
                        raiz_leon() + '\n' + lua_fxc(tabla) + '\n' + volumenes() + '\n' + ventanas_lua())


def lua_ganado():
    """ganado.lua (el de la casa) con su tabla RAIZ y los volumenes"""
    return lua_con_raiz(os.path.join(HERE, 'lua', 'ganado.lua'), raiz_ganado() + '\n' + volumenes())


def sonidos_personajes():
    """{entrada: archivo} de los sonidos de leon.lua / ganado.lua: combate, acciones (ventanas, vallas), recarga"""
    out = {}
    for sub in ('combate', 'acciones'):
        d = os.path.join(HERE, 'out', 'sonidos', sub)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith('.wav'):
                    out['sonidos/' + f] = os.path.join(d, f)
    for f in ('pistola_recarga.wav',):
        out['sonidos/' + f] = os.path.join(HERE, 'out', 'sonidos', f)
    return out


def ganado_lugar():
    """(pos, rot) del ganado de la casa al terminar la cinematica (r100_Sce_look)"""
    info = json.load(open(os.path.join(GJ, 'clips.json')))['post_cutscene']
    return list(info['ganado_pos_m']), [0, round(math.degrees(info['ganado_yaw_rad']), 3), 0]


def aplicar(proy, datos, extra, libreria=None):
    """agrega el ganado de juego (script), los efectos y sus texturas, y leon.lua / ganado.lua con sus tablas.
    libreria: los personajes vienen de la libreria (libreria_r100.py): el ganado de juego es un PROXY (oculto hasta
    la cinematica) y leon.lua / ganado.lua / la pistola / los sonidos de los personajes viven en la libreria."""
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    fx_objs, tabla, texs = efectos()
    pos_g, rot_g = ganado_lugar()
    if libreria:
        # el proxy va donde iba el armature (orden de dibujo: con los demas personajes, despues del palo del evento)
        px = libreria.proxy('Ganado_juego', pos_g, rot_g, visible={'.': False})
        k = next((i + 1 for i, o in enumerate(col['hijos']) if o.get('nombre') == 'Evento_palo'), len(col['hijos']))
        col['hijos'].insert(k, px)
    for o in col['hijos']:
        if o.get('nombre') == 'Ganado_juego' and o.get('tipo') == 'armature':
            o['pos'] = pos_g
            o['rot'] = rot_g
            o['visible'] = False
            o['scripts'] = [{'archivo': 'scripts/ganado.lua'}]
    # la PISTOLA con esqueleto reemplaza a la rigida en la mano del Leon de juego: Child Of a la mano derecha
    # (sus vertices ya vienen en el espacio de ese hueso). La rigida queda oculta (la usa la cinematica).
    # (con la libreria la pistola ya esta adentro del prefab Leon: make_personajes_w3d.py)
    if not libreria:
        poner_pistola(col['hijos'])
    # las VENTANAS: intacta + rota en su lugar (la rota oculta); la 1 es copia de la 0 (misma geometria)
    A = json.load(open(ACCIONES))
    ws = A['ventanas']['lista']
    vent = {o.get('nombre'): o for o in col['hijos'] if o.get('nombre', '').startswith('Ventana_')}
    for w in ws:
        for tipo in ('intacta', 'rota'):
            base_o = vent.get('Ventana_%s_0' % tipo)
            if not base_o:
                continue
            o = base_o if w['etc_no'] == 0 else json.loads(json.dumps(base_o))
            o['nombre'] = 'Ventana_%s_%d' % (tipo, w['etc_no'])
            o['pos'] = list(w['pos_m'])
            o['rot'] = [0, round(math.degrees(w['yaw_rad']), 4), 0]
            o['visible'] = (tipo == 'intacta')
            if o is not base_o:
                col['hijos'].append(o)
    # las ventanas son vidrio (mezclado): van DESPUES del mapa translucido (antes del mapa, el vidrio tapaba en z lo
    # que estaba detras y se veia el fondo por el hueco)
    vs = [o for o in col['hijos'] if o.get('nombre', '').startswith('Ventana_')]
    for o in vs:
        col['hijos'].remove(o)
    k = next((i + 1 for i, o in enumerate(col['hijos']) if o.get('nombre') == 'r100_alfa'), len(col['hijos']))
    col['hijos'][k:k] = vs
    # los TROZOS de vidrio: una copia (oculta) de la pieza del glb por trozo de cada salto; leon.lua los mueve
    piezas = {o.get('nombre'): o for o in col['hijos'] if o.get('nombre', '').startswith('Vidrio_efm_')}
    trozos = []
    for nom, nodo, esc, yaw in salto_lua()[1]:
        b = piezas.get('Vidrio_' + nodo)
        if not b:
            continue
        o = json.loads(json.dumps(b))
        o.update({'nombre': nom, 'pos': [0, 0, 0], 'rot': [0, round(math.degrees(yaw), 3), 0], 'escala': list(esc),
                  'visible': False})
        trozos.append(o)
    for o in piezas.values():
        col['hijos'].remove(o)
    col['hijos'].append({'tipo': 'objeto', 'nombre': 'Vidrio_trozos', 'pos': [0, 0, 0], 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'hijos': trozos})
    for m in proy.get('materiales', []):
        if m.get('nombre', '').startswith('vidrio_pieza'):
            m['difuso'] = [1.0, 1.0, 0.9647, 0.2941]   # alfa_inicial del juego
            m.setdefault('flags', {})['escribeProfundidad'] = False
    col['hijos'].append({'tipo': 'objeto', 'nombre': 'fx_combate', 'pos': [0, 0, 0], 'rot': [0, 0, 0],
                         'escala': [1, 1, 1], 'hijos': fx_objs})
    for t in texs:
        extra[RUTA_TEX + t] = os.path.join(TEX, t)
    if libreria:
        return
    datos['scripts/leon.lua'] = lua_leon(tabla).encode('utf-8')
    datos['scripts/ganado.lua'] = lua_ganado().encode('utf-8')
    extra.update(sonidos_personajes())


def poner_pistola(hijos):
    """la Pistola (armature con esqueleto) pasa a ser HIJA de Leon, con Child Of a la mano derecha"""
    import make_re4_w3d as base
    pist = [o for o in hijos if o.get('nombre') == 'Pistola' and o.get('tipo') == 'armature']
    leon_o = next((o for o in hijos if o.get('nombre') == 'Leon' and o.get('tipo') == 'armature'), None)
    for o in pist:
        o['pos'], o['rot'] = [0, 0, 0], [0, 0, 0]
        o['constraints'] = [base.child_of('Leon')]
        if leon_o is not None:          # HIJA de Leon: se oculta con el (en las cinematicas Leon de juego no se ve)
            hijos.remove(o)
            leon_o.setdefault('hijos', []).append(o)
