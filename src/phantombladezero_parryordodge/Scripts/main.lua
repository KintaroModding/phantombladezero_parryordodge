-- Parry or Dodge for Phantom Blade Zero.
--
-- In the game a blue attack wants a perfect parry and a red attack wants a perfect dodge. With this mod a perfect
-- parry also answers a red attack (ParryRed), and a perfect dodge also answers a blue attack (DodgeBlue), each with
-- the game's own counter. The timing, the range and the choice of the counter stay the game's.
--
-- How: when the player parries or dodges, the game asks DeflectComponent:GetNearestValidReceivedFrame which enemy
-- attack frame the move can answer; IsDodge says which kind of frame it wants. The mod hooks that function. When the
-- game found no frame, the mod asks the same function for the other kind, with the same angle, time and current
-- handle. It takes that frame only when its attack is a blue one (for a dodge) or a red one (for a parry), copies the
-- game's own frame into the function's output and returns its handle. Only the local player's component is changed;
-- enemies ask the same function.
--
-- A red frame goes to a parry only while the parry key is down and the perfect window of the player's deflect passive
-- is open, and only when the attack hits inside that window: holding the block gives nothing.
--
-- The game starts the counter of a perfect dodge by itself. For a red attack that was parried, the mod does what the
-- game does after a blue one: in the parry's "On Impact", when the result is a perfect parry of the frame the mod
-- gave, it writes the result into the component's PerfectDodgeResultData and calls the game's "Dodge After Deflect".
-- When the game prepared that frame itself, the mod leaves it alone.
--
-- After an error in one of the two callbacks the mod changes nothing more until the game starts again.
--
-- Settings: the player edits Scripts\config.lua. The mod reads it at start and again every CONFIG_INTERVAL_MS, so a
-- change shows without a restart; a broken or half-saved file keeps the last settings. DEFAULTS holds every setting
-- with its default. A player (or a mod manager) keeps their config.lua across updates, so a new main.lua can meet an
-- older file: a setting that the file lacks, or has with another type, keeps its default, and the log says so. Read a
-- setting only from Settings, never as `config.X or default`: for a true/false setting, `false or true` is true.

local MOD_NAME = "Parry or Dodge"
local VERSION = "1.0"
local CONFIG_INTERVAL_MS = 5000
-- The hooks are set at start; while one is missing, the mod looks again this often.
local HOOK_CHECK_MS = 2000
-- The query is a native function and is there at start: after this many checks without it, the mod gives up.
local MAX_QUERY_TRIES = 30
-- A Blueprint class can be found before its functions are ready: RegisterHook is tried this many times.
local MAX_IMPACT_TRIES = 5

local QUERY_PATH = "/Script/PBZDeflectSystem.DeflectComponent:GetNearestValidReceivedFrame"
local STANCE_CLASS_PATH = "/PBZDeflectSystem/Abilities/BP_StanceAction_Base_Player.BP_StanceAction_Base_Player_C"
local IMPACT_PATH = STANCE_CLASS_PATH .. ":On Impact"
local ATTACK_CLASS_PATH = "/Script/PBZDeflectSystem.LGAAction_DurationBulletWithDeflectBase"
local PLAYER_CLASS_PATH = "/Script/ProjectPBZ.PBZCharacter_Player"
local SYSTEM_LIBRARY_PATH = "/Script/Engine.Default__KismetSystemLibrary"
local COUNTER_LIBRARY_PATH = "/PBZDeflectSystem/BPL_DeflectUtils.Default__BPL_DeflectUtils_C"
local COUNTER_FUNCTION = "Dodge After Deflect"
-- The player's passive ability that handles the parry key; its fields are named with spaces.
local PASSIVE_CLASS_NAME = "BP_PlayerDeflectPassive_C"
local PASSIVE_KEY_DOWN = "Stance Key Down"
-- A game time: the perfect window is open until then (not a length).
local PASSIVE_WINDOW = "Perfect Window"
local STANCE_COMPONENT = "Deflect Component"
local PERFECT_TAG = "Deflect.Result.Perfect"
-- EDeflectBulletType: BlueEye and RedEye. Normal and power attacks are never changed.
local BLUE = 2
local RED = 3
-- The impact of a red frame must have the frame's hit time, within this many seconds.
local HIT_TIME_TOLERANCE = 0.01
-- A red frame the mod gave is forgotten when a newer one hits this many seconds later.
local RED_FRAME_SECONDS = 5
-- While the player has no deflect passive, search for it at most this often (a search looks at all objects).
local PASSIVE_SEARCH_SECONDS = 1
-- Log at most this many error lines, match lines and counter lines per game start (LogDetail: more).
local MAX_ERROR_LOGS = 5
local MAX_MATCH_LOGS = 20
local MAX_COUNTER_LOGS = 20
local MAX_DETAIL_LOGS = 400

