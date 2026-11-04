"""Lee un .glb (glTF binario): el JSON y los accessors como arreglos de numpy."""
import json
import struct

import numpy as np

TIPOS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
COMPONENTES = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class Glb:
    def __init__(self, ruta):
        b = open(ruta, 'rb').read()
        if b[:4] != b'glTF':
            raise ValueError('%s no es un .glb' % ruta)
        n = struct.unpack_from('<I', b, 12)[0]
        self.json = json.loads(b[20:20 + n])
        o = 20 + n
        m = struct.unpack_from('<I', b, o)[0]
        self.bin = b[o + 8:o + 8 + m]

    def accessor(self, i):
        a = self.json['accessors'][i]
        v = self.json['bufferViews'][a['bufferView']]
        tipo = np.dtype(TIPOS[a['componentType']])
        comp = COMPONENTES[a['type']]
        inicio = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        paso = v.get('byteStride', 0) or tipo.itemsize * comp
        n = a['count']
        if paso == tipo.itemsize * comp:
            arr = np.frombuffer(self.bin, tipo, n * comp, inicio).reshape(n, comp)
        else:
            arr = np.stack([np.frombuffer(self.bin, tipo, comp, inicio + k * paso) for k in range(n)])
        if comp == 1:
            arr = arr.reshape(n)
        return arr.copy()

    def nodo(self, nombre):
        for k, n in enumerate(self.json['nodes']):
            if n.get('name') == nombre:
                return k
        raise KeyError(nombre)
