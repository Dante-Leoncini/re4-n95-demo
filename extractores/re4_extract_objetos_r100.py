#!/usr/bin/env python3
"""
Objetos y bichos de r100 (RE4 GameCube USA) -> out/objetos_r100/ para el port nativo del N95:

  objetos_r100.json        resumen: cepos, el perro del cepo, cajas de madera, cuervos y los eventos de "examinar"
                           (colocaciones en metros, reglas del juego, parametros, sonidos, efectos, camaras, textos)
  cepo.glb                 el cepo (em2a ARC 4/5) con sus clips (abierto, morder, cerrar vacio, perro, reabrir ...)
  bomba_alambre.glb        la trampa de alambre con bomba (em2a type 2, ARC 8/9) en pose de reposo
  perro.glb                el perro (em21 ARC 4 + textura type 1 ARC 6) con los clips del cepo y la huida
  cuervo.glb               el cuervo (em23 ARC 5/8) con las dos alas (ARC 7 en el piso, ARC 6 en el aire) y sus clips
  leon_objetos.glb         Leon (re4_extract_leon.py) con los clips "cepo_atrapado" (em2a ARC 0x10 + SEQ 0x11) y
                           "soltar_perro" (em21 ARC 0x1B)
  caja_chica.glb / caja_mediana.glb          et0100.bin / et0200.bin (r100.das ETM) con la textura del EFM 0x04
  caja_chica_restos.glb / caja_mediana_restos.glb   el EFM 0x04 de et01.eff / et02.eff (los restos en el piso)
  caja_trozos.glb          las piezas que salen volando (EFM 0x01 y 0x0E de core.das, un nodo por parte)
  textures/*.png, *_N.png  texturas
  sonidos/*.wav            los SE que tocan (un WAV por SIT; los grupos al azar con todos sus miembros)

Convenciones: metros (mm * 0.001), Y arriba, coordenadas del cuarto r100; yaw en radianes con la convencion del juego
(el modelo mira a (sin y, 0, cos y)); 30 fps. Los glb animados: nodo raiz + hueso_NNN (una parte del modelo cada uno),
hueso_000 lleva la raiz de la motion relativa al frame 0 (igual que out/ganado_juego).

Fuentes (decomp ../re4/src): em2a/em2a.cpp (em2a_R0_Init, em2aDmCkTrap1/2, em2a_R1_Trap1Set/Bite/BiteSub/Break/Reset/
Trap1R100/Trap2Set/Bomb, plem2a_Trap1Bite, em2aTrap1BiteCk, em2aTrap1BiteSubCk, em2aTrap1CamMove, em2aTrap2HitCkPL/EM,
em2aTrap2Bomb, em2aYarareInit), em21/em21.cpp (em21DmCk, em21_R0_Init, em21_R1_R100TrapWait/TrapCancel/R100Escape,
em21TrapCancelAction, plemTrapCancel, plem21TrapCamMove, em21TrapSearch, em21EscapeWithYou), em23/em23.cpp (em23DmCk,
em23_R0_Init, em23_R1_Wait/Takeoff/TakeoffDash/Turn/Dm_Air/Die_Normal, em23SetWing, em23AddSpeedAir),
game/EtcModel.cpp (Et01_init, Et02_init), game/embox.cpp (SetBox, emBoxDmCk, emBoxSetBreak, emBox_R1_Break,
emBoxActEvtCk, emBoxAction, emBoxSetItem), game/em.cpp (SE de la SEQ: SndCall(8, Se - 1)), game/em_set.cpp,
game/sce_at.cpp (sceAtFunc_mes, SceAtSetMes, sceAtFunc_save), game/sce_com.cpp (SceUpCut, SceMesSet),
game/cam_ctrl.cpp (CutCall), st1/r100.cpp (R100Init, r100_trap_set, r100_Sce_zombi_dead, r100_MesDoor, r100_MesTruck,
r100_MesBrige, r100_mes_gaikotu*), st1/r119.cpp (SCF_R100_DOG_RUN).
Disco: em/em2a.drs, em/em21.drs, em/em23.drs, em/pl00.drs, St1/r100.das (CAM, AEV, MDT, ETS, ETM), etc/core.das,
etc/emleon00.esl. Lee out/items/items_r100.json (correr antes re4_extract_items.py).

Uso:  python3 re4_extract_objetos_r100.py [--sin-leon]
"""
import argparse
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import re4_extract_leon as L                 # noqa: E402  (pone ../re4/tools en el path)
import re4_extract_r100 as R                 # noqa: E402
import re4_extract_acciones as A             # noqa: E402
import re4_extract_ganado_juego as GJ        # noqa: E402
import re4_extract_salto_ventana as V        # noqa: E402
import re4_extract_emboscada_r100 as EMB     # noqa: E402
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf  # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'tools'))
import re4_eff                               # noqa: E402
import re4_sonidos as S                      # noqa: E402

meshbin._zero_pad = lambda *a: None
OUT = os.path.join(HERE, 'out', 'objetos_r100')
EXT = os.path.join(HERE, 'extracted')
MM = 0.001
FPS = 30.0
ROOM = 0x100


def rn(v, n=4):
    if isinstance(v, (list, tuple, np.ndarray)):
        return [rn(x, n) for x in v]
    return round(float(v), n)


def m3(v_mm):
    return rn([c * MM for c in v_mm])


# ---------------------------------------------------------------------------------------------------
#  evalhost en Windows: el Makefile de tools/motion/host arma un .so de Linux (mmap MAP_32BIT). Aca se arma la
#  misma biblioteca como DLL con el g++ de MSYS2 (mingw64) y un sys/mman.h minimo (VirtualAlloc debajo de 4 GB),
#  en tools/motion_host_win/. Los fuentes son los mismos (host/build/*_prep.cpp + motion_host.cpp + fdlibm).
# ---------------------------------------------------------------------------------------------------
MMAN_H = r'''#pragma once
#include <windows.h>
#include <stdint.h>
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_ANONYMOUS 0x20
#define MAP_32BIT 0x40
#define MAP_FAILED ((void*) -1)
static inline void* mmap(void* a, size_t n, int p, int f, int fd, long o)
{
    for (uintptr_t base = 0x10000000u; base < 0xF0000000u; base += 0x100000u) {
        void* r = VirtualAlloc((void*) base, n, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (r) {
            return r;
        }
    }
    return MAP_FAILED;
}
static inline int munmap(void* p, size_t n)
{
    VirtualFree(p, 0, MEM_RELEASE);
    return 0;
}
'''
FDLIBM = ('sf_sin', 'sf_cos', 'kf_sin', 'kf_cos', 'ef_rem_pio2', 'kf_rem_pio2', 'sf_scalbn', 'sf_floor', 'sf_fabs',
          'ef_acos', 'ef_sqrt')


