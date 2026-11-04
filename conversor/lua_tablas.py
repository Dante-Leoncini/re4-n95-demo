"""Las tablas que make_sonic_w3d.py inyecto arriba de los scripts del proyecto (ANILLOS = {...}, FISICA = {...}): un
lector de los literales de Lua (numeros, textos, true/false/nil y tablas con o sin claves) -> listas y diccionarios.
Una tabla con claves y sin elementos sueltos sale como dict; una sin claves, como list; mezclada, dict con los
elementos sueltos en 1, 2, 3..."""
import re

_TOKEN = re.compile(r'\s*(?:(--[^\n]*)|("(?:[^"\\]|\\.)*")|([A-Za-z_][A-Za-z_0-9]*)|(-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)|(.))')


def _tokens(texto):
    for m in _TOKEN.finditer(texto):
        com, cad, nom, num, sim = m.groups()
        if com:
            continue
        if cad is not None:
            yield ('cad', cad[1:-1])
        elif nom is not None:
            yield ('nom', nom)
        elif num is not None:
            yield ('num', float(num) if any(c in num for c in '.eE') else int(num))
        elif sim is not None and not sim.isspace():
            yield ('sim', sim)


class _Lector:
    def __init__(self, toks):
        self.t = list(toks)
        self.i = 0

    def ver(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ('fin', None)

    def tomar(self):
        v = self.ver()
        self.i += 1
        return v

    def valor(self):
        tipo, v = self.tomar()
        if tipo == 'sim' and v == '{':
            return self.tabla()
        if tipo == 'sim' and v == '-':
            return -self.valor()
        if tipo == 'nom':
            return {'true': True, 'false': False, 'nil': None}.get(v, v)
        return v

    def tabla(self):
        lista, dic = [], {}
        while True:
            tipo, v = self.ver()
            if tipo == 'sim' and v == '}':
                self.tomar()
                break
            if tipo == 'nom' and self.ver(1) == ('sim', '='):
                self.tomar(); self.tomar()
                dic[v] = self.valor()
            else:
                lista.append(self.valor())
            if self.ver() in (('sim', ','), ('sim', ';')):
                self.tomar()
        if not dic:
            return lista
        for k, x in enumerate(lista):
            dic[k + 1] = x
        return dic


def tablas(lua):
    """las asignaciones globales en MAYUSCULAS del principio del script: {nombre: valor}"""
    out = {}
    for linea in lua.splitlines():
        m = re.match(r'^([A-Z][A-Z_0-9]*)\s*=\s*(.*)$', linea)
        if not m:
            continue
        l = _Lector(_tokens(m.group(2)))
        out[m.group(1)] = l.valor()
    return out