-- Every setting with its default; config.lua ships the same names and values (tests\test_main.py checks it).
local DEFAULTS = {
    Enable = true,
    ParryRed = true,
    DodgeBlue = true,
    LogDetail = false,
}

local errors = 0
local details = 0

local function Log(message)
    print(string.format("[%s] %s\n", MOD_NAME, message))
end

local function LogError(message)
    errors = errors + 1
    if errors <= MAX_ERROR_LOGS then
        Log(message)
    end
end

local Settings = {}

-- LogDetail lines; message is a function, so nothing is built while LogDetail is off.
local function Detail(message)
    if Settings.LogDetail and details < MAX_DETAIL_LOGS then
        details = details + 1
        Log(message())
    end
end

-- LogDetail: why a frame was not taken, each reason once per game start. Always gives nil.
local reasons = {}
local function Skip(reason)
    if Settings.LogDetail and not reasons[reason] then
        reasons[reason] = true
        Detail(function() return "not taken (each reason is logged once): " .. reason end)
    end
    return nil
end

local function Valid(object)
    if object == nil then
        return false
    end
    local ok, valid = pcall(function()
        return object:IsValid()
    end)
    return ok and valid == true
end

-- Two values that are the same game object.
local function Same(a, b)
    return Valid(a) and Valid(b) and a:GetAddress() == b:GetAddress()
end

-- The kept object while it is valid, else the game object at `path`; nil when it is not there.
local function Find(kept, path)
    if Valid(kept) then
        return kept
    end
    local object = StaticFindObject(path)
    return Valid(object) and object or nil
end

local function FirstLine(message)
    return tostring(message):match("^[^\n]*")
end

---------------------------------------------------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------------------------------------------------

local function CopyDefaults()
    local settings = {}
    for name, value in pairs(DEFAULTS) do
        settings[name] = value
    end
    return settings
end