def preparar_evalhost():
    if os.name != 'nt':
        return
    from motion import evalhost
    dest = os.path.join(HERE, 'tools', 'motion_host_win')
    dll = os.path.join(dest, 'motion_host.dll')
    if not os.path.isfile(dll):
        host = evalhost.HOST_DIR
        root = os.path.normpath(os.path.join(host, '..', '..', '..'))
        gxx = 'g++'
        for c in (r'C:\msys64\mingw64\bin\g++.exe', r'C:\msys64\ucrt64\bin\g++.exe'):
            if os.path.isfile(c):
                gxx = c
        env = dict(os.environ, PATH=os.path.dirname(gxx) + os.pathsep + os.environ.get('PATH', ''))
        os.makedirs(os.path.join(dest, 'inc', 'sys'), exist_ok=True)
        with open(os.path.join(dest, 'inc', 'sys', 'mman.h'), 'w') as f:
            f.write(MMAN_H)
        fl = ['-O2', '-std=gnu++14', '-fno-strict-aliasing', '-fno-fast-math', '-ffunction-sections',
              '-fdata-sections', '-ffp-contract=off', '-w']
        defs = ['-Dsinf=re4_sinf', '-Dcosf=re4_cosf', '-Dacosf=re4_acosf', '-Dfabsf=re4_fabsf', '-Dfloorf=re4_floorf',
                '-Dscalbnf=re4_scalbnf']
        objs = []
        for f in FDLIBM:
            o = os.path.join(dest, f + '.o')
            subprocess.check_call([gxx] + fl + ['-I', os.path.join(root, 'include')] + defs +
                                  ['-c', os.path.join(root, 'src', 'lib', f + '.cpp'), '-o', o], env=env)
            objs.append(o)
        srcs = [os.path.join(host, 'build', s) for s in ('motion_prep.cpp', 'ik_prep.cpp', 'game_extract.cpp',
                                                         'sdk_extract.cpp')] + [os.path.join(host, 'motion_host.cpp')]
        subprocess.check_call([gxx] + fl + ['-I', os.path.join(dest, 'inc'), '-I', os.path.join(host, 'stub'),
                                            '-o', dll] + srcs + objs +
                              ['-shared', '-Wl,--gc-sections', '-static-libgcc', '-static-libstdc++', '-static'],
                              env=env)
    evalhost.build = lambda variant='plain': dll


# ---------------------------------------------------------------------------------------------------
#  archivos
# ---------------------------------------------------------------------------------------------------
ARC = L.Archivos(L.DEFAULT_DISC)
DAS = archive.Archive(os.path.join(EXT, 'St1', 'r100.das'))
ENT = list(DAS.entries())
ETM = dict(archive.parse_etm(next(e for e in ENT if e.tag == 'ETM').data))


def tag(t):
    return next(e for e in ENT if e.tag == t).data


def entrada(a, arc_no, tipo):
    """PL_ARC n del modulo = entrada n - 4 del .drs."""
    e = a.entry(arc_no - 4)
    if e.tag != tipo:
        sys.exit('%s: ARC %#x es %s, se esperaba %s' % (a.name, arc_no, e.tag, tipo))
    return e.data


# ---------------------------------------------------------------------------------------------------
#  glb animado (esqueleto + mallas skinneadas + clips evaluados con el codigo del juego)
# ---------------------------------------------------------------------------------------------------
def evaluar_clip(skel, a, stem, nombre, mot, seq, loop, fuente, nota=None):
    m = fcv.parse(entrada(a, mot, 'FCV'))
    sq = fcv.parse_seq(entrada(a, seq, 'SEQ')) if seq is not None else None
    poses, raiz, fr, pr = GJ.evaluar(skel, m, sq, loop)
    pf, af = pr[-1]
    info = dict(clip=nombre, motion='%s.drs:%d (ARC %#x)' % (stem, mot - 4, mot),
                seq='%s.drs:%d (ARC %#x)' % (stem, seq - 4, seq) if seq is not None else None,
                loop=loop, frames=len(poses), duracion_s=rn((len(poses) - 1) / FPS, 3),
                frames_motion=m.max_frame + 1, fuente=fuente,
                raiz_final_m=rn(np.array(pf) * MM), giro_final_rad=rn(af[1]))
    if nota:
        info['nota'] = nota
    if sq is not None:
        se = [dict(frame=i, se='%#x' % (k.se - 1)) for i, k in enumerate(sq.keys[:len(poses)]) if k.se]
        free = {}
        for i, k in enumerate(sq.keys[:len(poses)]):
            for b_ in range(8):
                if k.free & (1 << b_):
                    free.setdefault('%#x' % (1 << b_), []).append(i)
        if se:
            wav = {k: exportar_se('%s_seq' % stem, 'em/%s.drs' % stem, 8, int(k, 16), 'SEQ de los clips')['wav']
                   for k in sorted({c['se'] for c in se})}
            info['sonidos_seq'] = dict(regla='game/em.cpp: SndCall(8, Se - 1) en la parte 0 (banco ENEMY del modulo)',
                                       claves=se, wav=wav)
        if free:
            info['bits_free_seq'] = {k: GJ.rangos(v) for k, v in free.items()}
    return dict(nombre=nombre, poses=poses, raiz=raiz, info=info)


def glb_animado(salida, raiz_nombre, skel, fuentes, clips, extras=None):
    n = skel.n_parts
    rest = L.rest_world(skel)
    b = gltf.Builder()
    nodes = [{'name': raiz_nombre, 'children': []}]
    for p in skel.parts:
        nodes.append({'name': 'hueso_%03d' % p.no, 'translation': [c * MM for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0] * MM, -r[1] * MM, -r[2] * MM, 1] for r in rest]
    skin = {'name': raiz_nombre + '_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}

    def chk(j):
        if j >= n:
            raise ValueError('peso a la parte %d, el esqueleto tiene %d' % (j, n))
    carpeta = os.path.dirname(salida)
    images, tex_out, materials, meshes, mesh_nodes, stats = {}, set(), [], [], [], []
    for src, visible in fuentes:
        mesh, nv, nt, _ = gltf.build_mesh(b, src, MM, carpeta, images, tex_out, materials, chk)
        mesh_nodes.append(len(nodes))
        nd = {'name': src.label, 'mesh': len(meshes), 'skin': 0}
        if not visible:
            nd['extras'] = {'visible_inicial': False}
        nodes.append(nd)
        meshes.append(mesh)
        stats.append(dict(malla=src.label, vertices=nv, triangulos=nt, visible_inicial=visible))
    anims = [L.clip_esqueleto(b, nodes, n, c['poses'], c['nombre'], FPS, MM, c['raiz'], skel.roots()) for c in clips]
    for a_, c in zip(anims, clips):
        a_['extras'] = dict(a_['extras'], loop=c['info']['loop'])
    doc = {'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_objetos_r100.py'}, 'scene': 0,
           'scenes': [{'name': raiz_nombre, 'nodes': [0] + mesh_nodes}], 'nodes': nodes, 'skins': [skin],
           'meshes': meshes, 'animations': anims,
           'images': [{'uri': uri} for _, uri in materials],
           'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 10497, 'wrapT': 10497}],
           'textures': [{'source': i, 'sampler': 0} for i in range(len(materials))],
           'materials': [mat for mat, _ in materials],
           'accessors': b.accessors, 'bufferViews': b.buffer_views}
    if not anims:
        del doc['animations']
    if extras:
        doc['extras'] = extras
    gltf.write(doc, bytes(b.blob), salida)
    return dict(glb=os.path.basename(salida), partes=n, mallas=stats, clips=[c['info'] for c in clips])


