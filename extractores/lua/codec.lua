-- codec.lua: la LLAMADA DE RADIO a Hunnigan (pantalla del codec, OpeSetOpenTerm(0) de r100), en el Empty "Codec".
-- Las tablas (UNIDADES, SUBTITULOS, LUCES_MUNDO, ...) las inyecta codec_r100.py en la marca de abajo.
--
-- Arranca cuando compartido("codec_llamar") = true (lo pone la intro al terminar). Relojes de out/codec/codec.json:
--   g = frame global (0 = Leon empieza a sacar la radio) ; c = frame del codec (0 = primer frame de la pantalla)
--   g = c + G_CODEC (80, sin tiempo de carga del disco)
--
--   g 0     Leon: clip "radio" (71 f), tono de la radio (str1_003)
--   g 22    aparece la radio en la mano izquierda (Leon_radio, Child Of hueso_016)
--   g 71    fundido A NEGRO en 3 frames (FadeSetW(0, 3))
--   g 75    negro: se prende la pantalla del codec (Recorte Codec_pantalla + UI), las luces del codec
--   c 0     fundido DESDE negro en 5 frames, SE de abrir; los dos personajes en "espera" (loop)
--   c 31    corta el tono ; c 32 arranca la voz (str1_140) y el primer subtitulo
--   c 33    clip "llamada" (mezcla de 10 f desde "espera") + caras (animacion de escena "codec"): frame k en c = 33 + k
--   c 842   para la voz, borra el mensaje, SE de cerrar ; c 843 fundido a negro 3 f ; c 846 se apaga el codec
--   c 852   vuelve el juego: fundido desde negro 10 f, compartido cinematica / hud_visible / codec_fin
--
-- Mientras dura: compartido("cinematica") = true (leon.lua quieto), "hud_visible" = false.

--@@DATOS@@

local SON = "sonidos/codec_"
local ARMS = {"LeonCodec", "Hunnigan"}

local estado = "espera"     -- espera | radio | codec | fin
local t = 0                 -- segundos desde codec_llamar
local hecho = {}            -- los eventos puntuales ya disparados
local leon, pistola, radio, recorte, raizUI, subtitulo, grano
local arms = {}
local luces = {}            -- las luces del codec
local apagadas = {}         -- las luces del mundo que se apagaron (se vuelven a prender al salir)
local ui = {}               -- por unidad: {o, k, i (key actual), ruido, cuadro}
local subAct = 0
local tono, voz
local tVoz = 0              -- t cuando arranco la voz (desde ahi el reloj es la voz)

-- RELOJ de la cinematica: avanza con dt, pero si el AUDIO va mas adelante salta hasta el (el mixer va en tiempo real
-- aunque el cuadro tarde; en el N95 la logica topa el dt a 0.1 s y a menos de 10 fps la animacion se iba quedando
-- atras de la voz): la animacion saltea los frames que haga falta para quedar donde va el sonido (sonidoPosicion, el
-- frameskip del motor). t0 = donde estaba t cuando arranco el sonido. Sin sonido (todavia no, ya termino) solo dt.
-- (Con dt y no SOLO el audio: el harness simula mas rapido que el tiempo real y ahi manda dt, como siempre.)
local function relojCine(h, t0, t, dt)
    local nt = t + dt
    local s = h and sonidoPosicion and sonidoPosicion(h)
    if s and t0 + s > nt then nt = t0 + s end
    return nt
end

-- FUNDIDO del HUD (hud.lua): objetivo 0 (nada) .. 1 (negro) en 'seg'; 'ya' = valor inmediato
local function fundido(objetivo, seg, ya)
    if ya then setCompartido("fundido_ya", ya) end
    setCompartido("fundido_seg", seg)
    setCompartido("fundido", objetivo)
end

local function una(clave)
    if hecho[clave] then return false end
    hecho[clave] = true
    return true
end

