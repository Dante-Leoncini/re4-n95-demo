-- ============================================================================
--  hud.lua -- el HUD de Resident Evil 4 (GameCube) en Whisk3D. Va en la escena UI "HUD" (escenas/hud.w3dui,
--  la arma hud_r100.py con los datos de out/combate/hud.json).
--
--  Lo que dibuja (como cockpit.cpp del juego):
--    * MEDIDOR DE VIDA: un anillo cuyo relleno son hasta 3 "cuartos de anillo" que GIRAN 45 grados cada 400 PV
--      (LifeMeter::move, cockpit.cpp:205-232) con la vida SUAVIZADA m_life = 0.9*m_life + 0.1*vida por frame.
--      El color del relleno LATE (curva tipo corazon) segun el estado: Bien (> 800), Precaucion (> 400) y
--      Peligro; los colores de la plantilla del estado se persiguen 0.9/0.1 por frame (cockpit.cpp:249-319).
--      En Precaucion y Peligro ademas destella el disco (unidades 0x13 / 0x14, cockpit.cpp:343-358).
--    * BALAS: las CARGADAS en el arma (la version GameCube no muestra la reserva) con los digitos de la tira
--      0x27; la decena se ve siempre ("07"), la centena solo si no es 0. Sin balas cargadas y sin reserva:
--      cartel EMPTY (cockpit.cpp:540-618).
--    * Entrada/salida: la raiz se desliza 175 px a la derecha en 8 frames (camino de raiz_hud, ease in/out).
--    * GRANO de pantalla (esp04 "screen tiled overlay" de r100, out/r100_fx/emisores.json): ruido en mosaico cada
--      200x200 px de la pantalla del GameCube (512x448, pixel 1.1667 de ancho: el 4:3 de la tele), corrido al azar
--      +-100 / +-110 px cada frame. Queda tambien en las cinematicas (solo el medidor se oculta).
--
--  Lo que LEE (lo escriben otros scripts; este no escribe nada):
--    compartido("leon_vida")      0..1200            (nil = 1200)
--    compartido("leon_vida_max")  vida maxima         (nil = 1200; gira la rayita de la vida maxima)
--    compartido("balas")          balas cargadas      (nil = 10)
--    compartido("balas_reserva")  balas en el maletin (nil = 20)
--    compartido("hud_visible")    false en las cinematicas: el HUD sale deslizando (nil = true)
--    compartido("cinematica")     true mientras evento.lua tiene el control: tambien lo saca
--
--  Toda la logica corre a 30 pasos por segundo (el juego avanza sus timers de a 1 por frame de 30 fps).
-- ============================================================================

propiedades = {}

local DT = 1 / 30
local acum = 0

