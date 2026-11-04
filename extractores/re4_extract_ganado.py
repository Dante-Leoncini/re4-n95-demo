#!/usr/bin/env python3
"""
Extractor del GANADO (aldeano) de la cutscene r100s03 (Leon entra a la casa, el aldeano lo ataca) -> GLB para
Whisk3D, con las mismas convenciones que re4_extract_leon.py (y su codigo: atlas, malla, clips):

  - esqueleto: un nodo raiz "ganado" + un nodo hueso_NNN por parte del modelo (34 partes de em1000.bin),
  - UNA malla skinneada "Ganado_cuerpo" con mesh parts opaco / transparente (solo las que existan), UN atlas a la
    mitad de resolucion (PNG externo: el importador de Whisk3D no lee imagenes embebidas), simplificada con
    meshoptimizer (--reducir, default 0.006 como Leon para el N95),
  - metros (escala 0.001), 30 fps, extras.frameRate en cada clip,
  - un clip por corte del evento donde el aldeano tiene motion: "s03_cNN" (NN = numero de corte), largo = largo del
    corte. Los cortes donde no aparece no tienen clip.

El aldeano se arma como lo arma el evento (paquetes SetOm / SetParts del .evd, ver re4_evento.py): cuerpo
em/em10/em1000.bin, mano derecha em10rh00, mano izquierda em10lh03 (la que agarra), cabeza de evento ev1001 (con 9
shape keys de cara, que aca quedan en reposo) y ev1002 (los ojos), texturas em1000.tpl / ev1001.tpl / ev1002.tpl;
todo sale del propio .evd.

RAIZ EN EL MUNDO: las motions del evento traen la posicion de la parte 0 en coordenadas del MUNDO del cuarto (r100),
en milimetros; el evento no ubica a los modelos (no hay paquetes Pos para ellos: quedan en el origen) y las motions
no tienen claves raiz "Null". Asi hueso_000 de cada clip lleva la posicion/rotacion en el mundo (en metros): el
objeto armadura va en el ORIGEN de la escena del cuarto, sin rotar ni escalar, y el clip lo lleva a su lugar.

Tambien exporta los PROPS animados del evento (obm0300, obm0500, obm1000: modelos de 1 parte) como glb aparte en
la misma carpeta, igual: un hueso hueso_000 + la malla skinneada a el + clips s03_cNN en el mundo. El arma del evento
(wep0200) va colgada de la parte 10 (mano derecha) de Leon (paquete Pos flag 0x40000000 = OyaSetObj18) y su motion
esta vacia: es la geometria de wep02:2 = Leon_pistola de leon.glb (Child Of hueso_010), no se exporta aparte.

Y escribe clips.json: por corte, modelo -> glb, clip, frames, motion y la posicion en el mundo (m) de la parte 0 en
el primer frame (Leon incluido: sus clips los agrega `re4_extract_leon.py --evento r100s03.evd` a leon.glb).

Uso:
  python3 re4_extract_ganado.py                 # -> out/ganado/ganado.glb + ganado_atlas.png + props + clips.json
  python3 re4_extract_ganado.py --reducir 0     # la malla original del juego
"""
import argparse
import json
import os
import sys

import re4_extract_leon as L
import re4_evento as E
from motion import modelbin, meshbin, gxtex, gltf  # noqa: E402  (re4_extract_leon ya puso tools/ en el path)

HERE = os.path.dirname(os.path.abspath(__file__))


# archivos que el CUARTO registra para sus eventos (EvtMgr.SetBin en el Init del cuarto): nombre -> bytes.
# Vacio por defecto; ver re4_extract_personajes_evento.py --bins-cuarto.
BINS_CUARTO = {}


def datos(ev, arc, nombre):
    """Bytes de un archivo que pide el evento: del .evd, de los que registro el cuarto (BINS_CUARTO) o de pl00.drs
    para los del jugador (ExeBeginEvt)."""
    if nombre in ev.bins:
        return ev.bins[nombre]
    if nombre in BINS_CUARTO:
        return BINS_CUARTO[nombre]
    stem, idx = E.BINS_LEON[nombre]
    return arc(stem).entry(idx).data


