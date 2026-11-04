"""LAS CINEMATICAS para el N95 (cine.bin): por evento, sus cortes (que modelo toca que clip), la CAMARA cuadro a cuadro
(la de la pista "camara activa" de la animacion de escena: posicion, rotacion y lente) y las CARAS (el peso de cada
shape key por cuadro). Los modelos de las cinematicas (y los del juego que no son Leon ni el ganado: los vehiculos y
los policias sentados) salen como .mdl con modelos.py.

    'CIN1'
    u32 nmodelos; por modelo: char archivo[24]
    u32 neventos; por evento: char nombre[8], u32 total, ncortes, ncaras
        por corte: u32 inicio, cuadros, nactores; por actor: u16 modelo, u16 clip
        f32 camara[total * 8] (x y z, cuaternion x y z w, fov vertical)
        por cara: u16 modelo, u16 nformas, u16 forma[nformas], f32 pesos[total * nformas]
"""
import numpy as np

import binario
import esqueleto as esq

# (archivo, armature, [(malla, proporcion)], clips del animset (None: los del armature))
MODELOS = [
    # (archivo, armature, [(malla, proporcion, opciones)], clips del animset (None: los del armature), texturas a la
    # mitad, proporcion del nivel bajo (0: sin nivel bajo))
    ('leon_cine.mdl', 'Leon_ev', [('Leon_ev_cuerpo', 0.3), ('Leon_ev_cara', 0.5, {'forma_min': 0.25}), ('Leon_ev_pelo', 0.35)],
     list(range(33)), False, 0.18),
    ('ganado_ev.mdl', 'Ganado', [('Ganado_ev_cuerpo', 0.4), ('Ganado_ev_cara', 0.45, {'forma_min': 0.25}), ('Ganado_ev_ojos', 0.8)], None,
     False, 0.2),
    ('hacha_ev.mdl', 'Evento_hacha', [('Evento_hacha_malla', 1.0)], None, False, 0),
    ('foto_ev.mdl', 'Evento_foto', [('Evento_foto_malla', 1.0)], None, False, 0),
    ('palo_ev.mdl', 'Evento_palo', [('Evento_palo_malla', 1.0)], None, False, 0),
    ('policia_ev.mdl', 'Policia_ev', [('Policia_ev_cuerpo', 0.12), ('Policia_ev_cara', 0.25, {'forma_min': 0.25})], None, False, 0.15),
    ('policiaa_ev.mdl', 'PoliciaA_ev', [('PoliciaA_ev_cuerpo', 0.12), ('PoliciaA_ev_cara', 0.25, {'forma_min': 0.25}),
                                        ('PoliciaA_ev_gafas', 1.0)], None, False, 0.15),
    ('camioneta_ev.mdl', 'Camioneta_ev', [('obm1a00_malla', 0.75, {'error': 0.01})], None, True,
     0.12),
    ('camion.mdl', 'Camion_ev', [('Camion_malla', 0.3, {'permisivo': True, 'error': 0.05})], [0, 1, 2, 3], True, 0.12),
    ('coche_juego.mdl', 'Coche_juego', [('Coche_juego_malla', 0.3, {'permisivo': True, 'error': 0.04})], None, True,
     0.1),
    ('coche_barranco.mdl', 'Coche_barranco', [('Coche_barranco_malla', 0.2, {'permisivo': True, 'error': 0.06})], None,
     True, 0.1),
    ('policia_juego.mdl', 'Policia_juego', [('Policia_juego_malla', 0.25)], None, True, 0.1),
    ('policiaa_juego.mdl', 'PoliciaA_juego', [('PoliciaA_juego_malla', 0.25)], None, True, 0.1),
    # (el codec los muestra en dos ventanas de ~70 x 110 pixeles, solo la cara y los hombros)
    ('leon_codec.mdl', 'LeonCodec', [('LeonCodec_cuerpo', 0.12, {'error': 0.08}),
                                      ('LeonCodec_cabeza', 0.35, {'error': 0.04, 'forma_min': 0.25}),
                                      ('LeonCodec_ojos', 0.2, {'error': 0.05})],
     None, True, 0),
    ('hunnigan.mdl', 'Hunnigan', [('Hunnigan_cuerpo', 0.1, {'error': 0.08}),
                                  ('Hunnigan_cabeza', 0.35, {'error': 0.04, 'forma_min': 0.25}),
                                  ('Hunnigan_pieza4', 0.25, {'error': 0.05})],
     None, True, 0),
]
# los nombres de los scripts -> el modelo
ACTOR = {'Leon_e40': 'leon_cine.mdl', 'Leon_ev': 'leon_cine.mdl', 'Ganado': 'ganado_ev.mdl',
         'Evento_hacha': 'hacha_ev.mdl', 'Evento_foto': 'foto_ev.mdl', 'Evento_palo': 'palo_ev.mdl',
         'Policia_ev': 'policia_ev.mdl', 'PoliciaA_ev': 'policiaa_ev.mdl', 'Camioneta_ev': 'camioneta_ev.mdl',
         'Camion_ev': 'camion.mdl'}
