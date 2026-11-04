#!/usr/bin/env python3
"""
avanzado_r100.py: re4_r100*.w3d en el MODO AVANZADO de Whisk3D (rutinas: listas de pasos como las llamadas de OpenGL,
ver Whisk3D/docs/rutinas.md) para mandar la menor cantidad de llamadas GL posible. El mismo esquema que el Sonic del
ecosistema (conversiones/sonic/sonic_to_w3d/avanzado.py), con lo propio de r100:

  el mundo     el escenario estatico (cielo, fondo, los chunks opacos y translucidos con sus 3 LOD) se hornea en MALLAS
               UNIDAS (hasta 60000 vertices: indices de 16 bits) en coordenadas de mundo. La luz ya viene horneada en el
               color de vertice (los materiales del mapa son "color de vertice, sin luz"): se copia tal cual. Los
               vertices iguales (posicion, UV y color) se sueldan: el importador deja 3 por triangulo y en el telefono
               cada vertice es trabajo de transformacion (la imagen es la misma: son el mismo vertice)
  el LOD       cada nivel de cada chunk es una PIEZA con su caja y su bandera (@vp). La rutina prueba las cajas contra la
               camara que se esta dibujando con la distancia de cada nivel (L0 8 m, L1 20 m, L2 la del Culling): gana el
               mas cercano que pasa (los "Saltar si" apagan los otros). Sin Lua por cuadro: mide la camara activa, tambien
               en las cinematicas
  los bloques  r100.lua sigue haciendo el streaming de bloques del juego (areas del BLK, interior de la casa, puente
               sano / roto), pero en vez de setVisible escribe el PERMISO de cada chunk (@perm): la rutina saltea los
               tests de lo que no esta permitido
  los dibujos  por malla unida (saltada si su caja no se ve) y por material (saltado si la caja de su parte no se ve) UN
               "Dibujar elementos" con los rangos de triangulos de sus piezas y sus banderas: las visibles seguidas van
               en UNA llamada. Dos rutinas: lo opaco (donde estaba el cielo) y lo translucido de los chunks (donde
               estaba su Culling). Lo translucido no escribe z: el orden importa. Los rangos van de LEJOS a cerca (L2,
               L1, L0: el nivel sale de la distancia). El FONDO translucido (7 capas enormes alrededor del mapa) se dibuja
               capa por capa en el orden del Culling clasico (la distancia de la camara al centro de cada una), que
               cambia a lo largo del camino: una variante del orden por zona de ZONA m en x y r100.lua prende la de
               donde esta la camara (@fo)
Lo que mueve un script (la puerta de la casa) y todo lo demas (personajes, vehiculos, efectos) sigue clasico.

Lo llama make_r100_w3d.py (salvo con --clasico) sobre el .w3d ya armado. Suelto:  python3 avanzado_r100.py X.w3d
"""
import json
import math
import os
import re
import struct
import sys
import zipfile

import numpy as np

MAX_VERTS = 60000       # por malla unida (indices de 16 bits: GL ES 1.1)
MEM = 256               # floats por memoria de Whisk3D
CAJAS_POR_MEM = 42      # 6 floats por caja
VERSION_PASOS = 2
CELDA = 24.0            # para ordenar los chunks en el espacio (las mallas unidas quedan por zona)
FASES = ('opaco', 'fondoalfa', 'alfa')
ZONA = 10.0             # el fondo translucido: una variante de su orden por franja de ZONA m a lo largo del camino (x)
# los Culling del mapa (make_r100_w3d.editar_mapa) que se hornean y su fase; el cielo y el fondo no tienen distancia
# maxima. El fondo translucido va aparte (capa por capa, en el orden de su zona)
CONTENEDORES = {'r100_cielo': 'opaco', 'r100_fondo': 'opaco', 'r100_opaco': 'opaco', 'r100_fondo_alfa': 'fondoalfa',
                'r100_alfa': 'alfa'}
MODO_ARRAY = {'vertices': 0, 'normales': 1, 'uv': 2, 'colores': 3}


