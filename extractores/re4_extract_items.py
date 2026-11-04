#!/usr/bin/env python3
"""Items de r100 (RE4 GC USA): colocaciones (ITA), drops (enemigos / cajas), modelos (ITM), brillo (EFF core),
pantalla de recoger (IDC_EXAMINE + mensajes). Escribe en out/items/ (lo lee el conversor del N95: re4_n95/conversor/items.py).

Fuentes decomp (conversiones/re4/re4/src): game/sce_at.cpp (SceAtInit, sceAtSetItem, SceAtCheckSystemItemSet,
SceAtCreateItemAt, sceAtItemEffSet, sceAtItemDisappearEffSet, sceAtCheckItemEffectCol, sceAtGetItem),
include/sce_at.h (SceAtWork / SceAtItem), game/item_model.cpp (ITM), game/item.cpp (itemInfo, cItemMgr::get),
game/examine.cpp (exam_info, ItemExamine), game/em_sub.cpp (RandomItemCk, GetDropBullet, EmSetDropItem),
game/mes.cpp (MesSet attr), game/eff_sys.cpp (EFF_CORE = core.das#1, EFF_ITM = core.das#16).
"""
import json
import math
import os
import re
import struct
import sys

R3 = os.path.dirname(os.path.abspath(__file__)).replace(os.sep, '/')
RE4 = os.path.dirname(R3)
SRC = RE4 + '/re4/src'
OUT = R3 + '/out/items'
sys.path.insert(0, RE4 + '/re4/tools')
sys.path.insert(0, R3)
sys.path.insert(0, R3 + '/tools')
from motion import archive, meshbin, gxtex  # noqa: E402
meshbin._zero_pad = lambda *a: None
import re4_extract_r100 as R  # noqa: E402
import re4_extract_acciones as A  # noqa: E402
import re4_extract_hud as H  # noqa: E402
import re4_eff  # noqa: E402
from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

MM = 0.001


def rn(v, n=4):
    if isinstance(v, (list, tuple, np.ndarray)):
        return [rn(x, n) for x in v]
    return round(float(v), n)


def slug(s):
    s = s.replace('\u2212', '-').lower()
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')


# ------------------------------------------------------------------ tablas del decomp
def item_info_tbl():
    src = open(SRC + '/game/item.cpp', encoding='utf-8').read()
    body = src[src.index('void itemInfo(ITEM_ID id, ItemInfo* info)'):]
    body = body[:body.index('\n}\n')]
    out, pend, cur, default = {}, [], {}, None
    for ln in body.splitlines():
        ln = ln.strip()
        m = re.match(r'case (0x[0-9A-Fa-f]+|\d+):', ln)
        if m:
            pend.append(int(m.group(1), 0))
            continue
        if ln == 'default:':
            pend.append('default')
            continue
        m = re.match(r'info->(type|defNum|maxNum) = (\d+);', ln)
        if m:
            cur[m.group(1)] = int(m.group(2))
            continue
        if ln == 'break;':
            for k in pend:
                if k == 'default':
                    default = dict(cur)
                else:
                    out[k] = dict(cur)
            pend, cur = [], {}
    return out, default


def exam_info_tbl():
    src = open(SRC + '/game/examine.cpp', encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\{ (0x[0-9A-F]+), 0, \{ ([-\d.]+)f, ([-\d.]+)f, ([-\d.]+)f \}, ([-\d.]+)f, (\d+), (\d+), (\d+) \}',
                         src[:src.index('exam_info_ext')]):
        out[int(m.group(1), 16)] = dict(rot_deg=[float(m.group(i)) for i in (2, 3, 4)], escala=float(m.group(5)),
                                        luz=int(m.group(6)), eje_rot0=int(m.group(7)), eje_rot1=int(m.group(8)))
    return out


INFO, INFO_DEF = item_info_tbl()
EXAM = exam_info_tbl()


def info(i):
    return INFO.get(i, INFO_DEF)


