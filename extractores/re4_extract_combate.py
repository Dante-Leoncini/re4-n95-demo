#!/usr/bin/env python3
"""
Lo que hace falta para PELEAR en la demo (RE4 GameCube, disco USA), aparte de las animaciones de Leon
(esas van en `re4_extract_leon.py --combate` -> out/combate/leon_combate.glb + leon_combate_clips.json):

  out/combate/pistola.glb        la pistola inicial (wep02:2) con SU esqueleto de 4 partes (0 cuerpo, 1 corredera,
                                 2 cargador, 3 un marcador SIN malla que en el disparo salta atras/arriba) y sus motions (disparo, recarga, corredera trabada...);
                                 atlas propio pistola_atlas.png a resolucion completa. La raiz va en el hueso 10 de
                                 Leon (la mano derecha: objRuger.cpp init, pParts->pParent = getPartsPtr(0xA)).
  out/combate/efectos.json       los efectos (est) de sangre / impacto / laser, cada record traducido a un emisor
                                 generico con el MISMO formato que out/r100_fx/emisores.json (re4_extract_look.py:
                                 metros, segundos, factores por segundo, blend de GL) + el record crudo
  out/combate/tex/*.png          sus texturas (cuadros sueltos + tiras "<eff>_texXX_tiraN.png" si son animadas)

FUENTES (decomp re4/src):
  em10/em10.cpp em10BloodSet (bala / cuchillo en el ganado), em10LostHead (cabeza que explota), em10AtkCk (sangre
  de Leon), game/em_sub.cpp EmDmBloodSet2 / EmGetDmPos / EmPlBloodSet2, game/est.cpp EspSetEatEffect (bala en la
  pared / piso), game/pl_wep.cpp (PlWepHit: EspSetEatEffect), wep/pl_knife.cpp knife_r3_fire00 (estela),
  game/objWep.cpp drawLaserSight / drawPoint / getMarkerPos, game/esp_app.cpp EspDrawLaserLine, game/esp19.cpp
  (la linea del laser), game/pl_dmg.cpp (polvo de las caidas de Leon), wep/objRuger.cpp (la pistola).

Uso:  python3 re4_extract_combate.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import re4_extract_leon as L          # noqa: E402  (pone ../re4/tools en el path)
import re4_extract_look as LOOK       # noqa: E402  (emisor_de, exportar_texturas: el formato de emisores.json)
from motion import archive, fcv, modelbin, meshbin, gxtex, gltf  # noqa: E402
sys.path.insert(0, os.path.join(HERE, 'tools'))
import re4_eff  # noqa: E402

OUT = os.path.join(HERE, 'out', 'combate')
EXT = os.path.join(HERE, 'extracted')
MM = 0.001
FPS = 30.0
r = LOOK.r

# ---------------------------------------------------------------------------------------------------------------
#  PISTOLA con esqueleto (wep02: BIN 2 = modelo 0x6 de cObjRuger, TPL 1). Motions del ARMA (objRuger.cpp; entrada =
#  WEP_ARC_PTR - 4). OJO: el decomp llama "Punisher" a cObjRuger, pero es la pistola inicial (item 0x23 -> weapon_no 2,
#  PlayerInit; ver armas.json).
# ---------------------------------------------------------------------------------------------------------------
PISTOLA_CLIPS = [
    (50, 'reposo', 'motReset[0] 0x36: pose de reposo (cObjWep::resetMotion con balas en el cargador)'),
    (55, 'reposo_vacia', 'motReset[1] 0x3B: corredera TRABADA atras (cargador vacio)'),
    (48, 'disparar', 'moveFire 0x34: corredera atras y vuelve (f0-6); arranca junto con el clip disparar de Leon'),
    (53, 'disparar_ultima', 'moveFire 0x39: el ultimo tiro, la corredera queda trabada atras'),
    (52, 'recargar', 'moveReload 0x38 (nivel 0, con balas): cargador suelta f10, sale f11-13, el nuevo aparece f14, '
                     'entra f26-30, ItemMgr.reload() en f31 (reloadEnd[0]); SE 0x16 en f0'),
    (49, 'recargar_vacia', 'moveReload 0x35 (nivel 0, vacia): igual + la corredera se suelta en f37'),
    (58, 'recargar_nv1', '0x3E (mejora de recarga 1): el cargador entra f23-25, reload en f26; SE 0x20'),
    (56, 'recargar_vacia_nv1', '0x3C (mejora 1, vacia)'),
    (59, 'recargar_nv2', '0x3F (mejora 2): entra f14-16, reload en f17; SE 0x21'),
    (57, 'recargar_vacia_nv2', '0x3D (mejora 2, vacia)'),
]


def pistola(arc):
    L.ATLAS_COMPLETO = True
    scale = MM
    skel = modelbin.parse(arc('wep02').entry(2).data)
    m = meshbin.parse(arc('wep02').entry(2).data)
    tex = gxtex.parse_tpl(arc('wep02').entry(1).data)
    rest = L.rest_world(skel)
    imagenes = {}

    def clave_de(t, pref, part):
        alpha = part.alpha_tex if part.flags & 4 else None
        k = (pref, part.tex_id, alpha)
        if k not in imagenes:
            imagenes[k] = gltf.compose_image(t, part.tex_id, alpha)
        return k
    for part in m.parts:
        if part.triangles():
            clave_de(tex, 'wep02_001', part)
    atlas, rects = L.armar_atlas(imagenes)
    H, W = atlas.shape[:2]
    with open(os.path.join(OUT, 'pistola_atlas.png'), 'wb') as f:
        f.write(gxtex.png(atlas))
    b = gltf.Builder()
    grupos, n_tri, cutoff = L.malla_skinneada([(m, tex, 'wep02_001')], clave_de, rects, W, H, scale, 0)
    prims = []
    for transp, mat, parte in ((False, 0, 'opaco'), (True, 1, 'transparente')):
        index, pos, nrm, uv, jo, we, idx = grupos[transp]
        if idx:
            prims.append(L.primitiva(b, pos, nrm, uv, idx, mat, parte, jo, we))
    nombres = ['cuerpo', 'corredera', 'cargador', 'marcador']
    nodes = [{'name': 'pistola', 'children': []}]
    for p in skel.parts:
        nodes.append({'name': f'pistola_{p.no:03d}_{nombres[p.no] if p.no < 4 else "x"}',
                      'translation': [c * scale for c in p.pos], 'children': []})
    for p in skel.parts:
        nodes[0 if p.parent < 0 else p.parent + 1]['children'].append(p.no + 1)
    for nd in nodes:
        if not nd['children']:
            del nd['children']
    n = skel.n_parts
    ibm = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -q[0] * scale, -q[1] * scale, -q[2] * scale, 1] for q in rest]
    skin = {'name': 'pistola_esqueleto', 'joints': list(range(1, n + 1)), 'skeleton': 0,
            'inverseBindMatrices': b.accessor('16f', gltf.FLOAT, 'MAT4', ibm)}
    malla_nodo = len(nodes)
    nodes.append({'name': 'Pistola_malla', 'mesh': 0, 'skin': 0})
    anims, info = [], []
    for num, nombre, nota in PISTOLA_CLIPS:
        motion = fcv.parse(arc('wep02').entry(num).data)
        poses = L.play(skel, motion, ik=False)
        anims.append(L.clip_esqueleto(b, nodes, n, poses, nombre, FPS, scale))
        info.append({'clip': nombre, 'fcv': f'wep02:{num}', 'wep_arc': hex(num + 4), 'frames': len(poses), 'nota': nota})
    textura = {'baseColorTexture': {'index': 0}, 'metallicFactor': 0.0, 'roughnessFactor': 1.0}
    doc = {'asset': {'version': '2.0', 'generator': 're3_w3d re4_extract_combate.py'}, 'scene': 0,
           'scenes': [{'name': 'pistola', 'nodes': [0, malla_nodo]}], 'nodes': nodes, 'skins': [skin],
           'meshes': [{'name': 'Pistola_malla', 'primitives': prims}], 'images': [{'uri': 'pistola_atlas.png'}],
           'samplers': [{'magFilter': 9729, 'minFilter': 9729, 'wrapS': 33071, 'wrapT': 33071}],
           'textures': [{'source': 0, 'sampler': 0}],
           'materials': [{'name': 'Pistola_opaco', 'pbrMetallicRoughness': textura, 'extras': {'w3d_transparent': False}},
                         {'name': 'Pistola_transparente', 'pbrMetallicRoughness': textura, 'alphaMode': 'MASK',
                          'alphaCutoff': cutoff, 'extras': {'w3d_transparent': True}}],
           'animations': anims, 'accessors': b.accessors, 'bufferViews': b.buffer_views}
    gltf.write(doc, bytes(b.blob), os.path.join(OUT, 'pistola.glb'))
    print(f'pistola.glb: {n_tri} triangulos, {n} huesos, {len(anims)} clips, atlas {W}x{H}')
    return info


# ---------------------------------------------------------------------------------------------------------------
#  EFECTOS: (nombre, eff, est, que, cuando, fuente, orientacion)
# ---------------------------------------------------------------------------------------------------------------
ORIENT_DANO = ('EstSet(0, -1, pos, dir, ...) con pos = punto de impacto sobre la caja de dano (EmGetDmPos) y dir = '
               '(0, angulo XZ desde el centro de la parte golpeada HACIA el origen del dano (el que dispara), 0): el '
               '+Z local del efecto apunta al tirador (la sangre salta hacia el), +Y arriba; records Parts 255 = en '
               'el mundo por esa matriz')
ORIENT_PARED = ('EspSetEatEffect: rot = (-atan2(n.y, |n.xz|), atan2(n.x, n.z), 0) con n = normal de la superficie -> '
                'el +Z local sale de la pared (a lo largo de la normal)')
ORIENT_MODELO = 'EstSet(modelo, ...) sin pos: la cabeza del est (pos/parte) va sobre el modelo (partes del personaje)'

EFECTOS = [
    ('bala_ganado', 'em10', 0x01,
     'bala de pistola en la CARNE del ganado (cualquier parte, cabeza incluida): polvo/sangre en niebla, chorros, '
     'gotas, estelas de sangre',
     'em10BloodSet, m_Wep 1..4 (pistolas; weapon_no 2 = la inicial), parte sin armadura, sin lluvia',
     'em10/em10.cpp em10BloodSet (case 1,2,3,4: EmDmBloodSet2(em, 0x10, 1))', ORIENT_DANO),
    ('bala_ganado_agua', 'em10', 0x3B, 'idem con lluvia / agua (ChkWaterEffectEnable)',
     'em10BloodSet con STA_ROOM_RAIN (r100 NO: no llueve)', 'em10/em10.cpp em10BloodSet', ORIENT_DANO),
    ('bala_ganado_armadura', 'em10', 0x64, 'bala en una parte con ARMADURA (casco/metal): chispas, luz, sin sangre',
     'em10ArmorCk(parte) != 0 (el ganado de r100 no tiene)', 'em10/em10.cpp em10BloodSet (rama em10ArmorCk)', ORIENT_DANO),
    ('cuchillo_ganado', 'em10', 0x29, 'CUCHILLO en el ganado (m_Wep 0x10)', 'em10BloodSet case 0x10 / 0x1A',
     'em10/em10.cpp em10BloodSet', ORIENT_DANO),
    ('cabeza_explota', 'em10', 0x03, 'la cabeza que REVIENTA (sangre + trozos, efm 0xFE)',
     'em10LostHead(a 0/1) cuando la cabeza se puede perder; si CTRL12_ID_BIGEFF esta activo usa 0x34 (version chica). '
     'NO en r100: em10LostHead fuerza no=1 en stage 1 room 0 (la cabeza nunca revienta en la casa del primer ganado)',
     'em10/em10.cpp em10LostHead', ORIENT_MODELO),
    ('cabeza_explota_chica', 'em10', 0x34, 'version chica de la cabeza que revienta (hay otro efecto grande reciente)',
     'em10LostHead con CTRL12_ID_BIGEFF', 'em10/em10.cpp em10LostHead', ORIENT_MODELO),
    ('cabeza_explota_cuello', 'em10', 0x06, 'sangre que sale del cuello despues de perder la cabeza (siempre junto a 0x03/0x34)',
     'em10LostHead', 'em10/em10.cpp em10LostHead', ORIENT_MODELO),
    ('sangre_leon_golpe', 'em10', 0x0B, 'sangre de LEON cuando el ganado le pega (ataque basico, Em10AtkTbl 0)',
     'em10AtkCk: EmAtkHitCk acierta, ataque no 0 -> EmPlBloodSet2(em, a, 1, 0x10, 0xB)',
     'em10/em10.cpp em10AtkCk (~l.23195) + game/em_sub.cpp EmPlBloodSet2', ORIENT_DANO + ' (sobre Leon, hacia el ganado)'),
    ('sangre_generica', 'core', 0x00, 'sangre comun chica (cuchillos/escopeta en enemigos genericos, EmDmBloodSet)',
     'EmDmBloodSet m_Wep 1..4 etc / EmPlBloodSet type != 1', 'game/em_sub.cpp EmDmBloodSet', ORIENT_DANO),
    ('sangre_generica_grande', 'core', 0x01, 'sangre grande (core 1 + tres core 2 alrededor)',
     'EmDmBloodSet default / EmPlBloodSet type 1', 'game/em_sub.cpp EmDmBloodSet', ORIENT_DANO),
    ('sangre_generica_salpicon', 'core', 0x02, 'salpicon que acompana a core 1 (x3, desplazado +-0.15..0.25 m)',
     'EmDmBloodSet', 'game/em_sub.cpp EmDmBloodSet', ORIENT_DANO),
    ('bala_pared', 'core', 0x1F,
     'bala en pared / piso comun: nube de polvo que sale de la superficie + estela; NO deja agujero (ver bala_agujero)',
     'EspSetEatEffect tipo 0 "EAT_ET_NORMAL" (en r100: 1440 de los 1971 triangulos del EAT) y tipo 1 junto a 0x20',
     'game/est.cpp EspSetEatEffect, llamado por game/pl_wep.cpp (l.388) con el punto y la normal del rayo', ORIENT_PARED),
    ('bala_agujero', 'core', 0x20,
     'AGUJERO de bala (decal orientado sobre la superficie, 8 cm, 5 mm afuera, color (55,50,45) con mascara tex 0x1E; '
     'queda 375 frames = 12.5 s y despues se apaga x0.95/frame)',
     'EspSetEatEffect tipo 1 "EAT_ET_BULLET" (0x1F + 0x20; en r100: 106 triangulos del EAT)',
     'game/est.cpp EspSetEatEffect', ORIENT_PARED),
    ('bala_follaje_r100', 'r100', 0x0E,
     'bala en VEGETACION/arboles de r100 (hojas tex 0xF1 que caen aleteando + polvo)',
     'EspSetEatEffect tipo 4 "EAT_ET_ROOM0": r100_eff_info4.effGun = (EFF_ROOM, 0x0E) (en r100: 403 triangulos)',
     'st1/r100.cpp r100_eff_info4 + game/at_sub2.cpp AtEffInfo::getWepEff (armas 1..12 -> effGun)', ORIENT_PARED),
    ('bala_agua_r100', 'r100', 0x20, 'bala en el AGUA de r100 (EAT tipo 2: r100_eff_info2.effGun = (EFF_ROOM, 0x20))',
     'EspSetEatEffect tipo 2 (22 triangulos en r100)', 'st1/r100.cpp r100_eff_info2', ORIENT_PARED),
    ('bala_charco', 'core', 0x11, 'bala en un charco (piso con FlrAt se.eff_type 1, normal.y > 0.9); SE 2/0xC',
     'EspSetEatEffect tipo 0 + EspChkInPuddle', 'game/est.cpp EspSetEatEffect', 'sin rotacion (pos solamente)'),
    ('bala_agua', 'core', 0x14, 'bala en el agua (superficie de agua del cuarto)', 'EspSetWaterHitmark',
     'game/est.cpp EspSetWaterHitmark / game/pl_wep.cpp wepSetWaterShot', 'sin rotacion'),
    ('cuchillo_estela', 'core', 0x2B, 'la ESTELA del tajo del cuchillo (esp 0x12 sobre Leon)',
     'knife_r3_fire00, al empezar cada tajo', 'wep/pl_knife.cpp knife_r3_fire00 (l.368)', ORIENT_MODELO + ' (Leon)'),
    ('leon_muerte_polvo', 'pl00', 0x03, 'polvo al caer MUERTO (Pl_R0_Die; 4 en el agua)', 'Pl_R0_Die r_no_1 0',
     'game/pl_dmg.cpp Pl_R0_Die', ORIENT_MODELO + ' (Leon)'),
    ('leon_caida_polvo', 'pl00', 0x05, 'polvo del dano fuerte (vuela al piso; 6 en el agua)', 'damageBlow vivo',
     'game/pl_dmg.cpp damageBlow', ORIENT_MODELO + ' (Leon)'),
    ('leon_muerte_fuerte_polvo', 'pl00', 0x0D, 'polvo + sangre del dano fuerte MORTAL (0xE en el agua)', 'damageBlow muerto',
     'game/pl_dmg.cpp damageBlow', ORIENT_MODELO + ' (Leon)'),
    ('leon_levantarse_polvo', 'pl00', 0x0F, 'polvo al levantarse del piso (0x10 en el agua)', 'damageNormal/Blow r_no_2 0xA',
     'game/pl_dmg.cpp damageNormal', ORIENT_MODELO + ' (Leon)'),
]


def eat_r100():
    """Cuantos triangulos del EAT de r100 (colision de EFECTOS: la que usa el rayo de la bala) hay de cada tipo."""
    import re4_extract_r100 as R
    das = archive.Archive(os.path.join(EXT, 'St1', 'r100.das'))
    _, tris = R.sat(next(e for e in das.entries() if e.tag == 'EAT').data)
    cnt = {}
    for *_, attr, _clase in tris:
        t = (1 if attr & 0x800000 else 0) + (2 if attr & 0x8000 else 0) + (4 if attr & 0x80 else 0)
        cnt[t] = cnt.get(t, 0) + 1
    nombres = ['NORMAL', 'BULLET', 'WATER', 'PAD', 'ROOM0', 'ROOM1', 'ROOM2', 'ROOM3']
    return dict(fuente='r100.das EAT (formato SAT) ; tipo = at_sub.cpp EatGetEffectType', triangulos=len(tris),
                por_tipo={'%d_%s' % (k, nombres[k]): v for k, v in sorted(cnt.items())})


def laser_info(core):
    """La mira laser de la pistola: linea (core est 3, esp19) + punto (core est 0x50 record 0)."""
    ln = core.est[3]['records'][0]
    pt = core.est[0x50]['records'][0]
    largo = ln['Vec1'][0] or 12000.0
    return dict(
        fuente='game/objWep.cpp cObjWep::drawLaserSight / drawPoint / getMarkerPos, game/esp_app.cpp EspDrawLaserLine, '
               'game/esp19.cpp Draw_line3d_local_222, core.das EFF est 3 y est 0x50',
        rayo=dict(origen_arma_m=[0.228, -0.024, 0.029],
                  origen_nota='getMarkerPos: ofs[weapon_no 2] = (228, -24, 29) mm en la parte 0 del ARMA (= el espacio del '
                              'hueso 10 de Leon); direccion = -X del arma; el rayo de punteria mide 50 m (-50000)',
                  corta_en='GetWepTargetPos (em_sub.cpp): el primer choque con el escenario (EatMgr.hitCheck) o con un '
                           'enemigo (caja de dano) sobre ese rayo -> lcross; wep.m_ShotPos = lcross (ahi pega la bala)',
                  empieza_despues_m=0.5,
                  empieza_nota='la linea arranca 500 mm adelante del origen (lpos += 500*dir); si lcross esta a menos de '
                               '0.5 m no se dibuja nada'),
        linea=dict(esp='0x19 (linea 3D)', textura=None, color=LOOK.c255(ln['Col_start'][:3]), alfa=ln['Col_start'][3] / 255.0,
                   color_255=ln['Col_start'], blend=ln['Blend_type'], blend_nombre=LOOK.BLEND_NOMBRE[ln['Blend_type']],
                   blend_gl=LOOK.BLEND_GL[ln['Blend_type']],
                   ancho='linea GX de 2 vertices (GXBegin GX_LINES) sin textura: el ancho de linea por defecto (~1 px '
                         'en el EFB de 640x448); rate=1 (3 solo en los cuartos 22C/228, y ahi multiplica el LARGO)',
                   largo_max_m=largo * MM,
                   fundido='color del extremo lejano = color * (1 - d/largo_max) con d = largo dibujado (cortado a '
                           'largo_max): lineal a negro -> con blend aditivo se desvanece; a 19 m ya no se ve',
                   z='Z test LEQUAL con escritura (alfa 255; 0xFE lo apagaria), sin cull, sin luz, sin niebla propia',
                   vida='1 frame: se vuelve a crear cada frame mientras se apunta (Life_max 1)',
                   variante_noadd='STA_LASERSITE_NOADD: blend GX_BL_SRCALPHA / GX_BL_INVSRCALPHA (alfa normal) y alfa*0.8'),
        punto=dict(esp='0x00 (sprite billboard)', textura='core_tex%02X_f0.png' % pt['Tex_id'], tex_id='0x%02X' % pt['Tex_id'],
                   tamano_base_m=[pt['Size_base_x'] * MM, pt['Size_base_y'] * MM],
                   escala='s = min(0.8 + d_cam / 8.0 m, 3.0), d_cam = distancia de la CAMARA al punto: el sprite '
                          'crece con la distancia (casi tamano constante en pantalla); cuadrado final = 0.07 m * s '
                          '(0.056 m pegado a la camara, 0.21 m desde 17.6 m)',
                   escala_cuartos_22c_228='min(1 + d/3 m, 6)',
                   color=LOOK.c255(pt['Col_start'][:3]), alfa=pt['Col_start'][3] / 255.0, color_255=pt['Col_start'],
                   blend=pt['Blend_type'], blend_nombre=LOOK.BLEND_NOMBRE[pt['Blend_type']],
                   blend_gl=LOOK.BLEND_GL[pt['Blend_type']],
                   cuando='SOLO si el rayo pega en un ENEMIGO (GetWepTargetPos == 2) y el laser mide mas de 0.5 m; en '
                          'paredes y piso el juego NO dibuja punto (drawLaserSight case 1 no llama drawPoint)',
                   vida='1 frame (se re-crea cada frame); solo el record 0 de est 0x50 (el 1 es un destello esp 0x0E '
                        'que drawPoint no usa)',
                   textura_nota='I8: intensidad = color y alfa (brillo radial blanco); color final = textura * color'))


def main():
    os.makedirs(OUT, exist_ok=True)
    arc = L.Archivos(L.DEFAULT_DISC)
    info_pistola = pistola(arc)

    effs = {'core': re4_eff.load_effs(os.path.join(EXT, 'etc', 'core.das'), 1)[0],
            'em10': re4_eff.Eff(arc('em10').entry(0).data, 'em10'),     # EspDataLoad(PL_ARC_PTR(subArc, 4), EFF_EM10)
            'pl00': re4_eff.Eff(arc('pl00').entry(22).data, 'pl00'),    # EspDataLoad(PL_ARC_PTR(pPlayer, 0x1A), EFF_PL00)
            'r100': re4_eff.Eff(next(e for e in archive.Archive(os.path.join(EXT, 'St1', 'r100.das')).entries()
                                     if e.tag == 'EFF').data, 'r100')}  # EFF_ROOM de r100
    core = effs['core']

    def texlookup_de(eff):
        return lambda t: eff.tex.get(t) or core.tex.get(t)
    usados = {k: set() for k in effs}
    for nombre, pref, no, *_ in EFECTOS:
        eff = effs[pref]
        for q in eff.est[no]['records']:
            ids = set()
            if q['Id'] not in re4_eff.NO_TEX_IDS:
                ids.add(q['Tex_id'])
            if q['Tool_flg'] & 0x4000:
                ids.add(q['MaskTex_id'])
            for t in ids:
                (usados[pref] if t in eff.tex else usados['core']).add(t)
    usados['core'].add(core.est[0x50]['records'][0]['Tex_id'])   # el punto del laser
    carpeta_tex = os.path.join(OUT, 'tex')
    tex_arch = {}
    arch_por_eff = {}
    for pref, eff in effs.items():
        a = LOOK.exportar_texturas([(pref, eff)], {pref: usados[pref]}, carpeta_tex)
        arch_por_eff[pref] = a
    grupos = []
    for nombre, pref, no, que, cuando, fuente, orient in EFECTOS:
        eff = effs[pref]
        s = eff.est[no]
        # las texturas del propio archivo tienen prioridad sobre las del core (como EspSeqSet)
        tex_arch = dict(arch_por_eff['core'])
        tex_arch.update(arch_por_eff[pref])
        tl = texlookup_de(eff)
        recs = [LOOK.emisor_de(q, tex_arch, tl) for q in s['records']]
        crudo = [{k: (list(v) if isinstance(v, tuple) else v) for k, v in q.items()} for q in s['records']]
        grupos.append(dict(nombre=nombre, fuente='%s EFF est 0x%02X' % (pref, no), eff=pref, est='0x%02X' % no, que=que,
                           cuando=cuando, decomp=fuente, orientacion=orient,
                           cabeza=dict(pos_m=r([x * MM for x in s['pos']]), rot_grados=r(s['rot_deg']), parte=s['parts']),
                           duracion_frames=max((e['retardo_frames'] + (e['vida_simulada_frames'] or e['vida_max_frames'] or 0)
                                                + ((e['generador'] or {}).get('vida_frames') or 0)) for e in recs),
                           emisores=recs, crudo=crudo))
        print(f'  {nombre}: {pref} est 0x{no:02X}, {len(recs)} records')
    fx = dict(
        fuente='core.das EFF (efectos comunes) + em10.drs EFF (ganado, EFF_EM10 = 16) + pl00.drs EFF (Leon, EFF_PL00 = 3) '
               '+ r100.das EFF (EFF_ROOM = 1)',
        eat_r100=eat_r100(),
        unidades='metros, segundos (30 fps); *_por_frame = valor del juego por frame; colores 0..1',
        semantica=dict(
            por_frame='pos += vel; vel = (vel + acel) * arrastre; tam_mult += crec; crec *= freno (muere si tam_mult<=0); '
                      'ang += vel_ang; t<=aparicion: alfa = alfa0*t/aparicion; t >= aparicion+sostener: rgba *= color_mult '
                      '(muere si alfa < 4/255); muere en vida_max si != 0',
            tamano='cuadrado completo = tamano_m * tam_mult (centrado salvo Cx/Cy de la textura: Cy=H -> ancla abajo)',
            generador='espgen: cada espera_frames (+azar) emite por_emision particulas durante vida_frames (0 = siempre)'
                      '; pos = pos + azar uniforme en +-pos_azar',
            ejes='vel/pos/acel en el espacio de la MATRIZ del est (ver "orientacion" de cada grupo): +Z = hacia el '
                 'tirador (sangre) o la normal (pared), +Y arriba; Tool_flg 0x20 = solo la posicion sale de la parte',
            blend='ver blend_gl (glBlendFunc). mod2x: src*dst + dst', texturas='out/combate/tex (mismos nombres que '
                                                                          'out/r100_fx/tex: <eff>_texXX_fN / _tiraN)'),
        cual_usar=dict(
            pistola_en_ganado='bala_ganado (cuerpo Y cabeza: el efecto no cambia; la cabeza solo cambia el dano x1.2 y '
                              'la reaccion em10_R1_Dm_Head)',
            cuchillo_en_ganado='cuchillo_ganado + cuchillo_estela al empezar el tajo',
            bala_en_pared='segun el tipo EAT del triangulo que pega el rayo (attr bits 0x800000/0x8000/0x80 -> 1/2/4): '
                          '0 bala_pared, 1 bala_pared + bala_agujero, 2 bala_agua_r100, 4 bala_follaje_r100 (r100)',
            ganado_pega_a_leon='sangre_leon_golpe',
            laser='ver "laser"'),
        laser=laser_info(core),
        grupos=grupos)
    with open(os.path.join(OUT, 'efectos.json'), 'w') as f:
        json.dump(fx, f, indent=1, ensure_ascii=False)
    with open(os.path.join(OUT, 'pistola_clips.json'), 'w') as f:
        json.dump({'fps': FPS, 'glb': 'pistola.glb',
                   'montaje': 'raiz "pistola" en el hueso_010 de Leon (sin offset: objRuger init pParts->pParent = parte 0xA); '
                              'los vertices vienen en ese espacio, como Leon_pistola',
                   'partes': {'0': 'cuerpo (125 vertices)', '1': 'corredera (60)', '2': 'cargador (8: la base visible)',
                              '3': 'marcador sin malla (se mueve en el disparo)'},
                   'clips': info_pistola}, f, indent=1, ensure_ascii=False)
    print(f'-> {OUT}/efectos.json, pistola.glb, pistola_clips.json, tex/')


if __name__ == '__main__':
    main()
