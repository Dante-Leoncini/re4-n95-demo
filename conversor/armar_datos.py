"""Arma datos/ (lo que lee el juego del N95) desde lo de re3_w3d: el nivel re4_r100_full.w3d, su libreria de
personajes re4_personajes.w3d y lo extraido del disco en out/ (el mapa ya simplificado para el telefono).

    python conversor/armar_datos.py [--re3 ../re3_w3d] [--sonidos]

Sale en datos/:
  intro.txn, fuente.txn  la intro de Whisk3D y la letra (copiadas de las otras demos)
  texturas.txn           TODAS las texturas (16 bits con mipmaps) en el orden de su indice
  mundo.bin              el escenario (mundo.py)
  colision.bin           el piso y las paredes del juego (los triangulos; la grilla la arma el juego)
  *.mdl                  los personajes, vehiculos y la utileria (modelos.py)
  tablas.bin             los numeros de los scripts (la raiz de cada clip, las ventanas, los eventos...)
"""
import argparse
import io
import json
import math
import os
import shutil
import sys

import numpy as np
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import binario  # noqa: E402
import cine  # noqa: E402
import interfaz  # noqa: E402
import efectos_conv  # noqa: E402
import items  # noqa: E402
import objetos  # noqa: E402
import ruta  # noqa: E402
import fuentes  # noqa: E402
import modelos  # noqa: E402
import mundo  # noqa: E402
import sonidos  # noqa: E402
import texturas_n95  # noqa: E402
import w3dt  # noqa: E402

RAIZ = os.path.normpath(os.path.join(AQUI, '..'))
DATOS = os.environ.get('RE4N95_DATOS') or os.path.join(RAIZ, 'datos')
# las texturas de los vehiculos con vidrios (alfa intermedio): siempre RGBA4444
VIDRIOS_ALFA = {'obm1a00_atlas', 'obm2d00_atlas'}


class Tablas:
    """tablas.bin: 'TAB1', u32 n; por tabla: char nombre[32], u32 n, f32 v[n]"""

    def __init__(self):
        self.t = {}

    def poner(self, nombre, valores):
        assert len(nombre) < 32, nombre
        self.t[nombre] = np.asarray(valores, np.float32).reshape(-1)

    def guardar(self, ruta):
        w = binario.Escritor().b(b'TAB1').s('I', len(self.t))
        for k in sorted(self.t):
            v = self.t[k]
            w.nombre(k, 32).s('I', len(v)).b(v.tobytes())
        return w.guardar(ruta)