-- ---- datos del juego (out/combate/hud.json) --------------------------------
-- plantillas de color por estado (unidades 0x11 Bien / 0x10 Precaucion / 0x0F Peligro): col0 -> col1 con la
-- curva de pulso (claves {t, valor, tangente de salida, tangente de entrada}, Hermite_1CurveCalc)
local PLANTILLAS = {
    { c0 = {0, 35, 0},  c1 = {0, 85, 0},
      curva = {{0, 0, 0, 0}, {11.487703, 1, 0, 0}, {16.801392, 0.5, 0, 0}, {22.218796, 0.85, 0, 0}, {60, 0, 0, 0}} },
    { c0 = {40, 20, 0}, c1 = {100, 60, 0},
      curva = {{0, 0, 0, 0}, {6.280989, 1, 0, 0}, {10.468316, 0.6, 0, 0}, {14.942815, 1, 0, 0}, {31.404951, 0, 0, 0}} },
    { c0 = {40, 0, 0},  c1 = {130, 0, 0},
      curva = {{0, 0, 0, 0}, {2.673, 1, 0, 0}, {4.455, 0.6, 0, 0}, {7.128, 1, 0, 0}, {13.365, 0, 0, 0}} },
}
-- destellos: col1 = 0 -> el alpha ES la curva (0..255) y el rgb es col0 (id_sys.cpp idSysMove02)
local DESTELLOS = {
    [2] = { rgb = {125, 80, 0}, curva = {{0, 0, 0, 0}, {9.262221, 255, 0, 0}, {18.524443, 0, 0, 0}} },
    [3] = { rgb = {115, 0, 0},  curva = {{0, 0, 0, 0}, {2.522777, 255, 0, 0}, {5.045554, 0, 0, 0}} },
}
local GRIS_0A = 206 / 255              -- la textura del destello (tex 0x0A) es gris 206, no blanca
-- ADITIVO APROXIMADO (Whisk3DUI solo mezcla con alpha): se supone que debajo del destello esta el disco oscuro
-- (alpha 165/255, gris 206*25/255) sobre una escena gris 0.28 = FONDO. Con A = max S/(1-FONDO) y
-- tinte = (S + A*FONDO)/A la mezcla da dst + S + A*(FONDO - dst): exacto sobre el fondo supuesto
local FONDO = 0.28 * (1 - 165 / 255) + (165 / 255) * GRIS_0A * 25 / 255
-- brillo de la esfera: alpha por su curva (125..132, loop); la textura esta horneada con 132
local BRILLO_CURVA = {{0, 125, 0, 0}, {4, 132, 0, 0}, {7.5, 125, 0, 0}}
local BRILLO_MAX = 132
-- entrada/salida de la raiz: camino (217,-130) -> (392,-130) con la curva 0..1 en 8 frames (tangentes 0)
local SALIDA_PX = 175
local SALIDA_FRAMES = 8
-- digitos: tira propia de hud_r100.py (10 celdas de 16 px + 2 px vacios entre cada una)
local DIG_W, DIG_PAD = 16, 2
local TIRA_W = (DIG_W + DIG_PAD) * 10

-- grano: el mosaico en pixeles del framebuffer del GameCube y su temblor por frame
local GRANO_TILE = 200
local GRANO_TEMBLOR_X, GRANO_TEMBLOR_Y = 100, 110
local EFB_W, PIXEL_ASPECTO = 512, (4 / 3 * 448) / 512   -- el ancho de la imagen 4:3 en px del EFB y su aspecto
local granoU, granoV = 0, 0
-- FUNDIDO a/desde negro: compartido "fundido" = objetivo (0 nada .. 1 negro), "fundido_seg" = cuanto tarda,
-- "fundido_ya" = valor inmediato (se consume)
local fundido
local fundidoA = 0
-- el CARTEL del boton de accion: compartido "cartel_leon" (patada, ventana) o "cartel_camino" (hablar)
local accion, accionTexto
local cartelActual = nil

-- ---- objetos --------------------------------------------------------------
local raiz, destello, brillo, brilloEmpty, empty, grano
local cuartos = {}        -- [1..3] = contenedor que gira; cuartosImg[1..3] = la imagen (el tinte)
local cuartosImg = {}
local digitos = {}        -- [1] unidades, [2] decenas, [3] centenas
local marcaMax

-- ---- estado ---------------------------------------------------------------
local mLife = 1200        -- vida suavizada (cLifeMeter::m_life)
local col0, col1 = {0, 35, 0}, {0, 85, 0}   -- colores de la plantilla, suavizados
local tPulso = 0          -- timer[2] del grupo 0x12 (sigue corriendo aunque cambie la curva)
local tDest = {[2] = 0, [3] = 0}
local tBrillo = 0
local tSalida = 0         -- 0 = en su lugar, SALIDA_FRAMES = afuera
local estadoVida = 1
local ultimoDigito = {-1, -1, -1}

-- Hermite_1CurveCalc (hermite.cpp): fuera del rango da 0
local function hermite(claves, t)
    for i = 1, #claves - 1 do
        local k0, k1 = claves[i], claves[i + 1]
        if t >= k0[1] and t <= k1[1] then
            local dt = k1[1] - k0[1]
            local s = (t - k0[1]) / dt
            local s2, s3 = s * s, s * s * s
            local h01 = -(s3 + s3) + 3 * s2
            local h11 = s3 - s2
            local h10 = h11 - s2 + s
            local h00 = 1 - h01
            return h00 * k0[2] + h01 * k1[2] + dt * (h10 * k0[3] + h11 * k1[4])
        end
    end
    return 0
