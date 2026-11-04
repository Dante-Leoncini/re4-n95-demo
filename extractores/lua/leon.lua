-- ============================================================================
--  leon.lua -- Leon de Resident Evil 4 (GameCube) en Whisk3D. Va en el armature "Leon".
--
--  Controles:
--    W / flecha arriba      caminar para adelante (apuntando: apuntar mas arriba)
--    S / flecha abajo       caminar para atras    (apuntando: apuntar mas abajo, al piso)
--    A D / flechas izq der  girar (quieto gira en el lugar; apuntando tambien se gira)
--    shift (mantenido)      correr en vez de caminar
--    E                      apuntar con la pistola / dejar de apuntar (quieto, con laser)
--    Q                      sacar el cuchillo / guardarlo (quieto, como en el juego)
--    espacio                disparar (pistola) o tajo (cuchillo)
--    R                      recargar (10 balas en el cargador; sin balas, disparar recarga solo si hay reserva)
--    F                      patear al ganado aturdido (tiro en la cabeza o en la canilla), de cerca y de frente
--
--  El personaje usa el MIX de animaciones (capas) de Whisk3D, como el juego:
--    capa 1 = la BASE (caminar, correr, apuntar horizontal, cuchillo...)
--    capa 2 = la PUNTERIA: la pose "arriba" o "abajo" mezclada sobre la base segun el pitch, en el mismo
--             frame (cMot3 del juego, pl_class.cpp: mot0 horizontal + mot1 arriba / mot2 abajo con |pitch|)
--
--  Datos del juego (la decompilacion + el disco):
--    - AVANCE = root motion de cada animacion (mm por frame, lo que MotionMove suma al personaje)
--    - GIRO = SPEED_WALK_TURN 0.0418879 rad por frame a 30 fps; el pitch sube/baja 0.035 por frame (x0.8 hacia
--      arriba) con la cruceta (pl_wep.cpp)
--    - PASOS en los frames de las tablas SEQ (cPlayer::seqSeCtrl): Se 1/2 caminar izq/der, 3/4 correr
--    - DISPARO: cObjRuger::moveFire -> sonido, el efecto est 0 de wep02 (8 emisores) y el casquillo
--    - CUCHILLO: pl_knife.cpp -> el arma se oculta y aparece el cuchillo en el frame 4 de desenfundar (y al reves
--      al guardar); el tajo suena en el frame 3
--    - TRANSICIONES = el "hokan" de cada MotionSetCore del juego: la pose se funde desde la anterior durante
--      8 frames (quieto/caminar/correr/atras, player.cpp), 7 (girar), 3 (desenfundar/apuntar/cuchillo, mot3.set),
--      0 (disparo) y 5 (guardar). Caminar <-> correr conserva la fase del paso (player.cpp: frame escalado)
--    - CAMARA: se acerca al hombro al apuntar y sigue la punteria arriba/abajo, siempre suavizada
--    - COMBATE (out/combate/armas.json, out/ganado_juego/ia.json): el rayo del arma sale de (228, -24, 29) mm del hueso
--      de la mano por -X; corta en el escenario (la colision) o en el ganado (capsulas sobre sus huesos, por zona:
--      cabeza / torso / brazos / muslos / canillas). Pistola 150 (cabeza 180, 1 de 12 critico x10), cuchillo 100/120
--      (frames 6..10 del tajo), patada 200. Cargador 10 + 20 de reserva; recarga 52 frames (las balas entran en el 31).
--      Leon: 1200 de vida; el hacha saca 380. Debajo de 800 camina herido. Muere -> a los 4 s vuelve a empezar.
--      El laser corta donde pega el rayo y pone ahi el punto rojo (siempre mirando a camara).
--      Todo lo que comparte con los demas scripts va por compartido(): golpe_* (al ganado), leon_danio_* (de el),
--      leon_vida / balas / balas_reserva (el HUD).
-- ============================================================================

propiedades = {}

local leon, cam, laser, luz, pistola, cuchillo
local pistolaArm = nil   -- armadura de la pistola (corredera y cargador): sus clips van a la par de los de Leon

-- el clip de la PISTOLA (reposo / disparar / recargar; las variantes 'vacia' con la corredera trabada atras)
local function armaClip(c, loop)
    if pistolaArm then animClip(pistolaArm, c, loop or false, true); animVelocidad(pistolaArm, 1) end
end
local FX = {{"Leon_fx_r1", 1}, {"Leon_fx_r2", 1}, {"Leon_fx_r3", 1}, {"Leon_fx_r4", 1},
            {"Leon_fx_r5", 1}, {"Leon_fx_r6", 1}, {"Leon_fx_r7", 1}, {"Leon_fx_r8", 3}}
local fx = {}

local estado = "normal"   -- normal | desenfundar | apuntar | disparar | enfundar | sacar | cuchillo | tajo | guardar
local yaw = 0             -- grados alrededor de +Y (0 = mirando a +Z)
local pitch = 0           -- -1 (al piso) .. 0 (horizontal) .. 1 (arriba)
local px, py, pz = 0, 0, 0
local base = nil          -- el clip de la capa 1
local frameAnt = 0
local luzT, casquilloT = 0, -1
local armaCambiada = false  -- el cambio pistola/cuchillo ya se hizo en este desenfundar/guardar

-- COLISION con el escenario (si la escena lo trae: re4_r100.w3d): el SAT del juego exportado como dos mallas
-- ocultas. Leon sigue moviendose por root motion; despues el motor lo saca de las paredes (colPared) y lo apoya
-- en el piso (colSuelo). Sin esas mallas (re4.w3d, Leon solo) todo sigue como antes.
local colSueloM, colParedM, colCamionM = nil, nil, nil
local puertaM = nil        -- la puerta de la casa: tambien es pared (cerrada tapa el paso; r100.lua la abre)
local RADIO = 0.3          -- radio del cuerpo (el juego usa ~300 mm para el jugador)
local SUBIDA = 0.45        -- escalon maximo que se sube caminando
local CAIDA_VEL = 6.0      -- m/s al bajar a un piso mas bajo (no se "teletransporta" abajo)

local GIRO = 0.0418879 * 30 * 180 / math.pi   -- 72 grados por segundo
-- camara suavizada: los valores actuales persiguen al objetivo (exponencial, ~ un tercio de segundo)
local cam_ = { lejos = 2.3, costado = 0.45, alto = 1.65, pitch = 0, yaw = 0, iniciada = false }
local CAM_SUAVE = 7.0
local PITCH_VEL = 0.035 * 30                    -- 1.05 por segundo

-- la RAIZ de cada clip (x, z, giro por frame, metros / radianes, +Z adelante) y los efectos de impacto (FXC): los
-- escribe combate_r100.py al armar la escena (out/combate/leon_combate_clips.json, out/combate/efectos.json)
--@@RAIZ@@
if not RAIZ then RAIZ = {} end
if not RAIZY then RAIZY = {} end
if not FXC then FXC = {} end
if not VENTANAS then VENTANAS = {} end
if not SEQV then SEQV = {} end
if not CAMV then CAMV = {} end
if not TROZOS then TROZOS = {} end

