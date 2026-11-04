#!/usr/bin/env python3
"""
Personajes de la cutscene r100s03 TAL COMO LOS ARMA EL EVENTO, a detalle completo, con las caras animadas
(shape keys), para Whisk3D:

  out/evento_s03/leon_evento.glb      (+ leon_evento_mitad.glb)     Leon  = pl0000 + sus SetParts
  out/evento_s03/ganado_evento.glb    (+ ganado_evento_mitad.glb)   aldeano = em1000 + sus SetParts
  out/evento_s03/*_atlas.png / *_atlas_mitad.png                    atlas a resolucion completa / a la mitad
  out/evento_s03/caras.json                                         pesos de los shapes por frame global del evento

Como arma el juego los modelos (game/event.cpp):
  SetOm "pl0000"   cuerpo em/pl00/pl000a.bin (= pl00:0, ExeBeginEvt) con textura pl000a.tpl (= pl00:1)
  SetParts         cada pieza es un cModelInfo mas en la lista del padre (cModel::addModel), skinneada con las
                   matrices de las partes del PADRE (los ids de Weight son partes del padre).
                   Leon: ev0003 (manos), ev000e (chaqueta del evento; pl000e solo con los trajes 1/2), ev0002 (ojos),
                   ev0001 (cara+cabeza, 29 shapes), pl000d (= pl00:5, pelo/pestanas, transparente),
                   pl000l (= pl00:12, ver abajo).
                   Aldeano: em10rh00 (mano der.), ev1001 (cabeza, 9 shapes), ev1002 (ojos), em10lh03 (mano izq.).
  setPartsOffset   ExePacket_SetPartsSub: si la pieza se llama ev0002 / ev0102 / ev0202 / ev3002 / ev0402 el reposo de
                   TODAS las partes del padre pasa a ser el de los registros de ese .bin (cModel::setPartsOffset:
                   p->pos = rec->center, y lt_inv_mat = inversa del reposo nuevo -> las inverse bind matrices).
                   En r100s03: Leon usa el reposo de ev0002 (cambian las partes 32/33 = ojos, 105, 113).
  Shp (0xC)        ShapeSet(pieza, 0, fcv, flags 2): la cara reproduce <modelo>/face/*.fcv desde el frame 0 y se
                   SOSTIENE (flags 2) -- ver caras() para la evaluacion exacta.
  Mot (0xB)        MotionSetCore + ClrShape(modelo): una motion nueva en el cuerpo APAGA los shapes de sus piezas.

Mallas: un objeto skinneado por pieza (primitivas opaco / transparente segun alphaTex), todas con el mismo esqueleto
(hueso_NNN como leon.glb). La cara ("Leon_ev_cara" / "Ganado_ev_cara") lleva los shapes como morph targets glTF
(POSITION deltas en metros, nombres en mesh.extras.targetNames: shape_NN = indice NN de la tabla de shapes del .bin =
el partsNo del canal del fcv de cara). El juego suma peso * delta a las posiciones ANTES del skinning y no toca las
normales: igual que un morph target glTF.

Ojos: miran con HUESOS (ev0002 / ev1002 estan pesados a las partes 32/33, que las motions del evento animan); el
parpadeo es un SHAPE de la cara (Leon shape_09 = los dos parpados, 10/11 uno solo; aldeano shape_06; ver caras.json).

Animaciones: un clip por corte s03_cNN como re4_extract_leon.py --evento (raiz en el mundo, armadura en el origen),
evaluado con evalhost sobre ESTE esqueleto (reposo del evento). Las partes de tela (chaqueta/pelo de Leon: 64..118) no
tienen claves: en el juego las mueve la simulacion de tela (obj18.cpp PlClothMoveLeon), aca quedan en reposo.

Texturas: el atlas completo tiene cada textura a su tamanio original, en posiciones y tamanios PARES con 4 px de borde;
el atlas "_mitad" es exactamente ese PNG reducido a la mitad (caja 2x2), asi las UV sirven para los dos. El glb
<modelo>_evento.glb usa el completo y <modelo>_evento_mitad.glb (identico salvo images[0].uri) el de la mitad; para
cambiar a mano basta editar images[0].uri del glb (o renombrar los PNG).

Uso:
  python3 re4_extract_personajes_evento.py            # los dos personajes + caras.json
  python3 re4_extract_personajes_evento.py --solo leon
"""
import argparse
import json
import os
import struct
import sys