def caja_mm(m):
    P = np.array([m.position(v[0]) for p in m.parts for t in p.triangles() for v in t])
    return [rn(P.min(0) * MM), rn(P.max(0) * MM)]


# ---------------------------------------------------------------------------------------------------
#  sonidos
# ---------------------------------------------------------------------------------------------------
BANCOS = {}


def banco(ruta, blk):
    k = (ruta, blk)
    if k not in BANCOS:
        BANCOS[k] = S.load_bank(ruta, blk)
    return BANCOS[k]


def exportar_se(nombre, ruta, blk, no, cuando):
    """un SE -> sonidos/<nombre>_seNNN.wav (todos los miembros si el SIT es de un grupo al azar)."""
    bk = banco(ruta, blk)
    s = bk.sit(no)
    grupo = bk.rnd_group(s['rnd_no']) if s['rnd_no'] else []
    miembros = grupo or [no]
    wavs = []
    for k in miembros:
        if k >= bk.num or bk.sit(k)['flag'] & 0x8000:
            continue
        fn = 'sonidos/%s_se%03d.wav' % (nombre, k)
        S.write_wav_stereo(os.path.join(OUT, fn), S.render_se(bk, k), 32000)
        wavs.append(fn)
    return dict(llamada='SndCall(%d, %#x)' % (blk, no), banco='%s bloque %d (%s)' % (ruta, blk, S.BLK_NAMES.get(blk)),
                sit=no, al_azar_entre=grupo or None, volumen=s['vol'], wav=wavs, cuando=cuando,
                nombre_original='no determinable (los bancos no guardan nombres, solo numeros de SIT)')


# ---------------------------------------------------------------------------------------------------
#  efectos (est de un EFF)
# ---------------------------------------------------------------------------------------------------
def ests(eff, nos):
    out = {}
    for k in nos:
        s = eff.est.get(k)
        if not s:
            continue
        recs = []
        for r in s['records']:
            q = dict(Id='%#x' % r['Id'], kind=r['Kind'], tex_o_efm='%#x' % r['Tex_id'], vida=r['Life_max'],
                     tam=[rn(r['Size_base_x'], 1), rn(r['Size_base_y'], 1)], vel=rn(r['Speed'], 1),
                     color=r['Col_start'], blend=r['Blend_type'])
            if r['Id'] == 0xFE:
                q['que'] = 'obj05: modelo EFM %#x que estalla en piezas (EfmSetObj05)' % r['Tex_id']
                q['obj05'], _ = V.trozos_de_registro(r, [])
            elif r['Id'] == 0xFF:
                q['que'] = 'obj04: modelo EFM %#x fijo' % r['Tex_id']
            recs.append(q)
        out['%d' % k] = recs
    return out


# ---------------------------------------------------------------------------------------------------
#  camaras de corte (CamCtrl.CutCall)
# ---------------------------------------------------------------------------------------------------
TIPOS_CAM = {0: 'Fix', 1: 'Pan', 2: 'Track', 3: 'RailPan', 4: 'RailBehind', 5: 'Free',
             6: 'Motion: CameraMotion de las claves del corte (HermiteExport, interpola ojo/objetivo/fovy/roll en '
                'frames_claves)', 7: 'UpCut',
             8: 'hombro (QuasiFPS)'}


def cortes_camara(cam):
    narea = cam[5]
    out = {}
    for i in range(narea):
        ai, ci = struct.unpack_from('>II', cam, 0x10 + 16 * i + 8)
        _, cno, ctyp, cfl = struct.unpack_from('>BbbB', cam, ci)
        if cno in out:
            continue
        cnum, cpos, cat, croll, cfov = struct.unpack_from('>iIIII', cam, ci + 0x20)
        cfr, = struct.unpack_from('>I', cam, ci + 0x10)
        c = dict(corte=cno, tipo=ctyp, tipo_nombre=TIPOS_CAM.get(ctyp, '?'), claves=cnum)
        if 0 < cnum < 64 and 0 < cfr and cfr + 2 * cnum <= len(cam):
            c['frames_claves'] = [struct.unpack_from('>H', cam, cfr + 2 * k)[0] for k in range(cnum)]
        if 0 < cnum < 64 and cpos and cat:
            c['ojo_m'] = [m3(struct.unpack_from('>3f', cam, cpos + 12 * k)) for k in range(cnum)]
            c['objetivo_m'] = [m3(struct.unpack_from('>3f', cam, cat + 12 * k)) for k in range(cnum)]
            if cfov:
                c['fovy_grados'] = [rn(struct.unpack_from('>f', cam, cfov + 4 * k)[0], 2) for k in range(cnum)]
            if croll:
                c['roll'] = [rn(struct.unpack_from('>f', cam, croll + 4 * k)[0]) for k in range(cnum)]
        out[cno] = c
    return out