def eff_col(i):
    """sceAtCheckItemEffectCol (sce_at.cpp)."""
    if i == 0x8C:
        return 8
    t = info(i)['type']
    if t in (1, 2, 3, 4):
        return 5
    if t == 6:
        return 4
    if t in (0, 5, 7):
        return 2
    return 3


GLOW_EST = {   # sceAtItemEffSet, sin padre y sin modelo / con modelo (EFF_CORE, owner 0xC00)
    1: dict(sin_modelo=[0x21], con_modelo=[0x2D]),
    2: dict(sin_modelo=[0x33, 0x21], con_modelo=[0x33, 0x21]),
    3: dict(sin_modelo=[0x2C], con_modelo=[0x2C]),
    4: dict(sin_modelo=[0x31], con_modelo=[0x31]),
    5: dict(sin_modelo=[0x2F], con_modelo=[0x2F]),
    7: dict(sin_modelo=[0x46, 0x21], con_modelo=[0x46, 0x21]),
    8: dict(sin_modelo=['0x33 (800 mm abajo)', 0x21], con_modelo=['0x33 (800 mm abajo)', 0x21]),
    9: dict(sin_modelo=[0x4D], con_modelo=[0x4D]),
}
DISAPPEAR_EST = {3: 0x2E, 5: 0x30, 4: 0x32, 2: 0x34, 7: 0x47, 8: 0x34}   # sceAtItemDisappearEffSet


def nombres():
    d = json.load(open(R3 + '/out/texto/mensajes_en.json', encoding='utf-8'))
    obj = {m['n']: m['plano'] for m in d['tablas']['objeto']['mensajes']}
    core = {m['n']: m for m in d['tablas']['core']['mensajes']}
    return obj, core


OBJ, CORE = nombres()


def nombre(i):
    return OBJ.get(i, '?').replace('\u2212', '-')


# ------------------------------------------------------------------ disco
das = archive.Archive(R3 + '/extracted/St1/r100.das')
ENT = {e.index: e for e in das.entries()}
core = archive.Archive(R3 + '/extracted/etc/core.das')
CENT = {e.index: e for e in core.entries()}


def tag(t):
    return [e for e in ENT.values() if e.tag == t][0].data


def leer_ita():
    d = tag('ITA')
    assert d[:3] == b'ITA' and struct.unpack('>H', d[4:6])[0] == 0x105
    n = struct.unpack('>H', d[6:8])[0]
    out = []
    for i in range(n):
        r = d[0x10 + 0x9C * i:0x10 + 0x9C * (i + 1)]
        it = r[0x5C:0x9C]
        pos = struct.unpack('>3f', it[0:12])
        ofs = struct.unpack('>3f', it[0x10:0x1C])
        iid, flagNo, num, find = struct.unpack('>4H', it[0x1C:0x24])
        effType, effNo, modeMask, fl, fl2, timer = it[0x24:0x2A]
        size, = struct.unpack('>f', it[0x2C:0x30])
        rot = struct.unpack('>3f', it[0x30:0x3C])
        out.append(dict(indice=i, area_no=r[0x36], at_no=0x80 + r[0x36], flag=r[0x34], tipo_area=r[0x35],
                        trigger=r[0x38], checkType=r[0x39], linkType=r[0x46], linkNo=r[0x47],
                        id=iid, num=num, flagNo=flagNo, findFlagNo=find, effType=effType, modeMask=modeMask,
                        flag_item=fl, flag2=fl2, size_mm=size, pos_mm=list(pos), ofs_mm=list(ofs), rot=list(rot),
                        seFind=it[0x3C], seDamage=it[0x3D], area_registro=R.area_data(r[4:0x34])))
    return out


def leer_ets():
    return R.ets(tag('ETS'))


def leer_esl():
    import re4_extract_emboscada_r100 as E
    return E.leer_esl()