CARAS = {'Leon_ev_cara': 'leon_cine.mdl', 'Leon_e40_cara': 'leon_cine.mdl', 'Ganado_ev_cara': 'ganado_ev.mdl',
         'Policia_ev_cara': 'policia_ev.mdl', 'PoliciaA_ev_cara': 'policiaa_ev.mdl',
         'LeonCodec_cabeza': 'leon_codec.mdl', 'Hunnigan_cabeza': 'hunnigan.mdl'}


def quat_objeto(rot):
    """la rotacion de un OBJETO de Whisk3D (grados): R = Rx * Ry * Rz -> cuaternion x y z w (q = qx * qy * qz)"""
    h = np.radians(np.asarray(rot, float)) * 0.5
    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                         aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])
    qx = np.array([np.sin(h[0]), 0, 0, np.cos(h[0])])
    qy = np.array([0, np.sin(h[1]), 0, np.cos(h[1])])
    qz = np.array([0, 0, np.sin(h[2]), np.cos(h[2])])
    return mul(mul(qx, qy), qz)


def curva_k(k, frames, defecto):
    """una curva de animacion de escena ([cuadro, valor, interp, ...]) en esos cuadros"""
    if not k:
        return np.full(len(frames), defecto, float)
    fr = np.array([x[0] for x in k], float)
    v = np.array([x[1] for x in k], float)
    out = np.interp(frames, fr, v)
    esc = np.array([x[2] == 0 for x in k])
    if esc.any():
        i = np.clip(np.searchsorted(fr, frames, side='right') - 1, 0, len(fr) - 1)
        m = esc[i] & (frames < fr[-1])
        out[m] = v[i[m]]
    return out


def camara(proy, escena, total):
    """la camara activa cuadro a cuadro: (total, 8)"""
    frames = np.arange(1, total + 1, dtype=float)
    pistas = {o['objeto']: o.get('curvas', []) for o in escena.get('objetos', [])}
    cortes = sorted((c['frame'], c['camara']) for c in escena.get('camaraActiva', []))
    out = np.zeros((total, 8))
    for i, f in enumerate(frames):
        cam = None
        for fc, n in cortes:
            if fc <= f:
                cam = n
        if cam is None and cortes:
            cam = cortes[0][1]
        o = proy.objetos[cam]
        cv = pistas.get(cam, [])
        def val(p, c, d):
            for x in cv:
                if x['p'] == p and x['c'] == c:
                    return float(curva_k(x['k'], np.array([f]), d)[0])
            return d
        pos = [val(0, c, o['pos'][c]) for c in range(3)]
        rot = [val(1, c, o['rot'][c]) for c in range(3)]
        fov = val(6, 0, o.get('fov', 45))
        out[i, :3] = pos
        out[i, 3:7] = quat_objeto(rot)
        out[i, 7] = fov
        if i and np.dot(out[i, 3:7], out[i - 1, 3:7]) < 0:
            out[i, 3:7] *= -1
    return out


def caras(escena, total):
    """{malla de cara: {forma: pesos[total]}}"""
    frames = np.arange(1, total + 1, dtype=float)
    out = {}
    for o in escena.get('objetos', []):
        if o['objeto'] not in CARAS:
            continue
        d = {}
        for c in o.get('curvas', []):
            if c['p'] == 15:
                d[c['c']] = curva_k(c['k'], frames, 0.0)
        if d:
            out[o['objeto']] = d
    return out


class Cine:
    def __init__(self, nivel, log=print):
        self.nivel = nivel
        self.log = log
        self.clips = {}       # archivo -> [nombres de sus clips]
        self.eventos = []

    def evento(self, nombre, total, cortes, escena_nombre=None):
        """cortes: [(inicio, cuadros, {actor: clip})]"""
        esc = self.nivel.escena(escena_nombre or nombre)
        cam = camara(self.nivel, esc, total) if esc and esc.get('camaraActiva') else np.zeros((0, 8))
        cr = caras(esc, total) if esc else {}
        self.eventos.append((nombre, total, cortes, cam, cr))

    def guardar(self, ruta):
        archivos = [m[0] for m in MODELOS]
        w = binario.Escritor().b(b'CIN1').s('I', len(archivos))
        for a in archivos:
            w.nombre(a, 24)
        w.s('I', len(self.eventos))
        for nombre, total, cortes, cam, cr in self.eventos:
            w.nombre(nombre, 8).s('III', total, len(cortes), len(cr))
            for ini, n, act in cortes:
                lista = []
                for actor, clip in act.items():
                    arch = ACTOR[actor]
                    nombres = self.clips[arch]
                    if clip not in nombres:
                        raise ValueError('%s: %s no tiene el clip %s' % (nombre, arch, clip))
                    lista.append((archivos.index(arch), nombres.index(clip)))
                w.s('III', ini, n, len(lista))
                for m, c in lista:
                    w.s('HH', m, c)
            if len(cam):
                w.b(cam.astype(np.float32).tobytes())
            else:
                w.b(np.zeros((total, 8), np.float32).tobytes())
            for malla, formas in cr.items():
                idx = sorted(formas)
                w.s('HH', archivos.index(CARAS[malla]), len(idx)).b(np.array(idx, np.uint16).tobytes()).alinear()
                p = np.stack([formas[i] for i in idx], 1) if idx else np.zeros((total, 0))
                w.b(p.astype(np.float32).tobytes())
        n = w.guardar(ruta)
        self.log('cine.bin: %d eventos (%d KB)' % (len(self.eventos), n // 1024))