# ---------------------------------------------------------------------------------------------------
#  1. cepos
# ---------------------------------------------------------------------------------------------------
def cepos(esl, sonidos):
    a = ARC('em2a')
    skel = modelbin.parse(entrada(a, 4, 'BIN'))
    skel.check_tree()
    m = meshbin.parse(entrada(a, 4, 'BIN'))
    tpl = gxtex.parse_tpl(entrada(a, 5, 'TPL'))
    C = [
        ('abierto', 0xA, None, True, 'em2a_R1_Trap1Set: MotionSetCore(ARC 0xA, attr 5) armado, esperando'),
        ('morder', 0xB, 0xD, False, 'em2a_R1_Trap1Bite: se cierra sobre la pierna de Leon (ARC 0xB + SEQ 0xD)'),
        ('cerrar_vacio_disparo', 0xC, 0xE, False, 'em2a_R1_Trap1Break r_no_3 0: le dispararon / se cerro vacio '
                                                  '(ARC 0xC + SEQ 0xE, SE 8/0 + efecto EFF_EM2A est 2)'),
        ('cerrado_ya', 0xC, 0xF, False, 'em2a_R1_Trap1Break r_no_3 1: set 2 (ya disparado al crear; SEQ 0xF)'),
        ('perro_r100', 0x13, 0x14, False, 'em2a_R1_Trap1R100: con el perro atrapado re-arranca la motion CADA frame '
                                          '(queda en el frame 0 de este clip); al liberarlo (flag bit0) la reproduce '
                                          'entera una vez (381 frames, mas larga que "liberado" del perro: 244)'),
        ('reabrir', 0x15, None, False, 'em2a_R1_Trap1Reset: el cepo del perro baleado se reabre y se rearma (hp 1)'),
        ('ashley_morder', 0x16, None, True, 'em2a_R1_Trap1BiteSub caso 0 (Ashley; no ocurre en r100)'),
        ('ashley_sostener', 0x17, None, True, 'em2a_R1_Trap1BiteSub caso 2 (Ashley; no ocurre en r100)'),
        ('ashley_soltar', 0x18, 0x19, False, 'em2a_R1_Trap1BiteSub caso 4 (Ashley; no ocurre en r100)'),
    ]
    clips = [evaluar_clip(skel, a, 'em2a', *c) for c in C]
    info = glb_animado(os.path.join(OUT, 'cepo.glb'), 'cepo', skel,
                       [(gltf.MeshSource(m, tpl, 'Cepo', 'em2a_cepo'), True)], clips,
                       {'modelo': 'em2a ARC 4 (bin) / ARC 5 (tpl): em2a_R0_Init type 0'})
    info['caja_m'] = caja_mm(m)

    sk2 = modelbin.parse(entrada(a, 8, 'BIN'))
    m2 = meshbin.parse(entrada(a, 8, 'BIN'))
    t2 = gxtex.parse_tpl(entrada(a, 9, 'TPL'))
    bomba = glb_animado(os.path.join(OUT, 'bomba_alambre.glb'), 'bomba_alambre', sk2,
                        [(gltf.MeshSource(m2, t2, 'Bomba_alambre', 'em2a_bomba'), True)], [],
                        {'modelo': 'em2a ARC 8 / 9 (type 2); partes 1 y 2 (los postes) se corren en z * hp/1000*0.5'})
    bomba['partes_reposo_mm'] = [dict(parte=p.no, padre=p.parent, pos=rn(p.pos, 2)) for p in sk2.parts]

    lista = []
    for no, e in sorted(esl.items()):
        if e['id'] != 0x2A or e['room'] != ROOM:
            continue
        d = dict(esl='0x%02X' % no, type=e['type'], set=e['set'], pos_m=e['pos_m'], yaw_rad=e['rot_rad'][1],
                 hp=e['hp'], be_flag='%#x' % e['be_flag'])
        if e['type'] == 0:
            d['que'] = {0: 'cepo armado (Trap1Set)', 1: 'cepo del PERRO (Trap1R100): em21TrapSearch lo mueve a la pata '
                                                        'del perro', 2: 'cepo ya cerrado'}[e['set']]
        else:
            d['que'] = 'trampa de alambre con bomba type %d: largo del alambre = hp = %.2f m' % (e['type'], e['hp'] * MM)
        lista.append(d)

    snd = dict(
        cierre=exportar_se('cepo_cierre', 'em/em2a.drs', 8, 0,
                           'Trap1Bite / Trap1BiteSub / Trap1Break (vacio) / Trap1Reset: el chasquido del cepo'),
        balazo=exportar_se('cepo_balazo', 'em/em2a.drs', 8, 2, 'em2aDmCkTrap1: le pegan con un arma'),
        leon_grito=exportar_se('leon_cepo', 'em/pl00.drs', 1, 0x39, 'Trap1Bite: Leon atrapado (SndCall(1, 0x39) en Leon)'),
        explosion_bomba=exportar_se('bomba_explosion', 'em/pl00.drs', 1, 0x14,
                                    'em2aTrap2Bomb: SndCall(1, 0x14); el bloque 1 del jugador'),
    )
    sonidos.update({'cepo_' + k: v for k, v in snd.items()})
    eff = re4_eff.Eff(entrada(a, 0x12, 'EFF'), 'em2a ARC 0x12')
    return dict(
        colocaciones=lista,
        aparecen='r100_trap_set (EmSetFromList2 9, 0xA, 0xB, 0xC, 0xD, 0xE, 0x1D, 0x7A): SOLO despues de la muerte de '
                 'los policias (Rsf 10): en R100Init si ya esta Rsf 10, o al terminar el evento s20 '
                 '(r100_Sce_zombi_dead). Antes no hay cepos, ni perro, ni bombas de alambre.',
        modelo=info, bomba_alambre_modelo=bomba,
        disparo_jugador=dict(
            funcion='em2aTrap1BiteCk (cada frame en Trap1Set)',
            radio_xz_m=0.3, regla='(dx^2 + dz^2) <= 90000 mm^2 (0.30 m) y |dy| <= 0.5 m, Leon vivo y pl_life > 0; el '
                                  'cepo copia la altura de Leon (em->pos.y = pPL->pos.y)',
            efectos=['Trap1Bite: motion morder, SndCall(8, 0) en el cepo + SndCall(1, 0x39) en Leon, VibSetData(7)',
                     'EmCatchPLSet(em, 0, 0, 34.69, 0, 250.42, plem2a_Trap1Bite): el juego toma a Leon como "agarrado" '
                     '(los 3 floats parecen el offset local de Leon respecto del cepo en mm: x 34.69, z 250.42; no '
                     'verificado)',
                     'camara: em2aTrap1CamMove durante 120 frames: ojo = cepo + RotY(yaw de Leon) * (-1200, 1300, '
                     '-1000) mm, objetivo = cepo + RotY * (0, 500, -300) mm, cada uno se acerca 10%/frame '
                     '(PosToPos 0.1), fovy 55',
                     '10 frames de EmCatchMotionMove (sincroniza cepo y Leon) y luego el cepo termina su motion; '
                     'queda cerrado (hp 0) y Em_list.set = 2 (no reaparece armado)'],
            leon=dict(funcion='plem2a_Trap1Bite', clip='leon_objetos.glb "cepo_atrapado" (em2a ARC 0x10 + SEQ 0x11, '
                                                       'attr 1)',
                      dano=300, cara='PlSetFace(1)', efecto='EstSet(Leon, EFF_EM2A est 1) (sangre)',
                      termina='al terminar la motion (EmCatchMotionMove 0.3 / 0.2): EndPlDamage; NO hay que apretar '
                              'botones (no hay forcejeo en el codigo: la motion se reproduce una vez)'),
            si_leon_muere='queda en el ultimo frame de "morder"'),
        disparo_companera='em2aTrap1BiteSubCk: Ashley a < 0.5 m (250000 mm^2) -> Trap1BiteSub (300 de dano, 3 por '
                          'forcejeo, Leon la libera con ACT_RESCUE: plemResuceAshley, em2a ARC 0x1D). No aplica a r100 '
                          '(no hay Ashley)',
        enemigos='NO: el cepo solo prueba a Leon (pPL) y a la companera (pSUB); los ganados no caen (si caen en la '
                 'bomba de alambre: em2aTrap2HitCkEM ids 0x10..0x20)',
        disparar=dict(
            funcion='em2aDmCkTrap1',
            ignora_armas=['0x14', '0x16', '0x17', '0x2A', '0xE', '0x13', '0x29', '0x2D'],
            regla='cualquier otro golpe registrado (balas, cuchillo 0x10) lo cierra: hp 0, SndCall(8, 2), EFF_EM2A est '
                  '9 en el punto del golpe (EmDmBloodSet2 0x22, 9); cepo normal -> Trap1Break (cierra vacio, SE 8/0, '
                  'EFF_EM2A est 2, +puntos LVADD_CRITICALHIT, queda desactivado); cepo del perro -> Trap1Reset',
            caja_de_golpe_mm=dict(centro=[0, 0, 0], medio_ancho_x=500, alto=200, medio_largo_z=500,
                                  fuente='em2aYarareInit YarareInitCube')),
        colision='atari.init(0, 0, 0, 500, 400, 400, 1500, 3, 0x2000, 10) + AtariOff(0xFCFF): sin colision fisica',
        bomba_alambre=dict(
            regla='em2aTrap2HitCkPL/EM: Leon o un ganado vivo (id 0x10..0x20) dentro de la caja del alambre (local: '
                  'z 0..largo+0.1 m, |x| <= 0.4 m, y -2.0..+0.25 m) o un disparo (no mano / flash / mina) -> '
                  'Trap2Bomb: 3 frames despues explota',
            explosion='SndCall(1, 0x14); EFF_EM2A est 4 (type 2) / 0 (type 1) / 6 (bajo el agua); dos golpes '
                      'PlWepHitCheck2 tipo 0x13 radio 3 m a 2 m de cada poste hacia el centro; QuakeExec por '
                      'distancia a la camara (10/8/6/4 hasta 5/10/15/20 m)',
            efecto_armada='EstSet(EFF_EM2A est 5) (type 2) / est 3 (type 1) mientras esta armada'),
        efectos_em2a=dict(fuente='em2a.drs ARC 0x12 (EFF_EM2A = 34)', est=ests(eff, (1, 2, 3, 4, 5, 9))),
    )