def leer_itm():
    d = tag('ITM')
    _, oid, obin, otpl = struct.unpack('>4I', d[:16])
    n, = struct.unpack('>I', d[oid:oid + 4])
    ids = [struct.unpack('>H', d[oid + 4 + 8 * i:oid + 6 + 8 * i])[0] for i in range(n)]
    bofs = struct.unpack('>%dI' % n, d[obin + 4:obin + 4 + 4 * n])
    tofs = struct.unpack('>%dI' % n, d[otpl + 4:otpl + 4 + 4 * n])
    out = {}
    for i in range(n):
        b0 = obin + bofs[i]
        b1 = obin + bofs[i + 1] if i + 1 < n else otpl
        t0 = otpl + tofs[i]
        t1 = otpl + tofs[i + 1] if i + 1 < n else len(d)
        out[ids[i]] = (d[b0:b1], d[t0:t1])
    return out


# ------------------------------------------------------------------ exportes
def exportar_modelos(itm):
    os.makedirs(OUT + '/modelos', exist_ok=True)
    res = {}
    for iid, (bd, td) in itm.items():
        m = meshbin.parse(bd)
        tpl = gxtex.parse_tpl(td)
        nm = 'item_%02X_%s' % (iid, slug(nombre(iid)))
        ruta = '%s/modelos/%s.glb' % (OUT, nm)
        A.glb_estatico(ruta, [(nm, m, tpl, False)], nm)
        vs = [m.position(v[0]) for p in m.parts for t in p.triangles() for v in t]
        P = np.array(vs)
        res[iid] = dict(glb='modelos/%s.glb' % nm, triangulos=m.n_triangles(), partes_hueso=m.n_parts,
                        materiales=len(m.parts), texturas=[dict(w=t.width, h=t.height, fmt=t.fmt) for t in tpl]
                        if hasattr(tpl[0], 'width') else len(tpl),
                        caja_m=[rn(P.min(0) * MM), rn(P.max(0) * MM)], bytes_bin=len(bd), bytes_tpl=len(td))
    return res


def exportar_efm_brillo():
    """el modelo EFM del pilar de luz (registro 'effect model' Id 0xFF, Tex_id = id EFM 0x25 de core.das#1)."""
    eff = re4_eff.load_effs(R3 + '/extracted/etc/core.das', 1)[0]
    d, h = eff.d, eff.h
    n = struct.unpack_from('>I', d, h[5])[0]
    lista = [struct.unpack_from('>H', d, h[5] + 4 + 8 * i)[0] for i in range(n)]
    out = {}
    os.makedirs(OUT + '/fx', exist_ok=True)
    for i, idn in enumerate(lista):
        if idn != 0x25:
            continue
        eo = h[11] + struct.unpack_from('>I', d, h[11] + 4 + 4 * i)[0]
        _, om, ot, _, _ = struct.unpack_from('>5I', d, eo)
        m = meshbin.parse(d[eo + om:eo + ot])
        tpl = gxtex.parse_tpl(d[eo + ot:])
        A.glb_estatico(OUT + '/fx/efm25_pilar_brillo.glb', [('efm25_pilar_brillo', m, tpl, True)], 'efm25')
        vs = [m.position(v[0]) for p in m.parts for t in p.triangles() for v in t]
        P = np.array(vs)
        out = dict(glb='fx/efm25_pilar_brillo.glb', triangulos=m.n_triangles(), caja_m=[rn(P.min(0) * MM), rn(P.max(0) * MM)],
                   escala_en_juego='obj04 (esp_efm.cpp EfmSetObj04 / obj04.cpp): scaleXZ = Size_base_x*0.005 = 1.5, '
                                   'scaleY = Size_base_y*0.005 = 1.0 -> pilar de ~0.30 m de diametro y ~1.49 m de alto; '
                                   'color del modelo = Col_start rgb, transparencia invisible_factor = a/255 (a sube de 0 '
                                   'a Col_start.a en Col_max_cnt = 15 frames), gira Ang_plus.y = 3 grados/frame',
                   nota='modelo EFM 0x25 de core.das entrada 1 (EFF_CORE); sus texturas propias van en fx/efm25_*.png '
                        '(el registro lo tinta con Col_start, blend aditivo, Ang_plus y=3 grados/frame)')
    return out


