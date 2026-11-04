"""
libreria_r100.py: el NIVEL r100 usa a los personajes de la LIBRERIA re4_personajes.w3d (make_personajes_w3d.py) con
PROXIES W3D en vez de importarlos adentro. Lo usa make_r100_w3d.py (y combate_r100 / emboscada_r100 para sus proxies).

  * el registro "librerias" del proyecto: {"nombre": "re4_personajes", "archivo": "ext:<relativo al nivel>"}
  * un proxy por personaje: {"tipo": "proxy", "libreria", "elemento" (el prefab), pos / rot / escala, "overrides"}.
    El proxy se llama "Proxy_<prefab>": el objeto que GENERA conserva el nombre del prefab ("Leon", "Ganado_juego"),
    asi buscar("Leon") desde cualquier script del nivel encuentra al armature (no al proxy). Los nombres de adentro
    se resuelven primero en el scope del proxy y despues en el nivel (los Child Of a "Leon", buscar("Pistola")...).
  * scripts/colocar.lua en el Empty "Personajes_colocar" (PRIMERO en el arbol: corre antes que todos): el proxy
    UBICA al personaje (su transform), pero leon.lua / ganado.lua y los scripts del nivel trabajan en coordenadas de
    MUNDO con posicion() / setPosicion(), que son relativas al padre. Al arrancar la partida cada proxy le pasa su
    transform al objeto que genera y queda en el origen (en el editor, sin jugar, se ven ubicados igual).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NOMBRE = 're4_personajes'
ARCHIVO = os.path.join(HERE, 're4_personajes.w3d')
PREFIJO_PROXY = 'Proxy_'


class Libreria(object):
    """la libreria de personajes vista desde un nivel: arma los proxies y lleva la cuenta para colocar.lua"""

    def __init__(self, archivo=ARCHIVO, nombre=NOMBRE):
        self.archivo = os.path.abspath(archivo)
        self.nombre = nombre
        self.proxies = []          # [(nombre del proxy, objeto raiz que genera)] en el orden en que se crearon

    def registro(self, salida):
        """la fila del registro "librerias" del nivel que se escribe en 'salida' (ext: relativo a su carpeta)"""
        rel = os.path.relpath(self.archivo, os.path.dirname(os.path.abspath(salida)))
        return {'nombre': self.nombre, 'archivo': 'ext:' + rel.replace(os.sep, '/')}

    def proxy(self, prefab, pos, rot=(0, 0, 0), escala=(1, 1, 1), visible=None, props=None, raiz=None):
        """el nodo proxy del prefab 'prefab' de la libreria. visible: {ruta: bool} (ruta '.' = el objeto raiz que
        genera); props: {propiedad de script: valor} (se aplica a los scripts de adentro que la declaren)."""
        nombre = PREFIJO_PROXY + prefab
        o = {'tipo': 'proxy', 'nombre': nombre, 'pos': [round(float(v), 5) for v in pos],
             'rot': [round(float(v), 4) for v in rot], 'escala': [round(float(v), 5) for v in escala],
             'libreria': self.nombre, 'elemento': prefab}
        ov = {}
        if props:
            ov['propiedades'] = dict((k, str(v)) for k, v in sorted(props.items()))
        if visible:
            ov['visible'] = dict(sorted(visible.items()))
        if ov:
            o['overrides'] = ov
        self.proxies.append((nombre, raiz or prefab))
        return o

    def colocar(self):
        """(Empty "Personajes_colocar" con scripts/colocar.lua, texto de colocar.lua)"""
        filas = ',\n'.join('    {"%s", "%s"}' % p for p in self.proxies)
        emp = {'tipo': 'objeto', 'nombre': 'Personajes_colocar', 'pos': [0, 0, 0], 'rot': [0, 0, 0],
               'escala': [1, 1, 1], 'scripts': [{'archivo': 'scripts/colocar.lua'}]}
        return emp, LUA_COLOCAR % filas


LUA_COLOCAR = '''-- colocar.lua: los PERSONAJES del nivel son proxies de la libreria re4_personajes (generado por libreria_r100.py).
--
-- El proxy es el que UBICA al personaje en el nivel (su posicion, su giro y su escala), como cualquier instancia
-- de prefab. Pero leon.lua, ganado.lua y los scripts del nivel (los eventos, la emboscada) trabajan en coordenadas
-- de MUNDO con posicion() / setPosicion() / rotacion(), que son relativas al PADRE. Este script va en el primer
-- objeto del arbol (corre su inicio() antes que todos): cada proxy le pasa su transform al objeto raiz que genera
-- y queda en el origen; desde ahi la posicion del armature ES la del mundo. (Giro solo alrededor de Y y escala
-- uniforme: los personajes no se inclinan.) El Stop del editor repone todo como estaba.

local PROXIES = {
%s
}

function inicio()
    for _, p in ipairs(PROXIES) do
        local px = buscar(p[1])
        local r = px and buscar(p[2], px)
        if r then
            local x, y, z = puntoMundo(r, 0, 0, 0)
            local _, ryp = rotacion(px)
            local _, ryr = rotacion(r)
            local sp = escala(px)
            local sr = escala(r)
            setPosicion(r, x, y, z)
            setRotacion(r, 0, (ryp or 0) + (ryr or 0), 0)
            setEscala(r, (sp or 1) * (sr or 1))
            setPosicion(px, 0, 0, 0)
            setRotacion(px, 0, 0, 0)
            setEscala(px, 1, 1, 1)
        else
            aviso("colocar: no esta el proxy " .. p[1] .. " (o no genero " .. p[2] .. ")")
        end
    end
end
'''
