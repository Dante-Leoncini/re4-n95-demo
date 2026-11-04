#!/usr/bin/env python3
"""
Arma re4_personajes.w3d: la LIBRERIA DE PERSONAJES de la demo r100. Un .w3d comun cuyos PREFABS usan los niveles con
proxies W3D (make_r100_w3d.py, libreria_r100.py): nada de esto se copia adentro del nivel; N proxies del mismo
personaje comparten mallas (.w3db), animsets (.w3da), materiales y texturas.

  Prefab "Leon"           armature Leon (119 huesos, clips de combate + la radio) con scripts/leon.lua
    Leon_cuerpo             malla skinneada (opaco + transparente)
    Leon_pistola            la pistola RIGIDA (Child Of a la mano; oculta en juego, la usa la cinematica del nivel)
    Leon_cuchillo, Leon_laser   (ocultos, Child Of a la mano)
    Leon_fx_r1..r8          los 8 records del efecto del disparo (Particulas, Child Of a la boca del arma)
    Leon_fx_luz             la luz del fogonazo
    Pistola                 la pistola CON ESQUELETO (corredera y cargador, su animset) + Pistola_malla
    Leon_radio              la radio de la llamada (Child Of a la mano izquierda, oculta)
    Leon_hitbox             el HITBOX del cuerpo (etiqueta "jugador"): con el entra a las zonas del nivel
  Prefab "Ganado_juego"   el aldeano de la casa (el hacha en la mano izquierda) con scripts/ganado.lua (la IA)
  Prefabs "Ganado_eNN"    los 7 aldeanos de la emboscada, CADA VARIANTE un prefab (su modelo, su arma, sus clips) con
                          scripts/ganado_eNN.lua (ganado.lua + su RAIZ + su CONF). Lo que despierta a cada uno y su
                          vida son propiedades del script: el nivel las cambia en el override de su proxy.
  + los sonidos de leon.lua / ganado.lua y las texturas de los efectos del disparo (un script de la libreria nombra
    primero lo de SU libreria: sonido("sonidos/x.wav") lee lib:re4_personajes/sonidos/x.wav).

La escena de la libreria es un MUESTRARIO: una instancia de cada prefab en fila (sirve para mirarla en el editor).
Los prefabs tienen el objeto raiz en el origen: el que los UBICA es la instancia / el proxy.

Pasos (todo lo guarda el PROPIO Whisk3D, en su formato):
  1. whisk3d --script: importa los glb (Leon de combate + radio, pistola, ganado de juego, 7 aldeanos), renombra,
     guardarw3d
  2. se edita el proyecto.json: constraints, efectos, scripts con sus tablas, hitbox, sonidos (make_re4_w3d.py,
     combate_r100.py, emboscada_r100.py, codec_r100.py: lo mismo que antes se hacia adentro del nivel)
  3. whisk3d --script: abrirw3d + "Create Prefab" (prefabcrear) de cada personaje + guardarw3d: el motor escribe
     prefabs/<x>.w3dp, mallas/*.w3db y animaciones/*.w3da

Uso:  python3 make_personajes_w3d.py [-o re4_personajes.w3d] [--whisk3d RUTA]
"""
import argparse
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_re4_w3d as base  # noqa: E402
import combate_r100  # noqa: E402
import emboscada_r100  # noqa: E402
import codec_r100  # noqa: E402
import evento_s03  # noqa: E402
import libreria_r100  # noqa: E402

GLB_RADIO = os.path.join(HERE, 'out', 'r100_intro', 'radio.glb')
SEP = 1.6        # metros entre personajes en el muestrario
CARPETAS = {'Leon': 'Personajes', 'Ganado_juego': 'Personajes/Aldeanos'}   # (cosmetico: la vista de la libreria)


LEON_GLB = None   # (--leon: otro glb de Leon de combate, ej. el simplificado del N95)


def glb_leon():
    """Leon de COMBATE (atlas completo, clips de danio / muerte / herido) + el clip "radio": un solo glb"""
    sys.path.insert(0, os.path.join(HERE, 'tools_r100'))
    import unir_clips
    glb = LEON_GLB or combate_r100.GLB_LEON
    con_radio = os.path.join(os.path.dirname(glb), 'leon_combate_radio.glb')
    radio = os.path.join(HERE, 'out', 'r100_intro', 'leon_radio.glb')
    if not os.path.isfile(con_radio) or os.path.getmtime(con_radio) < max(os.path.getmtime(glb),
                                                                          os.path.getmtime(radio)):
        unir_clips.unir(con_radio, [glb, radio])
    return con_radio


def prefabs():
    """los nombres de los prefabs, en orden (Leon, el de la casa, los de la emboscada)"""
    return ['Leon', 'Ganado_juego'] + [emboscada_r100.nombre(e) for e in emboscada_r100.entradas()]


def lineas_importar():
    g = glb_leon()
    bl = os.path.splitext(os.path.basename(g))[0]
    out = ['selobj Cubo', 'delete', 'importgltf ' + g, 'activename %s_rig' % bl, 'objname Leon']
    for k, nom in enumerate(base.MALLAS):
        out += ['activename ' + (bl if k == 0 else '%s.%03d' % (bl, k)), 'objname ' + nom]
    out += combate_r100.lineas_importar_pistola()
    out += ['importgltf ' + GLB_RADIO, 'activename radio', 'objname Leon_radio']
    out += combate_r100.lineas_importar_ganado()
    out += emboscada_r100.lineas_importar_aldeanos()
    return out


