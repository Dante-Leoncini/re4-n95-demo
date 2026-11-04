"""
hud_r100.py: el HUD de Resident Evil 4 (GameCube) en Whisk3D: el medidor de vida (anillo con cuartos que giran y
laten) y el contador de balas, como una escena de interfaz (Whisk3DUI, .w3dui) dibujada sobre la camara del juego.

Datos: out/combate/hud.json + out/combate/hud/*.png (re4_extract_hud.py: las unidades del IDSystem del juego, en una
pantalla virtual de 640x480, ya resueltas a pixeles con origen arriba-izquierda).

Uso (en el mismo espiritu que evento_s03.aplicar):

    import hud_r100
    extra.update(hud_r100.agregar(proy, datos, extra))

  proy  = proyecto.json ya parseado (dict). Se le agrega el nodo {"tipo": "ui", "archivo": "escenas/hud.w3dui"} en el
          PRIMER nivel de proy['escena']['objetos'] (al lado de la Coleccion: el overlay 2D de Whisk3D solo dibuja las
          UI que cuelgan de la raiz de la escena; adentro de la Coleccion el motor la re-cuelga ahi y no se ve).
  datos = entradas del zip -> bytes (no se toca: todo lo nuevo va por 'extra', asi el escritor de make_r100_w3d.py
          lo agrega sin cambios).
  extra = entradas del zip -> archivo local. Se agregan: escenas/hud.w3dui, texturas/hud/*.png, scripts/hud.lua.
          Lo generado (el .w3dui y las texturas horneadas) se escribe en una carpeta temporal (o en 'salida').
  Devuelve 'extra' (el mismo dict, actualizado).

Interfaz con el juego (hud.lua solo LEE): compartido("leon_vida") 0..1200, compartido("balas") (cargadas),
compartido("balas_reserva"), compartido("hud_visible") (false en las cinematicas: el HUD sale deslizando).

ESCALA Y LUGAR: el juego es letterbox tambien jugando (barras negras 640x60 arriba y abajo): la imagen VISIBLE son
las filas 60..420 de la pantalla virtual 640x480, y eso es justo nuestro marco de camara (aspecto 1.7725). Por eso
el HUD se escala UNIFORME por alto/360 (tamModo 2 de Whisk3DUI mide en px x alto/480: los tamanos van x 480/360) y la
raiz (un contenedor de 1280x960 virtuales agarrado por su centro a la esquina abajo-derecha del marco) pone el punto
virtual (640,420) = la esquina de arriba de la barra inferior en esa esquina: el medidor queda a la misma distancia
del borde de abajo de la imagen visible y del borde derecho que en el juego original, en cualquier tamano.

LIMITACION DEL MOTOR: las imagenes 2D de Whisk3D solo mezclan con alpha (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA). Las
unidades ADITIVAS del juego (el brillo de la esfera y los destellos de Precaucion/Peligro, GX_BL_SRCALPHA + GX_BL_ONE)
se aproximan horneando lo que el juego SUMA (S = rgb * a) contra el fondo que se SUPONE debajo (escena gris 0.28 + disco
+ icono o cartel EMPTY): con alpha' = max S/(1-fondo) y color = (S + alpha'*fondo)/alpha' la mezcla da
dst + S + alpha'*(fondo - dst), exacto sobre el fondo supuesto (ver _aditivo). El brillo tiene dos texturas (sobre el
icono / sobre EMPTY); los destellos hacen la misma cuenta en hud.lua con el tinte.

GRANO de pantalla (esp04 de r100, out/r100_fx/emisores.json): imagen a pantalla completa, PRIMERA (detras del medidor),
ruido 256x256 en mosaico (Whisk3D sube las texturas 2D potencia de 2 con GL_REPEAT: uvRect > 1 repite) corrido al azar
cada frame por hud.lua. Sigue visible en las cinematicas.
"""
import io
import json
import os
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
HUD_JSON = os.path.join(HERE, 'out', 'combate', 'hud.json')
HUD_DIR = os.path.join(HERE, 'out', 'combate')        # los "archivo" del json son relativos a esta carpeta
LUA = os.path.join(HERE, 'lua', 'hud.lua')
FX_JSON = os.path.join(HERE, 'out', 'r100_fx', 'emisores.json')   # re4_extract_look / fx: el GRANO de pantalla
FX_TEX = os.path.join(HERE, 'out', 'r100_fx', 'tex')