# ---------------------------------------------------------------------------------------------------
#  2. el perro del cepo
# ---------------------------------------------------------------------------------------------------
def perro(esl, sonidos):
    a = ARC('em21')
    skel = modelbin.parse(entrada(a, 4, 'BIN'))
    skel.check_tree()
    m = meshbin.parse(entrada(a, 4, 'BIN'))
    tpl = gxtex.parse_tpl(entrada(a, 6, 'TPL'))
    C = [
        ('atrapado', 0x18, None, True, 'em21_R1_R100TrapWait: lloriquea en el cepo (ARC 0x18, attr 5 loop)'),
        ('liberado', 0x19, 0x1C, False, 'em21_R1_R100TrapCancel: sincronizado con Leon soltandolo (ARC 0x19 + SEQ '
                                        '0x1C, attr 5)'),
        ('correr', 0x1A, 0x1D, True, 'em21_R1_R100Escape: corre a la salida (ARC 0x1A + SEQ 0x1D) tras ser liberado'),
        ('correr_asustado', 9, 0x12, True, 'em21_R1_R100Escape r_no_3 1 / Escape: se solto por un golpe (ARC 9 + SEQ '
                                           '0x12; Escape elige 0x12..0x15 al azar)'),
        ('saltar_valla', 0x1E, None, False, 'em21_R1_R100Escape caso 2: salta (ARC 0x1E, attr 1; SE 8/7 en el frame 3)'),
        ('dormido', 0xB, None, True, 'em21_R0_Init: pose de arranque (ARC 0xB) antes de la rutina'),
    ]
    clips = [evaluar_clip(skel, a, 'em21', *c) for c in C]
    info = glb_animado(os.path.join(OUT, 'perro.glb'), 'perro', skel,
                       [(gltf.MeshSource(m, tpl, 'Perro', 'em21_perro'), True)], clips,
                       {'modelo': 'em21 ARC 4 (bin) + ARC 6 (tpl type 1); type 0 usaria ARC 5'})
    info['caja_m'] = caja_mm(m)
    e = esl[9]
    t = esl[0xC]
    yaw = e['rot_rad'][1]
    c, s = math.cos(yaw), math.sin(yaw)

    def local(v):
        return [rn(e['pos_m'][0] + (c * v[0] + s * v[2]) * MM), rn(e['pos_m'][1] + v[1] * MM),
                rn(e['pos_m'][2] + (-s * v[0] + c * v[2]) * MM)]
    snd = dict(
        lloriqueo=exportar_se('perro_lloriqueo', 'em/em21.drs', 8, 0xC, 'R100TrapWait: cada 75..104 frames'),
        ladrido_huida=exportar_se('perro_huida', 'em/em21.drs', 8, 0xB, 'R100Escape (suelto por golpe) / Escape'),
        salto=exportar_se('perro_salto', 'em/em21.drs', 8, 7, 'R100Escape: frame 3 del salto de la valla'),
    )
    sonidos.update({'perro_' + k: v for k, v in snd.items()})
    return dict(
        enemigo=dict(esl='0x09', id='0x21 (em21, perro)', archivo='em/em21.drs (modulo em21.rel)', type=e['type'],
                     set=e['set'], set_nombre='R100 Trap (t_emlist em21_dog_set[1])', pos_m=e['pos_m'], yaw_rad=yaw,
                     hp_juego=1000, nota='no se puede fijar la mira (EM_STATUS_LOCKOFF); nunca muere'),
        cepo=dict(esl='0x0C', type=0, set=1, pos_archivo_m=t['pos_m'],
                  pos_juego_m=local((256.48, 0.0, -304.75)), yaw_rad=yaw,
                  regla='em21TrapSearch: el cepo type 0 set 1 se mueve a dog.mat * (256.48, 0, -304.75) mm (la pata '
                        'trasera) con el yaw del perro'),
        modelo=info,
        interaccion=dict(
            cartel='ActBtn ACT_RESCUE (texto: core 0x2B, ver out/combate/acciones.json carteles) prioridad 5',
            condicion='em->l_pl <= 9000000 mm^2 (Leon a <= 3.0 m del perro en XZ), mientras R100TrapWait',
            al_apretar='em21TrapCancelAction: SetPlDamage(plemTrapCancel) en Leon, el perro -> R100TrapCancel',
            leon=dict(funcion='plemTrapCancel', clip='leon_objetos.glb "soltar_perro" (em21 ARC 0x1B, attr 1)',
                      pos_m=local((431.86002, 0.0, -989.88)), yaw_rad=yaw,
                      regla='Leon se teletransporta a dog.mat * (431.86, 0, -989.88) mm con el yaw del perro; al '
                            'terminar EndPlDamage y 30 frames sin dano'),
            camara=dict(funcion='plem21TrapCamMove (cada frame de plemTrapCancel)',
                        ojo='Leon.mat * (2500, 0, 0) mm + 2000 mm en Y', objetivo='Leon.mat * (0, 1000, 1000) mm',
                        fovy=55, suavizado='ninguno (PosToPos 1.0)'),
            perro='R100TrapCancel: motion "liberado", pTrap->flag |= 1 (el cepo queda cerrado y usado: '
                  'Trap1R100 caso 2, Em_list.set = 0), hp 0, sin colision de golpe; SndStrReq(1, 0xE, 0x80000003) '
                  '(cue de musica, cual stream: no determinado); ScfFlagOn(SCF_R100_DOG_RUN)'),
        despues=dict(
            huida='R100Escape: EmSetDie, corre ("correr") girando hacia (-24.95, -0.40, -26.74) m a pi/40 rad/frame; '
                  'a < 6 m del punto salta ("saltar_valla"), vuelve a correr hasta terminar la motion y se desvanece '
                  '(invisible_factor -0.1 por frame) y desaparece',
            recompensa='SCF_R100_DOG_RUN: en r119 (El Gigante) el perro aparece y ayuda (em21 set 2 VsElgigante, '
                       'st1/r119.cpp); en r100 no da items'),
        si_le_disparan='em21DmCk: cualquier golpe o fuego mientras esta en el cepo -> el cepo pasa a Trap1Reset (se '
                       'REABRE y queda armado de nuevo en ese lugar) y el perro huye asustado (R100Escape r_no_3 1, '
                       '"correr_asustado", SE 8/0xB) SIN marcar SCF_R100_DOG_RUN; si se le dispara al cepo: '
                       'em2aDmCkTrap1 con r_no_1 5 -> Trap1Reset, el perro lo ve en TrapWait y huye igual',
        colision='atari.init(0, -500, 0, 450, 400, 400, 1000, 3, 0x2000, 10), prioridad PRI_LV1 en set 1; cajas de '
                 'golpe em21YarareInit',
    )


