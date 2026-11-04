-- ============================================================================
--  ganado.lua -- el aldeano de la casa de r100 (Resident Evil 4, GameCube) en Whisk3D. Va en "Ganado_juego".
--
--  La IA del juego (em10.cpp / em12, ver out/ganado_juego/ia.json), simplificada a lo que pasa en esta casa:
--    * aparece al terminar la cinematica (evento.lua pone compartido "ganado_activo") caminando hacia Leon con el
--      hacha (caminar_hacha); los primeros 5 s no corre (Dash_wait 150)
--    * camina girando hacia Leon: ang += clamp(0.3 * dif, +-0.157) por frame (em10_R1_Walk); corre si Leon esta a
--      mas de 3.5 m (correr, 7.5..10.5 s, despues 5..10 s sin correr)
--    * ATACA si Leon esta a menos de 1.7 m, dentro de +-45 grados y con el hacha lista: ataque_hacha; gira hacia Leon
--      los primeros 20 frames; el golpe vale en los frames 15..21 (dos capsulas de 0.25 m a lo largo del hacha contra
--      el cilindro de Leon), 380 de danio, UN golpe por ataque; despues espera 0.5 s si acerto
--    * RECIBE los tiros / tajos que calcula leon.lua (compartido "golpe_n" + zona, danio, desde donde): 500 de vida;
--      cada impacto elige una reaccion por zona (probabilidades del juego); cabeza y canilla lo dejan ATURDIDO (Leon
--      puede patearlo: compartido "ganado_aturdido"); la patada lo tira; tirado 2..4 s y se levanta
--    * MUERE con vida <= 0 (morir / desplomarse / caer_muerto): el cadaver queda (en r100 no se disuelve)
--  Los clips van EN EL LUGAR: la raiz (x, z, giro por frame, tabla RAIZ) la aplica este script a la armadura.
-- ============================================================================

-- el MISMO script va en cada aldeano (yo()): cada uno publica / lee sus claves compartidas con su PREFIJO
-- ("" para el de la casa, "<nombre>_" para los demas) y se anota en compartido "enemigos" (leon.lua los recorre).
-- activar: la clave compartida que lo despierta (el de la casa: "ganado_activo", la pone evento.lua)
propiedades = {activar = "ganado_activo", vida = 500}

--@@RAIZ@@

-- CONF (la pone el generador en los aldeanos de la EMBOSCADA; el de la casa no la tiene):
--   caminar / ataque: sus clips; golpe = {frame0, frame1} del golpe activo; se_f: frame del swing; danio; alcance
--   (distancia para empezar el ataque); guardia = true: quieto en su puesto hasta encontrar a Leon (3.5 m siempre,
--   15 m en +-60 grados, si le pegan o si otro avisa a menos de 10 m) y sale solo si Leon esta a menos de guard_r de
--   su puesto; renombrar: clips del de la casa que este no tiene
if not CONF then CONF = {} end
local CAMINAR = CONF.caminar or "caminar_hacha"
local ATAQUE = CONF.ataque or "ataque_hacha"
local GOLPE0, GOLPE1 = (CONF.golpe or {15, 21})[1], (CONF.golpe or {15, 21})[2]
local SE_F = CONF.se_f or 15
local RENOMBRAR = CONF.renombrar or {}

local VIDA_MAX = 500
local K = ""
local function C(n) return compartido(K .. n) end
local function SC(n, v) setCompartido(K .. n, v) end
local VEL_GIRO_ATAQUE = 5.89          -- rad/s los primeros 20 frames del ataque
local ATAQUE_DIST, ATAQUE_ANG = CONF.alcance or 1.7, 0.7854
local HACHA_DANIO = CONF.danio or 380
local HACHA = {{0.1413, -0.0212, 0.001}, {0.357, -0.0212, 0.1275}, {-0.5487, -0.0212, -0.4038}}   -- hueso_016 (m)
local HACHA_R = 0.25
local LEON_R, LEON_ALTO = 0.35, 1.8
local RADIO = 0.35

-- transicion (hokan) al entrar a cada clip, en frames
local HOKAN = {caminar_hacha = 7, caminar_arma = 7, correr = 5, ataque_hacha = 10, ataque = 10, ataque_horca_alto = 10,
               quieto = 8, retroceder_hacha = 7, retroceder = 7}