-- frames de las claves SEQ con paso
local PASOS = {
    caminar   = {[1] = "caminar_der", [16] = "caminar_izq"},
    atras     = {[1] = "caminar_der", [11] = "caminar_izq"},
    correr    = {[9] = "correr_izq", [19] = "correr_der"},
    girar_izq = {[8] = "caminar_izq", [15] = "caminar_der", [28] = "caminar_izq", [36] = "caminar_der"},
    girar_der = {[11] = "caminar_der", [19] = "caminar_izq", [28] = "caminar_der", [35] = "caminar_izq"},
}
PASOS.herido_caminar, PASOS.herido_atras, PASOS.herido_correr = PASOS.caminar, PASOS.atras, PASOS.correr
-- HERIDO (vida < 800, dmMotCk): la locomocion cambia de clip
local HERIDO = {quieto = "herido_quieto", caminar = "herido_caminar", atras = "herido_atras", correr = "herido_correr"}

-- la punteria de cada base: {clip arriba, clip abajo}
local PUNTERIA = {
    apuntar         = {"apuntar_arriba", "apuntar_abajo"},
    disparar        = {"disparar_arriba", "disparar_abajo"},
    cuchillo_quieto = {"cuchillo_arriba", "cuchillo_abajo"},
    cuchillo_tajo   = {"cuchillo_tajo_arriba", "cuchillo_tajo_abajo"},
}

if not VOL then VOL = {} end
local function snd(nombre, vol)
    sonido("sonidos/" .. nombre .. ".wav", (VOL[nombre] or 1.0) * (vol or 1.0))
end
local function sndAzar(base, n, vol) snd(base .. "_" .. azar(1, n), vol) end

-- frames de transicion (hokan del juego) al ENTRAR a cada clip
local HOKAN = {
    quieto = 8, caminar = 8, correr = 8, atras = 8, girar_izq = 7, girar_der = 7,
    desenfundar = 3, apuntar = 3, disparar = 0, enfundar = 3,
    cuchillo_desenfundar = 3, cuchillo_quieto = 3, cuchillo_tajo = 3, cuchillo_guardar = 5,
    recargar = 3, patada = 3, dano_frente = 3, dano_atras = 3, dano_cabeza_frente = 3, dano_cabeza_atras = 3,
    muerte = 5, herido_quieto = 8, herido_caminar = 8, herido_atras = 8, herido_correr = 8,
}

-- ---- COMBATE ----
local VIDA_MAX = 1200
local CARGADOR = 10
local vida, balas, reserva = VIDA_MAX, CARGADOR, 20
local DANIO = {pistola = 150, pistola_cabeza = 180, cuchillo = 100, cuchillo_cabeza = 120, patada = 200}
local ALCANCE = 50
local BOCA = {0.228, -0.024, 0.029}          -- origen del rayo en el hueso de la mano (m); la direccion es -X
local laserFar = {}                            -- vertices de la punta del laser (indices)
local punto
local recargado, volverApuntar = false, false
local tajoHecho, patadaHecha = false, false
local patadaClip = "patada"
local danioVisto, reinicioVisto = 0, 0
local saltoV = nil          -- la ventana / el salto en curso (estado "ventana")
local trozosV = nil         -- los trozos de vidrio volando: {lista, t (frames desde la rotura)}
local ventanaRota = {}
local vozVentana = false
local muertoT = 0
local objFX = {}
-- las capsulas del ganado por zona: {hueso A, hueso B, radio, zona} (la cabeza: del cuello hacia arriba)
local ZONAS = {
    {"hueso_000", "hueso_003", 0.19, "torso"},
    {"hueso_007", "hueso_008", 0.075, "brazo_der"}, {"hueso_008", "hueso_010", 0.065, "antebrazo_der"},
    {"hueso_013", "hueso_014", 0.075, "brazo_izq"}, {"hueso_014", "hueso_016", 0.065, "antebrazo_izq"},
    {"hueso_018", "hueso_019", 0.095, "muslo_der"}, {"hueso_019", "hueso_020", 0.075, "canilla_der"},
    {"hueso_022", "hueso_023", 0.095, "muslo_izq"}, {"hueso_023", "hueso_024", 0.075, "canilla_izq"},
}

-- la capa 1 (la base). Pedir la misma que ya suena no la reinicia (salvo reiniciar). Al cambiar, la pose se
-- FUNDE desde la anterior (animTransicion) como en el juego; caminar <-> correr sigue en la misma fase del paso.
local function ponerBase(clip, loop, reiniciar)
    if vida < 800 and HERIDO[clip] then clip = HERIDO[clip] end
    if clip == base and not reiniciar then return end
    local fase = nil
    local cam1 = {caminar = 1, correr = 1, herido_caminar = 1, herido_correr = 1}
    if cam1[base] and cam1[clip] and base ~= clip then
        fase = animCapaFrame(leon, 1) / math.max(1, animLargo(leon, base))
    end
    local h = HOKAN[clip] or 5
    if base and h > 0 then animTransicion(leon, h) end
    base = clip
    animCapa(leon, 1, clip, 1, "mezclar", loop, reiniciar)
    if fase then
        animCapaFrame(leon, 1, fase * animLargo(leon, clip))
        frameAnt = animCapaFrame(leon, 1)
    else
        frameAnt = 0
    end
end

-- la capa 2 (la punteria): la pose arriba/abajo con |pitch|, en el MISMO frame que la base
local function punteria()
    local par = PUNTERIA[base]
    if not par or pitch == 0 then animCapaPeso(leon, 2, 0); return end
    local clip = (pitch > 0) and par[1] or par[2]
    animCapa(leon, 2, clip, math.abs(pitch), "mezclar", true)
    animCapaFrame(leon, 2, animCapaFrame(leon, 1))
end

-- la raiz del clip entre dos frames (con la vuelta del loop): dx, dz en el espacio de Leon
local function pistaEn(t, f)
    local n = #t // 3
    if f <= 0 then return t[1], t[2] end
    if f >= n - 1 then return t[3 * n - 2], t[3 * n - 1] end
    local i = math.floor(f); local k = f - i
    local a = 3 * i
    return t[a + 1] + (t[a + 4] - t[a + 1]) * k, t[a + 2] + (t[a + 5] - t[a + 2]) * k
end
local function avanceRaiz(clip, f0, f1)
    local t = RAIZ[clip]
    if not t then return 0, 0 end
    local x0, z0 = pistaEn(t, f0)
    local x1, z1 = pistaEn(t, f1)
    if f1 < f0 then
        local n = #t // 3
        return (t[3 * n - 2] - x0) + x1, (t[3 * n - 1] - z0) + z1
    end
    return x1 - x0, z1 - z0