# ------------------------------------------------------------------------------------------------- .w3db
def _bloques(d):
    out, off = {}, 20
    for _ in range(struct.unpack_from('<I', d, 12)[0]):
        fc = d[off:off + 4]
        dom, cnt, nb = struct.unpack_from('<III', d, off + 4)
        out[fc] = (dom, cnt, d[off + 16:off + 16 + nb])
        off += 16 + ((nb + 3) // 4) * 4
    return out


def leer_w3db(d):
    """los arrays de render: pos (n,3), uv (n,2), col (n,4) e indices; partes [(material, inicio, cantidad)]"""
    b = _bloques(d)
    nrv = struct.unpack_from('<I', b[b'INFO'][2], 0)[0]
    pos = np.frombuffer(b[b'RPOS'][2], np.float32, 3 * nrv).reshape(-1, 3)
    uv = (np.frombuffer(b[b'RUV '][2], np.float32, 2 * nrv).reshape(-1, 2) if b'RUV ' in b
          else np.zeros((nrv, 2), np.float32))
    col = (np.frombuffer(b[b'RCOL'][2], np.uint8, 4 * nrv).reshape(-1, 4) if b'RCOL' in b
           else np.full((nrv, 4), 255, np.uint8))
    dom, _, pl = b[b'RIDX']
    idx = np.frombuffer(pl, np.uint32 if dom & 0x100 else np.uint16).astype(np.int64)
    partes, q, off = [], b[b'PART'][2], 0
    for _ in range(b[b'PART'][1]):
        n = struct.unpack_from('<I', q, off)[0]
        off += 4 + n
        m = struct.unpack_from('<I', q, off)[0]
        mat = q[off + 4:off + 4 + m].decode('utf-8')
        off += 4 + m
        ini, cant = struct.unpack_from('<ii', q, off)
        off += 8
        partes.append((mat, ini, cant))
    return {'pos': pos, 'uv': uv, 'col': col, 'idx': idx, 'partes': partes}


def escribir_w3db(nombre, pos, uv, col, idx, partes):
    """una malla de render (solo los bloques que dibuja el juego): partes [(material, inicio, cantidad)]"""
    nrv = len(pos)
    mn, mx = pos.min(0), pos.max(0)
    c = (mn + mx) / 2
    r = float(np.sqrt(((pos - c) ** 2).sum(1)).max())
    nb = nombre.encode('utf-8')
    # INFO: nRV nIdx nPartes nCaras nEsquinas nPuntos nAristas banderas(AABB + escenario cerrado) prim(6) aabb centro
    # radio vertsAgrupados uvActiva colActiva grupoActivo uvGrupoActivo nombre
    info = struct.pack('<IIIIIiiIifffii3f3f3ffiiiii', nrv, len(idx), len(partes), 0, 0, nrv, -1, 2 | 4,
                       0, 0, 0, 0, 0, 0, *mn.tolist(), *mx.tolist(), *c.tolist(), r, 0, -1, -1, -1, -1) + \
        struct.pack('<I', len(nb)) + nb
    part = b''.join(struct.pack('<I', len(m.encode())) + m.encode() + struct.pack('<I', len(m.encode())) + m.encode() +
                    struct.pack('<ii', ini, cant) for m, ini, cant in partes)
    bloques = [(b'REQ ', 4, 4, b'INFORPOSRIDXPART'), (b'INFO', 4, 1, info),
               (b'RPOS', 5, nrv, np.asarray(pos, '<f4').tobytes()), (b'RUV ', 5, nrv, np.asarray(uv, '<f4').tobytes()),
               (b'RCOL', 5, nrv, np.asarray(col, np.uint8).tobytes()),
               (b'RIDX', 6, len(idx) // 3, np.asarray(idx, '<u2').tobytes()), (b'PART', 4, len(partes), part)]
    out = [b'W3DB', struct.pack('<IIII', 1, 0, len(bloques), 0)]
    for fc, dom, cnt, pl in bloques:
        out += [fc, struct.pack('<III', dom, cnt, len(pl)), pl, bytes((4 - len(pl) % 4) % 4)]
    return b''.join(out)


# ------------------------------------------------------------------------------------------------- estados de GL
def estado_material(m):
    """lo que pone una parte del mundo, por CLAVE (la luz ya esta en el color de vertice)"""
    f = m.get('flags', {})
    tex = m.get('textura')
    con_tex = bool(f.get('textura', True) and tex)
    E = {'textura': [{'paso': 'textura', 'on': con_tex}]}
    if con_tex:
        # el filtro y la repeticion son estado del objeto textura: gfx no los vuelve a mandar si no cambian
        E['fijarTextura'] = [{'paso': 'fijarTextura', 'ref': tex},
                             {'paso': 'texturaFiltro', 'modo': 1 if f.get('filtrado', True) else 0},
                             {'paso': 'texturaRepetir', 'modo': 0 if f.get('repetir', True) else 1}]
    E['caras'] = [{'paso': 'caras', 'on': bool(f.get('culling', True))}]
    E['escribirZ'] = [{'paso': 'escribirZ', 'on': bool(f.get('escribeProfundidad', True))}]
    tr = bool(f.get('transparente', False))
    E['mezclaActiva'] = [{'paso': 'mezclaActiva', 'on': tr}]
    if tr:
        E['mezclaModo'] = [{'paso': 'mezclaModo', 'modo': m.get('mezcla') or 1}]   # (0 = el alfa comun)
    ac = m.get('alfaCorte', 0) or 0
    E['alfaTest'] = [{'paso': 'alfaTest', 'on': ac > 0}]
    if ac > 0:
        E['alfaRef'] = [{'paso': 'alfaRef', 'n': [ac]}]
    return E


def fijos_de(estados):
    """las claves que TODAS las partes ponen igual: van una vez, al empezar"""
    vals = {}
    for E in estados:
        for k, v in E.items():
            vals.setdefault(k, []).append(v)
    return dict((k, v[0]) for k, v in vals.items() if len(v) == len(estados) and all(x == v[0] for x in v))


def cambiar(est, E):
    """los pasos que llevan el estado 'est' al E (y lo actualizan): solo las claves que cambian"""
    P = []
    for k, v in E.items():
        if est.get(k) != v:
            P += v
            est[k] = v
    return P


def rutina(nombre, pasos):
    return {'tipo': 'rutina', 'nombre': nombre, 'version': VERSION_PASOS, 'pasos': pasos}


def mem(nombre, i, por=MEM):
    """el lugar del elemento i de una serie de memorias de 'por' elementos"""
    return '@%s%d[%d]' % (nombre, i // por, i % por)


def lua_tabla(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return '%g' % v
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        return '{' + ', '.join('[%s] = %s' % (json.dumps(k), lua_tabla(x)) for k, x in v.items()) + '}'
    return '{' + ', '.join(lua_tabla(x) for x in v) + '}'


# ------------------------------------------------------------------------------------------------- el armado
def avanzar(w3d, log=print):
    with zipfile.ZipFile(w3d) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    datos = dict((i.filename, d) for i, d in entradas)
    proy = json.loads(datos['proyecto.json'])
    mats = {m['nombre']: m for m in proy.get('materiales', [])}
    entrada_de = {e['nombre']: e['entrada'] for e in proy['mallas']}
    lua = datos['scripts/r100.lua'].decode('utf-8')
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    hijos = col['hijos']
    por_nombre = {o['nombre']: o for o in hijos}
    if 'MUNDO = ' in lua.split('\n', 1)[0] or not any(n in por_nombre for n in CONTENEDORES):
        sys.exit('%s: ya esta en modo avanzado (o no es el mapa r100)' % w3d)

    # lo que un script busca por su nombre (la puerta: r100.lua la gira) sigue clasico
    del_script = set()
    for nombre, d in datos.items():
        if nombre.startswith('scripts/') and nombre.endswith('.lua'):
            del_script |= set(re.findall(r'buscar\("([^"]+)"\)', d.decode('utf-8', 'replace')))
    # los nombres del MAPA de r100.lua (los que tienen permiso: el resto, como el cielo, se dibuja siempre)
    con_permiso = set(re.findall(r'^\s*\{"([^"]+)", -?\d+, (?:true|false), ', lua, re.M))

    # ---------------------------------------------------------------- los grupos (un chunk con sus niveles)
    grupos, clasicos = [], {}
    for cont, fase in CONTENEDORES.items():
        c = por_nombre.get(cont)
        if not c:
            continue
        dmax = float(c.get('distanciaMax', 0) or 0)
        for o in c.get('hijos', []):
            if o['nombre'] in del_script or (o.get('tipo') == 'malla' and not o.get('malla')):
                clasicos.setdefault(cont, []).append(o)
            elif o.get('tipo') == 'lod':
                niveles = [h for h in o.get('hijos', []) if h.get('tipo') == 'malla' and h.get('malla')]
                dist = list(o.get('distancias', []))
                grupos.append({'nombre': o['nombre'], 'fase': fase, 'niveles': niveles, 'dist': dist, 'dmax': dmax,
                               'visible': o.get('visible', True)})
            elif o.get('tipo') == 'malla':
                grupos.append({'nombre': o['nombre'], 'fase': fase, 'niveles': [o], 'dist': [], 'dmax': dmax,
                               'visible': o.get('visible', True)})
            else:
                clasicos.setdefault(cont, []).append(o)

    cache = {}

    def malla(nombre):
        if nombre not in cache:
            cache[nombre] = leer_w3db(datos[entrada_de[nombre]])
        return cache[nombre]

    # ---------------------------------------------------------------- las piezas (un nivel de un grupo)
    piezas = []
    for g in grupos:
        g['piezas'] = []
        for nivel, o in enumerate(g['niveles']):
            if o.get('rot', [0, 0, 0]) != [0, 0, 0] or o.get('escala', [1, 1, 1]) != [1, 1, 1]:
                sys.exit('%s: el mapa no tiene rotaciones ni escalas (esta si)' % o['nombre'])
            M = malla(o['malla'])
            pos = M['pos'].astype(np.float64) + np.array(o.get('pos', [0, 0, 0]), np.float64)
            tris = [(mat, M['idx'][ini:ini + cant].reshape(-1, 3)) for mat, ini, cant in M['partes'] if cant > 0]
            if not tris:
                continue
            # los vertices iguales (posicion, UV y color) soldados, numerados por orden de primer uso (los triangulos
            # vecinos quedan cerca en el VBO)
            clave = np.concatenate([np.round(pos, 4), np.round(M['uv'].astype(np.float64), 5),
                                    M['col'].astype(np.float64)], 1)
            _, primero, inv = np.unique(clave, axis=0, return_index=True, return_inverse=True)
            inv = inv.reshape(-1)
            todos = np.concatenate([t.reshape(-1) for _, t in tris])
            unicos = inv[todos]
            _, primera_vez = np.unique(unicos, return_index=True)
            orden_uso = unicos[np.sort(primera_vez)]
            nuevo = np.empty(len(primero), np.int64)
            nuevo[orden_uso] = np.arange(len(orden_uso))
            src = primero[orden_uso]
            p = {'grupo': g, 'nivel': nivel, 'fase': g['fase'], 'nombre': o['nombre'],
                 'pos': pos[src].astype(np.float32), 'uv': M['uv'][src], 'col': M['col'][src],
                 'tris': [(mat, nuevo[inv[t]]) for mat, t in tris]}
            p['min'], p['max'] = p['pos'].min(0), p['pos'].max(0)
            # la distancia de dibujo del nivel: la del LOD (hasta el siguiente) y la del Culling para el ultimo
            p['lim'] = g['dist'][nivel] if nivel < len(g['dist']) and len(g['niveles']) > 1 else g['dmax']
            g['piezas'].append(p)
            piezas.append(p)
    grupos = [g for g in grupos if g['piezas']]
    for g in grupos:
        g['min'] = np.min([p['min'] for p in g['piezas']], 0)
        g['max'] = np.max([p['max'] for p in g['piezas']], 0)

    # ---------------------------------------------------------------- las mallas unidas (por zona)
    # sin distancia maxima (el cielo y el fondo, lejos y grandes) aparte de los chunks; en cada clase, por celdas de
    # CELDA m recorridas por columnas, y los grupos enteros (sus niveles juntos) hasta MAX_VERTS
    def clave_espacio(g):
        c = (g['min'] + g['max']) / 2
        return (g['dmax'] > 0, int(c[0] // CELDA), int(c[2] // CELDA) * (1 if int(c[0] // CELDA) % 2 == 0 else -1),
                float(c[0]))
    grupos.sort(key=clave_espacio)
    uniones, actual, nv, npz = [], [], 0, 0
    for g in grupos:
        v = sum(len(p['pos']) for p in g['piezas'])
        if v > MAX_VERTS:
            sys.exit('%s: %d vertices no entran en una malla unida' % (g['nombre'], v))
        # (tambien se corta cuando las banderas de sus piezas ya no entran en UNA memoria: el fondo del N95, partido
        # en celdas, son cientos de piezas chicas)
        if actual and (nv + v > MAX_VERTS or (actual[-1]['dmax'] > 0) != (g['dmax'] > 0) or
                       npz + len(g['piezas']) > MEM):
            uniones.append(actual)
            actual, nv, npz = [], 0, 0
        actual.append(g)
        nv += v
        npz += len(g['piezas'])
    if actual:
        uniones.append(actual)

    # las piezas numeradas por malla unida (sus banderas @vp en una sola memoria: un dibujo lee sus banderas de UNA)
    n = 0
    for u, gs in enumerate(uniones):
        cuantas = sum(len(g['piezas']) for g in gs)
        if cuantas > MEM:
            sys.exit('una malla unida con %d piezas (mas que una memoria de banderas)' % cuantas)
        if n // MEM != (n + cuantas - 1) // MEM:
            n = (n // MEM + 1) * MEM
        for g in gs:
            g['u'] = u
            for p in g['piezas']:
                p['i'] = n
                p['u'] = u
                n += 1
    n_piezas = n
    # el permiso de cada grupo del MAPA (r100.lua lo escribe)
    permisos = {}
    for g in grupos:
        if g['nombre'] in con_permiso:
            g['perm'] = len(permisos)
            permisos[g['nombre']] = g
        else:
            g['perm'] = None
    if len(permisos) > MEM * 8:   # (r100.lua las reparte en memorias "perm0", "perm1"... de MEM cada una)
        sys.exit('demasiados grupos con permiso (%d)' % len(permisos))

    def firma(fase, mat):
        m = mats.get(mat, {})
        f = m.get('flags', {})
        return (FASES.index(fase), bool(f.get('transparente')), not f.get('escribeProfundidad', True),
                bool(f.get('culling', True)), m.get('alfaCorte', 0) or 0, m.get('textura', ''), mat)

    # los DIBUJOS: por malla unida, por (fase, material) una parte con los rangos de sus piezas en el orden de la zona
    # (las visibles seguidas van en una llamada), partida de a 85 rangos. Lo opaco de cerca a lejos (L0, L1, L2) y lo
    # translucido de lejos a cerca (no escribe z: lo de adelante tiene que ir despues)
    dibujos, nuevas = [], []
    for u, gs in enumerate(uniones):
        nombre = 'r100_mundo_%d' % u
        ps = [p for g in gs for p in g['piezas']]
        base, offs = 0, {}
        for p in ps:
            offs[id(p)] = base
            base += len(p['pos'])
        claves = sorted(set((p['fase'], mat) for p in ps for mat, _ in p['tris']), key=lambda fm: firma(*fm))
        idx, partes = [], []
        for fase, mat in claves:
            ini = len(idx)
            rangos = []
            for p in sorted((p for p in ps if p['fase'] == fase),
                            key=lambda p: (p['nivel'] if fase == 'opaco' else -p['nivel'], p['i'])):
                t0 = (len(idx) - ini) // 3
                for m2, t in p['tris']:
                    if m2 == mat:
                        idx.extend((t + offs[id(p)]).reshape(-1).tolist())
                t1 = (len(idx) - ini) // 3 - 1
                if t1 >= t0:
                    rangos.append((t0, t1, p['i'] % MEM))
                    p.setdefault('partes', []).append((mat, len(partes), t0, t1))   # (el fondo: capa por capa)
            partes.append((mat, ini, len(idx) - ini))
            if fase == 'fondoalfa':
                continue
            bloque = ps[0]['i'] // MEM
            for j in range(0, len(rangos), (MEM - 1) // 3):
                dibujos.append({'u': u, 'k': len(partes) - 1, 'fase': fase, 'mat': mat, 'bloque': bloque,
                                'rangos': rangos[j:j + (MEM - 1) // 3]})
        datos['mallas/%s.w3db' % nombre] = escribir_w3db(
            nombre, np.concatenate([p['pos'] for p in ps]), np.concatenate([p['uv'] for p in ps]),
            np.concatenate([p['col'] for p in ps]), idx, partes)
        nuevas.append(nombre)
        log('   %s: %d chunks, %d vertices, %d partes, %d triangulos' % (nombre, len(gs), base, len(partes), len(idx) // 3))
    for nombre in nuevas:
        entradas.append((zipfile.ZipInfo('mallas/%s.w3db' % nombre), None))
        proy['mallas'].append({'nombre': nombre, 'entrada': 'mallas/%s.w3db' % nombre, 'carpeta': 'mundo'})
    # los rangos en memorias (varios dibujos por memoria, uno detras del otro: el dibujo apunta a donde empieza el suyo)
    m_rg, o_rg = 0, 0
    for d in dibujos:
        largo = 1 + 3 * len(d['rangos'])
        if o_rg + largo > MEM:
            m_rg, o_rg = m_rg + 1, 0
        d['rg'] = (m_rg, o_rg)
        o_rg += largo

    # ---------------------------------------------------------------- las rutinas
    cabecera = [{'paso': 'luz', 'on': False}, {'paso': 'colorVertice', 'on': False},
                {'paso': 'sombreado', 'on': True}, {'paso': 'texturaModo', 'modo': 0},
                {'paso': 'matrizUV', 'n': [0, 0, 1, 1]}, {'paso': 'testZ', 'on': True},
                {'paso': 'funcionZ', 'modo': 0}, {'paso': 'sesgoZ', 'on': False},
                {'paso': 'sesgoMetros', 'n': [0]}, {'paso': 'color', 'n': [1, 1, 1, 1]},
                {'paso': 'array', 'modo': MODO_ARRAY['vertices'], 'on': True},
                {'paso': 'array', 'modo': MODO_ARRAY['normales'], 'on': False},
                {'paso': 'array', 'modo': MODO_ARRAY['uv'], 'on': True},
                {'paso': 'array', 'modo': MODO_ARRAY['colores'], 'on': True}]

    def apagar(i):
        """deja en 0 la bandera de la pieza i: un test contra una caja a la que ninguna camara llega (@lejos, la escribe
        r100.lua; sin escribir es el origen) con distancia maxima de un milimetro"""
        return {'paso': 'visible', 'entero': -1, 'n': [mem('vp', i), '@lejos[0]', 0.001]}

    def tests(fases):
        """por grupo (salteado si no tiene permiso): el test de cada nivel con su distancia; gana el mas cercano"""
        P = []
        for g in grupos:
            if g['fase'] not in fases:
                continue
            ps = g['piezas']
            # (la caja de la pieza i en @cj: 42 por memoria, 6 floats cada una)
            T = [{'paso': 'visible', 'entero': -1,
                  'n': [mem('vp', p['i']), '@cj%d[%d]' % (p['i'] // CAJAS_POR_MEM, (p['i'] % CAJAS_POR_MEM) * 6),
                        p['lim']]}
                 for p in ps]
            # el mas cercano que pasa apaga a los de mas lejos (de lejos hacia cerca, asi un L1 apagado por el L0 no
            # deja prendido al L2)
            for a in range(len(ps) - 2, -1, -1):
                for b in range(len(ps) - 1, a, -1):
                    T += [{'paso': 'saltarSi', 'entero': 1, 'n': [mem('vp', ps[a]['i'])]}, apagar(ps[b]['i'])]
            if g['perm'] is not None:
                T = [{'paso': 'saltarSi', 'entero': len(T), 'n': [mem('perm', g['perm'])]}] + T
            P += T
        return P

    # el fondo translucido: por franja de ZONA m en x, el orden del Culling clasico (de la camara al centro de la caja de
    # cada capa, la mas lejana primero) visto desde los chunks de esa franja (a la altura de la camara); las franjas
    # con el mismo orden comparten la variante
    capas = [p for p in piezas if p['fase'] == 'fondoalfa']
    variantes, zonas = [], []
    if capas:
        chunks = [g for g in grupos if g['dmax'] > 0]
        camaras = np.array([[(g['min'][0] + g['max'][0]) / 2, g['min'][1] + 1.7, (g['min'][2] + g['max'][2]) / 2]
                            for g in chunks])
        x0 = math.floor(camaras[:, 0].min() / ZONA) * ZONA
        nz = int(math.ceil((camaras[:, 0].max() - x0) / ZONA)) + 1
        centros = [(p['min'] + p['max']) / 2 for p in capas]
        for z in range(nz):
            en = camaras[(camaras[:, 0] >= x0 + z * ZONA) & (camaras[:, 0] < x0 + (z + 1) * ZONA)]
            if not len(en):   # (una franja sin chunks: la de al lado)
                en = camaras[[int(np.argmin(np.abs(camaras[:, 0] - (x0 + (z + 0.5) * ZONA))))]]
            d = [float(np.linalg.norm(en - c, axis=1).mean()) for c in centros]
            orden = tuple(int(k) for k in np.argsort(d)[::-1])
            if orden not in variantes:
                variantes.append(orden)
            zonas.append(variantes.index(orden))

    def bloque_fondo(fijos):
        """una variante por orden: salteada si no es la de la zona (@fo); capa por capa, salteada si no se ve"""
        P = []
        for v, orden in enumerate(variantes):
            B, u_actual = [], None
            for k in orden:
                p = capas[k]
                C = []
                if p['u'] != u_actual:
                    u_actual = p['u']
                    nombre = 'r100_mundo_%d' % p['u']
                    C += [{'paso': 'punteroVertices', 'ref': nombre}, {'paso': 'punteroUV', 'ref': nombre},
                          {'paso': 'punteroColores', 'ref': nombre}]
                D = []
                for mat, kp, t0, t1 in p['partes']:
                    D += cambiar(dict(fijos), estado_material(mats.get(mat, {}))) + [
                        {'paso': 'dibujar', 'ref': 'r100_mundo_%d' % p['u'], 'entero': kp, 'rango': 1, 'n': [t0, t1]}]
                # (los punteros van aunque la capa no se vea: la siguiente de la misma malla los da por puestos)
                B += C + [{'paso': 'saltarSi', 'entero': len(D), 'n': [mem('vp', p['i'])]}] + D
            P += [{'paso': 'saltarSi', 'entero': len(B), 'n': ['@fo[%d]' % v]}] + B
        return P

    def pasada(fase):
        P = list(cabecera) + tests((fase, 'fondoalfa') if fase == 'alfa' else (fase,))
        de_fase = [d for d in dibujos if d['fase'] == fase]
        if not de_fase:
            return P
        estados = [estado_material(mats.get(d['mat'], {})) for d in de_fase]
        if fase == 'alfa':
            estados += [estado_material(mats.get(mat, {})) for p in capas for mat, _, _, _ in p['partes']]
        fijos = fijos_de(estados)
        P += [x for v in fijos.values() for x in v]
        if fase == 'alfa':
            P += bloque_fondo(fijos)
        for u in range(len(uniones)):
            suyos = [(k, d) for k, d in enumerate(dibujos) if d['u'] == u and d['fase'] == fase]
            if not suyos:
                continue
            nombre = 'r100_mundo_%d' % u
            lim = uniones[u][0]['dmax']
            bloque = [{'paso': 'punteroVertices', 'ref': nombre}, {'paso': 'punteroUV', 'ref': nombre},
                      {'paso': 'punteroColores', 'ref': nombre}]
            for k, d in suyos:
                dp = cambiar(dict(fijos), estado_material(mats.get(d['mat'], {}))) + [
                    {'paso': 'dibujar', 'ref': nombre, 'entero': d['k'], 'rango': 2,
                     'n': [0, 0, '@rg%d[%d]' % d['rg'], '@vp%d[0]' % d['bloque']]}]
                # (la parte entera fuera de la camara: ni su textura ni su dibujo)
                bloque += [{'paso': 'visible', 'ref': nombre, 'entero': d['k'], 'n': [mem('dv', k), 0, lim]},
                           {'paso': 'saltarSi', 'entero': len(dp), 'n': [mem('dv', k)]}] + dp
            P += [{'paso': 'visible', 'ref': nombre, 'entero': -1, 'n': [mem('un', u), 0, lim]},
                  {'paso': 'saltarSi', 'entero': len(bloque), 'n': [mem('un', u)]}] + bloque
        return P

    rut_opaco = rutina('r100_MundoOpaco', pasada('opaco'))
    rut_alfa = rutina('r100_MundoTranslucido', pasada('alfa'))

    # ---------------------------------------------------------------- el arbol nuevo
    # el opaco donde estaba el cielo (lo primero del mapa, despues de la niebla); r100_opaco queda como un vacio con
    # r100.lua y lo clasico (la puerta); el translucido (el fondo y los chunks) donde estaba el fondo translucido
    nuevo = []
    # (sin fondo translucido aparte -el N95-, el translucido va donde estaba el resto de lo translucido)
    lugar_alfa = 'r100_fondo_alfa' if any(o.get('nombre') == 'r100_fondo_alfa' for o in hijos) else 'r100_alfa'
    for o in hijos:
        n = o.get('nombre')
        if n == 'r100_cielo':
            nuevo.append(rut_opaco)
            if clasicos.get(n):
                nuevo += clasicos[n]
        elif n == 'r100_opaco':
            v = {'tipo': 'objeto', 'nombre': n, 'pos': [0, 0, 0], 'rot': [0, 0, 0], 'escala': [1, 1, 1],
                 'hijos': clasicos.get(n, [])}
            if o.get('scripts'):
                v['scripts'] = o['scripts']
            nuevo.append(v)
        elif n == lugar_alfa:
            nuevo.append(rut_alfa)
            if clasicos.get(n):
                nuevo += clasicos[n]
        elif n in CONTENEDORES:
            nuevo += clasicos.get(n, [])
        else:
            nuevo.append(o)
    col['hijos'] = nuevo

    # ---------------------------------------------------------------- el script: las tablas del mundo
    cajas = [None] * n_piezas
    for p in piezas:
        cajas[p['i']] = [round(float(v), 3) for v in np.concatenate([p['min'], p['max']])]
    cajas_mem = []
    for j in range(0, n_piezas, CAJAS_POR_MEM):
        trozo = []
        for c in cajas[j:j + CAJAS_POR_MEM]:
            trozo += c if c else [0, 0, 0, 0, 0, 0]
        cajas_mem.append(trozo)
    rangos = [[d['rg'][0], d['rg'][1], len(d['rangos'])] + [x for r in d['rangos'] for x in r] for d in dibujos]
    tabla = {'grupos': dict((n, {'p': g['perm'], 's': [p['i'] for p in g['piezas']]}) for n, g in permisos.items()),
             'rangos': rangos, 'cajas': cajas_mem}
    if variantes:
        tabla['fondo'] = {'x0': x0, 'zona': ZONA, 'v': zonas}
    cab = 'MUNDO = %s  -- (modo avanzado: avanzado_r100.py)\n' % lua_tabla(tabla)
    datos['scripts/r100.lua'] = (cab + lua).encode('utf-8')

    # ---------------------------------------------------------------- las mallas que ya nadie usa salen
    usadas = set()

    def usos(lista):
        for o in lista:
            usadas.add(o.get('malla'))
            for s in o.get('pasos', []):
                if s.get('paso') in ('punteroVertices', 'punteroNormales', 'punteroUV', 'punteroColores', 'dibujar',
                                     'visible'):
                    usadas.add(s.get('ref'))
            usos(o.get('hijos', []))
    usos(proy['escena']['objetos'])
    # (las mallas de los prefabs y de las escenas aparte tambien cuentan)
    for k, d in datos.items():
        if k.startswith(('prefabs/', 'escenas/')) and d:
            usadas |= set(re.findall(r'"malla": "([^"]+)"', d.decode('utf-8', 'replace')))
    sobran = [e for e in proy['mallas'] if e['nombre'] not in usadas and e['nombre'].startswith('r100')
              and any(e['nombre'] == lv.get('malla') for g in grupos for lv in g['niveles'])]
    fuera = set(e['entrada'] for e in sobran)
    nombres_fuera = set(e['nombre'] for e in sobran)
    proy['mallas'] = [e for e in proy['mallas'] if e['nombre'] not in nombres_fuera]
    entradas = [(i, d) for i, d in entradas if i.filename not in fuera]
    datos['proyecto.json'] = json.dumps(proy, ensure_ascii=False).encode('utf-8')
    tmp = w3d + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        for info, _ in entradas:
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            # (las mallas binarias van sin comprimir, como las guarda Whisk3D: se leen de una)
            zi.compress_type = (zipfile.ZIP_STORED if info.filename.endswith('.w3db')
                                else (info.compress_type or zipfile.ZIP_DEFLATED))
            zi.external_attr = info.external_attr
            z.writestr(zi, datos[info.filename])
    os.replace(tmp, w3d)
    log('   modo avanzado: %d chunks (%d piezas) horneados en %d mallas unidas, %d dibujos posibles, '
        '%d pasos (opaco %d, translucido %d), %d mallas sin uso menos'
        % (len(grupos), len(piezas), len(uniones), len(dibujos), len(rut_opaco['pasos']) + len(rut_alfa['pasos']),
           len(rut_opaco['pasos']), len(rut_alfa['pasos']), len(sobran)))
    return {'uniones': len(uniones), 'piezas': len(piezas), 'dibujos': len(dibujos)}


if __name__ == '__main__':
    avanzar(sys.argv[1])