import numpy as np

import re4_extract_leon as L
import re4_evento as E
import re4_extract_ganado as G
from motion import modelbin, meshbin, gxtex, gltf, fcv  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'evento_s03')

# piezas que pisan el reposo del padre (ExePacket_SetPartsSub)
PISAN_REPOSO = ('ev0002', 'ev0102', 'ev0202', 'ev3002', 'ev0402')

PERSONAJES = {
    'leon': dict(modelo='pl0000', raiz='leon', pref='Leon', cara='ev0001',
                 nombres={'pl0000': 'cuerpo', 'ev0003': 'manos', 'ev000e': 'chaqueta', 'ev0002': 'ojos',
                          'ev0001': 'cara', 'pl000d': 'pelo', 'pl000l': 'pl000l'}),
    'ganado': dict(modelo='em1000', raiz='ganado', pref='Ganado', cara='ev1001',
                   nombres={'em1000': 'cuerpo', 'em100r': 'mano_der', 'ev1001': 'cara', 'ev1002': 'ojos',
                            'em100l': 'mano_izq'}),
    # los dos policias de la introduccion (r100s40 / r120s00 / r120s01): pl0700 (el que maneja) y pl0700a
    'policia': dict(modelo='pl0700', raiz='policia', pref='Policia', cara='ev0701',
                    nombres={'pl0700': 'cuerpo', 'ev0702': 'ojos', 'ev0701': 'cara'}),
    'policia_a': dict(modelo='pl0700a', raiz='policia_a', pref='PoliciaA', cara='ev0701a',
                      nombres={'pl0700a': 'cuerpo', 'ev0702a': 'ojos', 'ev0701a': 'cara', 'ev0703a': 'gafas'}),
}
# sin --solo: los personajes de PERSONAJES que el evento arma (en r100s03: leon y ganado, como siempre)
ORDEN_DEFECTO = ['leon', 'ganado', 'policia', 'policia_a']


# ---------------------------------------------------------------------------------------------------
#  ATLAS a resolucion completa (posiciones/tamanios pares, borde 4) -> la mitad es el PNG reducido 2x
# ---------------------------------------------------------------------------------------------------
PAD = 4


def armar_atlas_completo(imagenes):
    orden = sorted(imagenes, key=lambda k: (-imagenes[k].shape[0], -imagenes[k].shape[1], str(k)))
    for k, im in imagenes.items():
        if im.shape[0] % 2 or im.shape[1] % 2:
            raise ValueError(f'textura {k} de tamanio impar {im.shape[:2]}: el atlas mitad no seria exacto')
    area = sum((m.shape[0] + 2 * PAD) * (m.shape[1] + 2 * PAD) for m in imagenes.values())
    ancho = max(m.shape[1] for m in imagenes.values()) + 2 * PAD
    W = 64
    while W < 4096 and (W * W < area or W < ancho):
        W *= 2
    while True:
        pos, x, y, alto = {}, 0, 0, 0
        for k in orden:
            h, w = imagenes[k].shape[:2]
            if x + w + 2 * PAD > W:
                x, y, alto = 0, y + alto, 0
            pos[k] = (x + PAD, y + PAD, w, h)
            x += w + 2 * PAD
            alto = max(alto, h + 2 * PAD)
        H = 1
        while H < y + alto:
            H *= 2
        if H <= W or W >= 4096:
            break
        W *= 2
    atlas = np.zeros((H, W, 4), np.uint8)
    for k, (x, y, w, h) in pos.items():
        atlas[y - PAD:y + h + PAD, x - PAD:x + w + PAD] = np.pad(imagenes[k], ((PAD, PAD), (PAD, PAD), (0, 0)), mode='edge')
    return atlas, pos