def exportar(ev, arc, modelo, salida, args, raiz_nombre, malla_nombre, reducir):
    """Un modelo del evento (cuerpo + sus SetParts) -> glb skinneado con un clip por corte. Devuelve
    {corte: (clip, frames, motion, frames de la motion, raiz mundo m)}."""
    scale = args.scale
    bin_n, tpl_n = ev.modelos[modelo]
    skel = modelbin.parse(datos(ev, arc, bin_n))
    skel.check_tree()
    n = skel.n_parts
    rest = L.rest_world(skel)
    fuentes = []
    for b_n, t_n in [(bin_n, tpl_n)] + [(b_, t_) for _, b_, t_ in ev.piezas_de(modelo)]:
        fuentes.append((meshbin.parse(datos(ev, arc, b_n)), gxtex.parse_tpl(datos(ev, arc, t_n)),
                        os.path.splitext(os.path.basename(t_n))[0]))

    # ---- atlas (las texturas usadas, a la mitad) ----
    imagenes = {}

    def clave_de(tex, pref, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (pref, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(tex, part.tex_id, alpha)
        return k
    for m, tex, pref in fuentes:
        for part in m.parts:
            if part.triangles():
                clave_de(tex, pref, part)
    atlas, rects = L.armar_atlas(imagenes)
    H, W = atlas.shape[:2]
    out_dir = os.path.dirname(os.path.abspath(salida))
    os.makedirs(out_dir, exist_ok=True)
    atlas_nombre = os.path.splitext(os.path.basename(salida))[0] + '_atlas.png'
    with open(os.path.join(out_dir, atlas_nombre), 'wb') as f:
        f.write(gxtex.png(atlas))
    print(f'{modelo}: {len(fuentes)} modelos, atlas {len(imagenes)} texturas a la mitad -> {atlas_nombre} {W}x{H}')

    # ---- la malla: UNA, skinneada, opaco / transparente ----
    b = gltf.Builder()
    grupos, n_tri, cutoff = L.malla_skinneada(fuentes, clave_de, rects, W, H, scale, reducir)
    prims = []
    for transp, mat, parte in ((False, 0, 'opaco'), (True, 1, 'transparente')):
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        if idx:
            prims.append(L.primitiva(b, pos, nrm, uv, idx, mat, parte, jo, we))
    n_vert = sum(len(g[1]) for g in grupos.values())

    # ---- esqueleto ----
    nodes = [{'name': raiz_nombre, 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'hueso_{p.no:03d}', 'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * scale, -r[1] * scale, -r[2] * scale, 1] for r in rest]
    skin = {'name': f'{raiz_nombre}_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    mesh_node = len(nodes)
    nodes.append({'name': malla_nombre, 'mesh': 0, 'skin': 0})
    print(f'{malla_nombre}: {n_vert} vertices, {n_tri} triangulos, {len(prims)} mesh parts (skinneado, {n} huesos)')

    # ---- un clip por corte ----
    animations, info = [], {}
    for corte in ev.cortes_de(modelo):
        motion = ev.motion(corte, modelo)
        poses, raiz = E.poses_corte(skel, motion, ev.cortes[corte], ik=not args.no_ik, lugar=ev.lugar(modelo))
        animations.append(L.clip_esqueleto(b, nodes, n, poses, ev.clip(corte), args.fps, scale, raiz, skel.roots()))
        w = E.raiz_mundo(poses[0], raiz[0] if raiz else None)
        info[corte] = (ev.clip(corte), len(poses), ev.mots[(corte, modelo)].rsplit('/', 1)[-1], motion.n_frames,
                       [round(c * scale, 4) for c in w])
        print(f'  anim {ev.clip(corte)}: {len(poses)} frames (motion {motion.n_frames}), '
              f'raiz ({w[0] * scale:.3f}, {w[1] * scale:.3f}, {w[2] * scale:.3f}) m')

    textura = {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
    pref = malla_nombre.split('_')[0]
    doc = {
        'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_ganado.py'},
        'scene': 0,
        'scenes': [{'name': raiz_nombre, 'nodes': [0, mesh_node]}],
        'nodes': nodes,
        'skins': [skin],
        'meshes': [{'name': malla_nombre, 'primitives': prims}],
        'images': [{'uri': atlas_nombre}],
        'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],   # CLAMP: es un atlas
        'textures': [{'source': 0, 'sampler': 0}],
        'materials': [
            {'name': f'{pref}_opaco', 'pbrMetallicRoughness': textura, 'extras': {'w3d_transparent': False}},
            {'name': f'{pref}_transparente', 'pbrMetallicRoughness': textura, 'alphaMode': 'MASK', 'alphaCutoff': cutoff,
             'extras': {'w3d_transparent': True}},
        ],
        'extras': {'evento': ev.nombre, 'modelo': modelo,
                   'raiz': 'hueso_000 en coordenadas del mundo del cuarto (m); la armadura va en el origen'},
    }
    if animations:
        doc['animations'] = animations
    doc['accessors'] = b.accessors
    doc['bufferViews'] = b.buffer_views
    gltf.write(doc, bytes(b.blob), salida)
    print(f'-> {salida}: {len(animations)} clips')
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disc', default=L.DEFAULT_DISC, help='imagen del disco (.rvz/.iso/.gcm)')
    ap.add_argument('--evd', default='r100s03.evd', help='el evento (ruta, o nombre en extracted/Evd/ o en el disco)')
    ap.add_argument('--modelo', default='em1000', help='nombre del aldeano en el evento')
    ap.add_argument('-o', '--output', default=os.path.join(HERE, 'out', 'ganado', 'ganado.glb'))
    ap.add_argument('--json', default=None, help='default: clips.json al lado del glb')
    ap.add_argument('--sin-props', action='store_true', help='no exportar los props animados (obmNNNN)')
    ap.add_argument('--scale', type=float, default=0.001, help='unidades por mm del juego (0.001 = metros)')
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--no-ik', action='store_true')
    ap.add_argument('--reducir', type=float, default=0.006,
                    help='error de la simplificacion del aldeano (0 = la malla original del juego)')
    ap.add_argument('--reducir-props', type=float, default=0.0, help='idem para los props (son chicos: 0)')
    args = ap.parse_args()
    arc = L.Archivos(args.disc)
    ev = E.Evento(E.resolver_evd(args.evd, args.disc))
    out_dir = os.path.dirname(os.path.abspath(args.output))
    rel = lambda p: os.path.relpath(p, HERE)   # noqa: E731

    por_modelo = {args.modelo: (rel(args.output), exportar(ev, arc, args.modelo, args.output, args, 'ganado',
                                                           'Ganado_cuerpo', args.reducir))}
    adjuntos = {a[0]: a for a in ev.adjuntos()}
    if not args.sin_props:
        for modelo in ev.modelos:
            if modelo in (args.modelo, 'pl0000') or modelo in adjuntos or not ev.cortes_de(modelo):
                continue
            salida = os.path.join(out_dir, f'{modelo}.glb')
            por_modelo[modelo] = (rel(salida), exportar(ev, arc, modelo, salida, args, modelo, f'{modelo}_malla',
                                                        args.reducir_props))

    # Leon: sus clips van en leon.glb (re4_extract_leon.py --evento); aca solo la posicion de su raiz por corte,
    # evaluada igual (esqueleto pl00:0, el de leon.glb)
    if 'pl0000' in ev.modelos:
        skel = modelbin.parse(arc('pl00').entry(0).data)
        info = {}
        for corte in ev.cortes_de('pl0000'):
            motion = ev.motion(corte, 'pl0000')
            poses, raiz = E.poses_corte(skel, motion, ev.cortes[corte], ik=not args.no_ik, lugar=ev.lugar('pl0000'))
            w = E.raiz_mundo(poses[0], raiz[0] if raiz else None)
            info[corte] = (ev.clip(corte), len(poses), ev.mots[(corte, 'pl0000')].rsplit('/', 1)[-1], motion.n_frames,
                           [round(c * args.scale, 4) for c in w])
        por_modelo['pl0000'] = ('out/leon/leon.glb (re4_extract_leon.py --evento %s.evd)' % ev.nombre, info)

    caras = {}
    for k in ev.paquetes:
        if k.tipo == 'Shp':
            caras.setdefault(k.cut, {})[k.nombre] = k.bin.rsplit('/', 1)[-1]
    cortes = []
    for c, largo in enumerate(ev.cortes):
        mods = {}
        for modelo, (glb, info) in por_modelo.items():
            if c in info:
                clip, frames, mot, mot_frames, w = info[c]
                mods[modelo] = {'glb': glb, 'clip': clip, 'frames': frames, 'motion': mot, 'frames_motion': mot_frames,
                                'raiz_mundo_m': w}
        d = {'corte': c, 'frames': largo, 'modelos': mods}
        if c in caras:
            d['caras_no_exportadas'] = caras[c]
        cortes.append(d)
    doc = {
        'evento': ev.nombre, 'fps': args.fps, 'escala': args.scale, 'frames_total': sum(ev.cortes),
        'convencion': 'un clip por corte "%s_cNN" (NN = corte), largo = largo del corte (si la motion es mas corta se '
                      'sostiene su ultimo frame). hueso_000 lleva la posicion/rotacion en el MUNDO del cuarto en metros: '
                      'la armadura va en el origen de la escena del cuarto, sin transformar. raiz_mundo_m = hueso_000 '
                      'en el frame 0 del clip. Un modelo sin clip en un corte no tiene motion en ese corte (el juego '
                      'hace MotClear al empezar cada corte).' % ev.sufijo,
        'adjuntos': [{'modelo': m, 'padre': p, 'hueso': f'hueso_{parte:03d}',
                      'nota': 'wep0200.bin = wep02:2 (misma geometria) = Leon_pistola de leon.glb; motion vacia'
                      if m == 'wep0200' else ''} for m, p, parte in ev.adjuntos()],
        'cortes': cortes,
    }
    ruta_json = args.json or os.path.join(out_dir, 'clips.json')
    with open(ruta_json, 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print(f'-> {ruta_json}')


if __name__ == '__main__':
    main()