# ---------------------------------------------------------------------------------------------------
#  3. cajas de madera
# ---------------------------------------------------------------------------------------------------
def cajas(items, sonidos):
    core = re4_eff.load_effs(os.path.join(EXT, 'etc', 'core.das'), 1)[0]
    salidas = {}
    for et, nombre, tipo in (('01', 'caja_chica', 0), ('02', 'caja_mediana', 1)):
        eff = re4_eff.Eff(ETM['et%s.eff' % et], 'et%s.eff' % et)
        efm = V.partes_efm(eff, ids=(0x04,))[0x04]
        m = meshbin.parse(ETM['et%s00.bin' % et])
        A.glb_estatico(os.path.join(OUT, nombre + '.glb'), [(nombre, m, efm[1], False)], nombre)
        A.glb_estatico(os.path.join(OUT, nombre + '_restos.glb'), [(nombre + '_restos', efm[0], efm[1], False)],
                       nombre + '_restos')
        salidas[nombre] = dict(
            etc_id=int(et), clase='SetBox type %d (cEmBox, id 0x43)' % tipo,
            modelo=dict(glb=nombre + '.glb', bin='r100.das ETM et%s00.bin' % et, triangulos=m.n_triangles(),
                        textura='TPL del EFM 0x04 de et%s.eff (EspGetEfmTplAddr(0x04))' % et, caja_m=caja_mm(m)),
            restos=dict(glb=nombre + '_restos.glb', fuente='EFM 0x04 de et%s.eff (est 4: lo que queda en el piso)' % et,
                        triangulos=efm[0].n_triangles(), caja_m=caja_mm(efm[0])),
            efectos=dict(fuente='r100.das ETM et%s.eff (EFF_ET%s, owner %#x)' % (et, et, 0x55 + int(et) - 1),
                         est=ests(eff, (0, 1, 2, 3, 4))),
            tam_mm={0: [200, 350, 550], 1: [450, 600, 1000]}[tipo])
    trozos = V.partes_efm(core, ids=(0x01, 0x0E))
    modelos = []
    for idn, (m, tpl, partes) in sorted(trozos.items()):
        for p in partes:
            if p['vertices']:
                modelos.append(('efm%02X_parte%d' % (idn, p['parte']), V._Pieza(m, p['parte'], p['pivote_mm']),
                                tpl, False))
    A.glb_estatico(os.path.join(OUT, 'caja_trozos.glb'), modelos, 'caja_trozos')
    re4_eff.export_pngs(core, os.path.join(OUT, 'fx_core'), 'core', ids=[0x01, 0x08, 0x09, 0x0A, 0x0E, 0x1D, 0x1E, 0x5F])

    ets = R.ets(tag('ETS'))
    drops = {}
    for c in items['colocaciones']:
        if c.get('linkType') == 2:
            drops[c['linkNo']] = dict(id=c['id'], nombre=c['nombre'], num=c['num'], pos_item_m=c['pos_m'])
    lista = []
    for e in ets:
        if e['id'] not in (1, 2):
            continue
        lista.append(dict(ets_no=e['no'], etc_flag=e['no'] & 0xFF, modelo='caja_chica' if e['id'] == 1 else 'caja_mediana',
                          pos_m=m3(e['pos']), yaw_rad=rn(e['rot'][1]), item=drops.get(e['no'])))
    sonidos['caja_rotura'] = exportar_se('caja_rotura', 'em/pl00.drs', 1, 0x1A,
                                         'emBoxSetBreak (cajas type 0/1/2): SndCall(1, 0x1A) en la caja')
    return dict(
        colocaciones=lista,
        modelos=salidas,
        trozos=dict(glb='caja_trozos.glb', fuente='core.das EFF_CORE EFM 0x01 (2 partes) y 0x0E (4 partes); un nodo '
                                                 'por parte con origen en el pivote (como vidrio_trozos_piezas.glb)',
                    partes={'%#x' % k: v[2] for k, v in trozos.items()},
                    texturas_particulas='fx_core/core_*.png (texturas de EFF_CORE que usan los est)'),
        romper=dict(
            hp=1000, funcion='emBoxDmCk + emBoxSetBreak',
            armas='ignora 0x14 (mano/patada), 0x16, 0x17, 0x2A (flash), 0xE (mina); el resto: 1000 de dano (pistola, '
                  'cuchillo 0x10, ...) o 9999 (rifles, magnum, explosivos; escopeta 9999 a < 6 m): UN golpe la rompe',
            fuego='un volumen de dano de fuego (DmgMgr tipos 1/4/5/7) la rompe',
            estilo='est 0 (disparo / cuchillo), 1 (escopeta de cerca, m_Dist < 6 m), 2 (armas pesadas); + est 4 '
                   '(restos en el piso, porque las cajas no tienen modelo roto propio)',
            al_romper='hp 0, oculta el modelo, sin colision (throughOn), SndCall(1, 0x1A), suelta el item del ITA '
                      '(linkType 2 = ETS no; SceAtCreateItemAt) y marca el bit 0 del flag etc del cuarto: al volver a '
                      'entrar aparece rota (setEff pone el est 4 de restos directo)',
            golpe_sin_romper='est 3 (astillas) en el punto del golpe (nunca pasa con 1000 hp y >= 1000 de dano)',
            patear='NO se pueden patear: en r100 el boton de accion (ACT_CHECK, Leon mirando a la caja a < 45 grados '
                   'y dentro de la caja + 1 m) muestra core 3 "It\'s a wooden box. / Looks like it can be broken."',
            cajas_de_golpe='YarareInitCube: medio x = size.x/2 + 50, alto size.y, medio z = size.z/2 + 50 (+ un cubo '
                           'interior)'),
    )