-- reacciones por zona (de frente); {clip, probabilidad acumulada}
local REACCION = {
    cabeza        = {{"golpe_cabeza", 0.333}, {"golpe_cabeza_b", 0.666}, {"golpe_cabeza_c", 1}},
    torso         = {{"golpe_cuerpo", 0.333}, {"golpe_cuerpo_b", 1}},
    brazo_der     = {{"golpe_cuerpo_b", 0.5}, {"golpe_brazo_fuerte", 1}},
    antebrazo_der = {{"golpe_mano", 0.5}, {"golpe_brazo_fuerte", 1}},
    brazo_izq     = {{"golpe_brazo_izq", 0.5}, {"golpe_brazo_fuerte_espejo", 1}},
    antebrazo_izq = {{"soltar_hacha", 1}},
    muslo_der     = {{"golpe_pierna_der", 0.333}, {"golpe_pierna_b_der", 0.666}, {"caer_pierna_der", 1}},
    muslo_izq     = {{"golpe_pierna_izq", 0.333}, {"golpe_pierna_b_izq", 0.666}, {"caer_pierna_izq", 1}},
    canilla_der   = {{"rodilla_der", 0.667}, {"caer_pierna_der", 1}},
    canilla_izq   = {{"rodilla_izq", 0.667}, {"caer_pierna_izq", 1}},
}
-- clips que lo dejan aturdido (patada disponible) y los que terminan en el PISO (boca arriba / abajo)
local ATURDE = {golpe_cabeza = true, golpe_cabeza_b = true, golpe_cabeza_c = true, rodilla_der = true, rodilla_izq = true}
local PISO = {caer_pierna_der = "arriba", caer_pierna_izq = "arriba", caer_atras = "arriba", caer_atras_b = "arriba",
              caer_adelante = "abajo", caer_adelante_b = "abajo", tropezar = "abajo", caer_aturdido = "abajo",
              caer_aturdido_atras = "arriba"}

-- sonidos en frames de la SEQ de cada clip (em10FootSe / SndCall 8, out/sonidos/combate/sonidos.json)
local PI, PD, CI, CD = "ganado_paso_caminar_izq", "ganado_paso_caminar_der", "ganado_paso_correr_izq", "ganado_paso_correr_der"
local RO, CU, GF = "ganado_cae_rodilla", "ganado_cae_cuerpo", "ganado_cae_golpe_fuerte"
local SEQ = {
    caminar_hacha = {[11] = PD, [34] = PI, [57] = PD, [80] = PI}, correr = {[9] = CD, [20] = CI, [31] = CD, [42] = CI},
    morir = {[35] = RO, [66] = CU}, desplomarse = {[19] = RO, [52] = CU}, caer_atras = {[15] = GF}, caer_atras_b = {[14] = GF},
    caer_adelante = {[10] = GF, [23] = CU}, caer_adelante_b = {[10] = GF, [41] = CU}, caer_muerto = {[22] = GF},
    caer_muerto_b = {[14] = GF, [39] = CU}, rodilla_der = {[9] = RO}, rodilla_izq = {[9] = RO}, caer_aturdido = {[14] = RO},
    caer_aturdido_atras = {[15] = CU}, caer_pierna_der = {[12] = RO}, caer_pierna_izq = {[12] = RO},
    tropezar = {[14] = RO, [24] = CU},
}

local g, leon, colSueloM, colParedM, colCamionM
local activo, estado = false, "espera"
local vida = VIDA_MAX
local px, py, pz, yaw = 0, 0, 0, 0     -- yaw en radianes (0 = mirando a +Z)
local clip, fAnt = nil, 0
local atkEspera, dashEspera, corrT = 0, 5, 0
local golpeHecho = false
local golpeVisto = 0
local pisoT, boca = 0, "arriba"
local reinicioVisto = 0
local p0 = nil
local respT = 4
local encontrado = false
local avisoVisto = 0

if not VOL then VOL = {} end
local function snd(n, vol) sonido("sonidos/" .. n .. ".wav", (VOL[n] or 1.0) * (vol or 1.0)) end
local function sndAzar(base, n, vol) snd(base .. "_" .. azar(1, n), vol) end

local function angDif(a)
    while a > math.pi do a = a - 2 * math.pi end
    while a < -math.pi do a = a + 2 * math.pi end
    return a
end

local function poner(c, loop)
    c = RENOMBRAR[c] or c
    if c == clip then return end
    local h = HOKAN[c] or 6
    if clip and h > 0 then animTransicion(g, h) end
    clip = c
    animClip(g, c, loop, true)
    animVelocidad(g, 1)
    fAnt = 0
