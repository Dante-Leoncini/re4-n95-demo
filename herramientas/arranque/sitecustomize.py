"""Se carga solo en cada Python que lanza re4n95.py (tambien en los extractores que lanzan otros extractores): deja la
libreria de animaciones ya compilada en lugar de compilarla con make (que en Windows no esta)."""
import os
import sys

_tools = os.environ.get('RE4N95_DECOMP_TOOLS')
_lib = os.environ.get('RE4N95_HOST')
if _tools and _lib:
    if _tools not in sys.path:
        sys.path.append(_tools)
    try:
        from motion import evalhost as _evalhost
        _evalhost.build = lambda variant='plain': _lib
    except ImportError:
        pass
