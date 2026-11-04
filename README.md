<p align="center">
  <b>English</b> | <a href="README.es.md">Español</a>
</p>

# Resident Evil 4 on the Nokia N95 (Whisk3D demo)

The first room of **Resident Evil 4** (GameCube): the arrival in the police car, the radio call, the path, the
villager's house and the ambush, running **natively on a Nokia N95** (2007) on the
[Whisk3D](https://github.com/Dante-Leoncini/Whisk3D-Editor) engine.

**This repository exists only to prove the demo is real**: that it actually runs on the phone and is not an AI-made
video, an edit or a staged act. Anyone with their own copy of the game can build the data and try it.

- **It contains nothing from the game.** No models, textures, sounds or game code. Everyone builds the data from
  **their own disc**.
- The demo is **for the Nokia N95 only** (Symbian S60 3rd FP1). Touch Nokias (S60 5th, Symbian^3) need a keyboard or a
  PS3 controller connected.
- The original game assets were extracted and adapted to run on Whisk3D with the help of **Claude Opus 5.5**.

## What's here

| | |
|---|---|
| `demo/re4.sisx` | the demo installer for the N95 (the program only, no data) |
| `re4n95.py` | builds the data folder from your disc |
| `extractores/`, `conversor/`, `herramientas/` | what `re4n95.py` uses (original code, except as noted in *Credits*) |
| `demo/datos/` | the Whisk3D intro and font (not from the game) |

## What you need

- **Your disc** of Resident Evil 4 for GameCube, **USA version, disc 1**, as a `.rvz`, `.iso` or `.gcm` image
  (for example, dumped from your own console with a backup homebrew and converted with Dolphin).
- **Python 3.10 or newer** with `numpy` and `pillow` (`pip install numpy pillow`).
- **git**.
- **g++** (to compile two small libraries on your machine):
  - Windows: [MSYS2](https://www.msys2.org/) and, in its console, `pacman -S mingw-w64-x86_64-gcc`. Then add
    `C:\msys64\mingw64\bin` to the PATH.
  - Linux: `sudo apt install g++` (or your distribution's package).
- **The Whisk3D editor** (used to build the models and animations). Build it from
  [Whisk3D-Editor](https://github.com/Dante-Leoncini/Whisk3D-Editor):
  - Windows: `platform\windows\build_windows.bat` (needs Visual Studio and CMake; the executable ends up in
    `platform\windows\build\Release\whisk3d.exe`).
  - Linux: see `platform/linux` in that repository.
- About **3 GB free** and an internet connection (the script downloads two free tools: see *Credits*).

## Building the data

Windows (in a console, from this repository's folder):

```bat
python re4n95.py --disco "D:\games\Resident Evil 4 (USA) (Disc 1).rvz" --whisk3d "C:\Whisk3D-Editor\platform\windows\build\Release\whisk3d.exe"
```

Linux:

```sh
python3 re4n95.py --disco ~/games/re4_disc1.iso --whisk3d ~/Whisk3D-Editor/platform/linux/build/whisk3d
```

The script tells you how many steps there are and how each one is going (its messages are in Spanish):

```
Resident Evil 4 -> datos del Nokia N95: 31 pasos
[ 1/31] Preparar la carpeta de trabajo... listo (2 s)
[ 2/31] Bajar la decompilacion publica (para las animaciones)... listo (6 s)
...
TERMINADO en 42 min 44 s.
Los datos estan en: ...\datos
```

It takes 25 to 40 minutes depending on the machine; the longest step is *El mapa del N95* (it ray-casts what can be
seen from inside the house: about 15 minutes). If something stops, run **the same command** again: it resumes from the
missing step. What each step does is logged in `trabajo/registro/`. The `trabajo/` folder can be deleted when done.

## Installing on the N95

1. Copy the `datos` folder built by the script to the phone's memory card as **`E:\re4\datos`**
   (with the USB cable in mass storage mode, or with Nokia PC Suite). You should end up with `E:\re4\datos\mundo.bin`,
   `E:\re4\datos\sonidos\...`, etc.
2. Install `demo/re4.sisx` to the memory card (E:). The certificate is self-signed: if the phone refuses unsigned
   applications, set *Application manager > Options > Settings > Software installation: All*.
3. If the phone doesn't have **Open C / Open C++** (a stock N95 doesn't), first install the Open C / Open C++ packages
   for S60 3rd (Nokia's *Open C/C++ plug-in*).
4. Open *Resident Evil 4* from the applications menu.

## Controls

| | N95 keypad | PS3 controller (Bluetooth) |
|---|---|---|
| Walk / turn | D-pad (or 2 4 6 8) | left stick or D-pad |
| Run | double-tap forward and hold | hold R2 |
| Quick turn | double-tap back | |
| Aim | OK (or 5) | hold R1 or L2 |
| Shoot | OK while aiming | X while aiming |
| Prompt action (kick, jump, talk) | OK, or left softkey (also while aiming) | square (or X when not aiming) |
| Knife | right softkey | hold L1 |
| Reload | 0 | circle |
| Skip a cutscene | OK | X |
| Pause (detail, fog, brightness, FPS) | left softkey | Start |
| Frames per second | # | |

## How the assets are extracted (educational explanation)

Everything is done **in good faith**: the purpose is to show that a 2007 phone can run a scene from a GameCube game,
not to distribute the game. Nothing taken from the disc is published, and only what the first room needs is used.
In broad strokes:

1. **Reading the disc.** The GameCube image is a file system; [dtk](https://github.com/encounter/decomp-toolkit) copies
   the needed files out of it (about 55 files, 77 MB): the room (`St1/r100.das` and its `.dat` files), the cutscenes
   (`Evd/r100sNN.evd`), the characters (`em/pl00.drs` Leon, `em10.drs` the villagers, `wepNN.drs` the weapons), the
   common resources (`etc/core.das`: HUD, effects, items), the fonts, the radio (`ss/`, `op/`) and the audio (`bgm/`).
2. **Opening the containers.** The `.das`/`.drs`/`.evd` files are file packages (some compressed with YZ2) holding
   models (BIN), texture palettes (TPL, GameCube formats such as CMPR or I8), animations (FCV), effects (EFF) and
   tables.
3. **Models and textures.** Each model becomes a mesh with its skeleton, and the textures are decoded to PNG and packed
   into one atlas per character.
4. **Animations.** FCV animations store per-bone keys with curves, plus inverse kinematics chains. To make them move
   exactly as on the console, the script **downloads the game's public decompilation and compiles only its animation
   module on your machine**, and uses it to evaluate every frame. That code is not in this repository.
5. **Cutscenes.** Each `.evd` yields the cuts, the frame-by-frame cameras, who acts in each cut and the facial
   expressions; the voice audio is decoded (DSP-ADPCM) to WAV.
6. **The map.** The room's pieces become meshes with the game's lighting already baked into each vertex, and several
   levels of detail are built for the phone (the N95 draws about 9000 triangles at 30 frames per second).
7. **Sound and music.** Effect banks and voices are DSP-ADPCM; the room's music is a MIDI sequence with its
   instruments, synthesized to WAV.
8. **Whisk3D.** All of that is assembled as Whisk3D editor projects (the level and the character library).
9. **The N95.** Finally, the converter turns those projects into the small formats the phone reads: the map in blocks
   for the GPU, the characters with their skeletons, 16-bit textures, IMA ADPCM sound and the demo's tables.

## Credits and licenses

- **This demo** (the script, extractors, converter and the `.sisx`): Dante Leoncini,
  [PolyForm Noncommercial 1.0.0](LICENSE) license: free to use, study and modify, but **not for commercial purposes**.
- **Whisk3D** (editor and engine): Dante Leoncini, MIT license.
- **[decomp-toolkit (dtk)](https://github.com/encounter/decomp-toolkit)**: reads the disc. Downloaded when the script
  runs.
- **[RE4 decompilation](https://github.com/adonis-singh/re4)** (CC0): its tools read the game's formats and its
  animation module is compiled on your machine. Downloaded when the script runs; not included here.
- **[meshoptimizer](https://github.com/zeux/meshoptimizer)** (MIT, Arseny Kapoulkine): simplifies the meshes
  (`extractores/tools/meshopt/src`, `conversor/meshopt/src`).
- Resident Evil 4 belongs to **Capcom**. This project is not affiliated with Capcom and uses none of its assets without
  the user's original disc.