ENTRADA_UI = 'escenas/hud.w3dui'
ENTRADA_LUA = 'scripts/hud.lua'
TEX = 'texturas/hud/'

# la raiz del HUD: el doble de la pantalla virtual, centrada en la esquina abajo-derecha de la pantalla real
RAIZ_W, RAIZ_H = 1280.0, 960.0
FILAS_VISIBLES = 360.0     # filas virtuales entre las barras del letterbox (60..420) = el alto de nuestro marco
BORDE_ABAJO = 420.0        # fila virtual del borde de abajo de la imagen visible (arriba de la barra inferior)
ESC_TAM = 480.0 / FILAS_VISIBLES   # px virtuales -> unidades de tamModo 2 (que escala por alto/480)
# el pivote del anillo (centro de los cuartos, ancla 2 del juego = su esquina arriba-derecha): 533,371
CUARTO = 44.0              # los cuartos de anillo miden 44x44 (tex 0x20)
CAJA_GIRO = 88.0           # contenedor que gira alrededor del pivote (el doble del cuarto)
DIG_W, DIG_H, DIG_PAD = 16, 24, 2   # tex 0x27: 16x24 por digito; tira propia con 2 px vacios entre digitos


def _rgba(ruta):
    return np.asarray(Image.open(ruta).convert('RGBA'), dtype=np.float32) / 255.0


def _png(arr01, ruta):
    a = np.clip(np.rint(arr01 * 255.0), 0, 255).astype(np.uint8)
    Image.fromarray(a, 'RGBA').save(ruta)


# el fondo que se SUPONE debajo de lo aditivo: la escena (gris medio) vista a traves del disco del medidor
FONDO_ESCENA = 0.28


def _aditivo(rgb, a, fondo):
    """una unidad ADITIVA (suma S = rgb * a) horneada para la mezcla alpha de Whisk3D, suponiendo que debajo hay
    'fondo' (por pixel). Con alpha' = max_c S/(1-fondo) y color = (S + alpha'*fondo)/alpha', la mezcla
    dst*(1-alpha') + alpha'*color = dst + S + alpha'*(fondo - dst): EXACTO cuando lo de abajo es el fondo supuesto, y
    el error es chico si no (ver la limitacion en el encabezado)."""
    s = rgb * a[..., None]
    al = np.clip((s / np.maximum(1.0 - fondo, 1e-3)).max(axis=2), 0.0, 1.0)
    col = np.where(al[..., None] > 1e-6, (s + al[..., None] * fondo) / np.maximum(al, 1e-6)[..., None], 0.0)
    return np.dstack([np.clip(col, 0, 1), al])


def _muestra(tex, x, y):
    """textura (h,w,4) en coords normalizadas 0..1 (arrays), BILINEAL como la dibuja GL (centros de texel en
    (i+0.5)/w, borde clampeado); afuera del quad = transparente."""
    h, w = tex.shape[:2]
    dentro = (x >= 0) & (x < 1) & (y >= 0) & (y < 1)
    fx, fy = x * w - 0.5, y * h - 0.5
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    ax, ay = (fx - x0)[..., None], (fy - y0)[..., None]
    c = lambda xx, yy: tex[np.clip(yy, 0, h - 1), np.clip(xx, 0, w - 1)]     # noqa: E731
    r = (c(x0, y0) * (1 - ax) * (1 - ay) + c(x0 + 1, y0) * ax * (1 - ay) +
         c(x0, y0 + 1) * (1 - ax) * ay + c(x0 + 1, y0 + 1) * ax * ay)
    r[~dentro] = 0.0
    return r


def _fondo_esperado(px, py, capas):
    """lo que hay dibujado (en px virtuales px,py) cuando llega el brillo: la escena gris y encima cada capa
    (textura (h,w,4), centro, tamano, tinte rgba 0..1), mezclada con alpha como la dibuja Whisk3D."""
    fondo = np.full(px.shape + (3,), FONDO_ESCENA, dtype=np.float32)
    for tex, (cx, cy), (w, h), tinte in capas:
        t = _muestra(tex, (px - cx) / w + 0.5, (py - cy) / h + 0.5)
        col = t[..., :3] * np.array(tinte[:3], dtype=np.float32)
        a = t[..., 3:4] * tinte[3]
        fondo = fondo * (1 - a) + a * col
    return fondo