end

-- la raiz del clip entre dos frames (con la vuelta del loop): dx, dz (espacio de la armadura) y giro
local function pistaEn(t, f)
    local n = #t // 3
    if f <= 0 then return t[1], t[2], t[3] end
    if f >= n - 1 then return t[3 * n - 2], t[3 * n - 1], t[3 * n] end
    local i = math.floor(f); local k = f - i
    local a = 3 * i
    return t[a + 1] + (t[a + 4] - t[a + 1]) * k, t[a + 2] + (t[a + 5] - t[a + 2]) * k, t[a + 3] + (t[a + 6] - t[a + 3]) * k
end
local function avanceRaiz(c, f0, f1)
    local t = RAIZ[c]
    if not t then return 0, 0, 0 end
    local x0, z0, r0 = pistaEn(t, f0)
    local x1, z1, r1 = pistaEn(t, f1)
    if f1 < f0 then   -- dio la vuelta: hasta el final + desde el principio
        local n = #t // 3
        return (t[3 * n - 2] - x0) + x1, (t[3 * n - 1] - z0) + z1, (t[3 * n] - r0) + r1
    end
    return x1 - x0, z1 - z0, r1 - r0
end

local function mover(dx, dz)
    local c, s = math.cos(yaw), math.sin(yaw)
    local nx, nz = px + dx * c + dz * s, pz - dx * s + dz * c
    if colParedM then nx, nz = colPared(colParedM, nx, py, nz, RADIO) end
    if colCamionM and not compartido("camino_libre") then nx, nz = colPared(colCamionM, nx, py, nz, RADIO) end
    -- los cuerpos no se atraviesan: no se mete a menos de 0.7 m de Leon (muerto, tirado o cayendo si)
    if estado ~= "muerto" and estado ~= "caer" and estado ~= "piso" then
        local lx, _, lz = posicion(leon)
        local ex, ez = nx - lx, nz - lz
        local d = math.sqrt(ex * ex + ez * ez)
        if d < 0.7 and d > 1e-4 then nx, nz = lx + ex / d * 0.7, lz + ez / d * 0.7 end
    end
    local suelo = colSueloM and colSuelo(colSueloM, nx, py + 0.3, nz, 0.5)
    if colSueloM and not suelo then return end
    px, pz = nx, nz
    if suelo then py = suelo end
end

local function aLeon()
    local lx, ly, lz = posicion(leon)
    local dx, dz = lx - px, lz - pz
    return math.sqrt(dx * dx + dz * dz), angDif(math.atan(dx, dz) - yaw), ly
end

local function girarHacia(dif, max)
    local d = math.max(-max, math.min(max, dif))
    yaw = yaw + d
end

