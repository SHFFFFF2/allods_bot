--------------------------------------------------------------------------------
-- Упаковка состояния в байты для пиксельной полосы.
-- Формат описан в aobot/protocol.py и должен совпадать с ним байт в байт
-- (проверяется tests/test_lua_packer.py).
--------------------------------------------------------------------------------
Global( "BOT_VERSION", 2 )
Global( "BOT_SYNC", { 0xA5, 0x5A, 0xC3 } )
Global( "BOT_CALIB", { 0x0F, 0x80, 0xF0 } )
Global( "BOT_PAYLOAD_LEN", 30 )
Global( "BOT_BODY_PADDED", 33 )
Global( "BOT_CELL_COUNT", 2 + 33 / 3 )

local floor = math.floor

local function round( v )
	return floor( v + 0.5 )
end

local function clamp( v, lo, hi )
	if v < lo then return lo end
	if v > hi then return hi end
	return v
end

-- n передаётся явно: длина таблицы с nil внутри в Lua не определена
local function bits( n, list )
	local v = 0
	for i = 1, n do
		if list[ i ] then
			v = v + 2 ^ ( i - 1 )
		end
	end
	return v
end

local function optByte( v )
	if v == nil then
		return 255
	end
	return clamp( floor( v ), 0, 254 )
end

local function pushU16( out, v )
	out[ #out + 1 ] = floor( v / 256 ) % 256
	out[ #out + 1 ] = v % 256
end

local function pushS24( out, meters )
	local v = clamp( round( meters * 10 ), -8388608, 8388607 )
	if v < 0 then
		v = v + 16777216
	end
	out[ #out + 1 ] = floor( v / 65536 ) % 256
	out[ #out + 1 ] = floor( v / 256 ) % 256
	out[ #out + 1 ] = v % 256
end

-- st: таблица с полями как у aobot.protocol.GameState (nil = неизвестно)
-- возвращает массив байт (с 1) длиной BOT_BODY_PADDED
local function BotPack( st )
	local out = {
		BOT_VERSION,
		floor( st.seq or 0 ) % 256,
		bits( 8, { st.avatar_exists, st.dead, st.in_combat, st.casting,
			st.has_target, st.target_dead, st.target_attackable,
			st.target_is_player } ),
		bits( 3, { st.target_in_melee, st.target_enemy, st.target_tagged_other } ),
		optByte( st.hp ), optByte( st.mana ), optByte( st.target_hp ),
	}
	local dist = 65535
	if st.target_distance ~= nil then
		dist = clamp( round( st.target_distance * 10 ), 0, 65534 )
	end
	pushU16( out, dist )
	pushU16( out, clamp( floor( ( st.gcd_ms or 0 ) / 10 ), 0, 65535 ) )
	pushU16( out, ( st.spells_known or 0 ) % 65536 )
	pushU16( out, ( st.spells_ready or 0 ) % 65536 )
	pushS24( out, st.x or 0 )
	pushS24( out, st.y or 0 )
	pushS24( out, st.z or 0 )
	pushU16( out, round( ( st.direction or 0 ) * 10000 ) % 62832 )
	pushU16( out, st.target_id or 0 )
	pushU16( out, st.target_kind or 0 )

	-- Fletcher-16
	local s1, s2 = 0, 0
	for i = 1, BOT_PAYLOAD_LEN do
		s1 = ( s1 + out[ i ] ) % 255
		s2 = ( s2 + s1 ) % 255
	end
	out[ #out + 1 ] = s1
	out[ #out + 1 ] = s2
	while #out < BOT_BODY_PADDED do
		out[ #out + 1 ] = 0
	end
	return out
end
Global( "BotPack", BotPack )
