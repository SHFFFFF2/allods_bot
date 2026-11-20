--------------------------------------------------------------------------------
-- Выгрузка каталога в mods.txt: умения книги, слоты панели с клавишами,
-- пассивки, изученные вехи и классовый ресурс. Строки BOTCAT разбирает
-- aobot/catalog.py. Вызовы тяжёлые — только по событиям смены, не каждый кадр.
--------------------------------------------------------------------------------
local SLOT_COUNT = 36
local MAX_TALENT_DIM = 64

-- Как в Collect.lua: ошибка API не роняет выгрузку, первая ошибка — в BOT_API_ERRORS.
-- Возвращает все значения функции (у некоторых функций их несколько).
local function safe( name, f, ... )
	if not f then
		BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or "функция отсутствует"
		return nil
	end
	local r = { pcall( f, ... ) }
	if r[ 1 ] then
		return unpack( r, 2, table.maxn( r ) )
	end
	BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or tostring( r[ 2 ] )
	return nil
end

-- Глобалы игры читаем через rawget: в клиенте обращение к несуществующему
-- глобалу — ошибка.
local function api( libName )
	return rawget( _G, libName )
end

local function fn( libName, key )
	local t = api( libName )
	return type( t ) == "table" and t[ key ] or nil
end

local function call( libName, key, ... )
	return safe( libName .. "." .. key, fn( libName, key ), ... )
end

-- WString / ValuedText / строка -> строка Lua.
local function text( v )
	if v == nil then return "" end
	local tv = type( v )
	if tv == "string" then return v end
	if tv == "number" or tv == "boolean" then return tostring( v ) end
	local isVT = fn( "common", "IsValuedText" )
	if isVT and safe( "common.IsValuedText", isVT, v ) then
		return call( "userMods", "FromValuedText", v ) or ""
	end
	return call( "userMods", "FromWString", v ) or ""
end

local ESC = { [ "\\" ] = "\\\\", [ "\t" ] = "\\t", [ "\n" ] = "\\n", [ "\r" ] = "\\r" }
local function esc( s )
	return ( string.gsub( tostring( s ), "[\\\t\n\r]", ESC ) )
end

local function int( v )
	v = tonumber( v )
	if not v or v ~= v then return "0" end
	return string.format( "%d", math.floor( v ) )
end

local function flag( v )
	return v and "1" or "0"
end

local function numText( v )
	v = tonumber( v )
	if not v or v ~= v then return "0" end
	return tostring( v )
end

local function list( t )
	return type( t ) == "table" and t or {}
end

-- Номер сессии: время клиента при первой выгрузке, дальше не меняется.
local session = nil

local function spellName( id )
	local d = call( "spellLib", "GetDescription", id )
	return d and text( d.name ) or nil, d
end

-- Константы-перечисления клиент отдаёт через __index глобального окружения,
-- поэтому rawget их не видит: читаем обычным обращением под pcall (строгие
-- глобалы бросают ошибку на неизвестное имя), запасной вариант — rawget.
local enumCache = {}
local function enum( name )
	local v = enumCache[ name ]
	if v ~= nil then return v end
	local ok, got = pcall( function() return _G[ name ] end )
	v = ok and got or nil
	if v == nil then v = rawget( _G, name ) end
	enumCache[ name ] = v
	return v
end

local function kindOf( t )
	if t == nil then return "other" end
	if t == enum( "ACTION_TYPE_SPELL" ) then return "spell" end
	if t == enum( "ACTION_TYPE_ITEM" ) then return "item" end
	if t == enum( "ACTION_TYPE_MOUNT" ) or t == enum( "ACTION_TYPE_MOUNT_METAMORPH" ) then return "mount" end
	if t == enum( "ACTION_TYPE_EMOTE" ) then return "emote" end
	return "other"
end

