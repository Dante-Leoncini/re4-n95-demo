#!/usr/bin/env python3
"""
unir_clips.py: junta en UN glb las animaciones de varios glb con el MISMO esqueleto (mismos nombres de nodos).
Toma el primero entero (mallas, esqueleto, atlas, sus clips) y le agrega los clips de los demas: cada canal se
re-apunta al nodo del mismo nombre del primero. Asi un solo armature de Whisk3D reproduce los clips de varios
eventos (la intro y las charlas con los policias) sin importar el modelo N veces.

    python3 tools_r100/unir_clips.py salida.glb base.glb otro1.glb [otro2.glb ...]
"""
import json
import struct
import sys


def leer(ruta):
    b = open(ruta, 'rb').read()
    off, doc, binario = 12, None, b''
    while off < len(b):
        n, tipo = struct.unpack('<II', b[off:off + 8])
        datos = b[off + 8:off + 8 + n]
        if tipo == 0x4E4F534A:
            doc = json.loads(datos)
        elif tipo == 0x004E4942:
            binario = datos
        off += 8 + n
    return doc, bytearray(binario)


def escribir(ruta, doc, binario):
    while len(binario) % 4:
        binario.append(0)
    doc['buffers'] = [{'byteLength': len(binario)}]
    j = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    while len(j) % 4:
        j += b' '
    total = 12 + 8 + len(j) + 8 + len(binario)
    with open(ruta, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(j), 0x4E4F534A)); f.write(j)
        f.write(struct.pack('<II', len(binario), 0x004E4942)); f.write(bytes(binario))


def copiar_accessor(base, bbin, otro, obin, ia):
    a = dict(otro['accessors'][ia])
    bv = otro['bufferViews'][a['bufferView']]
    datos = obin[bv.get('byteOffset', 0):bv.get('byteOffset', 0) + bv['byteLength']]
    while len(bbin) % 4:
        bbin.append(0)
    nuevo = {'buffer': 0, 'byteOffset': len(bbin), 'byteLength': len(datos)}
    if 'byteStride' in bv:
        nuevo['byteStride'] = bv['byteStride']
    bbin.extend(datos)
    base['bufferViews'].append(nuevo)
    a['bufferView'] = len(base['bufferViews']) - 1
    base['accessors'].append(a)
    return len(base['accessors']) - 1


def unir(salida, rutas):
    base, bbin = leer(rutas[0])
    por_nombre = {n.get('name'): i for i, n in enumerate(base['nodes'])}
    ya = {a.get('name') for a in base.get('animations', [])}
    base.setdefault('animations', [])
    for r in rutas[1:]:
        otro, obin = leer(r)
        for anim in otro.get('animations', []):
            if anim.get('name') in ya:
                continue
            nueva = {'name': anim.get('name'), 'samplers': [], 'channels': []}
            if 'extras' in anim:
                nueva['extras'] = anim['extras']
            mapa = {}
            for c in anim['channels']:
                nodo = otro['nodes'][c['target']['node']].get('name')
                if nodo not in por_nombre:
                    continue
                s = c['sampler']
                if s not in mapa:
                    sm = anim['samplers'][s]
                    mapa[s] = len(nueva['samplers'])
                    nueva['samplers'].append({'input': copiar_accessor(base, bbin, otro, obin, sm['input']),
                                              'output': copiar_accessor(base, bbin, otro, obin, sm['output']),
                                              'interpolation': sm.get('interpolation', 'LINEAR')})
                nueva['channels'].append({'sampler': mapa[s], 'target': {'node': por_nombre[nodo],
                                                                         'path': c['target']['path']}})
            if nueva['channels']:
                base['animations'].append(nueva)
                ya.add(nueva['name'])
    escribir(salida, base, bbin)
    return [a['name'] for a in base['animations']]


if __name__ == '__main__':
    print(unir(sys.argv[1], sys.argv[2:]))