local function elegir(tabla)
    local r = azar()
    for _, e in ipairs(tabla) do if r <= e[2] then return e[1] end end
    return tabla[#tabla][1]
end

-- ---- el HACHA contra Leon: distancia entre el segmento del hacha y el eje de Leon (cilindro) ----
local function distSegSeg(ax, ay, az, bx, by, bz, cx, cy, cz, dx, dy, dz)
    -- muestreo simple (8 puntos del hacha contra el segmento vertical de Leon): alcanza para una capsula
    local best = 1e9
    for i = 0, 8 do
        local t = i / 8
        local x, y, z = ax + (bx - ax) * t, ay + (by - ay) * t, az + (bz - az) * t
        local yy = math.max(cy, math.min(dy, y))
        local ex, ey, ez = x - cx, y - yy, z - cz
        local d = math.sqrt(ex * ex + ey * ey + ez * ez)
        if d < best then best = d end
    end
    return best
end
local function hachaPega()
    if CONF.alcance then
        -- el arma de los de la emboscada: Leon al alcance, adelante y a la altura (sin los puntos del arma)
        local d, dif, ly = aLeon()
        if d < ATAQUE_DIST + 0.45 and math.abs(dif) < 1.0 and math.abs(ly - py) < 1.5 then
            local lx, _, lz = posicion(leon)
            return true, {lx, ly + 1.2, lz}
        end
        return false
    end
    local lx, ly, lz = posicion(leon)
    local b = {huesoPunto(g, "hueso_016", HACHA[3][1], HACHA[3][2], HACHA[3][3])}
    for k = 1, 2 do
        local p = {huesoPunto(g, "hueso_016", HACHA[k][1], HACHA[k][2], HACHA[k][3])}
        if p[1] and b[1] then
            local d = distSegSeg(b[1], b[2], b[3], p[1], p[2], p[3], lx, ly, lz, lx, ly + LEON_ALTO, lz)
            if d < HACHA_R + LEON_R then return true, p end
        end
    end
    return false
end

local function morir(zona)
    estado = "muerto"; activo = false
    SC("ganado_aturdido", false)
    SC("ganado_muerto", true)
    local c = "morir"
    if zona == "cabeza" then c = (azar() < 0.667) and "desplomarse" or "caer_muerto" end
    if zona == "patada" then c = (azar() < 0.5) and "caer_muerto" or "caer_muerto_b" end
    poner(c, false)
    sndAzar("ganado_muerte", 2, 1.0)
end

local function reaccionar(zona, atras)
    SC("ganado_aturdido", false)
    if zona == "patada" then
        estado = "caer"
        local c = atras and ((azar() < 0.5) and "caer_adelante" or "caer_adelante_b")
                         or ((azar() < 0.5) and "caer_atras" or "caer_atras_b")
        poner(c, false)
        boca = PISO[c] or "arriba"
        sndAzar("ganado_dolor", 2, 1.0)
        return
    end
    if estado == "piso" or estado == "levantarse" or estado == "caer" then
        -- en el piso: golpe tirado y se levanta enseguida
        if estado == "piso" then
            estado = "caer"; poner(boca == "arriba" and "caido_golpe_boca_arriba" or "caido_golpe_boca_abajo", false)
        end
        return
    end
    local c
    if estado == "aturdido" then c = atras and "caer_aturdido_atras" or "caer_aturdido"
    elseif atras and zona ~= "canilla_der" and zona ~= "canilla_izq" then c = "golpe_espalda"
    else c = elegir(REACCION[zona] or REACCION.torso) end
    if PISO[c] then estado = "caer"; boca = PISO[c]
    elseif ATURDE[c] then estado = "aturdido"; SC("ganado_aturdido", true)
    else estado = "golpe" end
    poner(c, false)
    -- la voz de dolor segun la reaccion (Se_tbl del ganado: cabeza / pierna / rodilla / comun)
    if ATURDE[c] and (c == "rodilla_der" or c == "rodilla_izq") then snd("ganado_aturdido_rodilla", 1.0)
    elseif ATURDE[c] then snd("ganado_dolor_cabeza", 1.0)
    elseif string.find(c, "pierna") then snd("ganado_dolor_pierna", 1.0)
    else sndAzar("ganado_dolor", 2, 1.0) end
end

local function recibir()
    local n = C("golpe_n") or 0
    if n == golpeVisto then return end
    golpeVisto = n
    if estado == "muerto" or estado == "espera" then return end
    local danio = C("golpe_danio") or 0
    local zona = C("golpe_zona") or "torso"
    -- de espaldas si el tirador esta detras (a mas de 90 grados del frente)
    local ox, oz = C("golpe_ox") or px, C("golpe_oz") or pz
    local atras = math.abs(angDif(math.atan(ox - px, oz - pz) - yaw)) > math.pi / 2
    vida = vida - danio
    encontrado = true
    if vida <= 0 then morir(zona) else reaccionar(zona, atras) end
    info(string.format("ganado: %s %d -> vida %d, %s (%s)", zona, danio, vida, estado, clip or "-"))
end

local function empezar()
    activo = true; estado = "caminar"; vida = VIDA_MAX
    px, py, pz = p0[1], p0[2], p0[3]; yaw = p0[4]
    setVisible(g, true)
    encontrado = false
    avisoVisto = compartido("emboscada_aviso_n") or 0
    clip = nil
    if CONF.guardia then estado = "guardia"; poner("quieto", true) else poner(CAMINAR, true) end
    atkEspera, dashEspera, corrT = 0, 5, 0
    SC("ganado_muerto", false); SC("ganado_aturdido", false)
    respT = 4 + azar() * 4
end

function inicio()
    g = yo() or buscar("Ganado_juego")
    local nom = nombre(g)
    K = (nom == "Ganado_juego") and "" or (nom .. "_")
    VIDA_MAX = propiedad("vida") or VIDA_MAX
    -- anotarse en la lista de enemigos (nombres separados por ';')
    local lista = compartido("enemigos") or ""
    if not string.find(";" .. lista .. ";", ";" .. nom .. ";", 1, true) then
        setCompartido("enemigos", (lista == "") and nom or (lista .. ";" .. nom))
    end
    leon = buscar("Leon")
    colSueloM, colParedM = buscar("r100_col_suelo"), buscar("r100_col_pared")
    colCamionM = buscar("r100_col_camion")
    local x, y, z = posicion(g)
    local _, ry = rotacion(g)
    p0 = {x, y, z, math.rad(ry or 0)}
    setVisible(g, false)
    estado, activo = "espera", false
    golpeVisto = C("golpe_n") or 0
    reinicioVisto = compartido("reinicio_n") or 0
end

function actualizar(dt)
    if not g or not leon then return end
    -- el REINICIO (Leon murio y la partida vuelve a empezar despues de la cinematica)
    local rn = compartido("reinicio_n") or 0
    if rn ~= reinicioVisto then
        reinicioVisto = rn
        -- en la emboscada el de la casa sigue muerto; los que esperan su clave siguen esperando
        if compartido(propiedad("activar") or "ganado_activo") and not (K == "" and compartido("emboscada")) then
            empezar()
        end
    end
    if estado == "espera" then
        if compartido(propiedad("activar") or "ganado_activo") then empezar() end
        return
    end
    recibir()
    local f = animFrame(g)
    local d, dif, ly = aLeon()
    local leonVivo = (compartido("leon_vida") or 1) > 0

    if estado == "caminar" or estado == "correr" then
        respT = respT - dt
        if respT <= 0 then
            respT = 4 + azar() * 4
            if azar() < 0.2 then sndAzar("ganado_voz_acercarse", 2, 1.0) else snd("ganado_respiracion", 0.8) end
        end
        girarHacia(dif * 0.3 * dt * 30, 0.157 * dt * 30)
        atkEspera = math.max(0, atkEspera - dt); dashEspera = math.max(0, dashEspera - dt)
        if estado == "caminar" and dashEspera <= 0 and d > 3.5 and math.abs(dif) < 0.6 then
            estado = "correr"; corrT = 7.5 + azar() * 3; poner("correr", true)
        elseif estado == "correr" then
            corrT = corrT - dt
            if corrT <= 0 or d < 2.0 then estado = "caminar"; dashEspera = 5 + azar() * 5; poner(CAMINAR, true) end
        end
        if leonVivo and atkEspera <= 0 and d < ATAQUE_DIST and math.abs(dif) < ATAQUE_ANG and math.abs(ly - py) < 1.5 then
            estado = "atacar"; golpeHecho = false; poner(ATAQUE, false)
            sndAzar("ganado_voz_ataque", 2, 1.0)
        elseif not leonVivo and estado ~= "caminar" then
            estado = "caminar"; poner(CAMINAR, true)
        end
        if not leonVivo and d < 1.2 then estado = "quieto"; poner("quieto", true) end

    elseif estado == "atacar" then
        if f < 20 then girarHacia(dif, VEL_GIRO_ATAQUE * dt) end
        if fAnt < SE_F and f >= SE_F then snd("hacha_swing", 1.0) end
        if not golpeHecho and f >= GOLPE0 and f <= GOLPE1 then
            local pega, p = hachaPega()
            if pega then
                golpeHecho = true
                local lx, ly2, lz = posicion(leon)
                setCompartido("leon_danio", HACHA_DANIO)
                setCompartido("leon_danio_alto", (p[2] - ly2) > 1.3)
                setCompartido("leon_danio_ox", px); setCompartido("leon_danio_oz", pz)
                setCompartido("leon_danio_px", p[1]); setCompartido("leon_danio_py", p[2]); setCompartido("leon_danio_pz", p[3])
                setCompartido("leon_danio_n", (compartido("leon_danio_n") or 0) + 1)
            end
        end
        if animTermino(g) then
            atkEspera = golpeHecho and 0.5 or 0.0
            estado = "caminar"; poner(CAMINAR, true)
        end

    elseif estado == "golpe" or estado == "aturdido" then
        if animTermino(g) then
            SC("ganado_aturdido", false)
            estado = "caminar"; poner(CAMINAR, true)
        end

    elseif estado == "caer" then
        if animTermino(g) then estado = "piso"; pisoT = 2 + azar() * 2 end

    elseif estado == "piso" then
        pisoT = pisoT - dt
        if pisoT <= 0 then
            estado = "levantarse"
            poner(boca == "arriba" and "levantarse_boca_arriba" or "levantarse_boca_abajo", false)
            snd("ganado_levantarse", 1.0)
        end

    elseif estado == "levantarse" then
        if animTermino(g) then estado = "caminar"; poner(CAMINAR, true) end

    elseif estado == "guardia" then
        -- quieto en su puesto mirando a Leon; lo busca (em10FindCk) y avisa a los que estan cerca
        girarHacia(dif, (encontrado and 0.0245 or 0.1) * dt * 30)
        -- DESPERTAR (Leon salio de la casa: los de la puerta corren hacia el sin importar el radio de guardia)
        local desp = C("despertar")
        if desp then encontrado = true end
        if not encontrado then
            local an = compartido("emboscada_aviso_n") or 0
            if an ~= avisoVisto then
                avisoVisto = an
                local ax, az = compartido("emboscada_aviso_x") or 1e9, compartido("emboscada_aviso_z") or 1e9
                if math.sqrt((ax - px) ^ 2 + (az - pz) ^ 2) < 10 then encontrado = true end
            end
            if leonVivo and (d < 3.5 or (d < 15 and math.abs(dif) < 1.0472)) then
                encontrado = true
                setCompartido("emboscada_aviso_x", px); setCompartido("emboscada_aviso_z", pz)
                setCompartido("emboscada_aviso_n", an + 1); avisoVisto = an + 1
                sndAzar("ganado_voz_acercarse", 2, 1.0)
            end
        end
        local lx, _, lz = posicion(leon)
        local dl = math.sqrt((lx - p0[1]) ^ 2 + (lz - p0[3]) ^ 2)
        if leonVivo and atkEspera <= 0 and d < ATAQUE_DIST and math.abs(dif) < ATAQUE_ANG and math.abs(ly - py) < 1.5 then
            estado = "atacar"; golpeHecho = false; poner(ATAQUE, false)
            sndAzar("ganado_voz_ataque", 2, 1.0)
        elseif encontrado and leonVivo and (desp or dl < (CONF.guard_r or 30)) then
            estado = "caminar"; dashEspera = desp and 0 or 2; poner(CAMINAR, true)
        end
        atkEspera = math.max(0, atkEspera - dt)

    elseif estado == "quieto" then
        girarHacia(dif * 0.1, 0.05)
        if leonVivo then estado = "caminar"; poner(CAMINAR, true) end
    end

    -- el frame se RELEE: si este tick cambio de clip, poner() dejo fAnt = 0 y el frame leido arriba era del clip
    -- ANTERIOR -> la raiz del clip nuevo se aplicaba de golpe hasta ese frame (el ganado se teletransportaba ~1 m
    -- al empezar el hachazo)
    f = animFrame(g)
    -- los sonidos de la SEQ que cruzo este frame (con la vuelta del loop)
    local tabla = SEQ[clip]
    if tabla then
        local a, b = math.floor(fAnt), math.floor(f)
        for k, n in pairs(tabla) do
            local cruzo
            if b >= a then cruzo = (k > a and k <= b) else cruzo = (k > a or k <= b) end
            if cruzo then snd(n, 1.0) end
        end
    end
    -- la raiz del clip (en el lugar -> la armadura)
    local ax, az, ar = avanceRaiz(clip, fAnt, f)
    if ax ~= 0 or az ~= 0 then mover(ax, az) end
    yaw = yaw + ar
    fAnt = f
    if colSueloM and estado ~= "muerto" then
        local s = colSuelo(colSueloM, px, py + 0.3, pz, 0.5)
        if s then py = s end
    end
    setPosicion(g, px, py, pz)
    setRotacion(g, 0, math.deg(yaw), 0)
    -- para leon.lua: donde esta (la patada y la mira)
    SC("ganado_x", px); SC("ganado_z", pz); SC("ganado_yaw", yaw)
    -- para la musica de la emboscada: encontro a Leon y esta a menos de 30 m
    SC("ganado_alerta", encontrado and estado ~= "muerto" and d < 30)
    -- ARRODILLADO (tiro / tajo en la canilla, ya en el piso): Leon le pega la patada giratoria en vez de la de frente
    SC("ganado_rodillas", estado == "aturdido" and (clip == "rodilla_der" or clip == "rodilla_izq") and f >= 8)
end