-- One line for the log: every setting, sorted by name.
local function Describe(settings)
    local names = {}
    for name in pairs(settings) do
        names[#names + 1] = name
    end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do
        parts[i] = name .. "=" .. tostring(settings[name])
    end
    return table.concat(parts, ", ")
end

-- Lua's line number and reason, without the chunk name.
local function Reason(message)
    message = tostring(message)
    local line, reason = message:match("config%.lua:(%d+): ([^\n]*)")
    return line and ("line " .. line .. ": " .. reason) or (message:gsub("%s*\n%s*", " "))
end

-- DEFAULTS with the values of config.lua's text over them; nil and the reason when the text is not a usable file.
local function ParseConfig(text)
    local chunk, problem = load(text, "=config.lua", "t", {})
    if not chunk then
        return nil, "config.lua not read (" .. Reason(problem) .. ")"
    end
    local ok, config = pcall(chunk)
    if not ok then
        return nil, "config.lua not read (" .. Reason(config) .. ")"
    end
    if type(config) ~= "table" then
        return nil, "config.lua does not return a table"
    end
    local settings = CopyDefaults()
    for name, value in pairs(config) do
        local default = DEFAULTS[name]
        if default == nil then
            Log("config.lua: unknown setting " .. tostring(name) .. " ignored.")
        elseif type(value) ~= type(default) then
            Log(string.format("config.lua: %s must be a %s; the default %s is used.", name, type(default),
                tostring(default)))
        else
            settings[name] = value
        end
    end
    return settings
end

local configPath = nil
-- The text of the last read; false: no file at the last read; nil: not read yet.
local configText = nil

-- Reads config.lua when its text changed since the last read. At start, a missing or broken file means the defaults;
-- later, a broken file keeps the last settings (a half-saved file), and a missing one means the defaults.
local function ReadConfig()
    local atStart = configText == nil
    configPath = configPath or package.searchpath("config", package.path)
    local text = false
    if configPath then
        local file = io.open(configPath, "rb")
        if file then
            text = file:read("a") or false
            file:close()
        end
    end
    if text == configText then
        return
    end
    configText = text
    local settings, problem
    if text == false then
        settings, problem = CopyDefaults(), nil
        Log("No config.lua; every setting uses its default.")
    else
        settings, problem = ParseConfig(text)
    end
    if not settings then
        if atStart then
            Log(problem .. "; every setting uses its default.")
            settings = CopyDefaults()
        else
            Log(problem .. "; the last settings stay.")
            return
        end
    end
    local line = Describe(settings)
    if atStart or line ~= Describe(Settings) then
        Log("Settings: " .. line)
    end
    Settings = settings
end

---------------------------------------------------------------------------------------------------------------------
-- The frame query
---------------------------------------------------------------------------------------------------------------------

local stopped = false       -- an error in a callback: nothing more is changed until the game starts again
local busy = false          -- the mod's own call of the query runs: its callback must do nothing
local stanceClass = nil     -- the class whose "On Impact" is hooked; nil: not hooked (yet)

-- Game objects that are looked up when first needed and kept while they are valid.
local playerClass, attackClass, systemLibrary, counterLibrary
-- The deflect passive of the pawn of the last parry query, and when it was last searched.
local cachedPawn, passive, passiveSearchAt
-- The red frames the mod gave to a parry, for the component they belong to:
-- handle -> { action = the attack's address, time = its hit time, done = the impact was looked at }.
local redComponent, redFrames = nil, {}
-- For the log: the last matched handle per component and kind.
local lastMatch = {}
local matchLogs, counterLogs = 0, 0

-- The end of the open perfect window (a game time) while the parry key is down; nil when the key is up, the window
-- is over, or the player's passive is not there.
local function PerfectDeadline(pawn)
    if not Same(pawn, cachedPawn) then
        cachedPawn, passive, passiveSearchAt = pawn, nil, nil
    end
    if not Valid(passive) then
        passive = nil
        local now = os.clock()
        if passiveSearchAt and now - passiveSearchAt < PASSIVE_SEARCH_SECONDS then
            return nil
        end
        passiveSearchAt = now
        for _, candidate in ipairs(FindAllOf(PASSIVE_CLASS_NAME) or {}) do
            if Valid(candidate) and Same(candidate:GetAvatarActorFromActorInfo(), pawn) then
                passive = candidate
                break
            end
        end
    end
    if not Valid(passive) or not passive[PASSIVE_KEY_DOWN] then
        return nil
    end
    systemLibrary = Find(systemLibrary, SYSTEM_LIBRARY_PATH)
    if not systemLibrary then
        return nil
    end
    local deadline = passive[PASSIVE_WINDOW]
    if type(deadline) ~= "number" or deadline <= 0 or systemLibrary:GetGameTimeInSeconds(pawn) > deadline then
        return nil
    end
    return deadline
end

-- Runs right after the game's query, with its return value and its parameters. Gives the handle of a frame of the
-- other kind when the game found none and the mod may take one; nil keeps the game's answer.
local function Supplement(context, returned, angle, maxTime, isDodge, currentHandle, outFrame)
    -- The game found a frame; 0 is a handle too.
    if returned:get() >= 0 then
        return nil
    end
    local dodge = isDodge:get()
    if (dodge and not Settings.DodgeBlue) or (not dodge and not Settings.ParryRed) then
        return nil
    end
    local component = context:get()
    if not Valid(component) then
        return nil
    end
    local pawn = component:GetOwner()
    if not Valid(pawn) then
        return nil
    end
    playerClass = Find(playerClass, PLAYER_CLASS_PATH)
    if not playerClass or not pawn:IsA(playerClass) then
        return nil
    end
    local controller = pawn:GetController()
    if not Valid(controller) or not controller:IsLocalPlayerController() then
        return nil
    end

    local deadline
    if not dodge then
        -- Without the hook on the impact, a parried red attack would get no counter.
        if stanceClass == nil then
            return Skip("a red frame for a parry: the hook on the parry's impact is not set")
        end
        deadline = PerfectDeadline(pawn)
        if deadline == nil then
            return nil
        end
    end
    -- The same function for the other kind. Its angle, time and current-handle rules still run; `busy` keeps this
    -- call away from the mod's own callback. No frame of the game is changed or used up here.
    local discarded = {}
    local handle = component:GetNearestValidReceivedFrame(angle:get(), maxTime:get(), not dodge, currentHandle:get(),
        discarded)
    if type(handle) ~= "number" or handle < 0 then
        return nil
    end
    local received = component.ReceiveFrames
    if not received:Contains(handle) then
        return Skip("the frame of the other kind is not in the component's list")
    end
    local candidate = received:Find(handle):get()
    local action = candidate.SourceAction:Get()
    attackClass = Find(attackClass, ATTACK_CLASS_PATH)
    if not Valid(action) or not attackClass or not action:IsA(attackClass) then
        return Skip("the frame of the other kind has no attack action")
    end
    if action.DeflectBulletType ~= (dodge and BLUE or RED) or candidate.IsDodge ~= (not dodge) then
        return Skip(dodge and "a dodge: the nearest parry frame is not a blue attack"
            or "a parry: the nearest dodge frame is not a red attack")
    end
    if not dodge and candidate.HitGameTime > deadline then
        return Skip("a red frame for a parry: the attack hits after the perfect window")
    end

    -- The game's own struct is copied, with its weak pointer and its interface; a Lua table would lose them. The
    -- handle is given back only after this copy.
    outFrame:set(candidate)
    if not dodge then
        local address = component:GetAddress()
        if redComponent ~= address then
            redComponent, redFrames = address, {}
        end
        local existing = redFrames[handle]
        if not existing or existing.action ~= action:GetAddress() or existing.time ~= candidate.HitGameTime then
            redFrames[handle] = { action = action:GetAddress(), time = candidate.HitGameTime }
        end
        for id, frame in pairs(redFrames) do
            if candidate.HitGameTime - frame.time > RED_FRAME_SECONDS then
                redFrames[id] = nil
            end
        end
    end
    local key = tostring(component:GetAddress()) .. ":" .. tostring(dodge)
    if lastMatch[key] ~= handle then
        lastMatch[key] = handle
        local line = function()
            return string.format("%s attack: frame %d given to the %s.", dodge and "Blue" or "Red", handle,
                dodge and "perfect dodge" or "perfect parry")
        end
        if matchLogs < MAX_MATCH_LOGS then
            matchLogs = matchLogs + 1
            Log(line())
        else
            Detail(line)
        end
    end
    return handle
end

local function Stop(where, problem)
    stopped = true
    Log(string.format("Error in the %s: %s. The mod changes nothing more until the game starts again.", where,
        FirstLine(problem)))
end

-- The second callback of the hook on the query. A returned handle replaces the game's "no frame".
local function AfterQuery(...)
    if stopped or busy or not Settings.Enable then
        return nil
    end
    busy = true
    local ok, result = pcall(Supplement, ...)
    busy = false
    if not ok then
        Stop("frame query", result)
        return nil
    end
    return result
end

---------------------------------------------------------------------------------------------------------------------
-- The counter after a red attack was parried
---------------------------------------------------------------------------------------------------------------------

-- Runs after the parry's "On Impact" (a Blueprint function: the callback comes after it). When the impact is the
-- perfect parry of a red frame the mod gave, it starts the game's counter the way the game does for a blue attack.
local function CounterRed(context, handle, result, _, _, _, _, broken)
    if not Settings.ParryRed then
        return
    end
    local ability = context:get()
    if not Valid(ability) then
        return
    end
    local component = ability[STANCE_COMPONENT]
    if not Valid(component) or component:GetAddress() ~= redComponent then
        return
    end
    local id = handle:get()
    local pending = redFrames[id]
    if not pending or pending.done then
        return
    end
    -- One look per frame, set before any game code is called (a call can come back into this callback).
    pending.done = true
    local data = result:get()
    local action = data.SourceAction:Get()
    if broken:get() or not ability:IsAbilityRunning() then
        return Skip("a parried red attack: the parry broke or its ability ended")
    end
    if data.DeflectResult.TagName:ToString() ~= PERFECT_TAG then
        return Skip("a parried red attack: the parry was not a perfect one")
    end
    if not Valid(action) or action:GetAddress() ~= pending.action or action.DeflectBulletType ~= RED
        or math.abs(data.HitGameTime - pending.time) > HIT_TIME_TOLERANCE then
        return Skip("a parried red attack: the impact is not the frame the mod gave")
    end
    local pawn = component:GetOwner()
    if not Same(pawn, ability:GetAvatarActorFromActorInfo()) then
        return
    end
    local controller = pawn:GetController()
    if not Valid(controller) or not controller:IsLocalPlayerController() then
        return
    end
    if not Valid(data.SourceAvatar) then
        return
    end
    -- The game prepared this frame itself: its own counter, now or delayed, stays alone.
    local prepared = component.PerfectDodgeResultData
    if prepared.HitGameTime == data.HitGameTime and Same(prepared.SourceAction:Get(), action) then
        return Skip("a parried red attack: the game prepared the counter itself")
    end
    counterLibrary = Find(counterLibrary, COUNTER_LIBRARY_PATH)
    if not counterLibrary then
        return Skip("a parried red attack: the game's deflect library is not loaded")
    end
    -- The game's entry starts the counter ability, sets its tags and picks the counter.
    component.PerfectDodgeResultData = data
    counterLibrary[COUNTER_FUNCTION](counterLibrary, pawn, pawn)
    local line = function()
        return string.format("Red attack: perfect parry of frame %d, the game's counter is called.", id)
    end
    if counterLogs < MAX_COUNTER_LOGS then
        counterLogs = counterLogs + 1
        Log(line())
    else
        Detail(line)
    end
end

-- The callback of the hook on "On Impact". It gives nothing back: the game's results stay.
local function AfterImpact(...)
    if stopped or not Settings.Enable then
        return
    end
    local ok, problem = pcall(CounterRed, ...)
    if not ok then
        Stop("parry impact", problem)
    end
end

---------------------------------------------------------------------------------------------------------------------
-- The hooks
---------------------------------------------------------------------------------------------------------------------

local queryState = "none"   -- "none", "set", or "failed" (no second try: two hooks would both give frames)
local queryTries = 0
local impactTries = 0
local impactWaitLogged = false   -- the line "not loaded yet" is logged once

-- The hook on the frame query, a native function: it is there from the game's start.
local function SetQueryHook()
    if queryState ~= "none" then
        return
    end
    queryTries = queryTries + 1
    if not Valid(StaticFindObject(QUERY_PATH)) then
        if queryTries >= MAX_QUERY_TRIES then
            queryState = "failed"
            Log("No hook: the game function " .. QUERY_PATH .. " is not there. The mod changes nothing; a game update "
                .. "may need a new version of the mod.")
        elseif queryTries == 1 then
            Log("Not ready yet: the game function " .. QUERY_PATH .. " is not there. The mod looks again every "
                .. HOOK_CHECK_MS // 1000 .. " s.")
        end
        return
    end
    -- The first function runs before the game's function and has nothing to do; the second runs right after it.
    local set, problem = pcall(RegisterHook, QUERY_PATH, function() end, AfterQuery)
    if not set then
        queryState = "failed"
        Log("No hook: " .. FirstLine(problem) .. ". The mod changes nothing.")
        return
    end
    queryState = "set"
    Log("Hook set on the game's deflect frame query.")
end

-- The hook on the parry's impact, a Blueprint function: its class loads some seconds after the game's start, and it
-- can be unloaded and come back.
local function SetImpactHook()
    if stanceClass ~= nil and not Valid(stanceClass) then
        stanceClass = nil
        impactTries = 0
        impactWaitLogged = true
        Log("The parry class was unloaded; its hook is set again when it is back. Until then ParryRed does nothing.")
    end
    if stanceClass ~= nil or impactTries >= MAX_IMPACT_TRIES then
        return
    end
    local class = StaticFindObject(STANCE_CLASS_PATH)
    if not Valid(class) then
        if not impactWaitLogged then
            impactWaitLogged = true
            Log("The parry class is not loaded yet; the hook on the parry's impact is set when it is there. Until "
                .. "then ParryRed does nothing.")
        end
        return
    end
    impactTries = impactTries + 1
    local set, problem = pcall(RegisterHook, IMPACT_PATH, AfterImpact)
    if set then
        stanceClass = class
        Log("Hook set on the parry's impact (On Impact).")
    elseif impactTries >= MAX_IMPACT_TRIES then
        Log("No hook on the parry's impact: " .. FirstLine(problem) .. ". ParryRed does nothing; DodgeBlue works.")
    elseif impactTries == 1 then
        Log("The parry's impact is not ready yet (" .. FirstLine(problem) .. "); the mod tries again.")
    end
end

local function SetHooks()
    SetQueryHook()
    if queryState == "set" then
        SetImpactHook()
    end
end

---------------------------------------------------------------------------------------------------------------------
-- Start
---------------------------------------------------------------------------------------------------------------------

Settings = CopyDefaults()
Log(VERSION .. " loaded.")
local read, problem = pcall(ReadConfig)
if not read then
    LogError("Error while reading config.lua: " .. tostring(problem))
end
if not Settings.Enable then
    Log("Enable = false in config.lua: the mod changes nothing until it is true.")
end

local function HookStep()
    local ok, err = pcall(SetHooks)
    if not ok then
        LogError("Error while setting the hooks: " .. tostring(err))
    end
end

local function ConfigStep()
    local ok, err = pcall(ReadConfig)
    if not ok then
        LogError("Error while reading config.lua: " .. tostring(err))
    end
end

-- The objects of the old map are gone: the next query finds the new ones.
RegisterLoadMapPostHook(function()
    local ok, err = pcall(function()
        cachedPawn, passive, passiveSearchAt = nil, nil, nil
        redComponent, redFrames = nil, {}
        lastMatch = {}
        SetHooks()
    end)
    if not ok then
        LogError("Error after the map load: " .. tostring(err))
    end
end)

-- The hooks are set on the game thread: at once, and again on a timer while one is missing. Both loops run on the
-- game thread (UE4SS's Delayed Action API): no Lua on a second thread (Witch Time's crash lesson). A UE4SS without it
-- gets the old LoopAsync loops, and the log says so.
ExecuteInGameThread(HookStep)
if type(LoopInGameThreadWithDelay) == "function" then
    LoopInGameThreadWithDelay(HOOK_CHECK_MS, HookStep)
    LoopInGameThreadWithDelay(CONFIG_INTERVAL_MS, ConfigStep)
else
    Log("This UE4SS has no game-thread loops (LoopInGameThreadWithDelay): the older LoopAsync is used; a newer UE4SS "
        .. "is safer.")
    LoopAsync(HOOK_CHECK_MS, function()
        ExecuteInGameThread(HookStep)
        -- false keeps the loop running.
        return false
    end)
    LoopAsync(CONFIG_INTERVAL_MS, function()
        ExecuteInGameThread(ConfigStep)
        return false
    end)
end