class Datos:
    def __init__(self, re3):
        self.re3 = re3
        self.nivel = fuentes.Proyecto(os.path.join(re3, 're4_r100_full.w3d'))
        self.pers = fuentes.Proyecto(os.path.join(re3, 're4_personajes.w3d'))
        self.tex = texturas_n95.Texturas(tope=512)
        self.tablas = Tablas()

    # ------------------------------------------------------------------ texturas de los materiales
    def tex_material(self, proy, mj, mitad=False, tope=None):
        ruta = mj.get('textura', '')
        if not ruta:
            return 0xFFFFFFFF
        fl = mj.get('flags', {})
        nombre = os.path.basename(ruta)[:-4] + ('_m' if mitad else '')
        if nombre in self.tex.indice:
            return self.tex.indice[nombre]
        datos = proy.leer(ruta) if proy.existe(ruta) else None
        if datos is None:
            otro = self.pers if proy is self.nivel else self.nivel
            datos = otro.leer(ruta)
        img = Image.open(io.BytesIO(datos))
        # (los vidrios de los vehiculos: poca superficie de la textura con alfa intermedio; recortados en un bit
        # quedarian opacos)
        formato = w3dt.RGBA4444 if os.path.basename(ruta)[:-4] in VIDRIOS_ALFA else None
        return self.tex.agregar(nombre, img, repetir=fl.get('repetir', True), filtro=fl.get('filtrado', True),
                                mitad=mitad, tope=tope, formato=formato)

    # ------------------------------------------------------------------ el mapa y la colision
    def armar_mundo(self):
        piezas, chunks, mats, info = mundo.leer(os.path.join(self.re3, 'out', 'r100_n95'), self.tex)
        mundo.armar(piezas, chunks, mats, info, os.path.join(DATOS, 'mundo.bin'))

    def armar_colision(self):
        mallas = []
        for nombre, obj in (('suelo', 'r100_col_suelo'), ('pared', 'r100_col_pared'), ('camion', 'r100_col_camion'),
                            ('puerta', 'r100_puerta')):
            o = self.nivel.objetos[obj]
            m = self.nivel.malla(o['malla'])
            pos = m.pos.copy()
            if nombre == 'puerta':
                # la puerta queda TRABADA ABIERTA toda la demo (r100.lua: 90 grados en Y, bisagra en el origen)
                a = math.radians(90)
                c, s = math.cos(a), math.sin(a)
                R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
                pos = pos @ R.T
            pos = pos + np.array(o.get('pos', [0, 0, 0]))
            mallas.append((nombre, pos[m.idx.reshape(-1, 3)]))
        # la ruta del piloto de las pruebas: del arranque a la ventana, la casa, afuera y la salida del cuarto
        try:
            r = ruta.camino(mallas[0][1].reshape(-1, 9), np.concatenate([mallas[1][1], mallas[3][1]]).reshape(-1, 9),
                            [(-99.7, -0.5, -1.3), (-76.0, 0.0, -16.0), (-77.7, 0.9, -28.5), (-80.0, 0.9, -35.0),
                             (-77.7, 0.9, -28.5), (-60.0, 0.0, -15.0), (22.0, 1.8, -13.5)])
            self.tablas.poner('ruta.demo', [c for p in r for c in p])
            print('ruta de las pruebas: %d puntos' % len(r))
        except ValueError as e:
            print('ruta de las pruebas: %s' % e)
        w = binario.Escritor().b(b'COL1').s('I', len(mallas))
        for nombre, tris in mallas:
            w.nombre(nombre, 16).s('I', len(tris)).b(tris.astype(np.float32).tobytes())
        w.guardar(os.path.join(DATOS, 'colision.bin'))
        print('colision.bin: ' + ', '.join('%s %d' % (n, len(t)) for n, t in mallas))

    # ------------------------------------------------------------------ un armature a .mdl
    def modelo(self, proy, arm_nombre, archivo, mallas, clips=None, mitad=False, tope=None, renombrar=None,
               cuadros_max=None, bajo=0):
        """mallas: [(objeto malla, proporcion, opciones)]; clips: None = los del armature, o [(nombre, k, lazo)]"""
        arm = proy.objetos[arm_nombre]
        aset = proy.animset(arm['anims'])
        M = modelos.Modelo(archivo, arm, aset, self.tex)
        for nombre_obj, prop, op in mallas:
            o = proy.objetos[nombre_obj]
            malla = proy.malla(o['malla'])
            M.agregar_malla(malla, proy.materiales, lambda mj: self.tex_material(proy, mj, mitad, tope), prop,
                            error=op.get('error', 0.02), permisivo=op.get('permisivo', False),
                            sin_formas=op.get('sin_formas', False), rigida_en=op.get('hueso'),
                            forma_min=op.get('forma_min', 0.0))
        tabla, cl = aset
        if clips is None:
            for k in arm.get('clips', []):
                nom = cl[k].nombre
                if renombrar:
                    nom = renombrar(nom)
                M.agregar_clip(nom, k, False)
        else:
            for nom, k, lazo in clips:
                M.agregar_clip(nom, k, lazo)
        self.nombres_clips = [c[0] for c in M.clips]
        t = M.guardar(os.path.join(DATOS, archivo), cuadros_max)
        if bajo:
            M.guardar_bajo(os.path.join(DATOS, archivo[:-4] + '_b.mdl'), bajo)
        return t

    # ------------------------------------------------------------------ el ganado
    def armar_ganado(self):
        p = self.pers
        variantes = [('ganado', 'Ganado_juego', 'ganado.lua', [('Ganado_j_cuerpo', 0.5), ('Ganado_j_cara', 0.6),
                                                               ('Ganado_j_ojos', 1.0)], False)]
        for e in ('e03', 'e04', 'e05', 'e12', 'e13', 'e26', 'e27'):
            variantes.append(('ganado_' + e, 'Ganado_' + e, 'ganado_%s.lua' % e,
                              [('Ganado_%s_cuerpo' % e, 0.4, {'error': 0.04})], True))
        ataques = {'ataque_hacha': 0, 'ataque': 1, 'ataque_horca_alto': 2}
        # (los clips que pide la IA: enemigos.cpp)
        usados = {'quieto', 'caminar_hacha', 'caminar_arma', 'correr', 'ataque_hacha', 'ataque', 'ataque_horca_alto',
                  'morir', 'desplomarse', 'caer_muerto', 'caer_muerto_b', 'caer_adelante', 'caer_adelante_b',
                  'caer_atras', 'caer_atras_b', 'caido_golpe_boca_arriba', 'caido_golpe_boca_abajo', 'caer_aturdido',
                  'caer_aturdido_atras', 'golpe_espalda', 'levantarse_boca_arriba', 'levantarse_boca_abajo',
                  'golpe_cabeza', 'golpe_cabeza_b', 'golpe_cabeza_c', 'golpe_cuerpo', 'golpe_cuerpo_b',
                  'golpe_brazo_fuerte', 'golpe_mano', 'golpe_brazo_izq', 'golpe_brazo_fuerte_espejo', 'soltar_hacha',
                  'golpe_antebrazo_arma', 'golpe_pierna_der', 'golpe_pierna_b_der', 'caer_pierna_der',
                  'golpe_pierna_izq', 'golpe_pierna_b_izq', 'caer_pierna_izq', 'rodilla_der', 'rodilla_izq'}
        for i, (archivo, arm, script, mallas, mitad) in enumerate(variantes):
            aset = p.animset(p.objetos[arm]['anims'])
            vistos = set()
            clips = []
            for k in p.objetos[arm].get('clips', []):
                nom = aset[1][k].nombre
                if nom in usados and nom not in vistos:
                    vistos.add(nom)
                    clips.append((nom, k, False))
            self.modelo(p, arm, archivo + '.mdl', [(m[0], m[1], m[2] if len(m) > 2 else {}) for m in mallas],
                        clips=clips, mitad=mitad, bajo=0.15 if mitad else 0.25)
            lua = p.script(script)
            t = fuentes.tablas_locales(lua, ['RAIZ'])
            for nom, v in t['RAIZ'].items():
                self.tablas.poner('rg%d.%s' % (i, nom), v)
            conf = p.tablas(script).get('CONF') or {}
            golpe = conf.get('golpe', [15, 21])
            self.tablas.poner('gconf.%d' % i, [conf.get('alcance', 1.7), conf.get('danio', 380), golpe[0], golpe[1],
                                               conf.get('se_f', 15), 1 if conf.get('guardia') else 0,
                                               conf.get('guard_r', 30), ataques[conf.get('ataque', 'ataque_hacha')],
                                               1 if conf.get('caminar') == 'caminar_arma' else 0])
        print('ganado: %d variantes' % len(variantes))

    # ------------------------------------------------------------------ las cinematicas
    def armar_cine(self):
        n = self.nivel
        C = cine.Cine(n)
        for mod in cine.MODELOS:
            archivo, arm, mallas, sel, mitad, bajo = mod
            aset = n.animset(n.objetos[arm]['anims'])
            clips = None
            if sel is not None:
                clips = [(aset[1][k].nombre, k, False) for k in sel]
            self.modelo(n, arm, archivo, [(x[0], x[1], x[2] if len(x) > 2 else {}) for x in mallas], clips,
                        mitad=mitad, bajo=bajo)
            C.clips[archivo] = self.nombres_clips
        t = fuentes.tablas_locales(n.script('camino.lua'), ['EVENTOS', 'VENTANA'])
        for e in t['EVENTOS']:
            C.evento(e['nombre'], e['total'], [(c['inicio'], c['frames'], c['clips']) for c in e['cortes']])
            if e.get('area'):
                a = e['area']
                self.tablas.poner('ev.%s.area' % e['nombre'], [a['piso'], a['alto']] + [x for p in a['pts'] for x in p])
            if e.get('leon'):
                l = list(e['leon'])
                self.tablas.poner('ev.%s.leon' % e['nombre'], [l[0], l[1], l[2], l[3] if l[3] is not None else 999])
        v = t['VENTANA']
        C.evento('ventana', v['frames'], [])
        a = v['area']
        self.tablas.poner('ventana.area', [a['piso'], a['alto']] + [x for p in a['pts'] for x in p])
        self.tablas.poner('ventana.leon', v['leon'])
        ev = fuentes.tablas_locales(n.script('evento.lua'), ['CORTES', 'TOTAL', 'PISTOLA_CORTES', 'MUSICA_FRAME',
                                                              'LEON_DESPUES', 'MIRAR_DESPUES'])
        C.evento('s03', ev['TOTAL'], [(c['inicio'], c['frames'], c['clips']) for c in ev['CORTES']])
        self.tablas.poner('s03.pistola', ev['PISTOLA_CORTES'])
        self.tablas.poner('s03.despues', list(ev['LEON_DESPUES']) + list(ev['MIRAR_DESPUES']))
        C.evento('codec', 815, [])
        # la entrada a la casa: los hitbox hijos de Evento_s03 (en mundo: el objeto + su posicion)
        ent = []
        base = n.objetos['Evento_s03'].get('pos', [0, 0, 0])
        for h in n.hijos('Evento_s03'):
            if h.get('tipo') == 'hitbox':
                c = [base[k] + h.get('pos', [0, 0, 0])[k] + h.get('centro', [0, 0, 0])[k] * h.get('escala', [1, 1, 1])[k]
                     for k in range(3)]
                t = [h.get('tam', [1, 1, 1])[k] * h.get('escala', [1, 1, 1])[k] / 2 for k in range(3)]
                ent += c + t
        self.tablas.poner('s03.entrada', ent)
        C.guardar(os.path.join(DATOS, 'cine.bin'))
        # los lugares del juego: Leon al empezar y cada aldeano (su proxy)
        for o in n.objetos.values():
            if o.get('tipo') == 'proxy':
                self.tablas.poner('px.' + o['elemento'], list(o['pos']) + [o['rot'][1], o.get('escala', [1])[0]])
        # LAS LUCES de los personajes: las direccionales del cuarto (hacia la luz = -Z de la luz, R = Rx Ry Rz) y las
        # de la casa (puntuales: el juego las toma por su posicion)
        def hacia(o):
            a, b, c = [math.radians(x) for x in o['rot']]
            Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
            Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
            Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
            return list(-(Rx @ Ry @ Rz)[:, 2])
        K = 0.62
        v = [0.36, 0.36, 0.34, 2]
        for nom in ('r100_luz_00', 'r100_luz_01'):
            o = n.objetos[nom]
            v += hacia(o) + [c * K for c in o['color']]
        self.tablas.poner('luces.afuera', v)
        v = [0.30, 0.27, 0.23]
        for nom in ('r100_luzcasa_02', 'r100_luzcasa_06', 'r100_luzcasa_12'):
            o = n.objetos[nom]
            v += list(o['pos']) + [c * K for c in o['color']]
        self.tablas.poner('luces.casa', v)
        v = [0.30, 0.30, 0.30, 2]
        for nom in ('Codec_luz_0', 'Codec_luz_1'):
            o = n.objetos[nom]
            v += hacia(o) + [c * K for c in o['color']]
        self.tablas.poner('luces.codec', v)
        em = fuentes.tablas_locales(n.script('emboscada.lua'), ['CASA', 'SALIDA'])
        for k in ('CASA', 'SALIDA'):
            a = em[k]
            self.tablas.poner('emb.' + k.lower(), [a['piso'], a['alto']] + [x for p in a['pts'] for x in p])

    def rigido(self, proy, obj, archivo, prop=1.0, mitad=False):
        """una malla sin esqueleto (un arma, la radio, un vidrio) como modelo de UN hueso en su origen: se dibuja con la
        matriz que le toque (la mano, la ventana)"""
        arm = {'bones': [{'nombre': 'raiz', 'padre': -1, 'restT': [0, 0, 0], 'restR': [0, 0, 0], 'restS': [1, 1, 1],
                          'invBind': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
        M = modelos.Modelo(archivo, arm, ([], []), self.tex)
        o = proy.objetos[obj]
        M.agregar_malla(proy.malla(o['malla']), proy.materiales, lambda mj: self.tex_material(proy, mj, mitad), prop,
                        rigida_en='raiz')
        return M.guardar(os.path.join(DATOS, archivo))

    def armar_sonidos(self):
        vol = {}
        for p, s in ((self.pers, 'leon.lua'), (self.pers, 'ganado.lua')):
            vol.update(fuentes.tablas_locales(p.script(s), ['VOL']).get('VOL', {}))
        sonidos.armar([self.nivel, self.pers], vol, os.path.join(DATOS, 'sonidos'))

    def armar_leon(self):
        p = self.pers
        # LEON DE JUEGO: el cuerpo completo (9100 triangulos en el disco) a la mitad, cuidando las costuras
        self.modelo(p, 'Leon', 'leon.mdl', [('Leon_cuerpo', 0.4, {'error': 0.015})], bajo=0.22)
        self.modelo(p, 'Pistola', 'pistola.mdl', [('Pistola_malla', 1.0, {})])
        self.rigido(p, 'Leon_cuchillo', 'cuchillo.mdl')
        self.rigido(p, 'Leon_radio', 'radio.mdl')
        # la RAIZ de cada clip de Leon (x, z, giro por cuadro: leon.lua), las ventanas, la camara del salto y los vidrios
        t = fuentes.tablas_locales(p.script('leon.lua'), ['RAIZ', 'RAIZY', 'VENTANAS', 'CAMV', 'TROZOS'])
        clips_v = ['ventana_saltar_afuera', 'ventana_saltar_adentro', 'ventana_saltar_abajo']
        for w in t['VENTANAS']:
            self.tablas.poner('ventana.%d' % w['n'], [w['x'], w['y'], w['z'], w['yaw']])
            for k, sj in enumerate(w['saltos']):
                self.tablas.poner('salto.%d.%d' % (w['n'], k), [sj['lado'], clips_v.index(sj['clip']), sj['x'], sj['y'],
                                                               sj['z'], sj['yaw'], sj['rompe']])
        for nom, v in t['CAMV'].items():
            self.tablas.poner('camv.' + nom, v)
        n = self.nivel
        vidrios = ['Vidrio_efm_10_parte_0', 'Vidrio_efm_10_parte_1', 'Vidrio_efm_10_parte_2', 'Vidrio_efm_0e_parte_0',
                   'Vidrio_efm_0e_parte_1', 'Vidrio_efm_0e_parte_2', 'Vidrio_efm_0e_parte_3']
        objs = {o['nombre']: o for o in n.hijos('Vidrio_trozos')}
        for i, m in enumerate(vidrios):
            obj = next(o['nombre'] for o in objs.values() if o['malla'] == m)
            self.rigido(n, obj, 'vidrio_%d.mdl' % i)
        for ci, clip in enumerate(clips_v):
            for k, (nom, pos) in enumerate(t['TROZOS'].get(clip, [])):
                if not pos:
                    continue
                o = objs[nom]
                self.tablas.poner('tz.%d.%d' % (ci, k), [vidrios.index(o['malla']), o['rot'][1]] + list(o['escala']) +
                                  list(pos))
        self.rigido(n, 'Ventana_intacta_0', 'ventana_intacta.mdl')
        self.rigido(n, 'Ventana_rota_0', 'ventana_rota.mdl')
        self.rigido(n, 'r100_puerta', 'puerta.mdl')
        for k in (0, 1):
            o = n.objetos['Ventana_intacta_%d' % k]
            self.tablas.poner('prop.ventana.%d' % k, list(o['pos']) + [o['rot'][1]])
        self.tablas.poner('prop.puerta', list(n.objetos['r100_puerta']['pos']) + [90.0])
        for nom, v in t['RAIZ'].items():
            self.tablas.poner('rl.' + nom, v)
        for nom, v in t.get('RAIZY', {}).items():
            self.tablas.poner('ry.' + nom, v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--re3', default=os.path.join(RAIZ, '..', 're3_w3d'))
    ap.add_argument('--sonidos', action='store_true', help='rehacer los sonidos aunque ya esten')
    a = ap.parse_args()
    os.makedirs(DATOS, exist_ok=True)
    d = Datos(os.path.normpath(a.re3))
    # (todo lo que registra texturas corre siempre: el indice de cada una es el orden en que entra)
    d.armar_mundo()
    d.armar_colision()
    d.armar_leon()
    d.armar_ganado()
    d.armar_cine()
    interfaz.armar(d.nivel, d.tex, d.tablas)
    efectos_conv.armar(d.nivel, d.pers, d.tex, d.tablas)
    items.armar(d.re3, d.tex, d.tablas, DATOS)
    objetos.armar(d.re3, d.tex, d.tablas, DATOS)
    if a.sonidos or not os.path.isfile(os.path.join(DATOS, 'sonidos', 'lista.txt')):
        d.armar_sonidos()
    n, b, g = d.tex.guardar(os.path.join(DATOS, 'texturas.txn'))
    print('texturas.txn: %d texturas (%d KB)' % (n, b // 1024))
    d.tablas.guardar(os.path.join(DATOS, 'tablas.bin'))
    print('tablas.bin: %d tablas' % len(d.tablas.t))


if __name__ == '__main__':
    main()
