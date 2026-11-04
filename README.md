# Resident Evil 4 en el Nokia N95 (demo de Whisk3D)

El primer cuarto de **Resident Evil 4** (GameCube): la llegada en la camioneta, la llamada de radio, el camino, la casa
del aldeano y la emboscada, corriendo **nativo en un Nokia N95** (2007) con el motor de
[Whisk3D](https://github.com/Dante-Leoncini/Whisk3D-Editor).

**Este repositorio existe solo para demostrar que la demo es real**: que corre de verdad en el telefono y no es un video
hecho con IA, un montaje ni una actuacion. Cualquiera con su propia copia del juego puede armar los datos y probarla.

- **No contiene nada del juego.** Ni modelos, ni texturas, ni sonidos, ni codigo del juego. Los datos los genera cada
  uno desde **su propio disco**.
- La demo es **solo para el Nokia N95** (Symbian S60 3rd FP1). En un Nokia tactil (S60 5th, Symbian^3) hace falta
  conectarle un teclado o un joystick de PS3.
- Los recursos del juego original se extrajeron y se adaptaron para correr en Whisk3D con la ayuda de **Claude
  Opus 5.5**.

## Que hay aca

| | |
|---|---|
| `demo/re4.sisx` | el instalador de la demo para el N95 (solo el programa, sin datos) |
| `re4n95.py` | arma la carpeta de datos desde tu disco |
| `extractores/`, `conversor/`, `herramientas/` | lo que usa `re4n95.py` (codigo propio, salvo lo indicado en *Creditos*) |
| `demo/datos/` | la intro y la fuente de Whisk3D (no son del juego) |

## Lo que necesitas

- **Tu disco** de Resident Evil 4 para GameCube, **version USA, disco 1**, como imagen `.rvz`, `.iso` o `.gcm`
  (por ejemplo, sacada de tu consola con un homebrew de backup y convertida con Dolphin).
- **Python 3.10 o mas nuevo** con `numpy` y `pillow` (`pip install numpy pillow`).
- **git**.
- **g++** (para compilar dos librerias chicas en tu maquina):
  - Windows: [MSYS2](https://www.msys2.org/) y, en su consola, `pacman -S mingw-w64-x86_64-gcc`. Despues agrega
    `C:\msys64\mingw64\bin` al PATH.
  - Linux: `sudo apt install g++` (o el paquete de tu distribucion).
- **El editor Whisk3D** (se usa para armar los modelos y las animaciones). Se compila desde
  [Whisk3D-Editor](https://github.com/Dante-Leoncini/Whisk3D-Editor):
  - Windows: `platform\windows\build_windows.bat` (necesita Visual Studio y CMake; el ejecutable queda en
    `platform\windows\build\Release\whisk3d.exe`).
  - Linux: ver `platform/linux` en ese repositorio.
- Unos **3 GB libres** y una conexion a internet (el script baja dos herramientas libres: ver *Creditos*).

## Armar los datos

Windows (en una consola, desde la carpeta de este repositorio):

```bat
python re4n95.py --disco "D:\juegos\Resident Evil 4 (USA) (Disc 1).rvz" --whisk3d "C:\Whisk3D-Editor\platform\windows\build\Release\whisk3d.exe"
```

Linux:

```sh
python3 re4n95.py --disco ~/juegos/re4_disco1.iso --whisk3d ~/Whisk3D-Editor/platform/linux/build/whisk3d
```

El script dice cuantos pasos son y como va cada uno:

```
Resident Evil 4 -> datos del Nokia N95: 31 pasos
[ 1/31] Preparar la carpeta de trabajo... listo (2 s)
[ 2/31] Bajar la decompilacion publica (para las animaciones)... listo (6 s)
...
TERMINADO en 42 min 44 s.
Los datos estan en: ...\datos
```

Tarda entre 25 y 40 minutos segun la maquina; el paso mas largo es *El mapa del N95* (calcula con rayos que se ve
desde adentro de la casa: unos 15 minutos). Si algo se corta, volve a correr **el mismo comando**: sigue desde el paso
que faltaba. Lo que hace cada paso queda
anotado en `trabajo/registro/`. La carpeta `trabajo/` se puede borrar al terminar.

## Instalar en el N95

1. Copia la carpeta `datos` que armo el script a la tarjeta de memoria del telefono como **`E:\re4\datos`**
   (con el cable USB en modo almacenamiento, o con Nokia PC Suite). Tiene que quedar `E:\re4\datos\mundo.bin`,
   `E:\re4\datos\sonidos\...`, etc.
2. Instala `demo/re4.sisx` en la tarjeta (E:). El certificado es propio: si el telefono no deja instalar
   aplicaciones sin firmar, en *Gestor de aplicaciones > Opciones > Configuracion* poner *Instalacion de software:
   Todas*.
3. Si el telefono no tiene **Open C / Open C++** (el N95 de fabrica no lo trae), instala antes los paquetes de
   Open C / Open C++ para S60 3rd (el *Open C/C++ plug-in* de Nokia).
4. Abri *Resident Evil 4* desde el menu de aplicaciones.

## Controles

| | Teclado del N95 | Joystick de PS3 (Bluetooth) |
|---|---|---|
| Caminar / girar | cruceta (o 2 4 6 8) | stick izquierdo o cruceta |
| Correr | dos toques adelante y mantener | R2 mantenido |
| Media vuelta | dos toques atras | |
| Apuntar | OK (o 5) | R1 o L2 mantenido |
| Disparar | OK apuntando | X apuntando |
| Accion del cartel (patear, saltar, hablar) | OK, o softkey izquierdo (tambien apuntando) | cuadrado (o X sin apuntar) |
| Cuchillo | softkey derecho | L1 mantenido |
| Recargar | 0 | circulo |
| Saltar una cinematica | OK | X |
| Pausa (detalle, niebla, brillo, FPS) | softkey izquierdo | Start |
| Cuadros por segundo | # | |

## Como se extraen los recursos (explicacion educativa)

Todo se hace **de buena fe**: el proposito es mostrar que un telefono de 2007 puede mover una escena de un juego de
GameCube, no distribuir el juego. Nada de lo que sale del disco se publica, y solo se toma lo necesario para el primer
cuarto. A grandes rasgos:

1. **Leer el disco.** La imagen de GameCube es un sistema de archivos; [dtk](https://github.com/encounter/decomp-toolkit)
   copia de ahi los archivos que hacen falta (unos 55, 77 MB): el cuarto (`St1/r100.das` y sus `.dat`), las
   cinematicas (`Evd/r100sNN.evd`), los personajes (`em/pl00.drs` Leon, `em10.drs` los aldeanos, `wepNN.drs` las
   armas), los recursos comunes (`etc/core.das`: HUD, efectos, items), las fuentes, la radio (`ss/`, `op/`) y el audio
   (`bgm/`).
2. **Abrir los contenedores.** Los `.das`/`.drs`/`.evd` son paquetes de archivos (algunos comprimidos con YZ2) que
   adentro tienen modelos (BIN), paletas de texturas (TPL, formatos de la GameCube como CMPR o I8), animaciones (FCV),
   efectos (EFF) y tablas.
3. **Modelos y texturas.** Cada modelo se convierte a una malla con su esqueleto y las texturas se decodifican a PNG y
   se juntan en un atlas por personaje.
4. **Animaciones.** Las animaciones FCV guardan claves por hueso con curvas, mas cadenas de cinematica inversa. Para que
   se muevan exactamente igual que en la consola, el script **baja la decompilacion publica del juego y compila en tu
   maquina solo su modulo de animaciones**, y con eso evalua cada cuadro. Ese codigo no esta en este repositorio.
5. **Cinematicas.** De cada `.evd` salen los cortes, las camaras cuadro a cuadro, quien actua en cada corte y las
   expresiones de las caras; el audio de las voces se decodifica (DSP-ADPCM) a WAV.
6. **El mapa.** Las piezas del cuarto se convierten a mallas con la luz del juego ya calculada en cada vertice, y se
   arman varios niveles de detalle para el telefono (el N95 dibuja unos 9000 triangulos a 30 cuadros por segundo).
7. **Sonido y musica.** Los bancos de efectos y las voces son DSP-ADPCM; la musica del cuarto es una secuencia MIDI con
   sus instrumentos, que se sintetiza a WAV.
8. **Whisk3D.** Todo eso se arma como proyectos del editor Whisk3D (el nivel y la libreria de personajes).
9. **El N95.** Por ultimo, el conversor pasa esos proyectos a los formatos chicos que lee el telefono: el mapa en
   bloques para la GPU, los personajes con su esqueleto, las texturas en 16 bits, el sonido en IMA ADPCM y las tablas
   de la demo.

## Creditos y licencias

- **Esta demo** (el script, los extractores, el conversor y el `.sisx`): Dante Leoncini, licencia
  [PolyForm Noncommercial 1.0.0](LICENSE): se puede usar, estudiar y modificar, pero **no con fines comerciales**.
- **Whisk3D** (editor y motor): Dante Leoncini, licencia MIT.
- **[decomp-toolkit (dtk)](https://github.com/encounter/decomp-toolkit)**: lee el disco. Se baja al correr el script.
- **[Decompilacion de RE4](https://github.com/adonis-singh/re4)** (CC0): sus herramientas leen los formatos del juego y
  su modulo de animaciones se compila en tu maquina. Se baja al correr el script; no esta incluida aca.
- **[meshoptimizer](https://github.com/zeux/meshoptimizer)** (MIT, Arseny Kapoulkine): simplifica las mallas
  (`extractores/tools/meshopt/src`, `conversor/meshopt/src`).
- Resident Evil 4 es de **Capcom**. Este proyecto no esta afiliado a Capcom ni usa ningun recurso suyo sin el disco
  original del usuario.

---

## English

**Resident Evil 4** (GameCube), its first room, running **natively on a Nokia N95** (2007) on the
[Whisk3D](https://github.com/Dante-Leoncini/Whisk3D-Editor) engine. This repository exists **only to prove the demo is
real** (not an AI-made video or a fake): it contains **no game data and no game code**. You build the data from **your
own disc** (RE4 GameCube, USA, disc 1) and copy it to the phone.

```sh
python re4n95.py --disco <your disc .rvz/.iso> --whisk3d <path to the Whisk3D editor>
```

Requirements: Python 3.10+ with numpy and pillow, git, g++ (MSYS2/MinGW on Windows), and the Whisk3D editor built from
its repository. The script shows the number of steps and its progress, and resumes where it stopped if run again.
Copy the resulting `datos` folder to the phone's memory card as `E:\re4\datos` and install `demo/re4.sisx`. The demo is
**for the Nokia N95 only**; touch Nokias need a keyboard or a PS3 controller. The original game assets were extracted
and adapted to Whisk3D with the help of **Claude Opus 5.5**. See *Creditos* above for third-party tools (dtk, the CC0 RE4
decompilation tools, meshoptimizer).

**License:** [PolyForm Noncommercial 1.0.0](LICENSE). Free to use, study and modify, **no commercial use**.
