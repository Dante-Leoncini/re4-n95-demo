"""Lo que se ve desde adentro de la casa para el mapa del N95 (rayos; el juego del telefono solo dibuja eso adentro)."""
import json
import os
import sys

import pvs_interior

carpeta = sys.argv[1]
glb = os.path.join(carpeta, 'r100.glb')
info = json.load(open(os.path.join(carpeta, 'r100.json')))
vis, n, _ = pvs_interior.calcular(glb, info['piezas'])
firma = '%d-%d' % (os.path.getsize(glb), int(os.path.getmtime(glb)))
json.dump({'firma': firma, 'visibles': sorted(vis), 'total': n}, open(os.path.join(carpeta, 'pvs_interior.json'), 'w'),
          indent=1)
print('interior: %d de %d chunks' % (len(vis), n))
