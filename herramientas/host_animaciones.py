"""Compila en la maquina del usuario el modulo de animaciones de la decompilacion publica de RE4
(github.com/adonis-singh/re4, tools/motion/host): las mismas fuentes y opciones que su Makefile, sin make, para que
ande igual en Windows (MSYS2 / MinGW) y en Linux. El codigo del juego no esta en este repositorio: se lee del clon."""
import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
FDLIBM = ['sf_sin', 'sf_cos', 'kf_sin', 'kf_cos', 'ef_rem_pio2', 'kf_rem_pio2', 'sf_scalbn', 'sf_floor', 'sf_fabs',
          'ef_acos', 'ef_sqrt']
FDLIBM_DEFS = ['-Dsinf=re4_sinf', '-Dcosf=re4_cosf', '-Dacosf=re4_acosf', '-Dfabsf=re4_fabsf', '-Dfloorf=re4_floorf',
               '-Dscalbnf=re4_scalbnf']
MATH = ['hermite', 'RotMatrix', 'TransMatrix', 'ScaleMatrix', 'VecRadLimit', 'SetOrientationZX', 'SetOrientationZY',
        'VecAngle', 'VecLinearCombination']
SUB2 = ['RootSumSquare3', 'GetDistance3']
MODEL = ['cModel::partsMatCalc', 'cModel::partsWorldCalc', 'cModel::getPartsPtr', 'cModel::matBlend']
MTX = ['C_MTXIdentity', 'C_MTXCopy', 'C_MTXConcat', 'C_MTXInverse', 'C_MTXTranspose', 'C_MTXTrans', 'C_MTXScale',
       'C_MTXRotTrig', 'C_MTXRotRad', 'C_MTXRotAxisRad', 'C_MTXQuat']
MTXVEC = ['C_MTXMultVec', 'C_MTXMultVecSR']
VEC = ['C_VECAdd', 'C_VECSubtract', 'C_VECScale', 'C_VECNormalize', 'C_VECSquareMag', 'C_VECMag', 'C_VECDotProduct',
       'C_VECCrossProduct']
QUAT = ['C_QUATMtx', 'C_QUATSlerp']
CXXFLAGS = ['-O2', '-std=gnu++14', '-fno-strict-aliasing', '-fno-fast-math', '-ffunction-sections', '-fdata-sections',
            '-w', '-ffp-contract=off']


def compilar(dec, gxx='g++'):
    """dec: el clon de la decompilacion. Deja la libreria donde la busca tools/motion/evalhost.py"""
    dec = os.path.abspath(dec)
    host = os.path.join(dec, "tools", "motion", "host")
    build = os.path.join(host, 'build')
    lib = os.path.join(build, 'libmotion_host.so')
    if os.path.isfile(lib):
        return lib
    os.makedirs(build, exist_ok=True)
    py = sys.executable
    prep = os.path.join(host, 'prepare.py')

    def correr(args, **kw):
        r = subprocess.run(args, capture_output=True, text=True, **kw)
        if r.returncode:
            raise RuntimeError('fallo: %s\n%s' % (' '.join(args[:3]), (r.stderr or r.stdout)[-2000:]))

    # (rutas con / : prepare.py las escribe en un #line, y en Windows las \ se leen como escapes)
    src = lambda *p: os.path.join(dec, 'src', *p).replace(os.sep, '/')
    b = lambda n: os.path.join(build, n).replace(os.sep, '/')
    correr([py, prep, 'motion', src('game', 'motion.cpp'), b('motion_prep.cpp')], cwd=host)
    correr([py, prep, 'motion', src('game', 'ik.cpp'), b('ik_prep.cpp')], cwd=host)
    partes = [(src('game', 'math_sub.cpp'), 'x_math.cpp', MATH), (src('game', 'sub2.cpp'), 'x_sub2.cpp', SUB2),
              (src('game', 'model.cpp'), 'x_model.cpp', MODEL)]
    sdk = [(src('lib', 'mtx.c'), 'x_mtx.cpp', MTX), (src('lib', 'mtxvec.c'), 'x_mtxvec.cpp', MTXVEC),
           (src('lib', 'vec.c'), 'x_vec.cpp', VEC), (src('lib', 'quat.c'), 'x_quat.cpp', QUAT)]
    for grupo, salida in ((partes, 'game_extract.cpp'), (sdk, 'sdk_extract.cpp')):
        texto = ''
        for fuente, nombre, funciones in grupo:
            correr([py, prep, 'extract', fuente, b(nombre)] + funciones, cwd=host)
            texto += open(b(nombre), encoding='utf-8').read()
        with open(b(salida), 'w', encoding='utf-8') as f:
            f.write(texto)
    objetos = []
    for n in FDLIBM:
        o = b(n + '_plain.o')
        correr([gxx] + CXXFLAGS + ['-I', os.path.join(dec, 'include')] + FDLIBM_DEFS +
               ['-c', src('lib', n + '.cpp'), '-o', o])
        objetos.append(o)
    fuentes = [b('motion_prep.cpp'), b('ik_prep.cpp'), b('game_extract.cpp'), b('sdk_extract.cpp'),
               os.path.join(host, 'motion_host.cpp')]
    enlace = ['-shared', '-Wl,--gc-sections'] + (['-static'] if os.name == 'nt' else ['-fPIC', '-Wl,-Bsymbolic'])
    extra = ['-I', os.path.join(AQUI, 'windows')] if os.name == 'nt' else ['-fPIC']
    correr([gxx] + CXXFLAGS + extra + ['-I', os.path.join(host, 'stub'), '-o', lib] +
           fuentes + objetos + enlace)
    return lib


def gxx_disponible(gxx='g++'):
    return shutil.which(gxx) is not None
