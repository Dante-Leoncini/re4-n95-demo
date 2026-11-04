<p align="center">
  <a href="README.md">English</a> | <b>Español</b>
</p>

# Resident Evil 4 en el Nokia N95 (demo de Whisk3D)

El primer cuarto de **Resident Evil 4** (GameCube): la llegada en la camioneta, la llamada de radio, el camino, la casa
del aldeano y la emboscada, corriendo **nativo en un Nokia N95** (2007) con el motor de
[Whisk3D](https://github.com/Dante-Leoncini/Whisk3D-Editor).

**Este repositorio existe solo para demostrar que la demo es real**: que corre de verdad en el teléfono y no es un video
hecho con IA, un montaje ni una actuación. Cualquiera con su propia copia del juego puede armar los datos y probarla.

- **No contiene nada del juego.** Ni modelos, ni texturas, ni sonidos, ni código del juego. Los datos los genera cada
  uno desde **su propio disco**.
- La demo es **solo para el Nokia N95** (Symbian S60 3rd FP1). En un Nokia táctil (S60 5th, Symbian^3) hace falta
  conectarle un teclado o un joystick de PS3.
- Los recursos del juego original se extrajeron y se adaptaron para correr en Whisk3D con la ayuda de **Claude
  Opus 5.5**.

## Qué hay acá

| | |
|---|---|
| `demo/re4.sisx` | el instalador de la demo para el N95 (solo el programa, sin datos) |
| `re4n95.py` | arma la carpeta de datos desde tu disco |
| `extractores/`, `conversor/`, `herramientas/` | lo que usa `re4n95.py` (código propio, salvo lo indicado en *Créditos*) |
| `demo/datos/` | la intro y la fuente de Whisk3D (no son del juego) |

## Lo que necesitás

- **Tu disco** de Resident Evil 4 para GameCube, **versión USA, disco 1**, como imagen `.rvz`, `.iso` o `.gcm`
  (por ejemplo, sacada de tu consola con un homebrew de backup y convertida con Dolphin).
- **Python 3.10 o más nuevo** con `numpy` y `pillow` (`pip install numpy pillow`).
- **git**.
- **g++** (para compilar dos librerías chicas en tu máquina):
  - Windows: [MSYS2](https://www.msys2.org/) y, en su consola, `pacman -S mingw-w64-x86_64-gcc`. Después agregá
    `C:\msys64\mingw64\bin` al PATH.
  - Linux: `sudo apt install g++` (o el paquete de tu distribución).
- **El editor Whisk3D** (se usa para armar los modelos y las animaciones). Se compila desde
  [Whisk3D-Editor](https://github.com/Dante-Leoncini/Whisk3D-Editor):
  - Windows: `platform\windows\build_windows.bat` (necesita Visual Studio y CMake; el ejecutable queda en
    `platform\windows\build\Release\whisk3d.exe`).
  - Linux: ver `platform/linux` en ese repositorio.
- Unos **3 GB libres** y una conexión a internet (el script baja dos herramientas libres: ver *Créditos*).

## Armar los datos

Windows (en una consola, desde la carpeta de este repositorio):

```bat
python re4n95.py --disco "D:\juegos\Resident Evil 4 (USA) (Disc 1).rvz" --whisk3d "C:\Whisk3D-Editor\platform\windows\build\Release\whisk3d.exe"
```

Linux:

```sh
python3 re4n95.py --disco ~/juegos/re4_disco1.iso --whisk3d ~/Whisk3D-Editor/platform/linux/build/whisk3d
```

El script dice cuántos pasos son y cómo va cada uno:

```
Resident Evil 4 -> datos del Nokia N95: 31 pasos
[ 1/31] Preparar la carpeta de trabajo... listo (2 s)
[ 2/31] Bajar la decompilacion publica (para las animaciones)... listo (6 s)
...
TERMINADO en 42 min 44 s.
Los datos estan en: ...\datos
```

Tarda entre 25 y 40 minutos según la máquina; el paso más largo es *El mapa del N95* (calcula con rayos qué se ve
desde adentro de la casa: unos 15 minutos). Si algo se corta, volvé a correr **el mismo comando**: sigue desde el paso
que faltaba. Lo que hace cada paso queda anotado en `trabajo/registro/`. La carpeta `trabajo/` se puede borrar al
terminar.

## Instalar en el N95

1. Copiá la carpeta `datos` que armó el script a la tarjeta de memoria del teléfono como **`E:\re4\datos`**
   (con el cable USB en modo almacenamiento, o con Nokia PC Suite). Tiene que quedar `E:\re4\datos\mundo.bin`,
   `E:\re4\datos\sonidos\...`, etc.
2. Instalá `demo/re4.sisx` en la tarjeta (E:). El certificado es propio: si el teléfono no deja instalar
   aplicaciones sin firmar, en *Gestor de aplicaciones > Opciones > Configuración* poné *Instalación de software:
   Todas*.
3. Si el teléfono no tiene **Open C / Open C++** (el N95 de fábrica no lo trae), instalá antes los paquetes de
   Open C / Open C++ para S60 3rd (el *Open C/C++ plug-in* de Nokia).
4. Abrí *Resident Evil 4* desde el menú de aplicaciones.

## Controles

| | Teclado del N95 | Joystick de PS3 (Bluetooth) |
|---|---|---|
| Caminar / girar | cruceta (o 2 4 6 8) | stick izquierdo o cruceta |
| Correr | dos toques adelante y mantener | R2 mantenido |
| Media vuelta | dos toques atrás | |
| Apuntar | OK (o 5) | R1 o L2 mantenido |
| Disparar | OK apuntando | X apuntando |
| Acción del cartel (patear, saltar, hablar) | OK, o softkey izquierdo (también apuntando) | cuadrado (o X sin apuntar) |
| Cuchillo | softkey derecho | L1 mantenido |
| Recargar | 0 | círculo |
| Saltar una cinemática | OK | X |
| Pausa (detalle, niebla, brillo, FPS) | softkey izquierdo | Start |
| Cuadros por segundo | # | |

## Cómo se extraen los recursos (explicación educativa)

Todo se hace **de buena fe**: el propósito es mostrar que un teléfono de 2007 puede mover una escena de un juego de
GameCube, no distribuir el juego. Nada de lo que sale del disco se publica, y solo se toma lo necesario para el primer
cuarto. A grandes rasgos:

1. **Leer el disco.** La imagen de GameCube es un sistema de archivos; [dtk](https://github.com/encounter/decomp-toolkit)
   copia de ahí los archivos que hacen falta (unos 55, 77 MB): el cuarto (`St1/r100.das` y sus `.dat`), las
   cinemáticas (`Evd/r100sNN.evd`), los personajes (`em/pl00.drs` Leon, `em10.drs` los aldeanos, `wepNN.drs` las
   armas), los recursos comunes (`etc/core.das`: HUD, efectos, ítems), las fuentes, la radio (`ss/`, `op/`) y el audio
   (`bgm/`).
2. **Abrir los contenedores.** Los `.das`/`.drs`/`.evd` son paquetes de archivos (algunos comprimidos con YZ2) que
   adentro tienen modelos (BIN), paletas de texturas (TPL, formatos de la GameCube como CMPR o I8), animaciones (FCV),
   efectos (EFF) y tablas.
3. **Modelos y texturas.** Cada modelo se convierte a una malla con su esqueleto y las texturas se decodifican a PNG y
   se juntan en un atlas por personaje.
4. **Animaciones.** Las animaciones FCV guardan claves por hueso con curvas, más cadenas de cinemática inversa. Para que
   se muevan exactamente igual que en la consola, el script **baja la decompilación pública del juego y compila en tu
   máquina solo su módulo de animaciones**, y con eso evalúa cada cuadro. Ese código no está en este repositorio.
5. **Cinemáticas.** De cada `.evd` salen los cortes, las cámaras cuadro a cuadro, quién actúa en cada corte y las
   expresiones de las caras; el audio de las voces se decodifica (DSP-ADPCM) a WAV.
6. **El mapa.** Las piezas del cuarto se convierten a mallas con la luz del juego ya calculada en cada vértice, y se
   arman varios niveles de detalle para el teléfono (el N95 dibuja unos 9000 triángulos a 30 cuadros por segundo).
7. **Sonido y música.** Los bancos de efectos y las voces son DSP-ADPCM; la música del cuarto es una secuencia MIDI con
   sus instrumentos, que se sintetiza a WAV.
8. **Whisk3D.** Todo eso se arma como proyectos del editor Whisk3D (el nivel y la librería de personajes).
9. **El N95.** Por último, el conversor pasa esos proyectos a los formatos chicos que lee el teléfono: el mapa en
   bloques para la GPU, los personajes con su esqueleto, las texturas en 16 bits, el sonido en IMA ADPCM y las tablas
   de la demo.

## Créditos y licencias

- **Esta demo** (el script, los extractores, el conversor y el `.sisx`): Dante Leoncini, licencia
  [PolyForm Noncommercial 1.0.0](LICENSE): se puede usar, estudiar y modificar, pero **no con fines comerciales**.
- **Whisk3D** (editor y motor): Dante Leoncini, licencia MIT.
- **[decomp-toolkit (dtk)](https://github.com/encounter/decomp-toolkit)**: lee el disco. Se baja al correr el script.
- **[Decompilación de RE4](https://github.com/adonis-singh/re4)** (CC0): sus herramientas leen los formatos del juego y
  su módulo de animaciones se compila en tu máquina. Se baja al correr el script; no está incluida acá.
- **[meshoptimizer](https://github.com/zeux/meshoptimizer)** (MIT, Arseny Kapoulkine): simplifica las mallas
  (`extractores/tools/meshopt/src`, `conversor/meshopt/src`).
- Resident Evil 4 es de **Capcom**. Este proyecto no está afiliado a Capcom ni usa ningún recurso suyo sin el disco
  original del usuario.
