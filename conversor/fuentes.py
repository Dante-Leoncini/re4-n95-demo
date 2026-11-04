"""Lo que lee el conversor de los proyectos de re3_w3d: el .w3d del nivel (re4_r100_full.w3d) y su libreria de
personajes (re4_personajes.w3d). Los objetos (con sus prefabs), los materiales, las mallas .w3db, las bibliotecas de
clips .w3da, las animaciones de escena, los scripts (y las tablas que el generador inyecto en ellos) y los archivos del
zip (texturas, sonidos)."""
import json
import struct
import zipfile

import numpy as np

import lua_tablas
import w3da


class Malla:
    """Los bloques de render de un .w3db: posiciones, normales, UV, color, indices, partes, grupos y shape keys."""

    def __init__(self, datos, nombre=''):
        if datos[:4] != b'W3DB':
            raise ValueError('%s: no es un .w3db' % nombre)
        n, = struct.unpack_from('<I', datos, 12)
        p = 20
        self.bloques = {}
        for _ in range(n):
            cc, dominio, cantidad, nbytes = struct.unpack_from('<4sIII', datos, p)
            p += 16
            self.bloques[cc.decode()] = (dominio, cantidad, datos[p:p + nbytes])
            p += (nbytes + 3) & ~3
        _, nv, b = self.bloques['RPOS']
        self.nv = nv
        self.pos = np.frombuffer(b[:nv * 12], np.float32).reshape(nv, 3).astype(np.float64)
        self.uv = np.zeros((nv, 2))
        if 'RUV ' in self.bloques:
            self.uv = np.frombuffer(self.bloques['RUV '][2][:nv * 8], np.float32).reshape(nv, 2).astype(np.float64)
        self.nrm = np.tile(np.array([0, 127, 0], np.int8), (nv, 1))
        if 'RNRM' in self.bloques:
            self.nrm = np.frombuffer(self.bloques['RNRM'][2][:nv * 3], np.int8).reshape(nv, 3).copy()
        self.col = None
        if 'RCOL' in self.bloques:
            self.col = np.frombuffer(self.bloques['RCOL'][2][:nv * 4], np.uint8).reshape(nv, 4).copy()
        dom, ntri, b = self.bloques['RIDX']
        if dom & 0x100:
            self.idx = np.frombuffer(b[:ntri * 12], np.uint32).astype(np.int64)
        else:
            self.idx = np.frombuffer(b[:ntri * 6], np.uint16).astype(np.int64)
        self.grupos = {}
        if 'RVGR' in self.bloques:
            self.grupos = self._grupos(self.bloques['RVGR'], 1)
        self.formas = []
        if 'RSHP' in self.bloques:
            for nom, (idx, val) in self._grupos(self.bloques['RSHP'], 3, lista=True):
                self.formas.append((nom, idx, val.reshape(-1, 3)))
        self.partes = []
        _, npart, b = self.bloques['PART']
        q = 0
        for _ in range(npart):
            l, = struct.unpack_from('<I', b, q); q += 4
            nom = b[q:q + l].decode(); q += l
            l, = struct.unpack_from('<I', b, q); q += 4
            mat = b[q:q + l].decode(); q += l
            ini, cnt = struct.unpack_from('<ii', b, q); q += 8
            self.partes.append((nom, mat, ini, cnt))

    @staticmethod
    def _grupos(bloque, floats, lista=False):
        _, ng, b = bloque
        out = []
        q = 0
        for _ in range(ng):
            l, = struct.unpack_from('<I', b, q); q += 4
            nom = b[q:q + l].decode(); q += l
            n, = struct.unpack_from('<I', b, q); q += 4
            idx = np.frombuffer(b[q:q + 4 * n], np.int32).astype(np.int64); q += 4 * n
            val = np.frombuffer(b[q:q + 4 * n * floats], np.float32).astype(np.float64); q += 4 * n * floats
            out.append((nom, (idx, val)))
        return out if lista else dict(out)


class Proyecto:
    def __init__(self, ruta):
        self.ruta = ruta
        self.zip = zipfile.ZipFile(ruta)
        self.nombres = set(self.zip.namelist())
        self.json = json.loads(self.zip.read('proyecto.json').decode('utf8'))
        self.mallas = {m['nombre']: m['entrada'] for m in self.json.get('mallas', [])}
        self.animsets = {a['nombre']: a['entrada'] for a in self.json.get('animsets', [])}
        self.materiales = {m['nombre']: m for m in self.json.get('materiales', [])}
        self.objetos = {}
        self.padre = {}
        for o in self.json['escena']['objetos']:
            self._indexar(o, None)
        for n in sorted(self.nombres):
            if n.startswith('prefabs/') and n.endswith('.w3dp'):
                pf = json.loads(self.zip.read(n).decode('utf8'))
                self._indexar(pf['raiz'], None)
        self._cache_mallas = {}
        self._cache_sets = {}

    def _indexar(self, o, padre):
        if 'nombre' in o:
            self.objetos[o['nombre']] = o
            self.padre[o['nombre']] = padre
        for h in o.get('hijos', []):
            self._indexar(h, o.get('nombre'))

    def leer(self, entrada):
        return self.zip.read(entrada)

    def existe(self, entrada):
        return entrada in self.nombres

    def malla(self, nombre):
        if nombre not in self._cache_mallas:
            self._cache_mallas[nombre] = Malla(self.leer(self.mallas[nombre]), nombre)
        return self._cache_mallas[nombre]

    def animset(self, nombre):
        """(tabla de huesos, clips) de la biblioteca .w3da"""
        if nombre not in self._cache_sets:
            self._cache_sets[nombre] = w3da.leer(self.leer(self.animsets[nombre]))
        return self._cache_sets[nombre]

    def escena(self, nombre):
        for s in self.json.get('animaciones', {}).get('escenas', []):
            if s['nombre'] == nombre:
                return s
        return None

    def script(self, nombre):
        return self.leer('scripts/' + nombre).decode('utf8')

    def tablas(self, nombre):
        return lua_tablas.tablas(self.script(nombre))

    def hijos(self, nombre):
        return self.objetos[nombre].get('hijos', [])


def tablas_locales(lua, nombres):
    """las tablas 'local NOMBRE = {...}' de un script (las que el generador escribio adentro del codigo)"""
    out = {}
    lineas = lua.splitlines()
    for nombre in nombres:
        marca = 'local %s = ' % nombre
        for i, l in enumerate(lineas):
            if l.startswith(marca):
                texto = l[len(marca):]
                # (una tabla de varias lineas: hasta que cierran las llaves)
                prof = texto.count('{') - texto.count('}')
                j = i
                while prof > 0 and j + 1 < len(lineas):
                    j += 1
                    texto += '\n' + lineas[j]
                    prof += lineas[j].count('{') - lineas[j].count('}')
                lec = lua_tablas._Lector(lua_tablas._tokens(texto))
                out[nombre] = lec.valor()
                break
    return out
