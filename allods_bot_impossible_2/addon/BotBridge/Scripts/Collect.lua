--------------------------------------------------------------------------------
-- Сбор состояния персонажа и цели через Lua API игры.
-- Только чтение: аддон ничего не делает в игре сам.
--------------------------------------------------------------------------------
Global( "BOT_API_ERRORS", {} )

-- Вызов API, который не роняет весь сбор при ошибке.
-- Первую ошибку каждой функции запоминаем, чтобы показать в логе.
local function safe( name, f, ... )
	if not f then
		BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or "функция отсутствует"
		return nil
	end
	local ok, a = pcall( f, ... )
	if ok then
		return a
	end
	BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or tostring( a )
	return nil
end

-- Как safe, но сообщает, упал ли вызов: ok=false — ошибка API.
local function try( name, f, ... )
	if not f then
		BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or "функция отсутствует"
		return false, nil
	end
	local ok, a = pcall( f, ... )
	if ok then
		return true, a
	end
	BOT_API_ERRORS[ name ] = BOT_API_ERRORS[ name ] or tostring( a )
	return false, nil
end

local function lib( t, key )
	return t and t[ key ]
end

local function num( v )
	return v ~= nil and tonumber( v ) or nil
end

local function percents( id )
	local info = safe( "object.GetHealthInfo", lib( object, "GetHealthInfo" ), id )
	return info and num( info.valuePercents )
end

local function wstr( w )
	if w == nil then return nil end
	if type( w ) == "string" then return w end
	return safe( "userMods.FromWString", lib( userMods, "FromWString" ), w )
end

-- names: список названий (или системных имён) умений, как в Config.lua.
-- Возвращает массив той же длины: SpellId или false, если умения нет.
local function BotResolveSpells( names )
	local ids = {}
	for i = 1, #names do ids[ i ] = false end
	local book = safe( "avatar.GetSpellBook", lib( avatar, "GetSpellBook" ) ) or {}
	for _, id in ipairs( book ) do
		local d = safe( "spellLib.GetDescription", lib( spellLib, "GetDescription" ), id )
		if d then
			local name, sys = wstr( d.name ), d.sysName
			for i = 1, #names do
				if not ids[ i ] and ( names[ i ] == name or names[ i ] == sys ) then
					ids[ i ] = id
				end
			end
		end
	end
	return ids
end