end
-- otros sonidos de la SEQ (pl00): el cuerpo que cae al morir
local SEQL = {muerte = {[40] = "leon_cae_rodilla", [70] = "leon_cae_cuerpo"}, muerte_fuerte = {[22] = "leon_cae_cuerpo"},
              dano_fuerte = {[12] = "leon_cae_cuerpo"}}
local function pasos(clip, f0, f1)
    local otros = SEQL[clip]
    if otros then
        local a, b = math.floor(f0), math.floor(f1)
        for k, n in pairs(otros) do if k > a and k <= b then snd(n, 1.0) end end
    end
    local tabla = PASOS[clip]
    if not tabla then return end
    local a, b = math.floor(f0), math.floor(f1)
    for k, pie in pairs(tabla) do
        local cruzo
        if b >= a then cruzo = (k > a and k <= b) else cruzo = (k > a or k <= b) end
        if cruzo then
            snd("paso_tierra_" .. pie, 0.9)
            local corre = string.sub(pie, 1, 6) == "correr"
            snd((corre and "ropa_correr_" or "ropa_caminar_") .. azar(0, 4), 0.6)
        end
    end
end

-- ---- COMBATE: rayos, capsulas, efectos ----
-- el rayo del arma en el mundo: origen y direccion (unitaria)
local function rayoArma()
    local ox, oy, oz = huesoPunto(leon, "hueso_010", BOCA[1], BOCA[2], BOCA[3])
    local fx_, fy, fz = huesoPunto(leon, "hueso_010", BOCA[1] - 10, BOCA[2], BOCA[3])
    if not ox or not fx_ then return nil end
    local dx, dy, dz = fx_ - ox, fy - oy, fz - oz
    local l = math.sqrt(dx * dx + dy * dy + dz * dz)
    return ox, oy, oz, dx / l, dy / l, dz / l
end

-- el camion que tapa el camino: pared hasta que se va al barranco (compartido "camino_libre")
local function camionM() if colCamionM and not compartido("camino_libre") then return colCamionM end end

-- rayo contra el ESCENARIO (la colision del juego + la puerta): t y la normal
local function rayoMapa(ox, oy, oz, dx, dy, dz, mx)
    local tb, nx, ny, nz = nil, 0, 1, 0
    for _, m in ipairs({colParedM, colSueloM, puertaM, camionM()}) do
        if m then
            local t, a, b, c = colRayo(m, ox, oy, oz, dx, dy, dz, mx)
            if t and (not tb or t < tb) then tb, nx, ny, nz = t, a, b, c end
        end
    end
    return tb, nx, ny, nz
end

-- rayo contra una capsula (segmento A-B de radio r): el t de entrada (aprox.) o nil
local function rayoCapsula(ox, oy, oz, dx, dy, dz, ax, ay, az, bx, by, bz, r)
    local ux, uy, uz = bx - ax, by - ay, bz - az
    local wx, wy, wz = ox - ax, oy - ay, oz - az
    local a = ux * ux + uy * uy + uz * uz
    local b = ux * dx + uy * dy + uz * dz
    local d = ux * wx + uy * wy + uz * wz
    local e = dx * wx + dy * wy + dz * wz
    local den = a - b * b
    local sc, tc
    if den < 1e-8 then sc = 0; tc = -e else
        sc = (d - b * e) / den          -- sobre el segmento (0..1)
        tc = (b * d - a * e) / den      -- sobre el rayo
    end
    if sc < 0 then sc = 0; tc = -e elseif sc > 1 then sc = 1; tc = -(e - b) end
    if tc < 0 then return nil end
    local px_, py_, pz_ = ax + ux * sc, ay + uy * sc, az + uz * sc
    local qx, qy, qz = ox + dx * tc, oy + dy * tc, oz + dz * tc
    local ex, ey, ez = qx - px_, qy - py_, qz - pz_
    local dist2 = ex * ex + ey * ey + ez * ez
    if dist2 > r * r then return nil end
    return math.max(0, tc - math.sqrt(r * r - dist2))
end

