#!/usr/bin/env python3
"""Texturas de los efectos del disparo (out/efectos, exportadas por tools/re4_eff.py) -> out/leon/fx/,
a la mitad y en potencia de 2 (N95). El fogonazo es un flipbook de 2 cuadros en una tira."""
import os
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, 'out', 'efectos')
DST = os.path.join(HERE, 'out', 'leon', 'fx')


def mitad(nombre, lado):
    return Image.open(os.path.join(SRC, nombre)).convert('RGBA').resize((lado, lado), Image.BOX)


def main():
    os.makedirs(DST, exist_ok=True)
    tira = Image.new('RGBA', (64, 32))
    tira.paste(mitad('wep02_tex22_f0.png', 32), (0, 0))      # starburst del fogonazo, cuadro 0
    tira.paste(mitad('wep02_tex22_f1.png', 32), (32, 0))     # cuadro 1
    tira.save(os.path.join(DST, 'fx_fogonazo.png'))
    mitad('core_tex1E_f0.png', 64).save(os.path.join(DST, 'fx_humo.png'))
    mitad('core_tex1F_f0.png', 64).save(os.path.join(DST, 'fx_humo2.png'))
    mitad('core_tex08_f0.png', 32).save(os.path.join(DST, 'fx_chispa.png'))   # brillo radial (las chispas son lineas en GX)
    print('->', DST, sorted(os.listdir(DST)))


if __name__ == '__main__':
    main()
