--------------------------------------------------------------------------------
-- BotBridge: рисует полосу цветных ячеек с состоянием персонажа.
--------------------------------------------------------------------------------
local cells = {}
local seq = 0
local spellIds = {}
local ticks, ticksAtLastSecond = 0, -1
local castTicksLeft = 0
local castSecondsLeft = 0
local reportedErrors = {}
local seenKinds = {}

local MAX_SPELLS = 16
local catalogDirty = false

local state = { casting = false, slots = {}, catalog_gen = 0 }
Global( "BOT_STATE", state )

local function opt( name )
	return rawget( _G, name )
end

local function log( ... )
	pcall( common.LogInfo, common.GetAddonName(), ... )
end

local function wstr( w )
	if w == nil then return "" end
	if type( w ) == "string" then return w end
	local ok, s = pcall( userMods.FromWString, w )
	return ok and s or ""
end

local function setColor( w, r, g, b )
	w:SetBackgroundColor( { r = r / 255, g = g / 255, b = b / 255, a = 1.0 } )
end

local function layout()
	local p = common.GetPosConverterParams()
	local scale = 1
	if p and p.realSizeX and p.realSizeX > 0 then
		scale = p.fullVirtualSizeX / p.realSizeX
	end
	local size = BOT_CELL_PX * scale
	for i = 1, #cells do
		cells[ i ]:SetPlacementPlain( {
			alignX = opt( "WIDGET_ALIGN_LOW" ), alignY = opt( "WIDGET_ALIGN_LOW" ),
			posX = ( i - 1 ) * size, posY = 0, sizeX = size, sizeY = size,
		} )
	end
end

local function reportApiErrors()
	for name, err in pairs( BOT_API_ERRORS ) do
		if not reportedErrors[ name ] then
			reportedErrors[ name ] = true
			log( "BotBridge: ошибка API ", name, ": ", err )
		end
	end
end

-- SpellId из книги заклинаний: только такие id принимает spellLib.
-- Панель отдаёт числа, на них GetCooldown/CanRunAvatar падают.
local function bookIds()
	local byName = {}
	local ok, book = pcall( avatar.GetSpellBook )
	if not ok or type( book ) ~= "table" then return byName end
	for _, id in pairs( book ) do
		local okD, d = pcall( spellLib.GetDescription, id )
		if okD and type( d ) == "table" then
			local n = wstr( d.name )
			if n ~= "" and byName[ n ] == nil then byName[ n ] = id end
		end
	end
	return byName
end