-- ---------------------------------------------------------------------------------------------------------------
--  la capa 2D: cada unidad sigue su pista (solo se aplica cuando cambia la key o el cuadro de la estatica)
-- ---------------------------------------------------------------------------------------------------------------
local function aplicarKey(u, k)
    if k[2] == 0 then setVisible(u.o, false) return end
    setVisible(u.o, true)
    setTinte(u.o, k[3], k[4], k[5], k[6])
    setPosicion(u.o, k[7], k[8], 0)
    local w, h = pantalla()
    if w > 0 and h > 0 then setTamPx(u.o, k[9] * w, k[10] * h) end
end

local function uiFrame(c)
    for _, u in ipairs(ui) do
        local i = u.i
        while i < #u.k and u.k[i + 1][1] <= c do i = i + 1 end
        if i ~= u.i then
            u.i = i
            if i > 0 then aplicarKey(u, u.k[i]) else setVisible(u.o, false) end
        end
        if u.ruido and i > 0 then
            local cuadro = c % 2
            if cuadro ~= u.cuadro then
                u.cuadro = cuadro
                setTextura(u.o, "texturas/codec/ruido_" .. cuadro .. ".png")
            end
        end
    end
end

local function subtitulos(c)
    local n = 0
    if c < C_CIERRE then
        for i, s in ipairs(SUBTITULOS) do
            if c >= s.desde and c < s.hasta then n = i end
        end
    end
    if n == subAct or not subtitulo then return end
    subAct = n
    if n == 0 then setVisible(subtitulo, false) return end
    local s = SUBTITULOS[n]
    setTexto(subtitulo, s.texto)
    setTinte(subtitulo, s.color[1], s.color[2], s.color[3], s.color[4])
    setPosicion(subtitulo, s.x, (320 - 60) / 360, 0)
    setVisible(subtitulo, true)
end