def ui_examine():
    tabla = H.leer_tabla(CENT[26].data)
    eff = re4_eff.load_effs(R3 + '/extracted/etc/core.das', 25)[0]
    os.makedirs(OUT + '/ui', exist_ok=True)
    usados = sorted({r['tex'] for r in tabla if r['tex'] != 0xFF})
    cache = {}
    for t in usados:
        img = H.imagen(eff.tex[t], 0)
        cache[t] = img
        Image.fromarray(img, 'RGBA').save('%s/ui/examine_tex_%02X.png' % (OUT, t))
    ids = H.IdSys(eff.tex)
    ids.set(tabla, 0xFF, 0x13)
    # el color de la fila 0 y 6 lo anima la curva 2 (fade in); se dibuja el estado final (t = fin de curva)
    for _ in range(60):
        ids.mover()
    prev = H.render(ids.orden_dibujo(), lambda t, n: cache[t], escala=1, fondo=(90, 100, 80))
    prev.save(OUT + '/ui/examine_preview_640x480.png')
    # la pantalla con TRANSPARENCIA (lo que no tapa es el juego congelado): dos renders, sobre negro y sobre blanco
    negro = np.asarray(H.render(ids.orden_dibujo(), lambda t, n: cache[t], escala=1, fondo=(0, 0, 0)).convert('RGB'),
                       np.float32) / 255
    blanco = np.asarray(H.render(ids.orden_dibujo(), lambda t, n: cache[t], escala=1, fondo=(255, 255, 255))
                        .convert('RGB'), np.float32) / 255
    a = np.clip(1 - (blanco - negro).mean(2), 0, 1)
    rgb = np.clip(negro / np.maximum(a, 1e-3)[..., None], 0, 1)
    img = np.dstack([rgb, a])
    # (el panel de la derecha va espejado: rot y -180 en la tabla, el render 2D no lo aplica)
    img[:, 382:] = img[:, 382:][:, ::-1]
    Image.fromarray((img * 255 + 0.5).astype(np.uint8), 'RGBA').save(OUT + '/ui/examine_rgba_640x480.png')
    filas = []
    for r in tabla:
        filas.append({k: r[k] for k in ('fila', 'flags', 'id', 'no', 'nivel', 'padre', 'kind', 'tex', 'ancla', 'pos',
                                         'tam', 'col0', 'col1', 'rot', 'blend', 'tex_flag')} |
                     dict(curvas=r['curvas'], png=('ui/examine_tex_%02X.png' % r['tex']) if r['tex'] != 0xFF else None))
    return dict(fuente='core.das entrada 26 (pCore->ofs_78), clase IDC_EXAMINE 0x13, texturas de core.das entrada 25 '
                       '(ofs_74, IdTex del cockpit, ya cargadas en el juego)',
                coordenadas='pantalla virtual 640x480, origen al centro, Y hacia arriba (re4_extract_hud.a_pantalla: '
                            'px = 320 + x, py = 240 - y)',
                preview='ui/examine_preview_640x480.png (render por software con re4_extract_hud; fondo verde = juego)',
                unidades_marcadas={'0xF2': 'pos (0, 145): borde de arriba del cuadro donde se encaja el modelo',
                                   '0xF3': 'pos (0, -35): borde de abajo (ItemExamine::move centra el modelo entre '
                                           'ambos: dist = 240/tan(15 grados))',
                                   '0xF1': 'pos (-240, 150) 32x32 (no lo lee examine.cpp)'},
                filas=filas)