def atlas_mitad(atlas):
    a = atlas.astype(np.float32)
    m = (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) / 4.0
    return np.clip(np.floor(m + 0.5), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------
#  el esqueleto del evento
# ---------------------------------------------------------------------------------------------------
def esqueleto_evento(ev, arc, modelo):
    """modelbin.Model del cuerpo con el reposo que deja el evento (setPartsOffset de ev0002 & co.)."""
    bin_n, _ = ev.modelos[modelo]
    skel = modelbin.parse(G.datos(ev, arc, bin_n))
    skel.check_tree()
    fuente = None
    for nombre, b_n, _ in ev.piezas_de(modelo):
        if nombre in PISAN_REPOSO:
            pz = modelbin.parse(G.datos(ev, arc, b_n))
            if pz.n_parts < skel.n_parts:
                raise ValueError(f'{nombre}: {pz.n_parts} registros < {skel.n_parts} partes del padre')
            cambios = []
            for i, p in enumerate(skel.parts):
                c = pz.parts[i].pos
                if max(abs(a - b) for a, b in zip(p.pos, c)) > 1e-4:
                    cambios.append(i)
                p.pos = tuple(c)   # cModel::setPartsOffset: p->pos = rec->center (el padre no cambia)
            fuente = (nombre, cambios)
    return skel, fuente


# ---------------------------------------------------------------------------------------------------
#  una pieza -> primitivas (opaco / transparente) skinneadas, con shapes
# ---------------------------------------------------------------------------------------------------
def malla_pieza(b, m, tex, pref, clave_de, rects, W, H, scale, mat_opaco, mat_transp):
    grupos = {False: ({}, [], [], [], [], [], []), True: ({}, [], [], [], [], [], [])}
    cutoff = None
    n_tri = 0
    for part in m.parts:
        tris = part.triangles()
        if not tris:
            continue
        k = clave_de(tex, pref, part)
        transp = k[2] is not None
        if transp:
            c = (part.alpha_ref + 1) / 255.0
            cutoff = c if cutoff is None else min(cutoff, c)
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        vistos = set()
        for tri in tris:
            if len({v[0] for v in tri}) < 3 or frozenset(tri) in vistos:
                continue
            vistos.add(frozenset(tri))
            for v in tri:
                vk = (k, v)
                i = index.get(vk)
                if i is None:
                    i = index[vk] = len(pos)
                    pos.append(tuple(c * scale for c in m.position(v[0])))
                    nrm.append(tuple(gltf.normalize(m.normal(v[1]))))
                    uv.append(L.uv_atlas(m.texcoord(v[3]), rects[k], W, H))
                    pares = m.skin(v[0])
                    pares = pares + [(0, 0.0)] * (4 - len(pares))
                    jo.append(tuple(j for j, _ in pares))
                    we.append(tuple(w for _, w in pares))
                idx.append(i)
            n_tri += 1
    deltas = [m.shape_deltas(s) for s in range(len(m.shapes or []))]
    prims, n_vert, verts_shape = [], 0, []
    for transp, mat, parte in ((False, mat_opaco, 'opaco'), (True, mat_transp, 'transparente')):
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        if not idx:
            continue
        prim = L.primitiva(b, pos, nrm, uv, idx, mat, parte, jo, we)
        vidx = [None] * len(pos)
        for (k, v), i in index.items():
            vidx[i] = v[0]
        if deltas:
            cero = (0.0, 0.0, 0.0)
            prim['targets'] = [{'POSITION': b.accessor('3f', gltf.FLOAT, 'VEC3',
                                                       [tuple(c * scale for c in d.get(vi, cero)) for vi in vidx],
                                                       gltf.ARRAY_BUFFER, minmax=True)} for d in deltas]
        verts_shape.append((np.array(pos), vidx))
        prims.append(prim)
        n_vert += len(pos)
    return prims, n_vert, n_tri, cutoff, verts_shape


# ---------------------------------------------------------------------------------------------------
#  CARAS: ShapeSet / ShapeMove / CalculateShape_new (game/shape.cpp) por frame global del evento
# ---------------------------------------------------------------------------------------------------
def _hermite(x, v, t):
    t2 = t * t
    t3 = t * t2
    h01 = -(t3 + t3) + 3.0 * t2
    h11 = t3 - t2
    h10 = h11 - t2 + t
    return x[0] * (1.0 - h01) + x[1] * h01 + v[0] * h10 + v[1] * h11


def _clave(t, k):
    vf, tf = fcv.FCC_FMT[t]
    val = fcv.to_float(vf, k[0])
    if tf is None:
        return val, 0.0, 0.0
    return val, fcv.to_float(tf, k[1]), fcv.to_float(tf, k[2])


def hermite_eje(ax, t, frame, max_frame):
    """HermiteInterpolation (motion.cpp) de UN eje con flags 2 (sin loop): >= maxFrame -> ultima llave; llave exacta
    -> su valor; entre llaves hermite({v0, v1}, {out0, in1}, (f - f0) / (f1 - f0))."""
    fr = ax.frames
    n = len(fr)
    if n == 0:
        return 0.0
    if max_frame <= frame:
        return _clave(t, ax.keys[n - 1])[0]
    for i in range(n):
        if fr[i] == frame:
            return _clave(t, ax.keys[i])[0]
        if fr[i] < frame:
            nx = i + 1 if i + 1 < n else 0
            if frame < fr[nx]:
                v0, _, o0 = _clave(t, ax.keys[i])
                v1, i1, _ = _clave(t, ax.keys[nx])
                return _hermite((v0, v1), (o0, i1), (frame - fr[i]) / (fr[nx] - fr[i]))
    raise ValueError(f'frame {frame} fuera de las llaves {fr}')


def pesos_shape(sd, rate, n_shapes):
    """CalculateShape_new: por canal con flags & 4, peso = result[1] (eje Y) / 100 del shape idx[i] (shapeFlags 2:
    sin el x1.37 del bit 3). Los canales se SUMAN (cada uno agrega su delta)."""
    w = [0.0] * n_shapes
    max_frame = float(sd.n_frame & 0x3FFF) + 1.0
    for j in sd.joints:
        if not (j.kind & 4):   # flags[i] & 4 (fcv.Joint.kind = byte bajo, fcc_type = bits 12-15)
            continue
        v = hermite_eje(j.axes[1], j.fcc_type, float(rate), max_frame) / 100.0
        w[j.parts_no] += v
    return w


def caras(ev, personajes):
    """personajes: {malla: (modelo cuerpo, pieza cara, n_shapes)} -> ({malla: [pesos por frame]}, {malla: [(fcv,
    rate) | None por frame]}). Simula frame a frame lo que hace el juego:
      Event::Run ejecuta los paquetes del frame (en orden) y despues ObjMgr.move -> objMove -> ShapeMove.
      Mot (motion no vacia) en el cuerpo -> ClrShape: pShape = NULL (cara neutra).
      Shp en la pieza -> ShapeSet(flags 2): shape_frame = 0.
      ShapeMove: si hay pShape: slot = rate shape_frame; shape_frame++; si >= nFrame - 1 -> shape_frame-- (flags 2 =
      sostener: el ultimo rate usado es nFrame - 2). Sin pShape los slots quedan vacios (pesos 0).
    Un corte sin Mot para el cuerpo NO apaga la cara (sigue el fcv del corte anterior)."""
    estado = {m: None for m in personajes}      # malla -> [ShapeData, nombre, shape_frame]
    pesos = {m: [] for m in personajes}
    fuente = {m: [] for m in personajes}
    por_pieza = {pz: m for m, (_, pz, _) in personajes.items()}
    por_cuerpo = {}
    for m, (cu, _, _) in personajes.items():
        por_cuerpo.setdefault(cu, []).append(m)
    paq = {}
    for k in ev.paquetes:
        if k.tipo in ('Mot', 'Shp'):
            paq.setdefault((k.cut, k.frame), []).append(k)
    for c, largo in enumerate(ev.cortes):
        for f in range(largo):
            for k in paq.get((c, f), []):
                if k.tipo == 'Mot' and k.nombre in por_cuerpo:
                    if struct.unpack('>H', ev.bins[k.bin][:2])[0] == 0:
                        continue   # ExePacket_Mot: motion vacia -> return antes de ClrShape
                    for m in por_cuerpo[k.nombre]:
                        estado[m] = None
                elif k.tipo == 'Shp' and k.nombre in por_pieza:
                    d = ev.bins[k.bin]
                    sd = fcv.parse(d)
                    sd.n_frame = struct.unpack('>H', d[:2])[0]   # ShapeData.nFrame (u16 entero)
                    if sd.n_frame == 0:
                        estado[por_pieza[k.nombre]] = None      # ShapeSet: "frame 0 data" -> ShapeEnd
                    else:
                        estado[por_pieza[k.nombre]] = [sd, k.bin.rsplit('/', 1)[-1], 0]
            for m, (_, _, n_sh) in personajes.items():
                e = estado[m]
                if e is None:
                    pesos[m].append([0.0] * n_sh)
                    fuente[m].append(None)
                    continue
                sd, nombre, sf = e
                pesos[m].append(pesos_shape(sd, sf, n_sh))
                fuente[m].append((nombre, sf))
                sf += 1
                if sf >= sd.n_frame - 1:
                    sf -= 1
                e[2] = sf
    return pesos, fuente


# ---------------------------------------------------------------------------------------------------
def exportar(ev, arc, cfg, args, ev_malla=None):
    """ev_malla: el evento del que salen el esqueleto, las mallas y las texturas (default: el mismo `ev`); los clips
    salen siempre de `ev`. Sirve para que Leon de otro evento tenga EXACTAMENTE la malla / atlas de r100s03."""
    ev_malla = ev_malla or ev
    scale = args.scale
    modelo = cfg['modelo']
    pref = cfg['pref']
    skel, pisa = esqueleto_evento(ev_malla, arc, modelo)
    n = skel.n_parts
    rest = L.rest_world(skel)
    bin_n, tpl_n = ev_malla.modelos[modelo]
    lista = [(modelo, bin_n, tpl_n)] + ev_malla.piezas_de(modelo)
    if ev_malla is not ev:
        propias = [(modelo,) + ev.modelos[modelo]] + ev.piezas_de(modelo)
        if [(x[0], x[1]) for x in propias] != [(x[0], x[1]) for x in lista] or any(
                G.datos(ev, arc, a[1]) != G.datos(ev_malla, arc, b_[1]) for a, b_ in zip(propias, lista)):
            raise ValueError(f'{modelo}: las piezas / .bin de {ev.nombre} no son las de {ev_malla.nombre}')
        distintas = [f'{a[0]}: {a[2]} -> {b_[2]}' for a, b_ in zip(propias, lista) if a[2] != b_[2]]
        print(f'{modelo}: malla y texturas de {ev_malla.nombre} (mismos .bin; tpl cambiados: {distintas or "ninguno"})')
    fuentes = []
    for nombre, b_n, t_n in lista:
        fuentes.append((nombre, b_n, t_n, meshbin.parse(G.datos(ev_malla, arc, b_n)),
                        gxtex.parse_tpl(G.datos(ev_malla, arc, t_n)), os.path.splitext(os.path.basename(t_n))[0]))
    print(f'{modelo}: {len(fuentes)} modelos ({", ".join(f[0] for f in fuentes)}), {n} partes'
          + (f'; reposo de {pisa[0]} (partes cambiadas {pisa[1]})' if pisa else ''))

    # ---- atlas ----
    imagenes = {}

    def clave_de(tex, tp, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (tp, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for _, _, _, m, tex, tp in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, tp, part)
    atlas, rects = armar_atlas_completo(imagenes)
    H, W = atlas.shape[:2]
    base = cfg['raiz'] + '_evento'
    os.makedirs(OUT, exist_ok=True)
    png_full, png_mitad = base + '_atlas.png', base + '_atlas_mitad.png'
    with open(os.path.join(OUT, png_full), 'wb') as f:
        f.write(gxtex.png(atlas))
    with open(os.path.join(OUT, png_mitad), 'wb') as f:
        f.write(gxtex.png(atlas_mitad(atlas)))
    print(f'  atlas: {len(imagenes)} texturas -> {png_full} {W}x{H} y {png_mitad} {W // 2}x{H // 2}')

    b = gltf.Builder()
    # ---- esqueleto ----
    nodes = [{'name': cfg['raiz'], 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': f'{cfg["raiz"]}_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}

    # ---- mallas: una por pieza ----
    materials = [{'name': f'{pref}_ev_opaco', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                                       'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                  'extras': {'w3d_transparent': False}}]
    meshes, mesh_nodes, resumen, cara_info = [], [], [], None
    for nombre, b_n, t_n, m, tex, tp in fuentes:
        malla = f'{pref}_ev_{cfg["nombres"].get(nombre, nombre)}'
        # material transparente propio por cutoff (alphaSetup: alpha > alphaRef)
        prims, nv, nt, cutoff, vs = malla_pieza(b, m, tex, tp, clave_de, rects, W, H, scale, 0, None)
        for pr in prims:
            if pr['material'] is None:
                nombre_mat = f'{pref}_ev_transparente_{int(round(cutoff * 255)) - 1}'
                idx = next((i for i, mt in enumerate(materials) if mt['name'] == nombre_mat), None)
                if idx is None:
                    idx = len(materials)
                    materials.append({'name': nombre_mat,
                                      'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0,
                                                               'roughnessFactor': 1.0},
                                      'alphaMode': 'MASK', 'alphaCutoff': cutoff, 'extras': {'w3d_transparent': True}})
                pr['material'] = idx
        mesh = {'name': malla, 'primitives': prims,
                'extras': {'re4': {'pieza': nombre, 'bin': b_n, 'tpl': t_n}}}
        n_sh = len(m.shapes or [])
        if n_sh:
            mesh['weights'] = [0.0] * n_sh
            mesh['extras']['targetNames'] = [f'shape_{k:02d}' for k in range(n_sh)]
        mesh_nodes.append(len(nodes))
        nodes.append({'name': malla, 'mesh': len(meshes), 'skin': 0})
        meshes.append(mesh)
        resumen.append((malla, nombre, b_n, nv, nt, n_sh, [p['extras']['w3d_part'] for p in prims]))
        print(f'  {malla:22s} {nombre:7s} {nv:5d} vertices {nt:5d} triangulos  {len(prims)} parts'
              + (f'  {n_sh} shapes' if n_sh else ''))
        if nombre == cfg['cara']:
            if malla != f'{pref}_ev_cara':
                raise ValueError(malla)
            cara_info = (malla, m, vs)

    # (el arma del evento, wep0200 colgada de la parte 10 por Pos flag 0x40000000, es Leon_pistola de leon.glb: no va aca)

    # ---- clips ----
    animations = []
    for corte in ev.cortes_de(modelo):
        motion = ev.motion(corte, modelo)
        poses, raiz = E.poses_corte(skel, motion, ev.cortes[corte], ik=not args.no_ik, lugar=ev.lugar(modelo))
        animations.append(L.clip_esqueleto(b, nodes, n, poses, ev.clip(corte), args.fps, scale, raiz, skel.roots()))
    print(f'  {len(animations)} clips: {", ".join(a["name"] for a in animations)}')

    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_personajes_evento.py'},
        'scene': 0,
        'scenes': [{'name': cfg['raiz'], 'nodes': [0] + mesh_nodes}],
        'nodes': nodes,
        'skins': [skin],
        'meshes': meshes,
        'images': [{'uri': png_full}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': materials,
        'animations': animations,
        'extras': {'evento': ev.nombre, 'modelo': modelo,
                   'raiz': 'hueso_000 en coordenadas del mundo del cuarto (m); la armadura va en el origen',
                   'reposo': f'setPartsOffset({pisa[0]})' if pisa else 'el del cuerpo',
                   'atlas': {'completo': png_full, 'mitad': png_mitad}},
    }
    if ev_malla is not ev:
        doc['extras']['malla_de'] = (f'{ev_malla.nombre}: mismo esqueleto, mallas y atlas que el glb de ese evento '
                                     f'(los clips son de {ev.nombre})')
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    blob = bytes(b.blob)
    salida = os.path.join(OUT, base + '.glb')
    gltf.write(doc, blob, salida)
    doc['images'] = [{'uri': png_mitad}]
    gltf.write(doc, blob, os.path.join(OUT, base + '_mitad.glb'))
    print(f'  -> {salida} (+ {base}_mitad.glb)')
    return dict(glb=os.path.relpath(salida, HERE), resumen=resumen, cara=cara_info, modelo=modelo,
                atlas=(W, H), clips=len(animations))


def validar_cara(malla, m, vs, pesos):
    """max delta por shape (mm), cuantos vertices mueve y donde (el shape aplicado con numpy)."""
    print(f'  {malla}: {len(m.vtx)} vertices en el .bin, '
          f'{sum(len(p) for p, _ in vs)} en el glb; {len(m.shapes)} shapes')
    P = np.concatenate([p for p, _ in vs]) * 1000.0
    vidx = sum((v for _, v in vs), [])
    usados = set()
    for f in pesos:
        usados |= {i for i, w in enumerate(f) if w != 0.0}
    for k in range(len(m.shapes)):
        d = m.shape_deltas(k)
        D = np.array([d.get(vi, (0.0, 0.0, 0.0)) for vi in vidx])
        mag = np.linalg.norm(D, axis=1)
        mov = mag > 1e-6
        centro = P[mov].mean(0) if mov.any() else np.zeros(3)
        print(f'    shape_{k:02d}: max {mag.max():6.2f} mm, {int(mov.sum()):4d} vertices, zona media '
              f'({centro[0]:6.1f}, {centro[1]:7.1f}, {centro[2]:6.1f}) mm{"  (usado)" if k in usados else ""}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=L.DEFAULT_DISC)
    ap.add_argument('--evd', default='r100s03.evd')
    ap.add_argument('--solo', choices=sorted(PERSONAJES))
    ap.add_argument('--scale', type=float, default=0.001)
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--no-ik', action='store_true')
    ap.add_argument('--out', default=None, help='carpeta de salida (default out/evento_s03)')
    ap.add_argument('--malla-de', default=None, metavar='EVD',
                    help='toma el esqueleto, las mallas y las texturas de Leon (pl0000) de ESE evento (ej. r100s03.evd) '
                         'y solo los clips / caras de --evd: asi una misma armadura Leon_ev tiene los clips de los dos')
    ap.add_argument('--bins-cuarto', action='store_true',
                    help='agrega los archivos que st1/r100.cpp R100Init registra para sus eventos (EvtMgr.SetBin: '
                         'em/pl07/pl0700.bin = ROOM_ARC 0x24, pl0700.tpl = 0x25, pl0700a.bin = 0x26, obm2a00 = 0x1D/0x1E): '
                         'los usan r100s41 / s43 / s44, que no los traen en el .evd')
    args = ap.parse_args()
    global OUT
    if args.out:
        OUT = os.path.abspath(args.out)
    if args.bins_cuarto:
        from motion import archive
        cuarto = archive.Archive(os.path.join(HERE, 'extracted', 'St1', 'r100.das'))
        for nombre, n_arc in (('em/pl07/pl0700a.bin', 0x26), ('em/pl07/pl0700.bin', 0x24), ('em/pl07/pl0700.tpl', 0x25),
                              ('obj/objmodel/obm2a00.bin', 0x1D), ('obj/objmodel/obm2a00.tpl', 0x1E)):
            G.BINS_CUARTO[nombre] = cuarto.entry(n_arc - 4).data
    arc = L.Archivos(args.disc)
    ev = E.Evento(E.resolver_evd(args.evd, args.disc))
    ev_malla = E.Evento(E.resolver_evd(args.malla_de, args.disc)) if args.malla_de else None

    hechos = {}
    for clave in ([args.solo] if args.solo else [k for k in ORDEN_DEFECTO if PERSONAJES[k]['modelo'] in ev.modelos]):
        hechos[clave] = exportar(ev, arc, PERSONAJES[clave], args, ev_malla if clave == 'leon' else None)

    # ---- caras.json ----
    pers = {}
    for clave, h in hechos.items():
        malla, m, _ = h['cara']
        pers[malla] = (h['modelo'], PERSONAJES[clave]['cara'], len(m.shapes))
    pesos, fuente = caras(ev, pers)
    inicio, cortes = 0, []
    for c, largo in enumerate(ev.cortes):
        cortes.append({'corte': c, 'inicio': inicio, 'frames': largo})
        inicio += largo
    doc = {
        'evento': ev.nombre, 'fps': args.fps, 'frames_totales': inicio, 'cortes': cortes,
        'formato': 'por malla de cara: shapes = nombres en el orden de los morph targets del glb (shape_NN = indice NN de '
                   'la tabla de shapes del .bin); pesos[frame global][k] = peso del shape k (1 = delta completo; el '
                   'juego NO lo limita a 0..1: hay claves negativas y > 100%); fuente[frame] = [fcv, frame del shape] '
                   'o null (cara neutra). Frame global = inicio del corte + frame del corte (mismo eje que evento.json).',
        'regla': 'Shp -> ShapeSet(flags 2) arranca el fcv en 0 y sostiene su frame nFrame-2; un paquete Mot del cuerpo '
                 '(ClrShape) apaga la cara; un corte sin Mot del cuerpo sigue con la cara del anterior. '
                 'Peso = HermiteInterpolation(canal, frame).y / 100 (shape.cpp CalculateShape_new); el juego suma '
                 'round-to-s16(delta * peso) por vertice, aca el peso es continuo.',
        'ojos': 'los ojos miran con huesos (hueso_032 / hueso_033, en los clips); el parpadeo es un shape de la cara',
    }
    for malla, (modelo, pieza, n_sh) in pers.items():
        glb = next(h['glb'] for h in hechos.values() if h['cara'][0] == malla)
        doc[malla] = {'modelo': modelo, 'pieza': pieza, 'glb': glb, 'shapes': [f'shape_{k:02d}' for k in range(n_sh)],
                      'pesos': [[round(w, 5) for w in f] for f in pesos[malla]],
                      'fuente': [list(x) if x else None for x in fuente[malla]]}
    ruta = os.path.join(OUT, 'caras.json')
    with open(ruta, 'w') as f:
        json.dump(doc, f, separators=(',', ':'), ensure_ascii=False)
    print(f'-> {ruta}')

    # ---- validacion ----
    print('validacion:')
    for clave, h in hechos.items():
        malla, m, vs = h['cara']
        validar_cara(malla, m, vs, pesos[malla])
    for malla in pers:
        W = np.array(pesos[malla])
        activos = [c['corte'] for c in cortes if np.abs(W[c['inicio']:c['inicio'] + c['frames']]).max() > 0]
        print(f'  {malla}: cortes con cara animada {activos}')
    if 'Leon_ev_cara' in pesos and ev.nombre == 'r100s03':
        W = np.array(pesos['Leon_ev_cara'])[750:857]
        var = W.max(0) - W.min(0)
        print(f'  Leon_ev_cara frames 750..856 (corte 8): rango de peso por shape usado '
              + ', '.join(f'{k}:{var[k]:.2f}' for k in np.nonzero(var)[0]))
        h = hechos['leon']
        _, m, vs = h['cara']
        P = np.concatenate([p for p, _ in vs]) * 1000.0
        vidx = sum((v for _, v in vs), [])
        f = 750 + int(np.argmax(np.abs(np.array(pesos['Leon_ev_cara'])[750:857]).sum(1)))
        w = pesos['Leon_ev_cara'][f]
        D = np.zeros_like(P)
        for k, wk in enumerate(w):
            if wk:
                d = m.shape_deltas(k)
                D += wk * np.array([d.get(vi, (0.0, 0.0, 0.0)) for vi in vidx])
        mag = np.linalg.norm(D, axis=1)
        top = np.argsort(-mag)[:20]
        print(f'  frame {f}: con los pesos del juego la cara mueve {int((mag > 0.05).sum())} vertices (> 0.05 mm), '
              f'max {mag.max():.2f} mm; los 20 que mas se mueven estan en '
              f'y {P[top, 1].min():.0f}..{P[top, 1].max():.0f} mm, z {P[top, 2].min():.0f}..{P[top, 2].max():.0f} mm '
              f'(cabeza y {P[:, 1].min():.0f}..{P[:, 1].max():.0f})')


if __name__ == '__main__':
    main()