-- Нумерация: N-й слот панели с kind=="spell". Ненайденные умения сохраняют
-- своё место (false), чтобы номера остальных не съезжали.
local function spellIdsFromSlots( slots )
	local byName = bookIds()
	local ids, dbg = {}, {}
	for i = 1, #slots do
		local s = slots[ i ]
		if s.kind == "spell" and #ids < MAX_SPELLS then
			local id = byName[ s.name or "" ]
			if id == nil and s.spellId ~= nil and type( s.spellId ) ~= "number" then
				id = s.spellId
			end
			ids[ #ids + 1 ] = id or false
			dbg[ #dbg + 1 ] = #ids .. ":" .. tostring( s.name ) .. ":" .. ( id and "ok" or "NET" )
		end
	end
	log( "BotBridge: MAP ", table.concat( dbg, " " ) )
	return ids
end

-- Раз в секунду: что игра говорит про каждое умение ротации.
local function logReady()
	local parts = {}
	for i = 1, #spellIds do
		local id = spellIds[ i ]
		if not id then
			parts[ #parts + 1 ] = i .. "=NOID"
		else
			local okCd, cd = pcall( spellLib.GetCooldown, id )
			local okCan, can = pcall( spellLib.CanRunAvatar, id )
			parts[ #parts + 1 ] = i .. "=" ..
				( okCd and type( cd ) == "table" and tostring( cd.remainingMs ) or "CDERR" ) ..
				"/" .. ( okCan and tostring( can ) or "CANERR" )
		end
	end
	log( "BotBridge: READY ", table.concat( parts, " " ) )
end

local function requestCatalog()
	catalogDirty = true
end

local function dumpCatalog()
	if not catalogDirty or not avatar.IsExist() then
		return
	end
	state.slots = BotSlotCache()
	spellIds = spellIdsFromSlots( state.slots )
	state.catalog_gen = ( state.catalog_gen + 1 ) % 256
	BotCatalogDump( state.catalog_gen, function( text ) log( text ) end, state.slots )
	local okDiag, diag = pcall( BotCatalogDiag )
	log( okDiag and diag or ( "BotBridge: диаг: ошибка " .. tostring( diag ) ) )
	catalogDirty = false
end

local function paint()
	seq = ( seq + 1 ) % 256
	local st = BotCollect( seq, state.casting, spellIds )
	local body = BotPack( st )
	if st.target_kind and st.target_kind ~= 0 and not seenKinds[ st.target_kind ] then
		seenKinds[ st.target_kind ] = true
		log( "BotBridge: вид цели ", tostring( st.target_kind ), " = ", tostring( st.target_name ) )
	end
	setColor( cells[ 1 ], BOT_SYNC[ 1 ], BOT_SYNC[ 2 ], BOT_SYNC[ 3 ] )
	setColor( cells[ 2 ], BOT_CALIB[ 1 ], BOT_CALIB[ 2 ], BOT_CALIB[ 3 ] )
	for k = 1, BOT_CELL_COUNT - 2 do
		local j = ( k - 1 ) * 3
		setColor( cells[ k + 2 ], body[ j + 1 ], body[ j + 2 ], body[ j + 3 ] )
	end
	reportApiErrors()
end

local dbgLastGcd = nil
local function dbgSpells( why )
	local parts = {}
	for i = 1, #state.slots do
		local s = state.slots[ i ]
		local id = s.kind == "spell" and s.spellId
		local cd = id and spellLib and spellLib.GetCooldown and spellLib.GetCooldown( id )
		if cd then
			parts[ #parts + 1 ] = "slot" .. tostring( i ) .. "=" .. tostring( cd.remainingMs ) .. "/"
				.. tostring( cd.durationMs ) .. ( cd.ignoreGlobalCooldown and "i" or "" )
		end
	end
	local g = avatar.GetGlobalCooldown and avatar.GetGlobalCooldown()
	log( "GCDDBG ", why, " calc=", tostring( BotGcdRemaining() ), " cd ", table.concat( parts, " " ) )
end

local function dbgTick()
	if not opt( "BOT_DEBUG_GCD" ) then return end
	local now = BotGcdRemaining() > 0
	if now ~= dbgLastGcd then
		dbgLastGcd = now
		pcall( dbgSpells, now and "gcd-on" or "gcd-off" )
	end
end

local function onGlobalCooldown( params )
	BotOnGlobalCooldown( params )
end

local function tick()
	ticks = ticks + 1
	if castTicksLeft > 0 then
		castTicksLeft = castTicksLeft - 1
		if castTicksLeft == 0 then
			state.casting = false
		end
	end
	pcall( dbgTick )
	local ok, err = pcall( paint )
	if not ok and not reportedErrors[ "paint" ] then
		reportedErrors[ "paint" ] = true
		log( "BotBridge: ошибка отрисовки: ", tostring( err ) )
	end
	cells[ 1 ]:PlayFadeEffect( 1.0, 1.0, BOT_TICK_MS, opt( "EA_MONOTONOUS_INCREASE" ), true )
end

local function onEffectFinished( params )
	if params and params.effectType ~= nil and opt( "ET_FADE" ) ~= nil
		and params.effectType ~= opt( "ET_FADE" ) then
		return
	end
	tick()
end

local function onSecondTimer()
	if castSecondsLeft > 0 then
		castSecondsLeft = castSecondsLeft - 1
		if castSecondsLeft == 0 then
			state.casting = false
			castTicksLeft = 0
		end
	end
	if ticks == ticksAtLastSecond then
		tick()
	end
	ticksAtLastSecond = ticks
	local ok, err = pcall( dumpCatalog )
	if not ok and not reportedErrors[ "catalog" ] then
		reportedErrors[ "catalog" ] = true
		log( "BotBridge: ошибка выгрузки каталога: ", tostring( err ) )
	end
	if opt( "BOT_DEBUG_READY" ) ~= false then pcall( logReady ) end
end

local function onCastStart( params )
	state.casting = true
	local duration = params and tonumber( params.duration ) or 3000
	castTicksLeft = math.ceil( ( duration + 500 ) / BOT_TICK_MS )
	castSecondsLeft = math.ceil( ( duration + 500 ) / 1000 ) + 1
end

local function onCastFinish()
	state.casting = false
	castTicksLeft = 0
	castSecondsLeft = 0
end

local function init()
	local sysName = common.GetAddonSysName and common.GetAddonSysName() or common.GetAddonName()
	local form = common.GetAddonMainForm( sysName ) or opt( "mainForm" )
	local template = form:GetChildChecked( "Cell", false )
	cells[ 1 ] = template
	local desc = template:GetWidgetDesc()
	for i = 2, BOT_CELL_COUNT do
		cells[ i ] = form:CreateChildByDesc( desc )
	end
	layout()

	common.RegisterEventHandler( onEffectFinished, "EVENT_EFFECT_FINISHED" )
	common.RegisterEventHandler( onSecondTimer, "EVENT_SECOND_TIMER" )
	common.RegisterEventHandler( layout, "EVENT_POS_CONVERTER_CHANGED" )
	for _, ev in ipairs( { "EVENT_AVATAR_CREATED", "EVENT_SPELLBOOK_CHANGED", "EVENT_ACTION_PANEL_CHANGED",
			"EVENT_TALENTS_CHANGED", "EVENT_BINDING_CHANGED" } ) do
		pcall( common.RegisterEventHandler, requestCatalog, ev )
	end
	common.RegisterEventHandler( onCastStart, "EVENT_ACTION_PROGRESS_START" )
	common.RegisterEventHandler( onGlobalCooldown, "EVENT_GLOBAL_COOLDOWN" )
	common.RegisterEventHandler( onCastFinish, "EVENT_ACTION_PROGRESS_FINISH" )

	if avatar.IsExist() then
		requestCatalog()
	end
	log( "BotBridge: запущен, ячеек ", tostring( BOT_CELL_COUNT ), " MARKER-2" )
	tick()
end

init()