def _empty(hud):
    """cartel EMPTY (id 3F, tex 0x17): centro en pantalla virtual, tamano y color (propio x el del grupo del icono
    de municion, que es su padre: col_final = floor(propio * padre / 255))."""
    crudas = dict((u['nombre'], u) for u in hud['unidades_crudas']['vida'])
    raiz_u, u, grupo = crudas['raiz_hud'], crudas['cartel_EMPTY'], crudas['grupo_icono_municion']
    cx, cy = 320.0 + raiz_u['pos'][0] + u['pos'][0], 240.0 - raiz_u['pos'][1] - u['pos'][1]
    col = [int(a * b / 255) for a, b in zip(u['col0'], grupo['col0'])]
    return (cx, cy), (u['tam'][0], u['tam'][1]), col


def grano():
    """el emisor esp04 'screen tiled overlay' del grupo sst_cuarto 0 de r100 (GRANO de pantalla): textura de ruido
    repetida en mosaico sobre toda la pantalla, alpha 15/255, corrida al azar cada frame."""
    fx = json.load(open(FX_JSON))
    g = [g for g in fx['grupos'] if g.get('fuente') == 'sst_cuarto' and g.get('indice') == 0][0]
    return [e for e in g['emisores'] if e['esp_id'] == '0x04'][0]