-- ---------------------------------------------------------------------------------------------------------------
--  entrar / salir de la pantalla del codec
-- ---------------------------------------------------------------------------------------------------------------
local function prenderCodec()
    if recorte then setVisible(recorte, true) end
    if raizUI then setVisible(raizUI, true) end
    if grano then setVisible(grano, false) end        -- el grano del cuarto no se dibuja en el sub screen
    -- las luces: solo las del codec (las del mundo iluminarian a los personajes con el sol de r100)
    apagadas = {}
    for _, n in ipairs(LUCES_MUNDO) do
        local o = buscar(n)
        if o and visible(o) then setVisible(o, false); apagadas[#apagadas + 1] = o end
    end
    -- lo que la pantalla tapa entero (el mapa, los personajes, los efectos): no se dibuja mientras dura la llamada
    for _, n in ipairs(OCULTAR_MUNDO) do
        local o = buscar(n)
        if o and visible(o) then setVisible(o, false); apagadas[#apagadas + 1] = o end
    end
    for _, o in ipairs(luces) do setVisible(o, true) end
    for _, a in ipairs(arms) do
        animVelocidad(a, 1)
        animClip(a, "espera", true, true)
    end
    for _, u in ipairs(ui) do u.i = 0; u.cuadro = -1; setVisible(u.o, false) end
    subAct = -1
    subtitulos(-1)
end

local function apagarCodec()
    if recorte then setVisible(recorte, false) end
    if raizUI then setVisible(raizUI, false) end
    if grano then setVisible(grano, true) end
    for _, o in ipairs(luces) do setVisible(o, false) end
    for _, o in ipairs(apagadas) do setVisible(o, true) end
    apagadas = {}
    pararEscena()
end

local function empezar()
    estado, t, hecho = "radio", 0, {}
    setCompartido("codec_llamar", false)
    setCompartido("codec_fin", false)
    setCompartido("cinematica", true)
    setCompartido("hud_visible", false)
    if leon then
        -- leon.lua mezcla por CAPAS (1 = la base, 2 = la punteria): la radio va en la capa base, sin punteria;
        -- al volver el control (leon_resync) leon.lua repone "quieto" en la capa 1
        animTransicion(leon, 5)
        animCapa(leon, 1, "radio", 1, "mezclar", false, true)
        animCapaPeso(leon, 2, 0)
    end
    if pistola then setVisible(pistola, false) end     -- enfundada (leon.lua la vuelve a mostrar al resync)
    tono = sonido(SON .. "tono.wav", 1.0)
    info("codec: llamada de radio")
end

local function terminar()
    estado = "fin"
    fundido(0, 10 / 30, 1)                -- FadeSetW(0x80000001, 10): desde negro
    if radio then setVisible(radio, false) end
    setCompartido("leon_resync", true)
    setCompartido("cinematica", false)
    setCompartido("hud_visible", true)
    setCompartido("codec_fin", true)
    info("codec: fin")
end

function inicio()
    leon = buscar("Leon")
    radio = buscar("Leon_radio")
    pistola = buscar("Leon_pistola")
    recorte = buscar("Codec_pantalla")
    raizUI = buscar("codec_ui_raiz")
    subtitulo = buscar("codec_ui_subtitulo")
    grano = buscar("hud_grano")
    arms = {}
    for _, n in ipairs(ARMS) do local a = buscar(n); if a then arms[#arms + 1] = a end end
    luces = {}
    for _, n in ipairs({"Codec_luz_0", "Codec_luz_1", "Codec_luz_2"}) do
        local o = buscar(n); if o then luces[#luces + 1] = o end
    end
    ui = {}
    for _, d in ipairs(UNIDADES) do
        local o = buscar(d.nombre)
        if o then ui[#ui + 1] = {o = o, k = d.k, i = 0, ruido = d.ruido, cuadro = -1} end
    end
    if not raizUI or #ui == 0 then info("codec: no encuentro la UI del codec (codec_ui_*)") end
    estado, t, hecho = "espera", 0, {}
end

function actualizar(dt)
    if estado == "espera" then
        if compartido("codec_llamar") then empezar() else return end
    end
    if estado == "fin" then return end
    t = relojCine(voz, tVoz, t, dt)
    local g = t * 30
    local c = g - G_CODEC
    -- ---- Leon saca la radio ----
    if g >= 22 and una("radio") and radio then setVisible(radio, true) end
    if g >= 71 and una("negro") then fundido(1, 3 / 30) end
    if g >= 75 and una("prender") then prenderCodec(); estado = "codec" end
    if estado ~= "codec" then return end
    -- ---- la pantalla del codec ----
    if c >= 0 and una("abrir") then
        fundido(0, 5 / 30, 1)                 -- FadeSetW(0x80000000, 5)
        sonido(SON .. "abrir.wav", 1.0)
    end
    if c >= 31 and una("tono") and tono then pararSonido(tono, 0.03) end
    if c >= 32 and una("voz") then voz = sonido(SON .. "voz.wav", 1.0); tVoz = t end
    if c >= 33 then
        if una("llamada") then
            for _, a in ipairs(arms) do
                animTransicion(a, 10)            -- MotionSetCore(.., hokan 10, ..)
                animClip(a, "llamada", false, true)
                animVelocidad(a, 0)              -- el frame lo pone este reloj (voz, caras y cuerpos juntos)
            end
            animEscena("codec", false)
        end
        local k = math.min(c - 33, C_CIERRE - 33)
        for _, a in ipairs(arms) do animFrame(a, k) end
        animEscenaFrame(k + 1)
    end
    local cf = math.floor(c)
    if cf >= 0 then uiFrame(math.min(cf, C_CIERRE)) end
    subtitulos(cf)
    if c >= C_CIERRE and una("cerrar") then
        if voz then pararSonido(voz, 0.03) end
        sonido(SON .. "cerrar.wav", 1.0)
    end
    if c >= C_CIERRE + 1 and una("negro2") then fundido(1, 3 / 30) end     -- SsExitInit: FadeSetW(0, 3)
    if c >= C_CIERRE + 4 and una("apagar") then apagarCodec() end
    if c >= C_CIERRE + 10 then terminar() end
end