-- los ENEMIGOS: ganado.lua anota cada aldeano en compartido "enemigos" (nombres separados por ';'); cada uno publica
-- sus claves con un prefijo ("" el de la casa, "<nombre>_" los demas)
local enemigos, enemigosLista = {}, nil
local function actualizarEnemigos()
    local l = compartido("enemigos") or ""
    if l == enemigosLista then return end
    enemigosLista, enemigos = l, {}
    for nom in string.gmatch(l, "[^;]+") do
        local o = buscar(nom)
        if o then enemigos[#enemigos + 1] = {o = o, K = (nom == "Ganado_juego") and "" or (nom .. "_")} end
    end
end
local function vivo(e) return e and visible(e.o) and not compartido(e.K .. "ganado_muerto") end
local function ganadoVivo()
    for _, e in ipairs(enemigos) do if vivo(e) then return true end end
    return false
end

-- rayo contra UN enemigo: t, zona (nil si no le pega)
local function rayoUno(e, ox, oy, oz, dx, dy, dz)
    local ganado = e.o
    if not visible(ganado) then return nil end
    local gx, gz = compartido(e.K .. "ganado_x"), compartido(e.K .. "ganado_z")
    if gx then   -- descarte rapido: lejos del rayo
        local wx, wz = gx - ox, gz - oz
        local t = wx * dx + wz * dz
        local cx, cz = ox + dx * t - gx, oz + dz * t - gz
        if t < -1 or cx * cx + cz * cz > 4 then return nil end
    end
    local tb, zb = nil, nil
    for _, z in ipairs(ZONAS) do
        local ax, ay, az = huesoPunto(ganado, z[1])
        local bx, by, bz = huesoPunto(ganado, z[2])
        if ax and bx then
            local t = rayoCapsula(ox, oy, oz, dx, dy, dz, ax, ay, az, bx, by, bz, z[3])
            if t and (not tb or t < tb) then tb, zb = t, z[4] end
        end
    end
    -- la cabeza: una esfera un poco arriba del hueso de la cabeza (del cuello hacia arriba)
    local nx_, ny_, nz_ = huesoPunto(ganado, "hueso_003")
    local hx, hy, hz = huesoPunto(ganado, "hueso_004")
    if hx and nx_ then
        local cx, cy, cz = hx + (hx - nx_) * 1.2, hy + (hy - ny_) * 1.2, hz + (hz - nz_) * 1.2
        local t = rayoCapsula(ox, oy, oz, dx, dy, dz, hx, hy, hz, cx, cy, cz, 0.13)
        if t and (not tb or t <= tb + 0.05) then tb, zb = t, "cabeza" end
    end
    return tb, zb
end
-- rayo contra TODOS: t, zona, el enemigo (el mas cercano)
local function rayoGanado(ox, oy, oz, dx, dy, dz)
    local tb, zb, eb = nil, nil, nil
    for _, e in ipairs(enemigos) do
        local t, z = rayoUno(e, ox, oy, oz, dx, dy, dz)
        if t and (not tb or t < tb) then tb, zb, eb = t, z, e end
    end
    return tb, zb, eb
end

-- un efecto de impacto (Empty + sus emisores) en un punto, con su +Z mirando a (mx, mz) o por la normal
local function efecto(nombre, x, y, z, rx, ry)
    local o = objFX[nombre]
    if not o then return end
    setPosicion(o.emp, x, y, z)
    setRotacion(o.emp, rx or 0, ry or 0, 0)
    for _, e in ipairs(o.lista) do emitir(e[1], e[2]) end
end
local function haciaYaw(x, z, tx, tz) return math.deg(math.atan(tx - x, tz - z)) end

-- un golpe al ganado (lo procesa ganado.lua)
local function golpear(e, zona, danio, x, y, z)
    if not e then return end
    local K = e.K
    setCompartido(K .. "golpe_zona", zona); setCompartido(K .. "golpe_danio", danio)
    setCompartido(K .. "golpe_ox", px); setCompartido(K .. "golpe_oz", pz)
    setCompartido(K .. "golpe_n", (compartido(K .. "golpe_n") or 0) + 1)
    info(string.format("leon: golpe %s %d", zona, danio))
end

local function recargar()
    if reserva <= 0 or balas >= CARGADOR then return false end
    volverApuntar = (estado == "apuntar" or estado == "disparar")
    estado = "recargar"; recargado = false
    ponerBase("recargar", false, true)
    armaClip(balas == 0 and "recargar_vacia" or "recargar")
    snd("pistola_recarga", 1.0)
    return true
end

-- la camioneta de la policia: apuntandole, el juego NO deja disparar (zona "no disparar" del cuarto): uno de los
-- policias reacciona (camino.lua)
local NO_DISPARAR = {x = -102.5, y = 0.6, z = 1.95, r = 2.2, lejos = 20}
local function apuntaAPolicias()
    local ox, oy, oz, dx, dy, dz = rayoArma()
    if not ox then return false end
    local wx, wy, wz = NO_DISPARAR.x - ox, NO_DISPARAR.y - oy, NO_DISPARAR.z - oz
    local t = wx * dx + wy * dy + wz * dz
    if t < 0 or t > NO_DISPARAR.lejos then return false end
    local cx, cy, cz = ox + dx * t - NO_DISPARAR.x, oy + dy * t - NO_DISPARAR.y, oz + dz * t - NO_DISPARAR.z
    return cx * cx + cy * cy + cz * cz < NO_DISPARAR.r * NO_DISPARAR.r
end

local function disparar()
    if apuntaAPolicias() then
        setCompartido("policia_reaccion_n", (compartido("policia_reaccion_n") or 0) + 1)
        return
    end
    if balas <= 0 then
        snd("pistola_vacia_click", 1.0)
        recargar()
        return
    end
    balas = balas - 1
    armaClip(balas == 0 and "disparar_ultima" or "disparar")
    estado = "disparar"
    ponerBase("disparar", false, true)
    snd("disparo_pistola", 1.0)
    for i, e in ipairs(FX) do if fx[i] then emitir(fx[i], e[2]) end end
    setVisible(luz, true)
    luzT = 2 / 30
    casquilloT = 0.5
    -- la BALA: el primer choque sobre el rayo del arma
    local ox, oy, oz, dx, dy, dz = rayoArma()
    if not ox then return end
    local tm, nx, ny, nz = rayoMapa(ox, oy, oz, dx, dy, dz, ALCANCE)
    local tg, zona, en = rayoGanado(ox, oy, oz, dx, dy, dz)
    if tg and (not tm or tg < tm) and vivo(en) then
        local hx, hy, hz = ox + dx * tg, oy + dy * tg, oz + dz * tg
        local d = (zona == "cabeza") and DANIO.pistola_cabeza or DANIO.pistola
        if zona == "cabeza" and azar() < 1 / 12 then d = d * 10 end   -- el critico del juego (Rnd() % 12 == 6)
        golpear(en, zona, d, hx, hy, hz)
        efecto("fx_sangre", hx, hy, hz, 0, haciaYaw(hx, hz, px, pz))
        sndAzar("bala_carne", 2, 1.0)
    elseif tg and (not tm or tg < tm) then
        local hx, hy, hz = ox + dx * tg, oy + dy * tg, oz + dz * tg
        efecto("fx_sangre", hx, hy, hz, 0, haciaYaw(hx, hz, px, pz))
    elseif tm then
        local hx, hy, hz = ox + dx * tm, oy + dy * tm, oz + dz * tm
        local h = math.sqrt(nx * nx + nz * nz)
        efecto("fx_polvo", hx + nx * 0.02, hy + ny * 0.02, hz + nz * 0.02, -math.deg(math.atan(ny, h)), math.deg(math.atan(nx, nz)))
    end
end

-- el LASER: corta donde pega el rayo (escenario o ganado) y pone el punto rojo ahi
local function laserActualizar(prendido)
    setVisible(laser, prendido)
    if not prendido then return end
    local ox, oy, oz, dx, dy, dz = rayoArma()
    if not ox then return end
    local t = rayoMapa(ox, oy, oz, dx, dy, dz, 19)
    local tg = rayoGanado(ox, oy, oz, dx, dy, dz)
    if tg and (not t or tg < t) then t = tg end
    local largo = t or 19
    -- la punta del laser (en el espacio del hueso de la mano: el laser va por -X desde la boca)
    local lx = BOCA[1] - math.max(0.5, largo)
    for _, i in ipairs(laserFar) do
        local _, y, z = verticePos(laser, i)
        setVerticePos(laser, i, lx, y, z)
    end
    if t and t > 0.5 and punto then
        setPosicion(punto, ox + dx * (t - 0.01), oy + dy * (t - 0.01), oz + dz * (t - 0.01))
        emitir(punto, 1)
    end
end

-- el golpe que le da el ganado (ganado.lua): danio, reaccion (alto/bajo, frente/espalda) o muerte
local function recibirDanio()
    local n = compartido("leon_danio_n") or 0
    if n == danioVisto then return end
    danioVisto = n
    if estado == "muerto" then return end
    local d = compartido("leon_danio") or 0
    local ox, oz = compartido("leon_danio_ox") or px, compartido("leon_danio_oz") or pz
    local atras = math.abs(((haciaYaw(px, pz, ox, oz) - yaw + 180) % 360) - 180) > 90
    local alto = compartido("leon_danio_alto")
    -- como el juego: si le quedan mas de 300, 1 de 4 golpes que lo matarian lo dejan con 1 (LifeDownSet2)
    if vida - d <= 0 and vida > 300 and azar() < 0.25 then vida = 1 else vida = math.max(0, vida - d) end
    info(string.format("leon: recibe %d -> vida %d", d, vida))
    local hx, hy, hz = compartido("leon_danio_px"), compartido("leon_danio_py"), compartido("leon_danio_pz")
    if hx then efecto("fx_sangre_leon", hx, hy, hz, 0, haciaYaw(hx, hz, ox, oz)) end
    setVisible(cuchillo, false); setVisible(pistola, true); pitch = 0
    if vida <= 0 then
        estado = "muerto"; muertoT = 4
        ponerBase("muerte", false, true)
        snd("leon_muerte", 1.0)
    else
        estado = "dano"
        local c = alto and (atras and "dano_cabeza_atras" or "dano_cabeza_frente") or (atras and "dano_atras" or "dano_frente")
        ponerBase(c, false, true)
        sndAzar("leon_dolor", 3, 1.0)
    end
end

-- el cuchillo: el tajo corta en los frames 6..10 un segmento del pecho a la mano + 0.75 m (pl_knife)
local function tajoGolpe()
    if tajoHecho or not ganadoVivo() then return end
    local f = animCapaFrame(leon, 1)
    if f < 6 or f > 10 then return end
    local ax, ay, az = px, py + 1.2, pz
    local hx, hy, hz = huesoPunto(leon, "hueso_010")
    if not hx then return end
    local dx, dy, dz = hx - ax, hy - ay, hz - az
    local l = math.sqrt(dx * dx + dy * dy + dz * dz)
    if l < 1e-3 then return end
    dx, dy, dz = dx / l, dy / l, dz / l
    local t, zona, en = rayoGanado(ax, ay, az, dx, dy, dz)
    if t and t <= l + 0.75 and vivo(en) then
        tajoHecho = true
        local x, y, z = ax + dx * t, ay + dy * t, az + dz * t
        golpear(en, zona, zona == "cabeza" and DANIO.cuchillo_cabeza or DANIO.cuchillo, x, y, z)
        efecto("fx_cuchillo", x, y, z, 0, haciaYaw(x, z, px, pz))
        sndAzar("cuchillo_carne", 2, 1.0)
    end
end

-- VENTANA: la regla del juego (windowCheck): p0 = Leon + 0.4 m de alto, p1 = p0 + 1 m adelante. p1 dentro del campo
-- de salto (1 x 2 m centrado en la ventana, altura [ventana.y - 2, ventana.y + 1)) y el segmento p0 -> p1 CRUZA el plano
-- del vidrio. El salto sale del lado donde esta Leon. Devuelve la ventana y el salto (o nil).
local function ventanaDelante()
    local r = math.rad(yaw)
    local x0, y0, z0 = px, py + 0.4, pz
    local x1, z1 = x0 + math.sin(r), z0 + math.cos(r)
    for _, w in ipairs(VENTANAS) do
        if not ventanaRota[w.n] then
            local fx_, fz = math.sin(w.yaw), math.cos(w.yaw)       -- frente (+Z local)
            local rx, rz = math.cos(w.yaw), -math.sin(w.yaw)        -- derecha (+X local)
            local lz0 = (x0 - w.x) * fx_ + (z0 - w.z) * fz
            local lz1 = (x1 - w.x) * fx_ + (z1 - w.z) * fz
            local lx1 = (x1 - w.x) * rx + (z1 - w.z) * rz
            if math.abs(lx1) <= 0.5 and math.abs(lz1) <= 1.0 and y0 + 0.1 >= w.y - 2.0 and y0 < w.y + 1.0
               and ((lz0 > 0) ~= (lz1 > 0)) then
                local lado = (lz0 > 0) and 1 or -1
                for _, sj in ipairs(w.saltos) do
                    if sj.lado == lado then return w, sj end
                end
            end
        end
    end
    return nil
end

local function saltarVentana(w, sj)
    saltoV = {w = w, s = sj, rompio = false}
    estado = "ventana"; pitch = 0; vozVentana = false
    setVisible(cuchillo, false); setVisible(pistola, true)
    -- el juego lo pone en el lugar de arranque del salto (espacio de la ventana), sin colision hasta que termina
    px, py, pz = sj.x, sj.y, sj.z
    yaw = math.deg(sj.yaw)
    ponerBase(sj.clip, false, true)
    -- el juego oculta el medidor de vida durante el salto; en el frame 0 el efecto sobre Leon
    setCompartido("hud_visible", false)
    efecto(sj.fxl, px, py, pz, 0, yaw)
end

-- la PATADA: con el ganado aturdido, cerca (1.5 m) y de frente (60 grados)
local function puedePatear()
    for _, e in ipairs(enemigos) do
        if vivo(e) and compartido(e.K .. "ganado_aturdido") then
            local gx, gz = compartido(e.K .. "ganado_x"), compartido(e.K .. "ganado_z")
            if gx then
                local dx, dz = gx - px, gz - pz
                if dx * dx + dz * dz <= 1.5 * 1.5 then
                    local dif = ((math.deg(math.atan(dx, dz)) - yaw + 180) % 360) - 180
                    if math.abs(dif) < 60 then return e end
                end
            end
        end
    end
    return nil
end
local pateado = nil   -- el enemigo que se esta pateando

-- vuelve a empezar despues de morir: donde lo deja la cinematica, con todo lleno
local function reiniciar()
    vida, balas, reserva = VIDA_MAX, CARGADOR, 20
    px, py, pz = -82.91, 0.86, -38.48
    yaw = math.deg(1.75)
    estado = "normal"; pitch = 0
    cam_.iniciada = false
    base = nil
    ponerBase("quieto", true, true)
    setVisible(pistola, true); setVisible(cuchillo, false)
    setCompartido("reinicio_n", (compartido("reinicio_n") or 0) + 1)
end

-- la camara del juego: detras y a la derecha; apuntando (pistola o cuchillo) se arrima al hombro y sigue la
-- punteria arriba/abajo. Todo se interpola: nada salta
local function camara(dt)
    if not cam then return end
    -- saltando por una ventana la camara se queda donde estaba y sigue a Leon con la mirada (si lo siguiera, el
    -- rayo contra las paredes la meteria adentro del muro mientras Leon atraviesa la ventana)
    if estado == "ventana" then
        -- la camara de HOMBRO del juego durante el salto, por frame (salto_ventana.json: sigue la raiz de Leon con
        -- sus suavizados y el rayo contra las paredes); sin tabla: quieta mirando a Leon
        local t = CAMV[saltoV.s.clip]
        if t then
            local n = #t // 6
            local f = math.max(0, math.min(n - 1, math.floor(animCapaFrame(leon, 1))))
            local a = 6 * f
            setPosicion(cam, t[a + 1], t[a + 2], t[a + 3])
            mirarA(cam, t[a + 4], t[a + 5], t[a + 6])
            cam_.iniciada = false
        else
            mirarA(cam, px, py + 1.2, pz)
        end
        return
    end
    local lejos, costado, alto, pc = 2.3, 0.45, 1.65, 0
    if estado ~= "normal" then lejos, costado, alto = 1.2, 0.55, 1.55; pc = pitch * 38 end
    local k = math.min(1, dt * CAM_SUAVE)
    if not cam_.iniciada then cam_.yaw = yaw; cam_.iniciada = true; k = 1 end
    cam_.lejos   = cam_.lejos   + (lejos   - cam_.lejos)   * k
    cam_.costado = cam_.costado + (costado - cam_.costado) * k
    cam_.alto    = cam_.alto    + (alto    - cam_.alto)    * k
    cam_.pitch   = cam_.pitch   + (pc      - cam_.pitch)   * k
    local dy = yaw - cam_.yaw
    while dy > 180 do dy = dy - 360 end
    while dy < -180 do dy = dy + 360 end
    cam_.yaw = cam_.yaw + dy * math.min(1, dt * CAM_SUAVE * 1.5)
    local r = math.rad(cam_.yaw)
    local fx_, fz = math.sin(r), math.cos(r)
    local rx, rz = -fz, fx_
    -- al apuntar arriba/abajo la camara tambien baja/sube un poco (orbita el hombro)
    local sube = -math.sin(math.rad(cam_.pitch)) * cam_.lejos * 0.35
    local cx = px - fx_ * cam_.lejos + rx * cam_.costado
    local cy = py + cam_.alto + sube
    local cz = pz - fz * cam_.lejos + rz * cam_.costado
    -- que la camara no atraviese las paredes: si hay una entre la cabeza de Leon y la camara, se arrima
    if colParedM then
        local hx, hy, hz = px, py + cam_.alto, pz
        local dx, dy, dz = cx - hx, cy - hy, cz - hz
        local l = math.sqrt(dx * dx + dy * dy + dz * dz)
        if l > 0.01 then
            local t = colRayo(colParedM, hx, hy, hz, dx, dy, dz, l)
            if t then
                local k = math.max(0.15, t - 0.15) / l
                cx, cy, cz = hx + dx * k, hy + dy * k, hz + dz * k
            end
        end
    end
    setPosicion(cam, cx, cy, cz)
    local p = math.rad(cam_.pitch)
    mirarA(cam, cx + fx_ * math.cos(p) * 10, cy + math.sin(p) * 10, cz + fz * math.cos(p) * 10)
end

function inicio()
    leon     = buscar("Leon")
    cam      = buscar("Cámara")
    laser    = buscar("Leon_laser")
    luz      = buscar("Leon_fx_luz")
    -- la pistola con ESQUELETO (corredera / cargador animados) si la escena la trae; si no, la rigida
    pistolaArm = buscar("Pistola")
    pistola  = pistolaArm or buscar("Leon_pistola")
    if pistolaArm then setVisible(buscar("Leon_pistola"), false); armaClip("reposo", true) end
    cuchillo = buscar("Leon_cuchillo")
    for i, e in ipairs(FX) do fx[i] = buscar(e[1]) end
    px, py, pz = posicion(leon)
    local _, ry = rotacion(leon)
    yaw = ry or 0
    colSueloM = buscar("r100_col_suelo")
    colParedM = buscar("r100_col_pared")
    colCamionM = buscar("r100_col_camion")
    puertaM = buscar("r100_puerta")
    if colSueloM then
        local s = colSuelo(colSueloM, px, py + 1.0, pz, 0.0)   -- arranca apoyado en el piso de abajo
        if s then py = s end
    end
    -- COMBATE: el ganado, el punto del laser, los efectos de impacto, la punta del laser
    enemigosLista = nil
    punto = buscar("Leon_laser_punto")
    for nombre, lista in pairs(FXC) do
        local emp = buscar(nombre)
        if emp then
            local l = {}
            for _, e in ipairs(lista) do local o = buscar(e[1]); if o then l[#l + 1] = {o, e[2]} end end
            objFX[nombre] = {emp = emp, lista = l}
        end
    end
    laserFar = {}
    for i = 1, 8 do
        local x = verticePos(laser, i)
        if x and x < -1 then laserFar[#laserFar + 1] = i end
    end
    vida, balas, reserva = VIDA_MAX, CARGADOR, 20
    danioVisto = compartido("leon_danio_n") or 0
    setVisible(laser, false)
    setVisible(luz, false)
    setVisible(cuchillo, false)
    setVisible(pistola, true)
    ponerBase("quieto", true)
    animCapa(leon, 2, "apuntar_arriba", 0, "mezclar", true)   -- la capa de punteria existe desde el arranque
end

local enCine = false   -- una cinematica (evento.lua / intro.lua) tiene el control: compartido("cinematica")
-- CORRER en el telefono: dos toques a "adelante" y mantenerlo (en la PC tambien vale shift)
local DOBLE_TOQUE = 0.35
local reloj, ultimoAdelante, corriendo = 0, -10, false
local autoIni = false
-- una tecla recien apretada (el jugador no maneja mientras Leon camina solo)
local function tap(k) return not compartido("leon_auto") and teclaApretada(k) end

local function publicar()
    setCompartido("leon_vida", vida); setCompartido("balas", balas); setCompartido("balas_reserva", reserva)
end

-- los TROZOS de vidrio del salto: la trayectoria del juego por frame (sin el azar); al terminarse, desaparecen
local function moverTrozos(dt)
    if not trozosV then return end
    trozosV.t = trozosV.t + dt * 30
    local f = math.floor(trozosV.t)
    local vivos = false
    for _, tr in ipairs(trozosV.lista) do
        local o = tr.o
        if o == nil then o = buscar(tr[1]) or false; tr.o = o end
        if o then
            local p = tr[2]
            if 3 * f + 3 <= #p then
                vivos = true
                setVisible(o, true)
                setPosicion(o, p[3 * f + 1], p[3 * f + 2], p[3 * f + 3])
            else
                setVisible(o, false)
            end
        end
    end
    if not vivos then trozosV = nil end
end

function actualizar(dt)
    actualizarEnemigos()
    publicar()
    moverTrozos(dt)
    if compartido("cinematica") then enCine = true return end
    -- "leon_resync": lo deja evento.lua al terminar. Hace falta porque mientras dura la cinematica este Leon esta
    -- OCULTO y Whisk3D no corre los scripts de objetos ocultos: puede que nunca haya visto "cinematica"
    if compartido("leon_resync") then setCompartido("leon_resync", false); enCine = true end
    if enCine then
        -- volvio el control: releer donde quedo Leon (evento.lua lo deja donde lo deja el juego) y el rumbo
        enCine = false
        px, py, pz = posicion(leon)
        local _, ry = rotacion(leon)
        yaw = ry or 0
        estado = "normal"; pitch = 0
        cam_.iniciada = false
        ponerBase("quieto", true, true)
        animCapa(leon, 2, "apuntar_arriba", 0, "mezclar", true)
        setVisible(pistola, true); setVisible(cuchillo, false)
    end
    local arriba    = tecla("w") or tecla("arriba")
    local abajo     = tecla("s") or tecla("abajo")
    local izquierda = tecla("a") or tecla("izquierda")
    local derecha   = tecla("d") or tecla("derecha")
    reloj = reloj + dt
    if tap("arriba") or tap("w") then
        if reloj - ultimoAdelante < DOBLE_TOQUE then corriendo = true end
        ultimoAdelante = reloj
    end
    if not arriba then corriendo = false end
    local corre     = tecla("shift") or corriendo
    -- el TELEFONO (N95): el OK del D-pad (llega como "enter" y tambien como "espacio") y el softkey derecho ("softder").
    -- OK: con un cartel en pantalla hace la accion (patada, ventana, hablar); si no, apunta / dispara / acuchilla.
    -- Softkey derecho: apuntando deja de apuntar; sin apuntar saca el cuchillo y con el cuchillo lo guarda
    local ok      = tap("enter")
    local softder = tap("softder")

    -- CAMINAR SOLO (la escena de la ventana, intro.lua): el juego pone a Leon en un lugar (setPos / setAng) y lo hace
    -- caminar hacia la casa con la motion de caminar; el jugador no maneja
    if compartido("leon_auto") then
        if not autoIni then
            autoIni = true
            px, py, pz = compartido("leon_auto_x") or px, compartido("leon_auto_y") or py, compartido("leon_auto_z") or pz
            yaw = compartido("leon_auto_yaw") or yaw
            if colSueloM then local s2 = colSuelo(colSueloM, px, py + 1.0, pz, 1.5); if s2 then py = s2 end end
            estado = "normal"; pitch = 0
            setVisible(pistola, true); setVisible(cuchillo, false)
        end
        arriba, abajo, izquierda, derecha, corre = true, false, false, false, false
    else
        autoIni = false
    end

    recibirDanio()
    local bloqueado = (estado == "dano" or estado == "muerto" or estado == "patada" or estado == "ventana")
    if bloqueado then izquierda, derecha, arriba, abajo = false, false, false, false end

    if izquierda then yaw = yaw + GIRO * dt end
    if derecha   then yaw = yaw - GIRO * dt end

    -- apuntando / con el cuchillo no se camina: W/S mueven la punteria
    if estado == "apuntar" or estado == "cuchillo" then
        if arriba then pitch = math.min(1, pitch + PITCH_VEL * 0.8 * dt) end
        if abajo  then pitch = math.max(-1, pitch - PITCH_VEL * dt) end
    end

    -- BOTON DE ACCION (F / A del joystick): la patada al ganado aturdido sale tambien con el cuchillo en la mano
    -- (despues de un tajo a la cabeza o la canilla) o apuntando
    local accion = tap("f") or (not compartido("leon_auto") and botonApretado("a"))
    -- el CARTEL del boton de accion (lo dibuja el HUD): la patada le gana a todo; despues la ventana. Los de otros
    -- scripts (hablar con los policias) solo valen si Leon no ofrece nada (compartido "cartel_leon" vacio).
    local cartel, vent, salto = nil, nil, nil
    local patea = (estado == "normal" or estado == "cuchillo" or estado == "apuntar") and puedePatear()
    if patea then cartel = "KICK"
    elseif estado == "normal" then
        vent, salto = ventanaDelante()
        if salto then cartel = salto.cartel end
    end
    -- (el OK es la accion si hay un cartel y no se esta apuntando: apuntando, el OK dispara)
    if ok and (estado == "normal" or estado == "cuchillo") and
       (cartel ~= nil or (estado == "normal" and compartido("cartel_camino") ~= nil)) then
        accion = true; ok = false
    end
    setCompartido("cartel_leon", cartel)
    setCompartido("leon_accion", accion == true and cartel == nil)   -- el boton queda libre para otros scripts
    if accion and patea then
        setVisible(cuchillo, false); setVisible(pistola, true); pitch = 0
        estado = "patada"; patadaHecha = false
        -- de pie (tiro / tajo en la cabeza): la patada de frente; arrodillado: la patada giratoria
        pateado = patea
        patadaClip = compartido(patea.K .. "ganado_rodillas") and "patada" or "patada_frontal"
        ponerBase(patadaClip, false, true)
        snd("patada_voz", 1.0); snd("patada_swing", 1.0)
    elseif accion and salto then
        saltarVentana(vent, salto)
    elseif estado == "normal" and tap("r") then
        recargar()
    end

    if estado == "normal" then
        if tap("e") or ok then
            estado = "desenfundar"; pitch = 0
            ponerBase("desenfundar", false, true)
            snd("pistola_desenfundar", 1.0)
        elseif tap("q") or softder then
            estado = "sacar"; pitch = 0; armaCambiada = false
            ponerBase("cuchillo_desenfundar", false, true)
        elseif arriba then ponerBase(corre and "correr" or "caminar", true)
        elseif abajo then ponerBase("atras", true)
        elseif izquierda then ponerBase("girar_izq", true)
        elseif derecha then ponerBase("girar_der", true)
        else ponerBase("quieto", true) end

    elseif estado == "desenfundar" then
        if animCapaTermino(leon, 1) then estado = "apuntar"; ponerBase("apuntar", true) end

    elseif estado == "apuntar" or estado == "disparar" then
        if estado == "disparar" and animCapaTermino(leon, 1) then estado = "apuntar"; ponerBase("apuntar", true) end
        if tap("e") or softder then
            estado = "enfundar"; pitch = 0
            ponerBase("enfundar", false, true)
        elseif tap("r") then
            recargar()
        elseif (tap("espacio") or ok) and (estado == "apuntar" or animCapaFrame(leon, 1) >= 12) then
            disparar()
        end

    elseif estado == "enfundar" then
        if animCapaTermino(leon, 1) then estado = "normal"; ponerBase("quieto", true) end

    elseif estado == "sacar" then
        -- frame 4: la pistola se va y aparece el cuchillo (pl_knife.cpp, FACE_SET)
        if not armaCambiada and animCapaFrame(leon, 1) >= 4 then
            setVisible(pistola, false); setVisible(cuchillo, true); armaCambiada = true
        end
        if animCapaTermino(leon, 1) then estado = "cuchillo"; ponerBase("cuchillo_quieto", true) end

    elseif estado == "cuchillo" or estado == "tajo" then
        if estado == "tajo" and animCapaTermino(leon, 1) then estado = "cuchillo"; ponerBase("cuchillo_quieto", true) end
        if tap("q") or softder then
            estado = "guardar"; pitch = 0; armaCambiada = false
            ponerBase("cuchillo_guardar", false, true)
        elseif (tap("espacio") or ok) and estado == "cuchillo" then
            estado = "tajo"; tajoHecho = false
            ponerBase("cuchillo_tajo", false, true)
        end
        if estado == "tajo" then tajoGolpe() end
        if estado == "tajo" and frameAnt < 3 and animCapaFrame(leon, 1) >= 3 then snd("cuchillo_tajo", 1.0) end

    elseif estado == "recargar" then
        -- las balas entran en el frame 31 (objRuger moveReload); se puede salir desde el 36
        if not recargado and animCapaFrame(leon, 1) >= 31 then
            local n = math.min(CARGADOR - balas, reserva)
            balas = balas + n; reserva = reserva - n; recargado = true
        end
        if animCapaTermino(leon, 1) or (recargado and animCapaFrame(leon, 1) >= 36 and volverApuntar and not tecla("r")) then
            if volverApuntar then estado = "apuntar"; ponerBase("apuntar", true) else estado = "normal"; ponerBase("quieto", true) end
        end

    elseif estado == "ventana" then
        -- el salto: el vidrio se rompe en su frame; al terminar el clip vuelve el control (apoyado en el piso)
        local fv = animCapaFrame(leon, 1)
        local sj, w = saltoV.s, saltoV.w
        if not saltoV.rompio and fv >= sj.rompe then
            saltoV.rompio = true
            ventanaRota[w.n] = true
            setVisible(buscar("Ventana_intacta_" .. w.n), false)
            setVisible(buscar("Ventana_rota_" .. w.n), true)
            snd("vidrio_rompe", 1.0)
            efecto(sj.fx, w.x, w.y, w.z, 0, math.deg(w.yaw))    -- en el origen de la ventana, con su rotacion
            if TROZOS[sj.clip] then trozosV = {lista = TROZOS[sj.clip], t = 0} end
        end
        -- sonidos del clip (las voces de Leon son UNA al azar de las tres)
        local tabla = SEQV[sj.clip]
        if tabla then
            for k, n in pairs(tabla) do
                if k > frameAnt and k <= fv then
                    if string.sub(n, 1, 12) == "ventana_leon" then
                        if not vozVentana then vozVentana = true; snd("ventana_leon_" .. azar(1, 3), 1.0) end
                    else snd(n, 1.0) end
                end
            end
        end
        if animCapaTermino(leon, 1) then
            estado = "normal"; saltoV = nil
            setCompartido("hud_visible", true)
            if colSueloM then local s2 = colSuelo(colSueloM, px, py + 0.5, pz, 1.0); if s2 then py = s2 end end
            ponerBase("quieto", true)
        end

    elseif estado == "patada" then
        -- el pie llega en el frame 16: tira al ganado (200)
        if not patadaHecha and animCapaFrame(leon, 1) >= 16 then
            patadaHecha = true
            -- el juego pega con dos esferas de 1.2 m adelante de Leon: a TODOS los que toquen
            local r = math.rad(yaw)
            local cx, cz = px + math.sin(r) * 0.3, pz + math.cos(r) * 0.3
            for _, e in ipairs(enemigos) do
                local gx, gz = compartido(e.K .. "ganado_x"), compartido(e.K .. "ganado_z")
                if vivo(e) and gx and (gx - cx) ^ 2 + (gz - cz) ^ 2 < 1.5 * 1.5 then
                    golpear(e, "patada", DANIO.patada, gx, py + 1.2, gz)
                    snd("patada_impacto", 1.0)
                end
            end
        end
        if animCapaTermino(leon, 1) then estado = "normal"; ponerBase("quieto", true) end

    elseif estado == "dano" then
        if animCapaTermino(leon, 1) then estado = "normal"; ponerBase("quieto", true) end

    elseif estado == "muerto" then
        if animCapaTermino(leon, 1) then
            muertoT = muertoT - dt
            if muertoT <= 0 then reiniciar() end
        end

    elseif estado == "guardar" then
        if not armaCambiada and animCapaFrame(leon, 1) >= 4 then
            setVisible(cuchillo, false); setVisible(pistola, true); armaCambiada = true
        end
        if animCapaTermino(leon, 1) then estado = "normal"; ponerBase("quieto", true) end
    end

    punteria()

    -- root motion + pasos de la base
    local f = animCapaFrame(leon, 1)
    local ax, az = avanceRaiz(base, frameAnt, f)
    if estado == "ventana" then
        -- sin colision (el juego apaga la colision de Leon durante el salto) y con la ALTURA de la raiz (RAIZY)
        local r = math.rad(yaw)
        local c, sn = math.cos(r), math.sin(r)
        px, pz = px + ax * c + az * sn, pz - ax * sn + az * c
        local ty = RAIZY[base]
        if ty then
            local function en(t, fr)
                if fr <= 0 then return t[1] end
                if fr >= #t - 1 then return t[#t] end
                local i = math.floor(fr); return t[i + 1] + (t[i + 2] - t[i + 1]) * (fr - i)
            end
            if f >= frameAnt then py = py + en(ty, f) - en(ty, frameAnt) end
        end
        ax, az = 0, 0
    end
    if ax ~= 0 or az ~= 0 then
        local r = math.rad(yaw)
        local c, sn = math.cos(r), math.sin(r)
        local nx, nz = px + ax * c + az * sn, pz - ax * sn + az * c
        if colParedM then nx, nz = colPared(colParedM, nx, py, nz, RADIO) end
        if puertaM then nx, nz = colPared(puertaM, nx, py, nz, RADIO) end
        if camionM() then nx, nz = colPared(colCamionM, nx, py, nz, RADIO) end
        -- el ganado (vivo) es un cuerpo: Leon no se le mete adentro
        for _, e in ipairs(enemigos) do
            local gx, gz = compartido(e.K .. "ganado_x"), compartido(e.K .. "ganado_z")
            if gx and vivo(e) then
                local ex, ez = nx - gx, nz - gz
                local dd = math.sqrt(ex * ex + ez * ez)
                if dd < 0.7 and dd > 1e-4 then nx, nz = gx + ex / dd * 0.7, gz + ez / dd * 0.7 end
            end
        end
        if colSueloM then
            local s = colSuelo(colSueloM, nx, py, nz, SUBIDA)
            if s then
                px, pz = nx, nz
                if s < py then py = math.max(s, py - CAIDA_VEL * dt) else py = s end
            end   -- sin piso (borde del mapa): no se mueve
        else
            px, pz = nx, nz
        end
    elseif colSueloM and estado ~= "ventana" then
        local s = colSuelo(colSueloM, px, py, pz, SUBIDA)
        if s and s < py then py = math.max(s, py - CAIDA_VEL * dt) end
    end
    pasos(base, frameAnt, f)
    frameAnt = f

    setPosicion(leon, px, py, pz)
    setRotacion(leon, 0, yaw, 0)

    laserActualizar(estado == "apuntar" or estado == "disparar")
    -- la pistola vuelve a su reposo al terminar un disparo / recarga (vacia: la corredera queda trabada atras)
    if pistolaArm and animTermino(pistolaArm) then armaClip(balas == 0 and "reposo_vacia" or "reposo", true) end
    if luzT > 0 then
        luzT = luzT - dt
        if luzT <= 0 then setVisible(luz, false) end
    end
    if casquilloT >= 0 then
        casquilloT = casquilloT - dt
        if casquilloT < 0 then snd("casquillo_suelo", 0.7) end
    end

    camara(dt)
end