# ---------------------------------------------------------------------------------------------------
#  4. cuervos
# ---------------------------------------------------------------------------------------------------
def cuervos(esl, items, sonidos):
    a = ARC('em23')
    skel = modelbin.parse(entrada(a, 5, 'BIN'))
    skel.check_tree()
    tpl = gxtex.parse_tpl(entrada(a, 8, 'TPL'))
    cuerpo = meshbin.parse(entrada(a, 5, 'BIN'))
    ala7 = meshbin.parse(entrada(a, 7, 'BIN'))
    ala6 = meshbin.parse(entrada(a, 6, 'BIN'))
    C = [
        ('quieto_a', 9, None, True, 'em23WaitMotion (Rnd & 3 == 0)'),
        ('quieto_b', 0xA, None, True, 'em23WaitMotion (1)'),
        ('quieto_picotear_c', 0xB, 0x1C, True, 'em23WaitMotion (2)'),
        ('quieto_picotear_d', 0xC, 0x1D, True, 'em23WaitMotion (3)'),
    ] + [('despegue_s%02X' % s_, 0xE, s_, False, 'em23TakeoffMotion: emset_no %% 5 == %d' % k)
         for k, s_ in enumerate((0x24, 0x25, 0x26, 0x27, 0x28))] + [
        ('despegue_rapido', 0xF, None, False, 'em23_R1_TakeoffDash'),
        ('planear', 0xD, 0x23, True, 'em23_R1_Turn r_no_3 0 (los r_no_3 1..5 usan las SEQ 0x22..0x1E: mismo vuelo con '
                                     'otro ritmo)'),
        ('aletear', 0x17, None, True, 'em23_R1_Turn r_no_3 6 (al azar)'),
        ('aterrizar', 0x10, 0x29, False, 'em23_R1_Landing (solo con cadaver: no en r100)'),
        ('saltito_a', 0x1A, 0x2B, False, 'em23_R1_ToCorpse (no en r100)'),
        ('saltito_b', 0x1B, 0x2C, False, 'em23_R1_ToCorpse (no en r100)'),
        ('picotear_cadaver', 0x18, None, False, 'em23_R1_Eat (no en r100)'),
        ('caer_herido', 0x16, 0x2A, True, 'em23_R1_Dm_Air: cae girando'),
        ('recuperarse', 0x15, None, False, 'em23_R1_Dm_Air caso 2 (si sobrevive; con hp 10 nunca)'),
        ('morir', 0x14, None, False, 'em23_R1_Die_Normal'),
    ]
    clips = [evaluar_clip(skel, a, 'em23', *c) for c in C]
    info = glb_animado(os.path.join(OUT, 'cuervo.glb'), 'cuervo', skel,
                       [(gltf.MeshSource(cuerpo, tpl, 'Cuervo', 'em23_cuervo'), True),
                        (gltf.MeshSource(ala7, tpl, 'Cuervo_alas_piso', 'em23_cuervo'), True),
                        (gltf.MeshSource(ala6, tpl, 'Cuervo_alas_vuelo', 'em23_cuervo'), False)], clips,
                       {'modelo': 'em23 ARC 5 (cuerpo) + ARC 7 / ARC 6 (alas) con ARC 8 (tpl)'})
    info['alas'] = dict(
        regla='em23SetWing(on): on 1 -> ARC 7 (Cuervo_alas_piso), on 0 -> ARC 6 (Cuervo_alas_vuelo). Wait / Init '
              'ponen 1; Takeoff / TakeoffDash ponen 0 cuando la SEQ trae Free bit0; Dm_Air y Die ponen 0',
        caja_ARC7_m=caja_mm(ala7), caja_ARC6_m=caja_mm(ala6))
    info['caja_cuerpo_m'] = caja_mm(cuerpo)
    drops = {}
    for c in items['colocaciones']:
        if c.get('linkType') == 1:
            drops[c['linkNo']] = dict(id=c['id'], nombre=c['nombre'], num=c['num'])
    lista = []
    for no in (0x0F, 0x10, 0x11, 0x20, 0x21):
        e = esl[no]
        lista.append(dict(esl='0x%02X' % no, pos_m=e['pos_m'], yaw_rad=e['rot_rad'][1], hp=e['hp'], set=e['set'],
                          be_flag='%#x' % e['be_flag'], altura_vuelo_sobre_leon_m=((no % 5) * 1000 + 8000) * MM,
                          despegue_seq='0x%02X' % (0x24 + no % 5), item_ita=drops.get(no),
                          item_al_azar='RandomItemCk 0x23 (dinero; ver items_r100.json drops_aleatorios.cuervo_0x23)'))
    snd = dict(
        aleteo_despegue=exportar_se('cuervo_aleteo', 'em/em23.drs', 8, 0xA,
                                    'Takeoff: Ctrl11SetSe(10, 0xA, slot 0xB) al abrir las alas (SEQ Free bit0)'),
        aleteo_vuelo=exportar_se('cuervo_aleteo_vuelo', 'em/em23.drs', 8, 0xB,
                                 'cEm23::move: SEQ Free bit 0x80 y el cuervo a < 3 m sobre Leon'),
        golpe=exportar_se('cuervo_golpe', 'em/em23.drs', 8, 0xF, 'em23DmCk: al recibir el golpe (graznido)'),
        piso=exportar_se('cuervo_piso', 'em/em23.drs', 8, 9, 'Dm_Air: toca el piso'),
        muerte=exportar_se('cuervo_muerte', 'em/em23.drs', 8, 8, 'Die_Normal'),
    )
    sonidos.update({'cuervo_' + k: v for k, v in snd.items()})
    eff = re4_eff.Eff(entrada(a, 4, 'EFF'), 'em23 ARC 4')
    return dict(
        colocaciones=lista,
        aparecen='be_flag 1: EmSetFromList al entrar al cuarto (em_set.cpp), desde el arranque',
        modelo=info,
        escala='em23_R0_Init: escala uniforme al azar 0.9..1.1 (fRand1_1 * 0.1 + 1)',
        comportamiento=dict(
            quieto='em23_R1_Wait: una de las 4 motions quieto_* al azar, otra al terminar',
            se_asusta='EM23_PL_NEAR: Leon a < 5 m (25e6 mm^2) o Leon disparando (STA_PL_FIRE) a < 10 m -> Takeoff',
            despegue='gira hacia un rumbo al azar +-90 grados del actual a pi/16 rad/frame; al terminar la motion -> '
                     'Turn con velocidad local (0, 20, 30) mm/frame',
            vuelo='em23_R1_Turn + em23FlyMove: acelera 10 mm/frame^2 hasta 150 mm/frame hacia adelante, sube/baja a '
                  '10 mm/frame^2 (max 50) hacia altura_vuelo_sobre_leon; gira hacia Leon (Muku) 1 grado/frame o '
                  'pi/256 (alterna cada 120..239 frames; pi/32 si se movio en los ultimos 10 frames); cambia de SEQ de '
                  'planeo cada 5 vueltas de la motion',
            aterriza='solo con pCorpse (lo pone el cuarto; r100 no): en r100 los cuervos que despegan quedan volando en '
                     'circulos sobre Leon',
            dano='em23DmCk: armas 0/2/0xB/0x10 -> 900..1099; escopetas 7/8/0x21 9999 de cerca (< 6 m) si no 900..1099; '
                 'mina 0xE -> 0; el resto 9999. hp 10: cualquier golpe lo mata. Fuego -> muere (y se oscurece). '
                 'Efectos EFF_EM23 est 0 y 1 (plumas / sangre) en el golpe + SE 0xF',
            cae='Dm_Air: gira +-pi/20 rad/frame, gravedad -10 mm/frame^2, freno 0.95 en z; al tocar el piso SE 9 -> '
                'Die_Normal',
            muere='Die_Normal: motion "morir", SE 8, sin colision, EmSetDropItem: suelta el item del ITA (linkType 1) o '
                  'el RandomItemCk 0x23; queda el cuerpo',
            colision='atari.init(0, -100, 0, 350, 150, 150, 200, 1, 0x2000, 10); caja de golpe YarareInit(0, -100, 0, '
                     '250, 200); no se puede fijar la mira (LOCKOFF)'),
        efectos_em23=dict(fuente='em23.drs ARC 4 (EFF_EM23 = 27)', est=ests(eff, (0, 1))),
    )