def _todos(lista):
    for o in lista:
        yield o
        yield from _todos(o.get('hijos', []))


def editar_libreria(w3d):
    """lo que antes se le hacia a los personajes adentro del nivel: la pistola con esqueleto y la radio en Leon, su
    hitbox, los scripts con sus tablas (RAIZ, FXC, VOL, VENTANAS, CONF) y los sonidos; el muestrario en fila"""
    with zipfile.ZipFile(w3d) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    datos = dict((i.filename, d) for i, d in entradas)
    proy = json.loads(datos['proyecto.json'])
    col = next(o for o in proy['escena']['objetos'] if o.get('tipo') == 'coleccion')
    combate_r100.poner_pistola(col['hijos'])          # Pistola: hija de Leon, Child Of a la mano derecha
    codec_r100.radio_prop(proy)                        # Leon_radio: hija de Leon, Child Of a la izquierda, oculta
    por_nombre = dict((o.get('nombre'), o) for o in _todos(col['hijos']))
    leon = por_nombre['Leon']
    leon['hijos'] = [h for h in leon.get('hijos', []) if h.get('nombre') != 'Leon_hitbox'] + [evento_s03.hitbox_leon()]
    extra = {}
    datos['scripts/leon.lua'] = combate_r100.lua_leon().encode('utf-8')
    gj = por_nombre['Ganado_juego']
    gj['scripts'] = [{'archivo': 'scripts/ganado.lua'}]
    datos['scripts/ganado.lua'] = combate_r100.lua_ganado().encode('utf-8')
    for e in emboscada_r100.entradas():
        o = por_nombre[emboscada_r100.nombre(e)]
        ruta = emboscada_r100.ruta_lua(e)
        o['scripts'] = [{'archivo': ruta}]
        datos[ruta] = emboscada_r100.lua_aldeano(e).encode('utf-8')
    # el MUESTRARIO: cada personaje en fila mirando a la camara (Create Prefab deja la instancia en ese lugar y la
    # raiz del prefab en el origen)
    for k, n in enumerate(prefabs()):
        o = por_nombre[n]
        o['pos'], o['rot'], o['visible'] = [round(k * SEP, 3), 0, 0], [0, 0, 0], True
    for o in col['hijos']:
        if o.get('tipo') == 'camara':
            o['pos'], o['rot'] = [len(prefabs()) * SEP / 2.0, 1.4, 9.0], [-4.0, 0, 0]
    # los sonidos de los personajes (los de make_re4_w3d.SONIDOS ya estan: no se pisan, como en el nivel de antes)
    extra.update(combate_r100.sonidos_personajes())
    datos['proyecto.json'] = json.dumps(proy, ensure_ascii=False).encode('utf-8')

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
        for nombre, ruta in sorted(extra.items()):
            if nombre not in nombres:
                z.write(ruta, nombre, zipfile.ZIP_DEFLATED)
    os.replace(tmp, w3d)


def carpetas(w3d):
    """la carpeta (cosmetica) de cada prefab en el registro: Personajes / Personajes/Aldeanos"""
    with zipfile.ZipFile(w3d) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    datos = dict((i.filename, d) for i, d in entradas)
    proy = json.loads(datos['proyecto.json'])
    for f in proy.get('prefabs', []):
        f['carpeta'] = CARPETAS.get(f['nombre'], 'Personajes/Aldeanos')
    datos['proyecto.json'] = json.dumps(proy, ensure_ascii=False, indent=2).encode('utf-8')
    tmp = w3d + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        for info_z, _ in entradas:
            zi = zipfile.ZipInfo(info_z.filename, date_time=info_z.date_time)
            zi.compress_type = info_z.compress_type
            zi.external_attr = info_z.external_attr
            z.writestr(zi, datos[info_z.filename])
    os.replace(tmp, w3d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--output', default=libreria_r100.ARCHIVO)
    ap.add_argument('--whisk3d', default=base.WHISK3D_LOCAL if os.path.isfile(base.WHISK3D_LOCAL) else 'whisk3d')
    ap.add_argument('--leon', default=None, help='otro glb de Leon de combate (default: out/combate/leon_combate.glb)')
    ap.add_argument('--n95', action='store_true',
                    help='los modelos simplificados del N95 (n95_glb.REGLAS: Leon ~1.700 triangulos, aldeanos ~800)')
    args = ap.parse_args()
    global LEON_GLB
    LEON_GLB = os.path.abspath(args.leon) if args.leon else None
    out = os.path.abspath(args.output)
    importar = lineas_importar()
    if args.n95:
        import n95_glb
        importar = n95_glb.simplificadas(importar)
    base.correr_script(args.whisk3d, importar + ['guardarw3d ' + out])
    base.editar_proyecto(out)      # Leon: constraints de las armas, efectos del disparo, luz, leon.lua, sonidos
    editar_libreria(out)
    # "Create Prefab" de cada personaje: el motor muda el subarbol a prefabs/<x>.w3dp y deja la instancia
    lineas = ['abrirw3d ' + out]
    for n in prefabs():
        lineas += ['selobj ' + n, 'prefabcrear nombre ' + n]
    lineas += ['guardarw3d ' + out]
    base.correr_script(args.whisk3d, lineas)
    carpetas(out)
    salida = base.correr_script(args.whisk3d, ['abrirw3d ' + out, 'guardarw3d ' + out, 'raizinfo', 'scene'])
    print('\n'.join(l for l in salida.splitlines() if '[raizinfo]' in l or '[scene]' in l))
    print(f'-> {out} ({os.path.getsize(out) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