def hornear_texturas(hud, salida):
    """escribe en 'salida' las texturas del HUD (las que usan mascara o blend aditivo, horneadas) y devuelve
    {entrada del zip: archivo local}."""
    os.makedirs(salida, exist_ok=True)
    src = lambda n: os.path.join(HUD_DIR, 'hud', n)          # noqa: E731
    out = {}
    # el boton A del cartel de accion + la fuente del juego para su palabra (out/texto/whisk3d, layout ACT_BTN x1.25)
    import shutil
    for nombre, archivo in (('boton_aro.png', 'tex_F2_f0.png'), ('boton_a.png', 'tex_28_f0.png')):
        destino = os.path.join(salida, nombre)
        Image.open(src(archivo)).convert('RGBA').save(destino)
        out[TEX + nombre] = destino
    fdir = os.path.join(os.path.dirname(HUD_DIR), 'texto', 'whisk3d')
    fj = json.load(open(os.path.join(fdir, 'fuente_re4_boton_x125.json')))
    fj['textura'] = 'fuente_boton.png'
    destino = os.path.join(salida, 'fuente_boton.json')
    json.dump(fj, open(destino, 'w'), ensure_ascii=False)
    out[TEX + 'fuente_boton.json'] = destino
    shutil.copy(os.path.join(fdir, 'fuente_re4_boton_x125.png'), os.path.join(salida, 'fuente_boton.png'))
    out[TEX + 'fuente_boton.png'] = os.path.join(salida, 'fuente_boton.png')

    def copiar(nombre, archivo):
        destino = os.path.join(salida, nombre)
        Image.open(src(archivo)).convert('RGBA').save(destino)
        out[TEX + nombre] = destino

    def guardar(nombre, arr):
        destino = os.path.join(salida, nombre)
        _png(arr, destino)
        out[TEX + nombre] = destino

    blanco = _rgba(src('tex_0A_f0.png'))          # 32x32 gris 206 liso
    gris = float(blanco[..., 0].mean())
    m12 = _rgba(src('tex_12_f0.png'))             # esfera (y su alpha = circulo: la mascara del disco)
    m17 = _rgba(src('tex_17_f0.png'))             # cartel EMPTY (y su alpha = circulo: la mascara de los destellos)

    # disco de fondo: tex 0x0A con la mascara 0x12 (tex_flag 1: alpha = mascara.a * col.a, se ignora el de la base)
    d = np.zeros_like(m12)
    d[..., :3] = gris
    d[..., 3] = m12[..., 3]
    guardar('disco.png', d)
    # destellos (Precaucion / Peligro): quad blanco (tex 0x0A) con la mascara 0x17. El color y la curva de alpha van
    # por tinte desde hud.lua (aditivo aproximado con la misma cuenta de _aditivo, suponiendo el disco debajo)
    f = np.zeros_like(m17)
    f[..., :3] = 1.0
    f[..., 3] = m17[..., 3]
    guardar('destello.png', f)
    # brillo de la esfera (tex 0x12, aditivo, color propio (185,225,225) y alpha 125..132 por su curva): se hornea con
    # el color y el alpha MAXIMO de la curva; hud.lua escala con la opacidad (curva/132)
    br = [e for e in hud['elementos_en_orden_de_dibujo'] if e['nombre'] == 'brillo_medidor'][0]
    col = np.array(br['color_propio_col0'][:3], dtype=np.float32) / 255.0
    amax = max(k[1] for k in br['curvas']['color']) / 255.0
    # (el fondo supuesto: la escena gris, el disco y el icono de la pistola, en el espacio de la textura girada)
    el = dict((e['nombre'], e) for e in hud['elementos_en_orden_de_dibujo'])
    # a 256x256 (la esfera re-muestreada bilineal): el fondo supuesto sigue los bordes del icono tal como GL lo
    # filtra; con la resolucion original (64x64) el desfasaje dejaba un halo oscuro alrededor del icono
    (cx, cy), (w, h), rot = br['centro_pivote'], br['tamano'], np.radians(-br['rotacion_z_grados'])
    th = tw = 256
    v, u = np.mgrid[0:th, 0:tw]
    esfera = _muestra(m12, (u + 0.5) / tw, (v + 0.5) / th)
    ox, oy = ((u + 0.5) / tw - 0.5) * w, ((v + 0.5) / th - 0.5) * h
    px = cx + ox * np.cos(rot) - oy * np.sin(rot)       # Whisk3DUI gira horario con y hacia abajo
    py = cy + ox * np.sin(rot) + oy * np.cos(rot)
    c255 = lambda c: [v / 255.0 for v in c]      # noqa: E731
    disco = (d, el['disco_fondo']['centro_pivote'], el['disco_fondo']['tamano'], c255(el['disco_fondo']['color_rgba']))
    ic = el['icono_municion_pistola']
    icono = (_rgba(src('tex_29_f0.png')), ic['centro_pivote'], ic['tamano'], c255(ic['color_rgba']))
    ec, et, ecol = _empty(hud)
    cartel = (m17, ec, et, c255(ecol))
    # DOS versiones: con el icono de la pistola debajo, y con el cartel EMPTY (hud.lua prende una u otra). Con una sola
    # el brillo "dibujaba" el icono encima del EMPTY (su fondo supuesto era el icono)
    guardar('brillo.png', _aditivo(esfera[..., :3] * col, esfera[..., 3] * amax, _fondo_esperado(px, py, [disco, icono])))
    guardar('brillo_empty.png', _aditivo(esfera[..., :3] * col, esfera[..., 3] * amax,
                                         _fondo_esperado(px, py, [disco, icono, cartel])))
    # digitos: tira propia de 10 celdas (0..9) con 2 px transparentes entre cada una (con filtrado bilineal un recorte
    # UV pegado al vecino se "contagia" del digito de al lado)
    paso = DIG_W + DIG_PAD
    tira = np.zeros((DIG_H, paso * 10, 4), dtype=np.float32)
    for n in range(10):
        c = _rgba(src('tex_27_f%d.png' % n))
        tira[:, n * paso + DIG_PAD // 2: n * paso + DIG_PAD // 2 + DIG_W] = c
    guardar('digitos.png', tira)
    copiar('cuarto.png', 'tex_20_f0.png')         # cuarto de anillo (0x20), blanco: el color lo da el latido
    copiar('marco.png', 'tex_1D_f0.png')          # marco de piedra (0x1D)
    copiar('nombre_leon.png', 'tex_39_f0.png')    # "Leon" (0x39)
    copiar('icono_pistola.png', 'tex_29_f0.png')  # bala de pistola (0x29)
    copiar('empty.png', 'tex_17_f0.png')          # cartel EMPTY (0x17)
    copiar('blanco.png', 'tex_0A_f0.png')         # la rayita de la vida maxima
    # el grano de pantalla (ruido 256x256: potencia de 2 -> Whisk3D la sube con GL_REPEAT y el mosaico sale con un
    # uvRect mas grande que 1). Nombre propio (texturas/hud/): si compartiera ruta con una textura 3D el 2D usaria
    # esa subida y su modo de wrap.
    destino = os.path.join(salida, 'grano.png')
    Image.open(os.path.join(FX_TEX, grano()['textura']['archivos'][0])).convert('RGBA').save(destino)
    out[TEX + 'grano.png'] = destino
    return out


# ---------------------------------------------------------------------------------------------------------------
#  la escena .w3dui
# ---------------------------------------------------------------------------------------------------------------
def _pos(vx, vy):
    """punto de la pantalla virtual 640x480 -> pos relativa (fraccion) dentro de la raiz de 1280x960, cuyo centro es
    el punto virtual (640,420) = la esquina abajo-derecha de la imagen visible (= la del marco de camara)."""
    return [round((vx - 640.0) / RAIZ_W, 6), round((vy - BORDE_ABAJO) / RAIZ_H, 6), 0]


def _elem(tipo, nombre, pos, ancho, alto, rot=0.0, hijos=None, visible=True, opacidad=1.0, **kw):
    e = {'tipo': tipo, 'nombre': nombre, 'visible': visible, 'pos': pos, 'ancla': 0, 'rotacion': rot,
         'opacidad': opacidad, 'ancho': round(ancho * ESC_TAM, 4), 'alto': round(alto * ESC_TAM, 4), 'tamPx': False,
         'tamModo': 2}
    e.update(kw)
    e['hijos'] = hijos or []
    return e


def _img(nombre, pos, ancho, alto, textura, tinte=(1, 1, 1, 1), rot=0.0, **kw):
    t = [round(float(c), 5) for c in tinte]
    return _elem('imagen', nombre, pos, ancho, alto, rot=rot, textura=TEX + textura, modo=0, tinte=t,
                 usarAlpha=True, filtrado=True, palTinte=-1, **kw)


def _c255(c, a=None):
    r = [v / 255.0 for v in c[:3]]
    return r + [(c[3] if a is None else a) / 255.0]


def escena(hud):
    """arma el dict del .w3dui (orden de hijos = orden de dibujo, como la tabla OT del juego)."""
    el = dict((e['nombre'], e) for e in hud['elementos_en_orden_de_dibujo'])
    crudas = dict((u['nombre'], u) for u in hud['unidades_crudas']['vida'])
    raiz_u = crudas['raiz_hud']
    # la raiz del medidor en pantalla (visible = al final del camino de entrada): x = 320 + X, y = 240 - Y
    rx, ry = 320.0 + raiz_u['pos'][0], 240.0 - raiz_u['pos'][1]

    def hijo_raiz(u):
        return rx + u['pos'][0], ry - u['pos'][1]

    h = []
    # 1) disco oscuro de fondo (tex 0x0A + mascara 0x12)
    e = el['disco_fondo']
    h.append(_img('hud_disco', _pos(*e['centro_pivote']), e['tamano'][0], e['tamano'][1], 'disco.png',
                  _c255(e['color_rgba'])))
    # 2) destello de Precaucion/Peligro (aditivo aproximado; se dibuja apenas arriba del disco para no apagar los
    #    digitos: ver el encabezado). Oculto hasta que hud.lua lo prenda.
    dp = hud['elementos_extra_por_estado']['peligro'][0]
    h.append(_img('hud_destello', _pos(*dp['centro_pivote']), dp['tamano'][0], dp['tamano'][1], 'destello.png',
                  (1, 0, 0, 0), visible=False))
    # 3) los tres cuartos de anillo: cada uno en un contenedor centrado en el pivote del anillo que gira (Whisk3DUI
    #    gira un elemento alrededor de su centro; el cuarto va corrido para que su esquina arriba-derecha caiga en el
    #    centro del contenedor = el ancla 2 del juego). Orden de dibujo del juego: 3, 2, 1.
    q = el['cuarto_vida_1']
    px, py = q['centro_pivote']
    for n in (3, 2, 1):
        img = _img('hud_cuarto_%d_img' % n, [-0.25, 0.25, 0], CUARTO, CUARTO, 'cuarto.png', (0, 85 / 255.0, 0, 1))
        h.append(_elem('contenedor', 'hud_cuarto_%d' % n, _pos(px, py), CAJA_GIRO, CAJA_GIRO,
                       rot=-90.0 if n == 1 else 0.0, hijos=[img], visible=(n == 1)))
    # 4) icono de la municion del arma (bala de pistola, tex 0x29)
    e = el['icono_municion_pistola']
    h.append(_img('hud_icono_municion', _pos(*e['centro_pivote']), e['tamano'][0], e['tamano'][1],
                  'icono_pistola.png', _c255(e['color_rgba'])))
    # 5) digitos (tira 0x27): unidades, decenas, centenas (el juego los dibuja en ese orden: cada uno pisa al anterior)
    paso = DIG_W + DIG_PAD
    ancho_tira = paso * 10.0
    for nombre, cruda in (('hud_digito_unidades', 'digito_unidades'), ('hud_digito_decenas', 'digito_decenas'),
                          ('hud_digito_centenas', 'digito_centenas')):
        u = crudas[cruda]
        cx, cy = hijo_raiz(u)
        d = 1 if cruda == 'digito_decenas' else 0
        u0 = (d * paso + DIG_PAD // 2) / ancho_tira
        h.append(_img(nombre, _pos(cx, cy), u['tam'][0], u['tam'][1], 'digitos.png', _c255(u['col0']),
                      visible=(cruda != 'digito_centenas'),
                      uvU0=round(u0, 6), uvV0=0, uvU1=round(u0 + DIG_W / ancho_tira, 6), uvV1=1))
    # 6) cartel EMPTY (id 3F, tex 0x17): hijo del grupo del icono de municion -> color propio x el del grupo
    (cx, cy), (w, hh), col = _empty(hud)
    h.append(_img('hud_empty', _pos(cx, cy), w, hh, 'empty.png', _c255(col), visible=False))
    # 7) brillo de la esfera (aditivo aproximado, horneado con su color; gira -15 en el juego = 15 en Whisk3D, que
    #    gira en sentido horario con y hacia abajo)
    #    Dos: la horneada sobre el icono y la horneada sobre el cartel EMPTY (ver hornear_texturas)
    e = el['brillo_medidor']
    h.append(_img('hud_brillo', _pos(*e['centro_pivote']), e['tamano'][0], e['tamano'][1], 'brillo.png',
                  rot=-e['rotacion_z_grados']))
    h.append(_img('hud_brillo_empty', _pos(*e['centro_pivote']), e['tamano'][0], e['tamano'][1], 'brillo_empty.png',
                  rot=-e['rotacion_z_grados'], visible=False))
    # 8) marco de piedra y el nombre
    e = el['marco_medidor']
    h.append(_img('hud_marco', _pos(*e['centro_pivote']), e['tamano'][0], e['tamano'][1], 'marco.png',
                  _c255(e['color_rgba'])))
    e = el['nombre_Leon']     # ancla 1 del juego: el pivote es su esquina arriba-izquierda
    x0, y0, w, hh = e['pantalla_rect_xywh']
    h.append(_img('hud_nombre', _pos(x0 + w / 2, y0 + hh / 2), w, hh, 'nombre_leon.png', _c255(e['color_rgba'])))
    # 9) la rayita de la vida MAXIMA: grupo 0xFE centrado en el pivote del anillo que gira nivel*(-135)/20 - 45; la
    #    rayita (2x10) cuelga a 39 px del centro
    e = el['marca_vida_max']
    mu = crudas['marca_vida_max']
    marca = _img('hud_marca_vida_max_img', [0, round(-mu['pos'][1] / CAJA_GIRO, 6), 0], e['tamano'][0],
                 e['tamano'][1], 'blanco.png', _c255(e['color_rgba']))
    h.append(_elem('contenedor', 'hud_marca_vida_max', _pos(px, py), CAJA_GIRO, CAJA_GIRO, rot=45.0, hijos=[marca]))

    raiz = _elem('contenedor', 'hud_raiz', [0, 0, 0], RAIZ_W, RAIZ_H, hijos=h)
    raiz['ancla'] = 8          # agarrada por su centro a la esquina abajo-derecha de la pantalla
    # GRANO de pantalla (esp04 de r100): PRIMERO (detras del medidor), toda la pantalla (tamModo 0 = fraccion), color
    # = ruido x (1,1,1,alfa). El mosaico y el temblor los pone hud.lua con setUVRect cada frame (sigue en las
    # cinematicas: solo el medidor se oculta)
    gr = grano()
    fondo = _elem('imagen', 'hud_grano', [0, 0, 0], 1.0, 1.0, textura=TEX + 'grano.png', modo=0,
                  tinte=gr['color'] + [round(gr['alfa'], 5)], usarAlpha=True, filtrado=True, palTinte=-1,
                  uvU0=0, uvV0=0, uvU1=2.56, uvV1=1.685)
    fondo['tamModo'] = 0
    fondo['ancho'] = fondo['alto'] = 1.0   # toda la pantalla (fraccion)
    # el FUNDIDO a/desde negro (encima de todo): hud.lua lo anima con compartido "fundido" (objetivo 0..1),
    # "fundido_seg" (duracion) y "fundido_ya" (valor inmediato)
    fundido = _elem('rect', 'hud_fundido', [0, 0, 0], 1.0, 1.0, visible=False, color=[0, 0, 0, 1], palColor=-1)
    fundido['tamModo'] = 0
    fundido['ancho'] = fundido['alto'] = 1.0
    # el CARTEL DEL BOTON DE ACCION (hud.json boton_accion_A + layout ACT_BTN de la fuente): el boton A (aro aditivo +
    # la letra) y la palabra a su derecha. Contenedor anclado ABAJO AL CENTRO: su centro = el punto virtual (320, 420)
    def pos_c(vx, vy):
        return [round((vx - 320.0) / RAIZ_W, 6), round((vy - BORDE_ABAJO) / RAIZ_H, 6), 0]
    aro = _img('hud_accion_aro', pos_c(261.0, 391.0), 51.07, 51.0, 'boton_aro.png', (125 / 255.0, 105 / 255.0, 1.0, 1.0),
               mezcla=3)
    letra = _img('hud_accion_letra', pos_c(260.0, 392.0), 35.03, 35.32, 'boton_a.png')
    txt = _elem('texto', 'hud_accion_texto', pos_c(285.0, 378.0), 320.0, 44.0, texto='TALK',   # alineado a la izq. DESDE su posicion
                tam=round(31 * ESC_TAM, 3), alignX=0, alignY=1, color=[229 / 255.0, 217 / 255.0, 207 / 255.0, 1.0],
                fuente='', fuenteBitmap=TEX + 'fuente_boton.json', lineas=0, autoTam=False, palColor=-1)
    accion = _elem('contenedor', 'hud_accion', [0, 0, 0], RAIZ_W, RAIZ_H, hijos=[aro, letra, txt], visible=False)
    accion['ancla'] = 4        # agarrado por su centro al borde de abajo, al medio
    return {
        'version': 1,
        'nombre': 'HUD',
        'ventana': {'igualQueRender': True, 'ancho': 640, 'alto': 480, 'escalaGlobal': 1,
                    'escalaIgualEditor': False, 'color': [0, 0, 0, 0]},
        'padUni': True, 'padIzq': 0, 'padDer': 0, 'padArr': 0, 'padAba': 0,
        'layoutHijos': 0, 'layoutAjuste': 0, 'layoutAlign': 0, 'distribucion': 0, 'gap': 0, 'padGapPx': True,
        'overflowX': False, 'overflowY': False, 'scroll': False, 'scrollX': 0, 'scrollY': 0,
        'scripts': [{'ruta': ENTRADA_LUA, 'refs': {}}],
        'hijos': [fondo, raiz, accion, fundido],
    }


def agregar(proy, datos, extra, salida=None):
    """agrega el HUD al proyecto: nodo UI en la raiz de la escena + .w3dui + texturas + scripts/hud.lua.
    'salida' = carpeta para lo generado (default: una temporal nueva, que queda hasta que se escriba el zip)."""
    hud = json.load(open(HUD_JSON))
    salida = salida or tempfile.mkdtemp(prefix='hud_r100_')
    extra.update(hornear_texturas(hud, salida))
    ruta_ui = os.path.join(salida, 'hud.w3dui')
    with open(ruta_ui, 'w', encoding='utf-8') as f:
        json.dump(escena(hud), f, ensure_ascii=False, indent=1)
    extra[ENTRADA_UI] = ruta_ui
    extra[ENTRADA_LUA] = LUA
    objs = proy['escena']['objetos']
    objs[:] = [o for o in objs if not (o.get('tipo') == 'ui' and o.get('archivo') == ENTRADA_UI)]
    objs.append({'tipo': 'ui', 'archivo': ENTRADA_UI})
    # si el proyecto ya traia estas entradas (un HUD viejo), el escritor usa 'datos' para las existentes y saltea las
    # de 'extra' con el mismo nombre: se pisan sus bytes con los nuevos
    for k in (ENTRADA_UI, ENTRADA_LUA) + tuple(n for n in extra if n.startswith(TEX)):
        if k in datos:
            datos[k] = open(extra[k], 'rb').read()
    return extra


if __name__ == '__main__':
    h = json.load(open(HUD_JSON))
    print(json.dumps(hornear_texturas(h, tempfile.mkdtemp(prefix='hud_r100_')), indent=1))
    print(json.dumps(escena(h), indent=1)[:2000])