# ---------------------------------------------------------------------------------------------------
#  5. examinar (AEV)
# ---------------------------------------------------------------------------------------------------
def examinar(sonidos):
    textos = A.mdt_textos(tag('MDT'))
    core_das = archive.Archive(os.path.join(EXT, 'etc', 'core.das'))
    textos_core = A.mdt_textos(next(e for e in core_das.entries() if e.index == 6).data)
    A.CARTELES.update({k: textos_core[k + 0x16] for k in range(len(A.ACT)) if k + 0x16 < len(textos_core)})
    aev = A.aev_completo(tag('AEV'), textos)
    cams = cortes_camara(tag('CAM'))

    def centro(area):
        if 'centro' in area:
            return area['centro']
        P = np.array(area['pts'])
        return rn(P.mean(0))
    exec_txt = {
        11: dict(mensaje='0xB', texto=textos[0xB], camara_corte=None, se='SndCall(6, 0x29) golpe en la puerta',
                 funcion='r100_MesDoor (habilitada durante la emboscada)'),
        12: dict(mensaje='0xC', texto=textos[0xC], camara_corte=None, se=None,
                 funcion='r100_MesTruck (antes de Rsf 10)'),
        22: dict(mensaje='0x2F', texto=textos[0x2F], camara_corte=0xB,
                 se='stream de voz SndStrReq(0, 0x12, 3) con el stream del cuarto bajado (r100_mes_gaikotu_bgm)',
                 funcion='r100_mes_gaikotu: SceUpCut(mes 0x2F, cam 0xB) (reemplaza al MES del archivo, mismos datos)'),
        24: dict(mensaje='0xF antes de Rsf 10 / 0xE despues', texto=[textos[0xF], textos[0xE]], camara_corte=8,
                 se=None, funcion='r100_MesBrige: la rama 0xF ("aaa", texto de relleno) no se ve nunca: R100Init solo '
                                  'cuelga esta funcion del area 0x18 despues de Rsf 10. Despues: la 1a vez el evento '
                                  'del barranco (r100_GakeEvent), luego CutCall(8) + 0xE'),
    }
    lista = []
    for e in aev:
        no = e['no']
        if e['tipo'] not in (5, 8) and no not in exec_txt:
            continue
        d = dict(area='0x%02X' % no, tipo=e['tipo_nombre'], centro_xz_m=centro(e['area']), piso_m=e['area']['piso'],
                 alto_m=e['area']['alto'], poligono_xz_m=e['area'].get('pts'), dispara=e['dispara'],
                 mirada=e.get('mirada'), cartel=e.get('cartel'))
        if e['tipo'] == 5 and no not in exec_txt:
            ms = e['mensaje']
            d.update(mensaje=ms['no'], texto=ms['texto'], camara_corte=ms['camara_corte'], se=ms['se'],
                     funcion='sceAtFunc_mes -> SceAtSetMes')
        elif e['tipo'] == 8:
            d.update(mensaje='core 6', texto=textos_core[6], camara_corte=None, se=None,
                     funcion='sceAtFunc_save -> CardSave (maquina de escribir); el r100 MDT 0x15 ("I can\'t save my '
                             'progress in this version") no lo usa ningun codigo de la decomp USA')
        else:
            d.update(exec_txt[no])
        cc = d.get('camara_corte')
        d['camara'] = cams.get(cc) if cc is not None else None
        lista.append(d)
    otros = [
        dict(que='caja de madera (boton ACT_CHECK)', mensaje='core 3', texto=textos_core[3], funcion='emBoxAction'),
        dict(que='el primer ganado (s03), mirada hacia abajo', mensaje='0xD', texto=textos[0xD],
             funcion='r100_MesGanado: CamCtrl.StartLookDownEm + SceMesSet(0xD)'),
    ]
    sonidos['puerta_golpe'] = exportar_se('puerta_golpe', 'St1/r100.das', 6, 0x29, 'r100_MesDoor')
    return dict(
        regla='AEV tipo 5 (MES): tecla de accion sin cartel (Key.trg 0x400) dentro del area (prueba en el punto 0.55 m '
              'delante de Leon si check_flag bit0) y mirando al yaw +- rango si check_flag bit1. Con camara: '
              'SceUpCutStart (juego congelado, sin HUD), CamCtrl.CutCall(corte), mensaje, al cerrarlo '
              'CamCtrl.Comeback. Textos: r100.das MDT (ingles USA), con " / " = salto de pagina',
        areas=lista, otros=otros, cortes_camara_usados=sorted({d['camara_corte'] for d in lista
                                                               if d.get('camara_corte') is not None}))


# ---------------------------------------------------------------------------------------------------
def leon(sin_leon):
    salida = os.path.join(OUT, 'leon_objetos.glb')
    if not sin_leon:
        argv = sys.argv
        sys.argv = ['re4_extract_leon.py', '--anim', 'em2a:12+13=cepo_atrapado', '--anim', 'em21:23=soltar_perro',
                    '-o', salida]
        try:
            L.main()
        finally:
            sys.argv = argv
    return dict(glb='leon_objetos.glb', generado_con='re4_extract_leon.py --anim em2a:12+13=cepo_atrapado --anim '
                                                     'em21:23=soltar_perro (mismo esqueleto/mallas que leon.glb)',
                clips={'cepo_atrapado': 'em2a ARC 0x10 + SEQ 0x11 (plem2a_Trap1Bite: pl->subArc = el del cepo)',
                       'soltar_perro': 'em21 ARC 0x1B (plemTrapCancel)'})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sin-leon', action='store_true', help='no regenerar leon_objetos.glb')
    args = ap.parse_args()
    preparar_evalhost()
    os.makedirs(os.path.join(OUT, 'sonidos'), exist_ok=True)
    esl = EMB.leer_esl()
    items = json.load(open(os.path.join(HERE, 'out', 'items', 'items_r100.json'), encoding='utf-8'))
    sonidos = {}
    doc = dict(
        fuente='funciones del decomp y archivos del disco: ver el docstring de re4_extract_objetos_r100.py',
        unidades='metros, coordenadas del cuarto r100 (Y arriba); yaw en radianes (mira a (sin y, 0, cos y)); 30 fps',
        cepos=cepos(esl, sonidos),
        perro=perro(esl, sonidos),
        leon=leon(args.sin_leon),
        cajas=cajas(items, sonidos),
        cuervos=cuervos(esl, items, sonidos),
        examinar=examinar(sonidos),
        sonidos=sonidos,
    )
    with open(os.path.join(OUT, 'objetos_r100.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print('cepos:', len(doc['cepos']['colocaciones']), 'cajas:', len(doc['cajas']['colocaciones']),
          'cuervos:', len(doc['cuervos']['colocaciones']), 'examinar:', len(doc['examinar']['areas']),
          'sonidos:', len(sonidos))
    for k in ('cepos', 'perro', 'cuervos'):
        mo = doc[k]['modelo']
        print(k, mo['glb'], mo['partes'], 'partes', [(c['clip'], c['frames']) for c in mo['clips']])


if __name__ == '__main__':
    main()