-- Клавиша слота: первая привязка action_NN, части через "+"; "" — нет клавиши.
local function slotKeys( slot )
	local getBind = fn( "binding", "GetBind" )
	if not getBind then return "" end
	local b = safe( "binding.GetBind", getBind, "mission_actions", string.format( "action_%02d", slot ) )
	local combo = type( b ) == "table" and type( b.keys ) == "table" and b.keys[ 0 ] or nil
	if type( combo ) ~= "table" then return "" end
	local parts = {}
	local i = 0
	while combo[ i ] ~= nil and i < 8 do
		parts[ #parts + 1 ] = text( combo[ i ] )
		i = i + 1
	end
	return table.concat( parts, "+" )
end

-- Кэш слотов: [1..36] = { kind =, name =, spellId =, keys = }; kind "none" — пусто.
local function BotSlotCache()
	local slots = {}
	local byName = nil
	for i = 0, SLOT_COUNT - 1 do
		local slot = { kind = "none", name = "", spellId = nil, keys = "" }
		local info = call( "avatar", "GetActionInfo", i )
		if type( info ) == "table" then
			local kind = kindOf( info.type )
			-- тип не распознан, но id — умение: считаем слот умением.
			-- В слоте лежит id объекта умения (action id), а spellLib ждёт SpellId:
			-- сырой номер в spellLib не передаём никогда.
			if kind == "spell" or ( kind == "other" and info.id ~= nil ) then
				local name, spellId = "", nil
				if fn( "spellLib", "GetObjectSpell" ) then
					spellId = call( "spellLib", "GetObjectSpell", info.id )
				end
				if spellId ~= nil then
					name = spellName( spellId ) or ""
				elseif fn( "avatar", "GetSpellObjectInfo" ) then
					-- старый путь: имя объекта умения и поиск SpellId по имени в книге
					local so = call( "avatar", "GetSpellObjectInfo", info.id )
					name = type( so ) == "table"
						and ( text( so.name ) ~= "" and text( so.name ) or text( so.debugName ) ) or ""
					if name ~= "" then
						if not byName then
							byName = {}
							for _, id in pairs( list( call( "avatar", "GetSpellBook" ) ) ) do
								local n = spellName( id )
								if n and byName[ n ] == nil then byName[ n ] = id end
							end
						end
						spellId = byName[ name ]
					end
				end
            				-- GetObjectSpell отдаёт число: GetDescription его принимает,
				-- а GetCooldown/CanRunAvatar — нет. Берём id из книги заклинаний.
				if name ~= "" then
					if not byName then
						byName = {}
						for _, id in pairs( list( call( "avatar", "GetSpellBook" ) ) ) do
							local n = spellName( id )
							if n and n ~= "" and byName[ n ] == nil then byName[ n ] = id end
						end
					end
					if byName[ name ] ~= nil then
						spellId = byName[ name ]
					end
				end
				if type( spellId ) == "number" then
					spellId = nil
				end
				if kind == "spell" or name ~= "" then
					kind, slot.name, slot.spellId = "spell", name, spellId
				end
			end
			slot.kind = kind
			slot.keys = slotKeys( i + 1 )
		end
		slots[ i + 1 ] = slot
	end
	return slots
end

local function line( out, gen, tag, fields )
	local parts = { "BOTCAT", tostring( gen ), tag }
	for _, kv in ipairs( fields ) do
		parts[ #parts + 1 ] = kv[ 1 ] .. "=" .. esc( kv[ 2 ] )
	end
	out[ #out + 1 ] = table.concat( parts, "\t" )
end

local function spellRows( out, gen )
	for _, id in pairs( list( call( "avatar", "GetSpellBook" ) ) ) do
		local name, d = spellName( id )
		if name and name ~= "" then
			local ps = {}
			for _, p in pairs( list( call( "spellLib", "GetDescriptionParams", id ) ) ) do
				if type( p ) == "table" and type( p.value ) == "number" then
					ps[ #ps + 1 ] = text( p.key ) .. "=" .. tostring( p.value )
				end
			end
			local cv = list( call( "spellLib", "GetCurrentValues", id ) )
			local pr = list( call( "spellLib", "GetProperties", id ) )
			local cd = list( call( "spellLib", "GetCooldown", id ) )
			line( out, gen, "SPELL", {
				{ "name", name }, { "sys", text( d.sysName ) }, { "desc", text( d.description ) },
				{ "params", table.concat( ps, ";" ) },
				{ "cd_ms", int( cv.predictedCooldown ) }, { "cast_ms", int( cv.prepareDuration ) },
				{ "channel", flag( pr.isChanneled ) }, { "harmful", flag( pr.isHarmful ) },
				{ "helpful", flag( pr.isHelpFul ) }, { "target", int( pr.targetType ) },
				{ "range", numText( cv.range ) }, { "nogcd", flag( cd.ignoreGlobalCooldown ) },
			} )
		end
	end
end

local function slotRows( out, gen, slots )
	for i = 1, SLOT_COUNT do
		local s = slots[ i ]
		if s and s.kind ~= "none" then
			line( out, gen, "SLOT", { { "slot", tostring( i ) }, { "kind", s.kind },
				{ "name", s.name or "" }, { "keys", s.keys or "" } } )
		end
	end
end

local function passiveRows( out, gen )
	if not fn( "avatar", "GetAbilities" ) then return end
	for _, id in pairs( list( call( "avatar", "GetAbilities" ) ) ) do
		local info = call( "avatar", "GetAbilityInfo", id )
		if type( info ) == "table" then
			line( out, gen, "PASSIVE", { { "name", text( info.name ) }, { "desc", text( info.description ) } } )
		end
	end
end

-- Ранг для текста, не завися от индексации ranks (с 0 или с 1): запись с
-- r.rank == currentRank; иначе с наибольшим r.rank <= currentRank; иначе
-- последняя. В игре currentRank считается с 1, а в ranks часто лежит только
-- первый ранг.
local function pickRank( ranks, cur )
	local exact, best, last, lastKey = nil, nil, nil, nil
	for k, r in pairs( ranks ) do
		if type( r ) == "table" then
			local n = tonumber( r.rank )
			if n == cur and not exact then exact = r end
			if n and n <= cur and ( not best or n > tonumber( best.rank ) ) then best = r end
			if type( k ) == "number" and ( not lastKey or k > lastKey ) then last, lastKey = r, k end
		end
	end
	return exact or best or last
end

-- Текст текущего ранга: пассивка -> умение -> сырое описание ранга.
local function talentRow( out, gen, field, row, col, info )
	if type( info ) ~= "table" or info.isEmpty or not info.isLearned then return end
	local ranks = list( info.ranks )
	local cur = tonumber( info.currentRank ) or 0
	local r = pickRank( ranks, cur )
	if not r then return end
	local desc, src = nil, "raw"
	if r.abilityId ~= nil then
		local a = call( "avatar", "GetAbilityInfo", r.abilityId )
		if type( a ) == "table" and a.description ~= nil then
			desc, src = text( a.description ), "ability"
		end
	end
	if not desc and r.spellId ~= nil then
		local d = call( "spellLib", "GetDescription", r.spellId )
		if type( d ) == "table" and d.description ~= nil then
			desc, src = text( d.description ), "spell"
		end
	end
	if not desc then
		desc = text( r.desc )
	end
	line( out, gen, "TALENT", { { "field", tostring( field ) }, { "row", tostring( row ) },
		{ "col", tostring( col ) }, { "rank", tostring( cur ) }, { "name", text( r.name ) },
		{ "desc", desc }, { "src", src } } )
end

local function dim( v )
	v = tonumber( v ) or 0
	return math.max( 0, math.min( MAX_TALENT_DIM, math.floor( v ) ) )
end

local function talentRows( out, gen )
	-- базовые таланты: поле 0
	if fn( "avatar", "GetBaseTalentTableSize" ) then
		local a, b = call( "avatar", "GetBaseTalentTableSize" )
		if type( a ) == "table" then a, b = a.layersCount, a.linesCount end
		for la = 0, dim( a ) - 1 do
			for li = 0, dim( b ) - 1 do
				talentRow( out, gen, 0, la, li, call( "avatar", "GetBaseTalentInfo", la, li ) )
			end
		end
	end
	-- поля вех: в API с 0, в каталоге 1..3
	if fn( "avatar", "GetFieldTalentTableSize" ) then
		local f, r, c = call( "avatar", "GetFieldTalentTableSize" )
		if type( f ) == "table" then f, r, c = f.fieldsCount, f.rowsCount, f.columnsCount end
		for fi = 0, math.min( dim( f ), 3 ) - 1 do
			for ri = 0, dim( r ) - 1 do
				for ci = 0, dim( c ) - 1 do
					talentRow( out, gen, fi + 1, ri, ci, call( "avatar", "GetFieldTalentInfo", fi, ri, ci ) )
				end
			end
		end
	end
end

local function resourceRow( out, gen )
	if not fn( "avatar", "GetNecromancerBloodPool" ) then return end
	local pool = call( "avatar", "GetNecromancerBloodPool" )
	if type( pool ) == "table" and pool.maxValue ~= nil then
		line( out, gen, "RES", { { "name", "blood" }, { "max", int( pool.maxValue ) } } )
	end
end

-- Пишет одну выгрузку функцией log(text); возвращает число записанных строк.
-- slots — готовый кэш BotSlotCache() (если нет — считается здесь).
local function BotCatalogDump( gen, log, slots )
	if session == nil then
		session = fn( "common", "GetAbsTimeMs" ) and int( call( "common", "GetAbsTimeMs" ) ) or "0"
	end
	local rows = {}
	local steps = {
		function() spellRows( rows, gen ) end,
		function() slotRows( rows, gen, slots or BotSlotCache() ) end,
		function() passiveRows( rows, gen ) end,
		function() talentRows( rows, gen ) end,
		function() resourceRow( rows, gen ) end,
	}
	for i = 1, #steps do
		local n = #rows
		local ok, err = pcall( steps[ i ] )
		if not ok then
			-- недописанный шаг выбрасываем целиком, остальное выгружаем
			for k = #rows, n + 1, -1 do rows[ k ] = nil end
			BOT_API_ERRORS[ "catalog" ] = BOT_API_ERRORS[ "catalog" ] or tostring( err )
		end
	end
	local out = {}
	line( out, gen, "BEGIN", { { "v", "1" }, { "session", session } } )
	for i = 1, #rows do out[ #out + 1 ] = rows[ i ] end
	line( out, gen, "END", { { "count", tostring( #rows ) } } )
	for i = 1, #out do
		log( out[ i ] )
	end
	return #out
end

local function fields( t )
	if type( t ) ~= "table" then return tostring( t ) .. "(" .. type( t ) .. ")" end
	local parts = {}
	for k, v in pairs( t ) do
		parts[ #parts + 1 ] = tostring( k ) .. "=" .. tostring( v ) .. "(" .. type( v ) .. ")"
		if #parts >= 12 then break end
	end
	return "{" .. table.concat( parts, " " ) .. "}"
end

-- Одна строка диагностики к выгрузке (не BOTCAT — разборщик её пропускает):
-- что лежит в первом непустом слоте и что отдаёт пул крови.
local function BotCatalogDiag()
	local parts = { "BotBridge: диаг" }
	local get = fn( "avatar", "GetActionInfo" )
	local found = false
	for i = 0, SLOT_COUNT - 1 do
		local ok, info = pcall( get, i )
		if ok and info ~= nil then
			local okIdx, idx = pcall( function() return _G[ "ACTION_TYPE_SPELL" ] end )
			parts[ #parts + 1 ] = string.format( "слот %d type=%s(%s) id=%s SPELL raw=%s idx=%s info=%s",
				i + 1, tostring( type( info ) == "table" and info.type ), type( type( info ) == "table" and info.type ),
				tostring( type( info ) == "table" and info.id ), tostring( rawget( _G, "ACTION_TYPE_SPELL" ) ),
				okIdx and tostring( idx ) or ( "ошибка " .. tostring( idx ) ), fields( info ) )
			found = true
			break
		end
	end
	if not found then parts[ #parts + 1 ] = "слотов нет" end
	local pool = fn( "avatar", "GetNecromancerBloodPool" )
	if pool then
		local ok, p = pcall( pool )
		if ok and type( p ) == "table" then
			parts[ #parts + 1 ] = string.format( "; кровь value=%s min=%s max=%s %s", tostring( p.value ),
				tostring( p.minValue ), tostring( p.maxValue ), fields( p ) )
		else
			parts[ #parts + 1 ] = "; кровь " .. ( ok and fields( p ) or ( "ошибка " .. tostring( p ) ) )
		end
	else
		parts[ #parts + 1 ] = "; кровь: функции нет"
	end
	-- эффекты на себе: вдруг кровь видна как стаки эффекта
	local buffs = {}
	local okMe, me = pcall( fn( "avatar", "GetId" ) )
	local okB, ids = pcall( fn( "object", "GetBuffs" ), okMe and me or nil )
	if okB and type( ids ) == "table" then
		for _, id in ipairs( ids ) do
			if #buffs >= 15 then buffs[ #buffs + 1 ] = "…" break end
			local ok, b = pcall( fn( "object", "GetBuffInfo" ), id )
			if ok and type( b ) == "table" then
				local okN, nm = pcall( text, b.name )
				buffs[ #buffs + 1 ] = ( okN and nm or "?" ) .. "x" .. tostring( b.stackCount )
			end
		end
		parts[ #parts + 1 ] = "; эффекты " .. tostring( #ids ) .. ": " .. table.concat( buffs, ", " )
	else
		parts[ #parts + 1 ] = "; эффекты: нет данных"
	end
	return table.concat( parts, " " )
end

Global( "BotSlotCache", BotSlotCache )
Global( "BotCatalogDump", BotCatalogDump )
Global( "BotCatalogDiag", BotCatalogDiag )