def efectos():
    eff = re4_eff.load_effs(R3 + '/extracted/etc/core.das', 1)[0]
    ests = {}
    for k in (0x21, 0x24, 0x25, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x46, 0x47, 0x4D):
        s = eff.est[k]
        recs = []
        for r in s['records']:
            recs.append(dict(Id='0x%02X' % r['Id'], kind=r['Kind'], tex='0x%02X' % r['Tex_id'], set_time=r['Set_time'],
                             tool_flg='0x%X' % r['Tool_flg'], pos=r['Pos'], speed=r['Speed'], ang=r['Ang'],
                             ang_plus=r['Ang_plus'], size=[r['Size_base_x'], r['Size_base_y']], r_size=r['R_size_base'],
                             size_plus=r['Size_plus'], d_size_plus=r['D_size_plus'], color=r['Col_start'],
                             col_d=r['Col_d'], col_max_cnt=r['Col_max_cnt'], col_start_cnt=r['Col_start_cnt'],
                             life_max=r['Life_max'], blend=r['Blend_type'], work32=r['Work32'],
                             espgen=dict(id=r['Espgen_id'], type=r['Espgen_type'], flg=r['Espgen_flg'],
                                         work8=r['Espgen_work8'], work16=r['Espgen_work16']) if r['Kind'] == 1 else None))
        ests['0x%02X' % k] = dict(head_pos=s['pos'], records=recs)
    # EFF_ITM: efectos del examen por item (EstSet(model, EFF_ITM, id) en ItemExamine::init)
    itm = re4_eff.load_effs(R3 + '/extracted/etc/core.das', 16)[0]
    return ests, sorted(itm.est.keys()), itm


