# ---------------------------------------------------------------------------------------------------------------
#  Lectura del proyecto de Whisk3D (.w3d = un zip): el proyecto.json y las mallas .w3db (los arrays de render, las
#  normales y los grupos de vertices del skinning). Solo lo que usa la demo nativa.
# ---------------------------------------------------------------------------------------------------------------
import json
import struct
import zipfile


class Proyecto:
    def __init__(self, ruta):
        self.zip = zipfile.ZipFile(ruta)
        self.json = json.loads(self.zip.read('proyecto.json').decode('utf8'))
        self.mallas = {m['nombre']: m['entrada'] for m in self.json['mallas']}
        self.objetos = {}
        for o in self.json['escena']['objetos']:
            self._indexar(o)

    def _indexar(self, o):
        if 'nombre' in o:
            self.objetos[o['nombre']] = o
        for h in o.get('hijos', []):
            self._indexar(h)

    def leer(self, entrada):
        return self.zip.read(entrada)

    def malla(self, nombre):
        return MallaW3db(self.leer(self.mallas[nombre]))


class MallaW3db:
    """Los bloques de render de un .w3db: posiciones, UV, colores, indices (triangulos) y las partes."""

    def __init__(self, datos):
        if datos[:4] != b'W3DB':
            raise ValueError('no es un .w3db')
        _, version, _, n, _ = struct.unpack_from('<4sIIII', datos, 0)
        p = 20
        self.bloques = {}
        for _ in range(n):
            cc, dominio, cantidad, nbytes = struct.unpack_from('<4sIII', datos, p)
            p += 16
            self.bloques[cc.decode()] = (dominio, cantidad, datos[p:p + nbytes])
            p += (nbytes + 3) & ~3
        _, nv, pos = self.bloques['RPOS']
        self.nv = nv
        self.pos = struct.unpack('<%df' % (nv * 3), pos[:nv * 12])
        self.uv = None
        if 'RUV ' in self.bloques:
            b = self.bloques['RUV '][2]
            self.uv = struct.unpack('<%df' % (nv * 2), b[:nv * 8])
        self.col = None
        if 'RCOL' in self.bloques:
            self.col = self.bloques['RCOL'][2][:nv * 4]
        dom, ntri, b = self.bloques['RIDX']
        if dom & 0x100:
            self.idx = struct.unpack('<%dI' % (ntri * 3), b[:ntri * 12])
        else:
            self.idx = struct.unpack('<%dH' % (ntri * 3), b[:ntri * 6])
        self.nrm = None
        if 'RNRM' in self.bloques:
            self.nrm = struct.unpack('<%db' % (nv * 3), self.bloques['RNRM'][2][:nv * 3])
        # los grupos de vertices (el skinning): nombre -> [(render-vert, peso)]
        self.grupos = {}
        if 'RVGR' in self.bloques:
            _, ng, b = self.bloques['RVGR']
            q = 0
            for _ in range(ng):
                l, = struct.unpack_from('<I', b, q); q += 4
                nom = b[q:q + l].decode(); q += l
                n, = struct.unpack_from('<I', b, q); q += 4
                idx = struct.unpack_from('<%di' % n, b, q); q += 4 * n
                pes = struct.unpack_from('<%df' % n, b, q); q += 4 * n
                self.grupos[nom] = list(zip(idx, pes))
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