-- Список умений книги: { { name =, sysName = }, ... } — для подсказки в логе.
local function BotListSpells()
	local list = {}
	local book = safe( "avatar.GetSpellBook", lib( avatar, "GetSpellBook" ) ) or {}
	for _, id in ipairs( book ) do
		local d = safe( "spellLib.GetDescription", lib( spellLib, "GetDescription" ), id )
		if d then
			list[ #list + 1 ] = { name = wstr( d.name ) or "?", sysName = d.sysName or "?" }
		end
	end
	return list
end

local function spellMasks( ids, gcdMs )
	local known, ready = 0, 0
	for i = 1, math.min( #ids, 16 ) do
		local id = ids[ i ]
		if id then
			local bit = 2 ^ ( i - 1 )
			known = known + bit
			local okCd, cd = try( "spellLib.GetCooldown", lib( spellLib, "GetCooldown" ), id )
			local okCan, can = try( "spellLib.CanRunAvatar", lib( spellLib, "CanRunAvatar" ), id )
			local remaining = cd and num( cd.remainingMs ) or 0
			-- Ошибка API — НЕ «готово»: иначе умение жмётся вслепую, в КД и без ресурса.
			-- Кулдаун, равный остатку ГКД, — это сам ГКД, умение готово.
			if okCd and okCan and can ~= false and remaining <= gcdMs then
				ready = ready + bit
			end
		end
	end
	return known, ready
end

-- ГКД: опрос avatar.GetGlobalCooldown и, на случай если он молчит, событие
-- EVENT_GLOBAL_COOLDOWN — по нему запоминаем момент конца ГКД.
local gcdEventEnd = nil

local function absMs()
	return num( safe( "common.GetAbsTimeMs", lib( common, "GetAbsTimeMs" ) ) )
end

local function BotOnGlobalCooldown( params )
	local finished = rawget( _G, "EFFECT_TYPE_COOLDOWN_FINISHED" )
	if not params or ( finished ~= nil and params.effect == finished ) then
		gcdEventEnd = nil
		return
	end
	local rem, now = num( params.remaining ), absMs()
	if rem and now then
		gcdEventEnd = now + rem
	end
end

local function BotGcdRemaining()
	local gcd = safe( "avatar.GetGlobalCooldown", lib( avatar, "GetGlobalCooldown" ) )
	-- клиент отдаёт remainingMs, хотя в документации написано remaining
	local polled = gcd and ( num( gcd.remainingMs ) or num( gcd.remaining ) ) or 0
	local fromEvent = 0
	if gcdEventEnd then
		local now = absMs()
		if now then
			fromEvent = math.max( 0, gcdEventEnd - now )
		end
	end
	return math.max( polled, fromEvent )
end

-- Вид цели: хэш байт названия, та же формула, что aobot.protocol.kind_hash.
local function BotKind( name )
	if type( name ) ~= "string" or name == "" then
		return 0
	end
	local h = 0
	for i = 1, #name do
		h = ( h * 31 + string.byte( name, i ) ) % 65521
	end
	return h + 1
end

local function BotCollect( seq, casting, spellIds )
	local st = { seq = seq, casting = casting and true or false }
	if not safe( "avatar.IsExist", lib( avatar, "IsExist" ) ) then
		return st
	end
	local me = safe( "avatar.GetId", lib( avatar, "GetId" ) )
	if not me then
		return st
	end
	st.avatar_exists = true
	st.dead = safe( "object.IsDead", lib( object, "IsDead" ), me ) and true or false
	st.in_combat = safe( "object.IsInCombat", lib( object, "IsInCombat" ), me ) and true or false
	st.hp = percents( me )
	local getManaPct = lib( unit, "GetManaPercentage" )
	if getManaPct then
		st.mana = num( safe( "unit.GetManaPercentage", getManaPct, me ) )
	end
	if st.mana == nil and lib( object, "GetManaInfo" ) then
		local mi = safe( "object.GetManaInfo", object.GetManaInfo, me )
		st.mana = mi and num( mi.valuePercents )
	end

	local pos = safe( "avatar.GetPos", lib( avatar, "GetPos" ) )
	if pos then
		st.x, st.y, st.z = num( pos.posX ), num( pos.posY ), num( pos.posZ )
	end
	st.direction = num( safe( "avatar.GetDir", lib( avatar, "GetDir" ) ) )

	st.gcd_ms = BotGcdRemaining()

	local t = safe( "avatar.GetTarget", lib( avatar, "GetTarget" ) )
	if t and safe( "object.IsExist", lib( object, "IsExist" ), t ) then
		st.has_target = true
		st.target_id = type( t ) == "number" and t % 65535 + 1 or 0
		st.target_name = wstr( safe( "object.GetName", lib( object, "GetName" ), t ) )
		st.target_kind = BotKind( st.target_name )
		st.target_dead = safe( "object.IsDead", lib( object, "IsDead" ), t ) and true or false
		st.target_attackable = safe( "object.CanAttack", lib( object, "CanAttack" ), t ) and true or false
		st.target_enemy = safe( "object.IsEnemy", lib( object, "IsEnemy" ), t ) and true or false
		st.target_is_player = safe( "unit.IsPlayer", lib( unit, "IsPlayer" ), t ) and true or false
		st.target_in_melee = safe( "avatar.IsTargetInMeleeRange",
			lib( avatar, "IsTargetInMeleeRange" ) ) and true or false
		local tagged = safe( "unit.IsTagged", lib( unit, "IsTagged" ), t )
		local mine = safe( "unit.IsTaggedByMainPlayer", lib( unit, "IsTaggedByMainPlayer" ), t )
		st.target_tagged_other = ( tagged and not mine ) and true or false
		st.target_hp = percents( t )
		st.target_distance = num( safe( "object.GetDistance", lib( object, "GetDistance" ), t ) )
	end

	st.spells_known, st.spells_ready = spellMasks( spellIds or {}, st.gcd_ms )
	return st
end

Global( "BotResolveSpells", BotResolveSpells )
Global( "BotListSpells", BotListSpells )
Global( "BotKind", BotKind )
Global( "BotCollect", BotCollect )
Global( "BotOnGlobalCooldown", BotOnGlobalCooldown )
Global( "BotGcdRemaining", BotGcdRemaining )