def main():
    ita = leer_ita()
    ets = {e['no']: e for e in leer_ets()}
    esl = leer_esl()
    itm = leer_itm()
    modelos = exportar_modelos(itm)
    efm = exportar_efm_brillo()
    ui = ui_examine()
    ests, itm_ests, itm_eff = efectos()
    ETC_NOMBRE = {0: 'ETC_WINDOW00 (ventana)', 1: 'ETC_WOODBOX_SML (caja de madera chica, et0100.bin)',
                  2: 'ETC_WOODBOX_MDL (caja de madera mediana, et0200.bin)', 13: 'ETC_IRON_DOOR00 (puerta)'}
    colocados = []
    for r in ita:
        iid = r['id']
        pos_m = rn([c * MM for c in r['pos_mm']])
        e = dict(indice_ita=r['indice'], at_no='0x%02X' % r['at_no'], id='0x%X' % iid,
                 nombre=nombre(iid) if iid < 0x1000 else None, num=r['num'],
                 pos_m=pos_m, rot_rad=rn(r['rot']),
                 rot_aplicada=r['rot'][2] > 0,
                 effType_ita=r['effType'], flag2='0x%02X' % r['flag2'], findFlagNo=r['findFlagNo'],
                 radio_recoger_m=rn((r['size_mm'] or 1500.0) * 2 * MM, 3),
                 linkType=r['linkType'], linkNo=r['linkNo'])
        if iid < 0x1000:
            inf = info(iid)
            e.update(tipo_item=inf['type'], defNum=inf.get('defNum'), maxNum=inf.get('maxNum'))
            if iid == 0x78:
                e['pesetas'] = (r['num'] or 30) * 10
        if iid == 0x1001:
            e['nombre'] = 'ALEATORIO: RandomItemCk(0x10, ..., ctrl 0) (tabla de ganado)'
        if r['linkType'] == 1:
            en = esl[r['linkNo']]
            e['origen'] = dict(tipo='lo suelta un enemigo de la lista (emleon00.esl entrada 0x%02X)' % r['linkNo'],
                               enemigo_id='0x%02X' % en['id'], enemigo='cuervo (em23)' if en['id'] == 0x23 else '?',
                               enemigo_pos_m=en['pos_m'], hp=en['hp'],
                               como='SceAtSetEmItem -> cEm::setItem(id, num, flagNo, findFlagNo, effType); al morir '
                                    'EmSetDropItem -> SceAtCreateItemAt(pos del enemigo + 100 mm)')
            e['brillo_effType'] = r['effType'] or eff_col(iid)
        elif r['linkType'] == 2:
            et = ets.get(r['linkNo'])
            e['origen'] = dict(tipo='aparece al romper el objeto ETS no %d' % r['linkNo'],
                               objeto=ETC_NOMBRE.get(et['id'], 'etc id %d' % et['id']) if et else '?',
                               objeto_pos_m=rn([c * MM for c in et['pos']]) if et else None,
                               objeto_rot_y=rn(et['rot'][1]) if et else None,
                               como='sceAtSetItem: getRoomEtcBreak(linkNo) y bit0 de GetEtcFlgPtr; flag2 bit0 = 1 -> '
                                    'usa la pos del ITA (no la de la caja); con rot.z > 0 aplica rot.x/rot.y')
            e['brillo_effType'] = r['effType']
        else:
            e['origen'] = dict(tipo='colocado en el piso desde el arranque' if r['pos_mm'][1] > -7000 else
                               'ESCONDIDO (7.3 m bajo el piso, x = -99.7): no se puede alcanzar')
            e['brillo_effType'] = r['effType']
        e['brillo_est'] = GLOW_EST.get(e['brillo_effType'], 'sin brillo (effType 0)') if e['brillo_effType'] else \
            'sin brillo (effType 0: sceAtItemEffSet retorna sin efecto)'
        if iid < 0x1000:
            e['modelo'] = modelos.get(iid, {}).get('glb')
            e['examen'] = EXAM.get(iid)
            e['efecto_examen_EFF_ITM'] = ('0x%02X' % iid) if iid in itm_ests else None
        colocados.append(e)

    items_usados = sorted(itm)
    catalogo = {}
    for iid in items_usados:
        inf = info(iid)
        catalogo['0x%02X' % iid] = dict(nombre=nombre(iid), tipo_item=inf['type'], defNum=inf.get('defNum'),
                                        maxNum=inf.get('maxNum'), brillo_si_cae=eff_col(iid),
                                        examen=EXAM.get(iid), modelo=modelos[iid],
                                        efecto_examen_EFF_ITM=('0x%02X' % iid) if iid in itm_ests else None)
    msgs = {k: CORE[k]['plano'] for k in (0x11, 0x12, 0x13, 0x14, 0x15, 0x3E)}
    doc = dict(
        fuente='St1/r100.das: ITA (entrada 30, v0x105, %d registros de 0x9C), ITM (entrada 10, %d modelos), ETS (12); '
               'etc/emleon00.esl; etc/core.das (EFF 1 = EFF_CORE, EFF 16 = EFF_ITM, UWF 26 = IDC_EXAMINE, EFF 25 = '
               'texturas ID, MDT 6 = core, MDT 17 = nombres)' % (len(ita), len(itm)),
        coordenadas='mundo del cuarto en metros (mm * 0.001, Y arriba, sin cambio de ejes: igual que pos_m de '
                    're4_extract_salto_ventana.py / r100.json); rot en radianes (x, y); el juego aplica rot.x/rot.y '
                    'solo si rot.z > 0 (SceAtSetItemModel), rot.z es solo la bandera',
        colocaciones=colocados,
        catalogo_itm=catalogo,
        brillo=dict(
            regla='sceAtSetItem / SceAtCreateItemAt / sceAtItemEffSet (sce_at.cpp): effType del ITA; 0 = SIN brillo; '
                  'los items que caen de enemigos (SceAtCreateItemAt con effType -1/0/6) toman '
                  'sceAtCheckItemEffectCol(id): tipo item 1-4 -> 5, 6 -> 4, 0/5/7 -> 2, 8/12/otros -> 3, id 0x8C -> 8',
            effType_a_est=GLOW_EST, desaparicion=DISAPPEAR_EST,
            colores_pilar={'3 (est 0x2C)': [135, 182, 245], '5 (est 0x2F)': [225, 152, 155],
                           '4 (est 0x31)': [155, 202, 155], '2 (est 0x33)': [155, 155, 155]},
            est=ests, efm=efm,
            texturas='fx/tex_core/core_texXX_f0.png (re4_eff --png); EFM 0x25 en fx/efm25_pilar_brillo.glb',
            timer_caida='items soltados por enemigos (no persistentes): item.timer = 0x3D, baja 1 cada 30 Frame_cnt '
                        '(sce_at.cpp); en timer 6 cambia al est de desaparicion; en 0 se borra'),
        recoger=dict(
            disparo='trigger 8 (boton de accion) con actBtnKind 0x28 -> mensaje core 0x3E "%s"; area automatica '
                    'cilindro radio 2*size (size 0 = 1500 -> 3 m) alto 3000 desde pos.y - 2000 (SceAtItemAutoArea); '
                    'ademas SceAtItemHitCheck: linea de vista item -> Leon sin pared (EatMgr)' % msgs[0x3E],
            mensajes={('core:%d' % k): v for k, v in msgs.items()},
            mensaje_por_tipo={'2 (municion)': 'core 0x13 "Take the X(n)?" Yes/No (attr 0x211)',
                              '1/3/9 (armas, cuchillo, partes)': 'core 0x11 "Take the X?" Yes/No (attr 0x111)',
                              '6 (hierbas/spray)': 'core 0x12 "Take the X? Yes No Use" si falta vida, si no 0x11 (attr 0x411)',
                              '8 (dinero 0x78)': 'core 0x14 "You got #." con # = pesetas ganadas, sin opciones',
                              '0/4/5/7/12 (tesoro, llave...)': 'core 0x15 "You got the X." sin opciones (lo guarda directo)'},
            texto_pos='MesSet(no, x = 0x64 = 100, y = 0x129 - font_h - lineSpace, ...) en la pantalla de mensajes '
                      '512x384 de messageCamera (ver re4_extract_texto.py)',
            seleccion='m_sel 1 = Yes -> PutInCase (si no entra abre el maletin SS_OPEN_PZZL); 2 = No -> se deja; '
                      '3 = Use -> ItemMgr.use; B (Key.trg 0x40000000) cancela',
            examen='ItemExamine (examine.cpp): fondo = copia del framebuffer (store/render), modelo al origen centrado en '
                   'su bound, rot inicial exam_info (grados), gira pi/60 rad por frame (3 grados/frame = 90 grados/s a '
                   '30 fps; item 0x93 a la mitad) en Y del mundo (eje_rot0 0) o Y del modelo (1); camara fovy 30, '
                   'aspecto 4/3, distancia que encaja la diagonal del bound / exam_info.escala entre las unidades '
                   '0xF2/0xF3 del IDC_EXAMINE; 3 luces del LIT core.das 18..22 segun exam_info.luz; '
                   'EFF_ITM est = id del item si existe',
            pausa='SceUpCutStart, STA_ITEM_GET, pG->Disp_flg = -1, apaga DPF_COCKPIT / DPF_ESP / DPF_ID_SYSTEM / '
                  'DPF_MESSAGE, LightMgr.offScr(0x20); al salir borra los efectos ESP_CORE_KIND_ITEM del modelo',
            ui=ui),
        drops_aleatorios=dict(
            ganado_y_0x1001='RandomItemCk(em 0x10..0x20 / 0x1001): 20%% (r <= 19) -> 0x78 dinero, num = '
                            '5*(4d6+10) redondeado a decenas (x10 pesetas), 1/64 -> 990 (330 con 15/16); si no, 60%% '
                            'pasa (o racha de no-drop), luego municion por GetDropBullet si GetBulletPoint < 30 '
                            '(50%%) o < 150, hierbas/spray (5, 6, 0x19) si GetRecoveryPoint <= 1 (3 en dificultad <= 2)',
            cuervo_0x23='RandomItemCk 0x23: siempre 0x78 con num = (rnd%3)*10 + 20 (200-400 pesetas); 1/4 de las veces '
                        '100/200 o 400/500',
            nota='ITA 0..8 (escondidos bajo el piso) + el pack ITM listan exactamente los ids que pueden salir de '
                 'GetDropBullet / RandomItemCk en r100 (el ITM solo trae modelos de esos ids)'),
    )
    with open(OUT + '/items_r100.json', 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    for c in colocados:
        print(c['indice_ita'], c['id'], c['nombre'], c['num'], c['pos_m'], c['origen']['tipo'], c['brillo_effType'])


if __name__ == '__main__':
    main()
