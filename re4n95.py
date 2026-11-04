#!/usr/bin/env python3
"""Arma la carpeta de datos de la demo de Resident Evil 4 para el Nokia N95 desde TU copia del juego (GameCube, USA).

    python re4n95.py --disco "Resident Evil 4 (USA) (Disc 1).rvz" --whisk3d RUTA/whisk3d[.exe]

Al terminar, copia la carpeta de salida (por defecto ./datos) a E:\\re4\\datos en la tarjeta del telefono.
Si se corta, volve a correr el mismo comando: sigue desde el paso que fallo.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, 'herramientas'))
import host_animaciones  # noqa: E402

DECOMP_URL = 'https://github.com/adonis-singh/re4'
DECOMP_COMMIT = '7e20c89c'
DTK_TAG = 'v1.8.3'
CARPETA_DISCO = 'Resident Evil 4 (USA) (Disc 1)'
NOMBRE_DISCO = 'Resident Evil 4 (USA) (Disc 1).rvz'
MAPA_N95 = ['--l0-prop', '0.35', '--l0-costuras', '--lod', '0.1,0.03', '--lod-alfa', '0.3,0.12', '--lod-error',
            '0.03,0.08', '--lado', '6,10,20', '--fondo-prop', '0.45', '--fondo-lado', '10', '--fondo-celda', '16',
            '--tev-juego', '--l0-prop-casa', '0.85']


ARCHIVOS_DISCO = (
    ['St1/r100.das'] + ['St1/r100_%02d.dat' % i for i in range(5)] +
    ['Evd/r100s%s.evd' % e for e in ('00', '03', '20', '30', '40', '41', '43', '44')] +
    ['em/%s.drs' % m for m in ('pl00', 'em10', 'em12', 'em32', 'wep00', 'wep01', 'wep02')] +
    ['etc/core.das', 'etc/emleon00.esl', 'font/common_p.fnt', 'font/event1_p.fnt', 'op/op01.das',
     'ss/Cmn/ss_oc101.dat', 'ss/Cmn/ss_tel01.dat', 'ss/Eng/ss_cmmn.dat', 'ss/Eng/ss_term.dat'] +
    ['ss/Eng/tel%s_101_%s.fcv' % (a, b) for a in ('0000', '0100') for b in ('b', 'f')] +
    ['bgm/bgmtbl.dat', 'bgm/bio4midi.hed', 'bgm/bio4midi.dat', 'bgm/bio4str.hed'])


class Error(Exception):
    pass


class Armado:
    def __init__(self, a):
        self.disco = os.path.abspath(a.disco)
        self.trabajo = os.path.abspath(a.trabajo)
        self.salida = os.path.abspath(a.salida)
        self.whisk3d = a.whisk3d and os.path.abspath(a.whisk3d)
        self.gxx = a.gxx
        self.ext = os.path.join(self.trabajo, 'extractores')
        self.dec = os.path.join(self.trabajo, 're4')
        self.registro = os.path.join(self.trabajo, 'registro')
        self.hechos = os.path.join(self.trabajo, 'hechos')
        self.host = None

    # ------------------------------------------------------------------------------------------- ayudas
    def correr(self, nombre, args, cwd=None, env=None):
        os.makedirs(self.registro, exist_ok=True)
        log = os.path.join(self.registro, nombre + '.log')
        e = dict(os.environ)
        e.update(env or {})
        with open(log, 'w', encoding='utf-8', errors='replace') as f:
            r = subprocess.run(args, cwd=cwd, env=e, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            cola = open(log, encoding='utf-8', errors='replace').read()[-2500:]
            raise Error('fallo (registro completo en %s):\n%s' % (log, cola))

    def extractor(self, nombre, script, *args):
        # (el arranque deja la libreria de animaciones ya compilada en cada Python que se lance, tambien en los
        # extractores que corren otros extractores)
        env = {'RE4N95_HOST': self.host or host_animaciones.compilar(self.dec, self.gxx),
               'RE4N95_DECOMP_TOOLS': os.path.join(self.dec, 'tools'), 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1',
               'PYTHONPATH': os.pathsep.join([os.path.join(AQUI, 'herramientas', 'arranque'), self.ext])}
        self.correr(nombre, [sys.executable, os.path.join(self.ext, script)] + list(args), cwd=self.ext, env=env)

    def dtk(self):
        return os.path.join(self.ext, 'tools', 'dtk.exe' if os.name == 'nt' else 'dtk')

    # ------------------------------------------------------------------------------------------- pasos
    def preparar(self):
        os.makedirs(self.trabajo, exist_ok=True)
        # el codigo de los extractores y del conversor va a la carpeta de trabajo (lo generado queda al lado)
        for sub in ('extractores', 'conversor'):
            shutil.copytree(os.path.join(AQUI, sub), os.path.join(self.trabajo, sub), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__'))
        # el disco donde lo buscan los extractores: un enlace (o una copia si esta en otra unidad)
        dest = os.path.join(self.trabajo, CARPETA_DISCO, NOMBRE_DISCO)
        if not os.path.isfile(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                os.link(self.disco, dest)
            except OSError:
                print('      (el disco esta en otra unidad: se copia, 1,2 GB)')
                shutil.copyfile(self.disco, dest)

    def decomp(self):
        if not os.path.isdir(os.path.join(self.dec, '.git')):
            self.correr('decomp_clonar', ['git', 'clone', '--filter=blob:none', '--no-checkout', DECOMP_URL, self.dec])
        self.correr('decomp_commit', ['git', '-C', self.dec, 'checkout', '-q', DECOMP_COMMIT])

    def compilar_host(self):
        self.host = host_animaciones.compilar(self.dec, self.gxx)

    def bajar_dtk(self):
        if not os.path.isfile(self.dtk()):
            self.correr('dtk', [sys.executable, os.path.join(self.dec, 'tools', 'download_tool.py'), 'dtk',
                                self.dtk(), '--tag', DTK_TAG])
        # los archivos del disco que usa la demo (el primer cuarto): unos 50, 77 MB
        for ruta in ARCHIVOS_DISCO:
            # (la musica: el extractor la lee de extracted/tmp)
            destino = 'tmp/bio4midi.dat' if ruta == 'bgm/bio4midi.dat' else ruta
            local = os.path.join(self.ext, 'extracted', *destino.split('/'))
            if not os.path.isfile(local):
                os.makedirs(os.path.dirname(local), exist_ok=True)
                self.correr('disco', [self.dtk(), 'vfs', 'cp', '%s:files/%s' % (self.disco, ruta), local])

    def efectos(self):
        out = os.path.join(self.ext, 'out', 'efectos')
        os.makedirs(out, exist_ok=True)
        core = os.path.join(self.ext, 'extracted', 'etc', 'core.das')
        for arma in ('wep01', 'wep02'):
            self.extractor('efectos_' + arma, os.path.join('tools', 're4_eff.py'),
                           os.path.join(self.ext, 'extracted', 'em', arma + '.drs'), '--core', core, '--png', out,
                           '--json', os.path.join(out, arma + '_est.json'))
        # (el impacto del laser y el humo: efectos del nucleo, core.das entrada 1)
        self.extractor('efectos_nucleo', os.path.join('tools', 're4_eff.py'), core, '--entry', '1', '--est', '0x03',
                       '0x1F', '0x20', '0x50', '--png', out, '--json', os.path.join(out, 'core_laser_hit_est.json'))
        self.extractor('efectos_texturas', os.path.join('tools', 'fx_texturas.py'))

    def mapa_n95(self):
        carpeta = os.path.join(self.ext, 'out', 'r100_n95')
        self.extractor('mapa_n95', 're4_extract_r100.py', '-o', carpeta, *MAPA_N95)
        self.extractor('mapa_n95_interior', os.path.join(AQUI, 'herramientas', 'pvs_n95.py'), carpeta)

    def eventos(self):
        for ev in ('r100s03', 'r100s40', 'r100s41', 'r100s43', 'r100s44', 'r100s20'):
            self.extractor('evento_' + ev, 're4_extract_evento.py', '--evento', ev)

    def ganado_juego(self):
        self.extractor('ganado_juego', 're4_extract_ganado_juego.py')
        self.extractor('ganado_juego_lugar', 're4_extract_ganado_juego.py', '--en-lugar')

    def personajes(self):
        # (con la malla de la cinematica de la casa; las charlas del camino con los modelos del cuarto)
        for ev, extra in (('s40', []), ('s41', ['--bins-cuarto']), ('s43', ['--bins-cuarto']), ('s44', ['--bins-cuarto']),
                          ('s20', [])):
            self.extractor('personajes_' + ev, 're4_extract_personajes_evento.py', '--evd', 'r100%s.evd' % ev, '--out',
                           os.path.join('out', 'evento_' + ev), '--malla-de', 'r100s03.evd', *extra)

    def libreria(self):
        self.extractor('libreria', 'make_personajes_w3d.py', '--whisk3d', self.whisk3d)

    def nivel(self):
        self.extractor('nivel', 'make_r100_w3d.py', '--full', '--whisk3d', self.whisk3d)

    def datos(self):
        conv = os.path.join(self.trabajo, 'conversor')
        env = {'RE4N95_DATOS': self.salida, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        self.correr('datos', [sys.executable, os.path.join(conv, 'armar_datos.py'), '--re3', self.ext], env=env)
        for n in ('intro.txn', 'fuente.txn'):
            shutil.copyfile(os.path.join(AQUI, 'demo', 'datos', n), os.path.join(self.salida, n))

    def pasos(self):
        x = self.extractor
        return [
            ('Preparar la carpeta de trabajo', self.preparar),
            ('Bajar la decompilacion publica (para las animaciones)', self.decomp),
            ('Compilar el modulo de animaciones', self.compilar_host),
            ('Bajar dtk (lee el disco)', self.bajar_dtk),
            ('Sonidos de los bancos del juego', lambda: x('sonidos', os.path.join('tools', 're4_sonidos.py'))),
            ('Leon (modelo y animaciones)', lambda: x('leon', 're4_extract_leon.py')),
            ('Efectos del disparo', self.efectos),
            ('Leon de combate', lambda: x('leon_combate', 're4_extract_leon.py', '--combate')),
            ('Las cinematicas (camaras, audio)', self.eventos),
            ('El aldeano', lambda: x('ganado', 're4_extract_ganado.py')),
            ('Los personajes de la cinematica de la casa', lambda: x('personajes_s03', 're4_extract_personajes_evento.py')),
            ('Los personajes de las otras cinematicas', self.personajes),
            ('El aspecto del cuarto (niebla, luces, particulas)', lambda: x('look', 're4_extract_look.py')),
            ('El mapa', lambda: x('mapa', 're4_extract_r100.py')),
            ('Los aldeanos de juego', self.ganado_juego),
            ('La pistola y sus efectos', lambda: x('combate', 're4_extract_combate.py')),
            ('El HUD', lambda: x('hud', 're4_extract_hud.py')),
            ('Los textos y la fuente', lambda: x('texto', 're4_extract_texto.py', '--sin-whisk3d', '--sin-muestra')),
            ('La intro (camioneta, policias, ventana)', lambda: x('intro', 're4_extract_intro_r100.py')),
            ('La emboscada', lambda: x('emboscada', 're4_extract_emboscada_r100.py')),
            ('Las acciones de Leon (patada, radio)', lambda: x('acciones', 're4_extract_acciones.py')),
            ('El salto por la ventana', lambda: x('ventana', 're4_extract_salto_ventana.py')),
            ('Los sonidos de combate', lambda: x('sonidos_combate', 're4_extract_sonidos_combate.py')),
            ('La llamada de radio (codec)', lambda: x('codec', 're4_extract_codec.py', '--sin-control')),
            ('La musica del cuarto', lambda: x('musica', 're4_extract_bgm_midi.py')),
            ('Los items', lambda: x('items', 're4_extract_items.py')),
            ('La libreria de personajes (Whisk3D)', self.libreria),
            ('El nivel (Whisk3D)', self.nivel),
            ('El mapa del N95', self.mapa_n95),
            ('Los objetos del cuarto (cajas, cuervos)', lambda: x('objetos', 're4_extract_objetos_r100.py')),
            ('Los datos del N95', self.datos),
        ]

    def requisitos(self):
        faltan = []
        for m in ('numpy', 'PIL'):
            try:
                __import__(m)
            except ImportError:
                faltan.append('el modulo de Python "%s" (pip install %s)' % (m, 'pillow' if m == 'PIL' else m))
        if not shutil.which('git'):
            faltan.append('git')
        if not host_animaciones.gxx_disponible(self.gxx):
            faltan.append('el compilador g++ (Windows: MSYS2 con mingw-w64-x86_64-gcc, y su carpeta bin en el PATH)')
        if not os.path.isfile(self.disco):
            faltan.append('el disco: no existe ' + self.disco)
        if not self.whisk3d or not os.path.isfile(self.whisk3d):
            faltan.append('el editor Whisk3D: pasalo con --whisk3d o la variable WHISK3D (ver el README)')
        if faltan:
            raise Error('falta:\n  - ' + '\n  - '.join(faltan))

    def todo(self):
        self.requisitos()
        pasos = self.pasos()
        n = len(pasos)
        os.makedirs(self.hechos, exist_ok=True)
        print('Resident Evil 4 -> datos del Nokia N95: %d pasos' % n)
        print('  disco:   %s\n  trabajo: %s\n  salida:  %s\n' % (self.disco, self.trabajo, self.salida))
        t0 = time.time()
        for i, (titulo, paso) in enumerate(pasos, 1):
            marca = os.path.join(self.hechos, '%02d.ok' % i)
            if os.path.isfile(marca) and i > 1:
                print('[%2d/%d] %s: ya estaba' % (i, n, titulo))
                continue
            print('[%2d/%d] %s...' % (i, n, titulo), end='', flush=True)
            t = time.time()
            paso()
            if i == 3 and self.host is None:
                self.host = host_animaciones.compilar(self.dec, self.gxx)
            open(marca, 'w').close()
            print(' listo (%s)' % duracion(time.time() - t))
        print('\nTERMINADO en %s.' % duracion(time.time() - t0))
        print('Los datos estan en: %s' % self.salida)
        print('Copia esa carpeta a la tarjeta del N95 como E:\\re4\\datos e instala demo\\re4.sisx.')


def duracion(s):
    s = int(s)
    return '%d min %02d s' % (s // 60, s % 60) if s >= 60 else '%d s' % s


def main():
    ap = argparse.ArgumentParser(description='Arma los datos de la demo de RE4 para el Nokia N95 desde tu disco.')
    ap.add_argument('--disco', required=True, help='la imagen de TU disco de RE4 GameCube USA (disco 1: .rvz, .iso o .gcm)')
    ap.add_argument('--whisk3d', default=os.environ.get('WHISK3D'), help='el ejecutable del editor Whisk3D')
    ap.add_argument('--trabajo', default=os.path.join(AQUI, 'trabajo'), help='carpeta de trabajo (unos 2 GB)')
    ap.add_argument('--salida', default=os.path.join(AQUI, 'datos'), help='donde quedan los datos del N95')
    ap.add_argument('--gxx', default='g++', help='el compilador de C++ (g++)')
    a = ap.parse_args()
    try:
        Armado(a).todo()
    except Error as e:
        print('\n\nERROR: %s' % e)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n\nCortado. Volve a correr el mismo comando para seguir.')
        sys.exit(1)


if __name__ == '__main__':
    main()