end

-- el timer de una curva con loop: sube de a 1 y vuelve a 0 al llegar a la ultima clave (idSysMove02)
local function avanzar(t, claves)
    t = t + 1
    if t >= claves[#claves][1] then t = 0 end
    return t
end

local function num(nombre, defecto)
    local v = compartido(nombre)
    if type(v) ~= "number" then return defecto end
    return v
end

-- cPlayer::getLifeLevel (pl_class.cpp): tope fijo, NO usa la vida maxima
local function nivelVida(vida)
    if vida > 800 then return 1 end
    if vida > 400 then return 2 end
    return 3
end

function inicio()
    raiz     = buscar("hud_raiz")
    grano    = buscar("hud_grano")
    fundido  = buscar("hud_fundido")
    accion   = buscar("hud_accion")
    accionTexto = buscar("hud_accion_texto")
    destello = buscar("hud_destello")
    brillo   = buscar("hud_brillo")
    brilloEmpty = buscar("hud_brillo_empty")   -- el mismo brillo horneado sobre el cartel EMPTY
    empty    = buscar("hud_empty")
    marcaMax = buscar("hud_marca_vida_max")
    for i = 1, 3 do
        cuartos[i] = buscar("hud_cuarto_" .. i)
        cuartosImg[i] = buscar("hud_cuarto_" .. i .. "_img")
    end
    digitos[1] = buscar("hud_digito_unidades")
    digitos[2] = buscar("hud_digito_decenas")
    digitos[3] = buscar("hud_digito_centenas")
    -- LifeMeter::roomInit: arranca con la vida actual y los colores de su estado (sin transicion)
    local vida = num("leon_vida", 1200)
    mLife = vida
    estadoVida = nivelVida(vida)
    local p = PLANTILLAS[estadoVida]
    col0 = {p.c0[1], p.c0[2], p.c0[3]}
    col1 = {p.c1[1], p.c1[2], p.c1[3]}
    local vis = compartido("hud_visible")
    tSalida = (vis == false or compartido("cinematica") == true) and SALIDA_FRAMES or 0
    acum = 0
end

-- ---- los SETTERS solo cuando cambia el valor: cada llamada al motor cuesta (en el N95 el HUD se comia 5-10 ms por
-- cuadro: ~35 llamadas por paso y, a pocos fps, hasta 4 pasos de recuperacion por cuadro)
local cacheV, cacheO, cacheR, cacheT, cacheP = {}, {}, {}, {}, {}
local function ponVisible(o, v) if o and cacheV[o] ~= v then cacheV[o] = v; setVisible(o, v) end end
local function ponOpacidad(o, a) if o and cacheO[o] ~= a then cacheO[o] = a; setOpacidad(o, a) end end
local function ponRot(o, r) if o and cacheR[o] ~= r then cacheR[o] = r; setRot2D(o, r) end end
local function ponTinte(o, r, g, b, a)
    if not o then return end
    local t = cacheT[o]
    if not t then t = {}; cacheT[o] = t end
    if t[1] ~= r or t[2] ~= g or t[3] ~= b or t[4] ~= a then t[1], t[2], t[3], t[4] = r, g, b, a; setTinte(o, r, g, b, a) end
end
local function ponPosPx(o, x, y)
    if not o then return end
    local t = cacheP[o]
    if not t then t = {}; cacheP[o] = t end
    if t[1] ~= x or t[2] ~= y then t[1], t[2] = x, y; setPosPx(o, x, y) end
end

-- lo que se lee del juego UNA vez por cuadro (no cambia entre los pasos del mismo cuadro)
local vidaF, vidaMaxF, ocultarF = 1200, 1200, false
local rPulso, opBrillo = 0, 1

-- un frame de 30 fps de la logica del juego: SOLO el estado (los timers, el suavizado, el azar del grano). Lo que se
-- ve lo pone aplicar(), una vez por cuadro, con el estado del ultimo paso
local function paso()
    mLife = 0.9 * mLife + 0.1 * vidaF        -- vida suavizada (METER_ROT usa la suavizada)
    estadoVida = nivelVida(vidaF)
    local p = PLANTILLAS[estadoVida]
    for k = 1, 3 do
        col0[k] = 0.9 * col0[k] + 0.1 * p.c0[k]
        col1[k] = 0.9 * col1[k] + 0.1 * p.c1[k]
    end
    rPulso = hermite(p.curva, tPulso)
    tPulso = avanzar(tPulso, p.curva)
    -- destellos (aditivos en el juego: ver FONDO)
    for e, d in pairs(DESTELLOS) do
        d.alpha = hermite(d.curva, tDest[e])
        tDest[e] = avanzar(tDest[e], d.curva)
    end
    -- brillo de la esfera (su curva de alpha, con loop)
    opBrillo = hermite(BRILLO_CURVA, tBrillo) / BRILLO_MAX
    tBrillo = avanzar(tBrillo, BRILLO_CURVA)
    -- grano: nuevo corrimiento al azar (en fracciones del mosaico)
    granoU = (azar() * 2 - 1) * GRANO_TEMBLOR_X / GRANO_TILE
    granoV = (azar() * 2 - 1) * GRANO_TEMBLOR_Y / GRANO_TILE
    -- entrada / salida deslizando (frameIn / frameOut)
    if ocultarF then
        if tSalida < SALIDA_FRAMES then tSalida = tSalida + 1 end
    else
        if tSalida > 0 then tSalida = tSalida - 1 end
    end
end

-- lo que se ve, con el estado del ultimo paso (sin tablas nuevas por cuadro: menos basura para el GC)
local function aplicar()
    -- los cuartos (METER_ROT: base - (rate - lo) * 45)
    local rate = mLife / 400
    local v1, v2, v3, r1, r2, r3
    if rate > 4 then
        v1, v2, v3, r1, r2, r3 = true, true, true, 90, 0, 0 - (rate - 4) * 45
    elseif rate > 2 then
        v1, v2, v3, r1, r2, r3 = true, true, false, 90, 90 - (rate - 2) * 45, 0
    else
        v1, v2, v3, r1, r2, r3 = true, false, false, 180 - rate * 45, 0, 0
    end
    -- (el juego gira antihorario y arriba; Whisk3DUI horario y abajo)
    ponVisible(cuartos[1], v1); ponRot(cuartos[1], -r1)
    ponVisible(cuartos[2], v2); ponRot(cuartos[2], -r2)
    ponVisible(cuartos[3], v3); ponRot(cuartos[3], -r3)

    -- la rayita de la vida maxima: nivel = round(20*(max-1200)/1200), angulo = nivel*(-135)/20 - 45
    if marcaMax then
        local nivel = math.floor(20 * (vidaMaxF - 1200) / 1200 + 0.5)
        if nivel < 0 then nivel = 0 end
        if nivel > 20 then nivel = 20 end
        ponRot(marcaMax, -(nivel * -135 / 20 - 45))
    end

    -- el color del latido: el grupo guarda col0/col1 como u8; los cuartos (blancos, 255) heredan multiplicando y
    -- truncando
    local r = rPulso
    local function canal(k)
        local a, b = math.floor(col0[k]), math.floor(col1[k])
        local v = (1 - r) * a + r * b
        if v < 0 then v = 0 end
        if v > 255 then v = 255 end
        return math.floor(v) / 255
    end
    local cr, cg, cb = canal(1), canal(2), canal(3)
    for i = 1, 3 do ponTinte(cuartosImg[i], cr, cg, cb, 1) end

    if destello then
        local d = DESTELLOS[estadoVida]
        if d then
            local s1 = d.rgb[1] / 255 * GRIS_0A * d.alpha / 255
            local s2 = d.rgb[2] / 255 * GRIS_0A * d.alpha / 255
            local s3 = d.rgb[3] / 255 * GRIS_0A * d.alpha / 255
            local a = math.min(1, math.max(s1, s2, s3) / (1 - FONDO))
            if a > 1 / 255 then
                ponTinte(destello, (s1 + a * FONDO) / a, (s2 + a * FONDO) / a, (s3 + a * FONDO) / a, a)
            end
            ponVisible(destello, a > 1 / 255)
        else
            ponVisible(destello, false)
        end
    end

    -- balas cargadas / EMPTY
    local balas = math.floor(num("balas", 10))
    local reserva = math.floor(num("balas_reserva", 20))
    if balas < 0 then balas = 0 end
    local vacio = (balas == 0 and reserva <= 0)
    ponVisible(empty, vacio)
    -- el brillo: la version horneada sobre lo que hay debajo (icono o cartel EMPTY)
    if brillo then ponVisible(brillo, not vacio); ponOpacidad(brillo, opBrillo) end
    if brilloEmpty then ponVisible(brilloEmpty, vacio); ponOpacidad(brilloEmpty, opBrillo) end
    local n = balas
    for i = 1, 3 do
        local d = n % 10
        n = n // 10
        local o = digitos[i]
        if o then
            local ver = not vacio
            if i == 3 and d == 0 then ver = false end   -- solo la CENTENA se oculta en 0
            ponVisible(o, ver)
            if d ~= ultimoDigito[i] then
                local u0 = (d * (DIG_W + DIG_PAD) + DIG_PAD // 2) / TIRA_W
                setUVRect(o, u0, 0, u0 + DIG_W / TIRA_W, 1)
                ultimoDigito[i] = d
            end
        end
    end
end

function actualizar(dt)
    if fundido then
        local ya = compartido("fundido_ya")
        if ya then fundidoA = ya; setCompartido("fundido_ya", nil) end
        local objetivo = compartido("fundido") or 0
        local seg = compartido("fundido_seg") or 0.5
        local paso_ = (dt or DT) / math.max(seg, 0.001)
        if math.abs(objetivo - fundidoA) <= paso_ then fundidoA = objetivo
        elseif objetivo > fundidoA then fundidoA = fundidoA + paso_ else fundidoA = fundidoA - paso_ end
        ponVisible(fundido, fundidoA > 0.001)
        ponOpacidad(fundido, fundidoA)
    end
    if accion then
        local c = compartido("cartel_leon") or compartido("cartel_camino")
        if compartido("cinematica") == true or compartido("hud_visible") == false then c = nil end
        if c ~= cartelActual then
            cartelActual = c
            setVisible(accion, c ~= nil)
            if c and accionTexto then setTexto(accionTexto, c) end
        end
    end
    vidaF = num("leon_vida", 1200)
    if vidaF < 0 then vidaF = 0 end
    vidaMaxF = num("leon_vida_max", 1200)
    -- (ademas de hud_visible, una cinematica de evento.lua -compartido "cinematica"- tambien lo saca)
    ocultarF = compartido("hud_visible") == false or compartido("cinematica") == true
    acum = acum + (dt or DT)
    local n = 0
    while acum >= DT - 1e-6 and n < 4 do
        paso()
        acum = acum - DT
        n = n + 1
    end
    if n == 4 then acum = 0 end   -- un tiron largo (carga): no recuperar los frames perdidos
    -- lo que se ve, una vez (afuera del todo no hace falta: la raiz esta oculta)
    if tSalida < SALIDA_FRAMES then aplicar() end

    -- el grano: la imagen del juego (sin las barras) ocupa el ancho del EFB (512 px) -> filas de EFB visibles segun
    -- el aspecto de la pantalla; el mosaico repite (textura 256x256 = GL_REPEAT en Whisk3D)
    local w, h = pantalla()
    if grano and w > 0 and h > 0 then
        local filas = EFB_W * PIXEL_ASPECTO * h / w
        local su, sv = EFB_W / GRANO_TILE, filas / GRANO_TILE
        setUVRect(grano, granoU, granoV, granoU + su, granoV + sv)
    end

    -- la raiz: corrida a la derecha segun la salida (px virtuales x la escala: alto/360, las filas visibles
    -- entre las barras del letterbox del juego = nuestro marco; ver hud_r100.py)
    if raiz then
        local esc = math.min(w, h) / 360
        local s = tSalida / SALIDA_FRAMES
        local t = 3 * s * s - 2 * s * s * s          -- Hermite 0 -> 1 con tangentes 0
        ponPosPx(raiz, SALIDA_PX * t * esc, 0)
        ponVisible(raiz, tSalida < SALIDA_FRAMES)
    end
end
