#!/usr/bin/env python3
"""
Arma re4.w3d: un proyecto de Whisk3D con Leon listo para abrir con doble click.

  Leon           armature (119 huesos) con las animaciones de la demo
    Leon_cuerpo    malla skinneada, 2 mesh parts (opaco + transparente), atlas unico
    Leon_pistola   malla RIGIDA con constraint Child Of -> Leon / hueso_010 (la mano derecha)
    Leon_cuchillo  idem, OCULTA (visible false)

Las armas son hijas REALES del armature (mover a Leon las mueve) y ademas siguen a la mano por el
Child Of: una matriz por frame en vez de skinnear cada vertice. Sus vertices ya vienen en el espacio
del hueso (re4_extract_leon.py), asi que la inversa del constraint es la identidad.

Pasos (todo lo guarda el PROPIO Whisk3D, en su formato):
  1. whisk3d --script: importgltf out/leon/leon.glb, borra el cubo, renombra, guardarw3d
  2. se edita el proyecto.json: constraints de las armas, cuchillo oculto, camara/vista sobre Leon
  3. whisk3d --script: abrirw3d + guardarw3d (el archivo queda en el formato canonico) + la escena

Uso:  python3 make_re4_w3d.py [-o re4.w3d] [--whisk3d RUTA]
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
GLB = os.path.join(HERE, 'out', 'leon', 'leon.glb')
# el build local de Whisk3D (tiene el Child Of y el fix de los rigs glTF); si no, el instalado
WHISK3D_LOCAL = os.path.normpath(os.path.join(HERE, '..', '..', 'Whisk3D', 'platform', 'linux', 'build', 'whisk3d'))

# orden de las mallas en el glb (re4_extract_leon.py) -> el importador las nombra leon, leon.001, ...
MALLAS = ['Leon_cuerpo', 'Leon_pistola', 'Leon_cuchillo', 'Leon_laser']
ARMAS = ('Leon_pistola', 'Leon_cuchillo', 'Leon_laser')
HUESO_MANO = 'hueso_010'
OCULTOS = {'Leon_cuchillo', 'Leon_laser'}
SONIDOS = ['disparo_pistola.wav', 'pistola_desenfundar.wav', 'casquillo_suelo.wav', 'pistola_vacia_click.wav',
           'paso_tierra_caminar_izq.wav', 'paso_tierra_caminar_der.wav', 'paso_tierra_correr_izq.wav',
           'paso_tierra_correr_der.wav', 'cuchillo_tajo.wav'] + \
          ['ropa_caminar_%d.wav' % i for i in range(5)] + ['ropa_correr_%d.wav' % i for i in range(5)]
MIRA = (0.0, 0.95, 0.0)    # punto al que miran la camara y el viewport (pecho de Leon)
DIST = 3.6


def correr_script(whisk3d, lineas):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write('\n'.join(lineas) + '\n')
        path = f.name
    try:
        r = subprocess.run([whisk3d, '--script', path], capture_output=True, text=True, timeout=600)
    finally:
        os.remove(path)
    salida = r.stdout + r.stderr
    if r.returncode != 0:
        sys.exit(f'whisk3d --script fallo:\n{salida[-3000:]}')
    return salida


def child_of(arm):
    return {'tipo': 'childOf', 'nombre': 'Child Of', 'influencia': 100, 'fuente': 'objeto', 'objeto': arm,
            'ejes': [True, True, True], 'hueso': HUESO_MANO, 'hereda': [True, True, True],
            'inversa': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}


# ---------------------------------------------------------------------------------------------------
#  EFECTOS DEL DISPARO: se TRADUCEN los records del est 0 de wep02 (decodificados por tools/re4_eff.py en
#  out/efectos/wep02_est.json) a emisores Particulas de Whisk3D, uno por record. Cada record nace en el
#  espacio de la parte 3 del arma (la boca), que en reposo esta en (-289.56, -24, 83.57) mm del hueso de la
#  mano, sin rotacion (el cañon apunta a -X): el emisor es hijo de Leon con Child Of a la mano, en esa
#  posicion + la del record. El juego integra POR FRAME a 30 fps; Whisk3D va por SEGUNDO:
#     velocidad mm/f -> m/s (x30/1000)   aceleracion mm/f^2 -> m/s^2 (x900/1000)
#     D_speed (por frame) -> arrastre = D^30      Col_d.a -> alphaDecae = k^30
#     size += plus; plus *= D  -> crecimiento = plus*30*(-ln D)/(1-D), freno = D^30  (la misma curva)
#     muere con alpha < 4 (de 255) -> alphaMuerte = 4/255
# ---------------------------------------------------------------------------------------------------
import json as _json
BOCA = (-289.56, -24.0, 83.57)       # mm, parte 3 del arma en el espacio del hueso de la mano
F = 30.0
TEX_FX = {0x1E: 'fx_humo.png', 0x1F: 'fx_humo2.png', 0x22: 'fx_fogonazo.png'}


def records_disparo():
    d = _json.load(open(os.path.join(HERE, 'out', 'efectos', 'wep02_est.json')))
    return d['est']['0x00']['records']


def emisor_de_record(i, r):
    v3 = lambda v, k: [round(c * k, 6) for c in v]
    D = r['D_size_plus']
    plus = r['Size_plus']
    if abs(plus) < 1e-4:
        crec, freno = 0.0, 1.0
    elif D >= 0.9999:
        crec, freno = plus * F, 1.0
    else:
        crec, freno = plus * F * (-math.log(D)) / (1.0 - D), D ** F
    o = {'tipo': 'particulas', 'nombre': 'Leon_fx_r%d' % i, 'rot': [0, 0, 0], 'escala': [1, 1, 1],
         'pos': [round((BOCA[k] + r['Pos'][k]) / 1000.0, 5) for k in range(3)],
         'textura': ('texturas/' + TEX_FX[r['Tex_id']]) if r['Tex_id'] in TEX_FX else '',
         'cantidad': 0, 'vida': round(r['Life_max'] / F, 4), 'tam': r['Size_base_x'] / 1000.0,
         'vel': 0, 'dispersion': 0, 'gravedad': 0,
         'mezcla': 3 if r['Blend_type'] == 1 else 1,   # bl[1] del juego: src*srcA + dst = AddAlpha
         'color': [round(c / 255.0, 4) for c in r['Col_start']], 'desvanecer': False, 'activo': True,
         'variacion': 0, 'turbulencia': 0,
         'velLocal': v3(r['Speed'], F / 1000.0), 'velAzar': v3(r['R_speed'], F / 1000.0),
         'posAzar': v3(r['R_pos'], 1 / 1000.0), 'aceleracion': v3(r['Speed_plus'], F * F / 1000.0),
         'arrastre': round(r['D_speed'] ** F, 6), 'crecimiento': round(crec, 5), 'frenoCrecimiento': round(freno, 6),
         'alphaDecae': round(r['Col_d'][3] ** F, 8), 'alphaMuerte': round(4 / 255.0, 5),
         'rotInicial': r['Ang'][2], 'rotAzar': r['R_ang'][2],
         'velRotacion': r['Ang_plus'][2] * F, 'velRotAzar': r['R_ang_plus'][2] * F, 'giroSignoAzar': False,
         'constraints': [child_of('Leon')]}
    if r['Tex_id'] == 0x22:            # starburst: 2 cuadros a 30 fps y muere al terminar
        o.update(flipCuadros=2, flipCols=2, flipFilas=1, flipFps=F, flipUnaVez=True)
    if r['Kind'] == 1 and r['Id'] == 3:   # espgen -> esp03: chispas como LINEAS (estela de 4 puntos)
        o.update(forma='linea', estelaPuntos=4, estelaPaso=round(1 / F, 5), grosorLinea=1)
    return o


def fx_disparo():
    """[(objeto particulas, cuantas por disparo)] de los records 1..8 (el 0 es la luz)."""
    out = []
    for i, r in enumerate(records_disparo()):
        if r['Kind'] == 0 and r['Id'] == 0x11:
            continue                       # luz puntual: va aparte (luz_disparo)
        n = r['Espgen_work8'][1] + 1 if r['Kind'] == 1 else 1   # espgen: rafaga de 3
        out.append((emisor_de_record(i, r), n))
    return out


def luz_disparo():
    # rec 0: luz puntual de 1-2 frames, (255, 205, 165) x ~0.5, en la boca
    return {'tipo': 'luz', 'nombre': 'Leon_fx_luz', 'visible': False,
            'pos': [round((BOCA[0] - 30) / 1000.0, 5), round((BOCA[1] - 5.7) / 1000.0, 5), round((BOCA[2] - 20) / 1000.0, 5)],
            'rot': [0, 0, 0], 'escala': [1, 1, 1], 'color': [0.6, 0.48, 0.39],   # (255, 205, 165) x ~0.6 como el record 0 del juego
            # se apaga con la distancia como la del juego (cuadratica, radio 4 m): ilumina al personaje y lo cercano
            'atenuacion': [0.6, 0.0, 5.0], 'constraints': [child_of('Leon')]}


def editar_proyecto(w3d):
    with zipfile.ZipFile(w3d) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    datos = dict((i.filename, d) for i, d in entradas)
    proy = json.loads(datos['proyecto.json'])

    def objetos(lista):
        for o in lista:
            yield o
            yield from objetos(o.get('hijos', []))
    vistos = set()
    for o in objetos(proy['escena']['objetos']):
        nom = o.get('nombre')
        if nom in ARMAS:
            o['constraints'] = [child_of('Leon')]
            vistos.add(nom)
        if nom in OCULTOS:
            o['visible'] = False
        if o.get('tipo') == 'camara':
            # misma direccion de vista que la camara por defecto, pero centrada en Leon
            d = o['pos']
            n = math.sqrt(sum(c * c for c in d))
            o['pos'] = [round(MIRA[i] + d[i] / n * DIST, 4) for i in range(3)]
        if o.get('tipo') == 'luz':
            o['pos'] = [1.5, 2.8, 2.5]
        if nom == 'Leon' and o.get('tipo') == 'armature':
            o.setdefault('hijos', []).extend([e for e, n in fx_disparo()] + [luz_disparo()])
            o['scripts'] = [{'archivo': 'scripts/leon.lua'}]
            vistos.add('Leon')
    for m in proy.get('materiales', []):
        if m.get('nombre') == 'Leon_laser':
            m['lineas'] = True
            m['grosorLinea'] = 2
    vistos.discard('Leon')
    if vistos != set(ARMAS):
        sys.exit(f'proyecto.json: faltan las armas (encontre {sorted(vistos)})')
    lay = proy.get('layout', '')
    # el layout guarda el pivote con el cruce historico posY<->pivot.z / posZ<->pivot.y (GuardarW3D.cpp):
    # la ALTURA (pivot.y) va en posZ
    lay = re.sub(r'posZ: [-0-9.e]+', f'posZ: {MIRA[1]}', lay, count=1)
    lay = re.sub(r'orbitDistance: [-0-9.e]+', f'orbitDistance: {DIST}', lay, count=1)
    # el overlay del esqueleto (lineas azules encima de todo) no deja ver al personaje: apagado en el
    # viewport 3D (Overlays > Objects > Armature, se puede volver a prender)
    # (idem las lineas de parentesco: los emisores, la luz, el laser y las armas cuelgan de Leon -cuyo origen
    # esta en el piso- pero se ven en la mano por el Child Of, y las lineas bajaban de la mano al piso)
    if 'showArmature' not in lay:
        lay = re.sub(r'(orbitDistance: [-0-9.e]+\n)',
                     r'\1        showArmature: false\n        ShowRelantionshipsLines: false\n', lay, count=1)
    proy['layout'] = lay
    # abre sin nada seleccionado (sino queda activo el ultimo importado: el cuchillo oculto)
    if isinstance(proy.get('sesion'), dict):
        proy['sesion']['activo'] = ''
        proy['sesion']['seleccion'] = []
    # el Play del editor sin cache de juego (rewind): no graba snapshots por frame, corre fluido (N95)
    proy['cacheJuego'] = False
    datos['proyecto.json'] = json.dumps(proy, ensure_ascii=False).encode('utf-8')

    tmp = w3d + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        for info, _ in entradas:
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type   # mimetype sigue primero y STORED
            zi.external_attr = info.external_attr
            z.writestr(zi, datos[info.filename])
        # lo que no viene del glb: el script, los sonidos (version N95) y las texturas de los efectos
        # leon.lua con su tabla de RAIZ (el avance de cada clip) inyectada, como en la escena r100
        if 'scripts/leon.lua' not in datos:
            import combate_r100
            z.writestr('scripts/leon.lua', combate_r100.lua_con_raiz(os.path.join(HERE, 'lua', 'leon.lua'),
                                                                     combate_r100.raiz_leon()).encode('utf-8'),
                       zipfile.ZIP_DEFLATED)
        extra = []
        for f in SONIDOS:
            extra.append(('sonidos/' + f, os.path.join(HERE, 'out', 'sonidos', 'n95', f)))
        for t in sorted(set(TEX_FX.values())):
            extra.append(('texturas/' + t, os.path.join(HERE, 'out', 'leon', 'fx', t)))
        puestos = set(datos) | {'scripts/leon.lua'}
        for nombre, ruta in extra:
            if nombre in puestos:
                continue
            puestos.add(nombre)
            z.write(ruta, nombre, zipfile.ZIP_DEFLATED)
    os.replace(tmp, w3d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--output', default=os.path.join(HERE, 're4.w3d'))
    ap.add_argument('--whisk3d', default=WHISK3D_LOCAL if os.path.isfile(WHISK3D_LOCAL) else 'whisk3d')
    args = ap.parse_args()
    out = os.path.abspath(args.output)

    if not os.path.isfile(GLB):
        subprocess.check_call([sys.executable, os.path.join(HERE, 're4_extract_leon.py'), '-o', GLB])

    lineas = ['selobj Cubo', 'delete', f'importgltf {GLB}', 'activename leon_rig', 'objname Leon']
    for k, nom in enumerate(MALLAS):
        lineas += [f'activename {"leon" if k == 0 else f"leon.{k:03d}"}', f'objname {nom}']
    lineas += [f'guardarw3d {out}']
    correr_script(args.whisk3d, lineas)
    editar_proyecto(out)
    salida = correr_script(args.whisk3d, [f'abrirw3d {out}', f'guardarw3d {out}', 'scene'])
    print('\n'.join(l for l in salida.splitlines() if '[scene]' in l))
    print(f'-> {out}')


if __name__ == '__main__':
    main()
