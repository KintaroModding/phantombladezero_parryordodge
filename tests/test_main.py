"""Offline test of Scripts/main.lua with lupa (Lua 5.4) and small mocks of UE4SS and the game.

The mocks stand in for the UE4SS functions that the script uses (RegisterHook with one or two callbacks,
StaticFindObject, FindAllOf, RegisterLoadMapPostHook, the game-thread loops LoopInGameThreadWithDelay, the old
LoopAsync, ExecuteInGameThread) and for the game: a player with a deflect component, the deflect passive (parry key,
perfect window) and the parry ability, attack frames, the game's frame query, the parry's impact and the counter
library. As in UE4SS, a hook's parameters are params (get, set), and a call of the hooked query from Lua runs the
hook's callbacks again.

QUERY(component, isDodge) is the game asking for a frame: the callback before, the game's own search (the nearest
frame of that kind), the callback after with the result; a handle that the callback gives back replaces the result.
IMPACT(ability, handle, result) is the parry's "On Impact". In these tests a blue attack is frame 7 (a parry frame),
a red attack frame 8 (a dodge frame); the game time is 100.0, the perfect window is open until 100.3, and the attacks
hit at 100.2. PROBE() gives what a dodge gets for a blue attack and what a parry gets for a red one: "7, 8" with the
mod, "-1, -1" in the game alone.

The checks: the hooks and the loops; a dodge for a blue attack; a parry for a red attack (key, window, hit time, the
search for the passive); the counter after a parried red attack and every case in which it must not come; the
switches, live; the log lines; what happens when the game differs (a missing function or class, a failed
RegisterHook, an unloaded class, a map load) and when a callback fails. Then the settings files a player may have
instead of the shipped config.lua: main.lua must start, and every setting the file does not give keeps its default;
the shipped config.lua must hold exactly the defaults of main.lua.

Usage:
    python tests/test_main.py        (needs lupa: python -m pip install lupa)

Exit code: 0 = all checks passed, 1 = a check failed.
"""

import json
import sys
import tempfile
from pathlib import Path

from lupa import lua54

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "phantombladezero_parryordodge" / "Scripts" / "main.lua"
CONFIG = MAIN.parent / "config.lua"

MOCKS = r"""
LOG = {}
print = function(...) LOG[#LOG + 1] = table.concat({...}, "") end

LOOPS = {}
DELAYS = {}
ASYNC_LOOPS = 0
GAME_THREAD_CALLS = 0
function LoopInGameThreadWithDelay(ms, callback) LOOPS[#LOOPS + 1] = callback DELAYS[#DELAYS + 1] = ms return #LOOPS end
function LoopAsync(ms, callback) ASYNC_LOOPS = ASYNC_LOOPS + 1 LOOPS[#LOOPS + 1] = callback DELAYS[#DELAYS + 1] = ms end
function ExecuteInGameThread(callback) GAME_THREAD_CALLS = GAME_THREAD_CALLS + 1 callback() end
function RUN(ms) for i = 1, #LOOPS do if DELAYS[i] == ms then LOOPS[i]() end end end
function RETRY(times) for _ = 1, times or 1 do RUN(2000) end end
function CONFIG() RUN(5000) end
MAP_LOADS = {}
function RegisterLoadMapPostHook(callback) MAP_LOADS[#MAP_LOADS + 1] = callback end
function MAP_LOAD() for _, callback in ipairs(MAP_LOADS) do callback() end end

-- The mod's pause between two searches for the passive uses the real clock; the tests set it.
CLOCK = 0
os.clock = function() return CLOCK end

QUERY_PATH = "/Script/PBZDeflectSystem.DeflectComponent:GetNearestValidReceivedFrame"
STANCE_PATH = "/PBZDeflectSystem/Abilities/BP_StanceAction_Base_Player.BP_StanceAction_Base_Player_C"
IMPACT_PATH = STANCE_PATH .. ":On Impact"
ATTACK_PATH = "/Script/PBZDeflectSystem.LGAAction_DurationBulletWithDeflectBase"
PLAYER_PATH = "/Script/ProjectPBZ.PBZCharacter_Player"
SYSTEM_PATH = "/Script/Engine.Default__KismetSystemLibrary"
COUNTER_PATH = "/PBZDeflectSystem/BPL_DeflectUtils.Default__BPL_DeflectUtils_C"
NORMAL, BLUE, RED, POWER = 1, 2, 3, 4

function Param(value) return { get = function() return value end } end
-- An out parameter: the frame goes into store.frame.
function OutParam(store)
    return { get = function() return store.frame end, set = function(_, frame) store.frame = frame end }
end
local function Name(text) return { ToString = function() return text end } end
function Weak(object) return { Get = function() return object end } end
local function Float(value) return (string.unpack("f", string.pack("f", value))) end

-- The game's own search: the nearest frame of the asked kind; -1 when there is none. FORCE[isDodge] replaces it.
NATIVE_CALLS = {}
FORCE = {}
local function Native(component, angle, maxTime, isDodge, currentHandle)
    NATIVE_CALLS[#NATIVE_CALLS + 1] = { angle = angle, maxTime = maxTime, isDodge = isDodge, currentHandle = currentHandle }
    if FORCE[isDodge] ~= nil then return FORCE[isDodge] end
    local best, bestTime = -1, math.huge
    for handle, frame in pairs(component.frames) do
        if frame.IsDodge == isDodge and handle ~= currentHandle and frame.HitGameTime < bestTime then
            best, bestTime = handle, frame.HitGameTime
        end
    end
    return best
end

HOOKS = {}
HOOK_CALLS = {}
HOOK_FAILS = {}
function RegisterHook(path, before, after)
    HOOK_CALLS[path] = (HOOK_CALLS[path] or 0) + 1
    if (HOOK_FAILS[path] or 0) > 0 then
        HOOK_FAILS[path] = HOOK_FAILS[path] - 1
        error("Was unable to register a hook with Lua function 'RegisterHook', information:\nUFunction::Func: 0x0\n"
            .. "stack traceback:\n    [C]: in ?", 0)
    end
    HOOKS[path] = after and { before = before, after = after } or { after = before }
    return 1, 2
end

-- The hooked query: the callback before, the game's search, the callback after (context, result, parameters).
BEFORE_RESULTS = 0
function CALL_QUERY(component, angle, maxTime, isDodge, currentHandle, out)
    local hook = HOOKS[QUERY_PATH]
    if hook and hook.before(Param(component), Param(angle), Param(maxTime), Param(isDodge), Param(currentHandle), out) ~= nil then
        BEFORE_RESULTS = BEFORE_RESULTS + 1
    end
    local result = Native(component, angle, maxTime, isDodge, currentHandle)
    if result >= 0 and component.frames[result] then out:set(component.frames[result]) end
    if hook then
        local changed = hook.after(Param(component), Param(result), Param(angle), Param(maxTime), Param(isDodge),
            Param(currentHandle), out)
        if changed ~= nil then result = changed end
    end
    return result
end

-- Game objects: each has its own address.
local nextAddress = 0x1000
local ObjectMeta = {}
ObjectMeta.__index = {
    IsValid = function(self) return self.valid ~= false end,
    GetAddress = function(self) return self.address end,
    IsA = function(self, class) return self.class == class end,
    GetOwner = function(self) return self.owner end,
    GetController = function(self) return self.controller end,
    IsLocalPlayerController = function(self) return self.localPlayer == true end,
    GetAvatarActorFromActorInfo = function(self) return self.avatar end,
    IsAbilityRunning = function(self) return self.running ~= false end,
    -- A call from Lua: UE4SS fills the table that stands for the out parameter, and the hook runs as for the game.
    GetNearestValidReceivedFrame = function(self, angle, maxTime, isDodge, currentHandle, outTable)
        return CALL_QUERY(self, angle, maxTime, isDodge, currentHandle, OutParam(outTable))
    end,
}
function Object(fields)
    fields = fields or {}
    nextAddress = nextAddress + 0x100
    fields.address = fields.address or nextAddress
    return setmetatable(fields, ObjectMeta)
end

PLAYER_CLASS, ATTACK_CLASS = Object(), Object()
GAME_TIME = 100.0
COUNTERS = {}
COUNTER_THROWS = false
OBJECTS = {
    [QUERY_PATH] = Object(),
    [STANCE_PATH] = Object(),
    [ATTACK_PATH] = ATTACK_CLASS,
    [PLAYER_PATH] = PLAYER_CLASS,
    [SYSTEM_PATH] = Object({ GetGameTimeInSeconds = function() return GAME_TIME end }),
    [COUNTER_PATH] = Object({ ["Dodge After Deflect"] = function(self, avatar, context)
        if COUNTER_THROWS then error("the counter failed") end
        COUNTERS[#COUNTERS + 1] = { avatar = avatar, context = context, data = W.component.PerfectDodgeResultData }
    end }),
}
FINDS = 0
function StaticFindObject(path) FINDS = FINDS + 1 return OBJECTS[path] or Object({ valid = false }) end
PASSIVES = {}
FIND_ALLS = 0
function FindAllOf(name)
    FIND_ALLS = FIND_ALLS + 1
    if name ~= "BP_PlayerDeflectPassive_C" or #PASSIVES == 0 then return nil end
    return PASSIVES
end

function Component(owner)
    local component = Object({ owner = owner, frames = {},
        PerfectDodgeResultData = { SourceAction = Weak(Object({ valid = false })), HitGameTime = 0 } })
    component.ReceiveFrames = {
        Contains = function(_, handle) return component.frames[handle] ~= nil end,
        Find = function(_, handle) return Param(component.frames[handle]) end,
    }
    return component
end
-- An attack frame: kind NORMAL, BLUE, RED or POWER; isDodge: the frame wants a dodge (false: a parry).
function Frame(kind, isDodge, time, class)
    return { SourceAction = Weak(Object({ class = class or ATTACK_CLASS, DeflectBulletType = kind })),
        HitGameTime = time or 100.2, IsDodge = isDodge }
end
-- The result data of a parry's impact for a frame (its hit time is a 32-bit float there).
function Result(frame, tag)
    return { SourceAction = frame.SourceAction, SourceAvatar = Object(),
        DeflectResult = { TagName = Name(tag or "Deflect.Result.Perfect") }, HitGameTime = Float(frame.HitGameTime) }
end
-- A new player (global W): pawn, controller, deflect component, the passive (key down, window open until 100.3)
-- and the parry ability.
function World()
    local w = {}
    w.controller = Object({ localPlayer = true })
    w.pawn = Object({ class = PLAYER_CLASS, controller = w.controller })
    w.component = Component(w.pawn)
    w.passive = Object({ avatar = w.pawn, ["Stance Key Down"] = true, ["Perfect Window"] = 100.3 })
    w.ability = Object({ avatar = w.pawn, ["Deflect Component"] = w.component })
    PASSIVES = { w.passive }
    GAME_TIME = 100.0
    W = w
    return w
end

-- The game asks for a frame. Gives the handle; OUT is the frame in the out parameter afterwards.
function QUERY(component, isDodge, currentHandle)
    local store = {}
    NATIVE_CALLS = {}
    local handle = CALL_QUERY(component, 120, 0.5, isDodge, currentHandle or -1, OutParam(store))
    OUT = store.frame
    return handle
end
-- The parry's "On Impact" (a Blueprint function: one callback, after it). IMPACT_RESULTS counts what it gives back.
IMPACT_RESULTS = 0
function IMPACT(ability, handle, result, broken)
    local hook = HOOKS[IMPACT_PATH]
    if hook and hook.after(Param(ability), Param(handle), Param(result), Param(0), Param(Name("hand_r")), Param(false),
        Param(false), Param(broken == true), Param(false)) ~= nil then
        IMPACT_RESULTS = IMPACT_RESULTS + 1
    end
end

-- A new player; a dodge with only a blue attack there, then a parry with only a red attack there.
function PROBE()
    World()
    W.component.frames = { [7] = Frame(BLUE, false) }
    local dodge = QUERY(W.component, true)
    W.component.frames = { [8] = Frame(RED, true) }
    local parry = QUERY(W.component, false)
    return dodge .. ", " .. parry
end
-- A new player parries a red attack (frame 8) in the perfect window; the handle the parry gets.
function RED_PARRY(time)
    World()
    W.component.frames = { [8] = Frame(RED, true, time) }
    return QUERY(W.component, false)
end
-- A parried red attack, then the parry's impact; change(result) may change the world or the result before it.
-- Gives the number of counter calls; RESULT is the impact's result data.
function IMPACT_CASE(change, tag, broken)
    COUNTERS = {}
    if RED_PARRY() ~= 8 then return "no frame" end
    RESULT = Result(W.component.frames[8], tag)
    if change then change(RESULT) end
    IMPACT(W.ability, 8, RESULT, broken)
    return #COUNTERS
end

function DESCRIBE(t)
    local names = {}
    for name in pairs(t) do names[#names + 1] = tostring(name) end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do parts[i] = name .. "=" .. tostring(t[name]) end
    return table.concat(parts, ", ")
end
"""

GAME = "-1, -1"     # the game alone: no frame for the dodge of a blue attack, none for the parry of a red one
MOD = "7, 8"        # the mod: the blue frame for the dodge, the red frame for the parry
DODGE_ONLY = "7, -1"
PARRY_ONLY = "-1, 8"

PLAYER_CONFIGS = [
    ("no config.lua", None, "No config.lua"),
    ("an empty or older config.lua", "return {}\n", None),
    ("a broken config.lua", "return {\n    Enable =\n", "config.lua not read"),
    ("a config.lua without a table", "-- nothing here\n", "does not return a table"),
    ("a config.lua with wrong types", "wrong types", "must be a"),
    ("a config.lua with an unknown setting", "return { NoSuchSetting = 1 }\n", "unknown setting NoSuchSetting"),
]


def lua_path(path: Path) -> str:
    return "[[" + path.as_posix() + "]]"


class Run:
    """main.lua in a fresh Lua state, with config.lua read from config_folder; before: Lua run before main.lua."""

    def __init__(self, config_folder: Path, before: str = ""):
        self.folder = config_folder
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute(f'package.path = {lua_path(config_folder)} .. "/?.lua"; package.cpath = ""')
        if before:
            self.lua.execute(before)
        self.g = self.lua.globals()
        self.do(MAIN.read_text(encoding="utf-8"))

    def do(self, code: str):
        """Runs Lua code; a Lua error that stops it becomes an "Error" line in the log, so the checks fail."""
        try:
            return self.lua.execute(code)
        except lua54.LuaError as error:
            self.g.LOG[len(self.g.LOG) + 1] = "Error: main.lua stopped: " + str(error).splitlines()[0]

    def eval(self, expression: str):
        return self.lua.eval(expression)

    def log(self):
        return [self.g.LOG[i].rstrip() for i in range(1, len(self.g.LOG) + 1)]

    def count(self, text: str) -> int:
        return sum(text in line for line in self.log())

    def write_config(self, text: str):
        (self.folder / "config.lua").write_text(text, encoding="utf-8")


def settings_lines(log):
    return [line.split("] Settings: ", 1)[1] for line in log if "] Settings: " in line]


def main() -> None:
    version = json.loads((ROOT / "mod.json").read_text(encoding="utf-8"))["version"]
    failures = []

    def check(condition, text):
        print(("ok    " if condition else "FAIL  ") + text)
        if not condition:
            failures.append(text)

    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        shipped_text = CONFIG.read_text(encoding="utf-8")

        def folder(name, text=shipped_text):
            f = temp / name
            f.mkdir()
            if text is not None:
                (f / "config.lua").write_text(text, encoding="utf-8")
            return f

        def config(**values):
            """The shipped config.lua with other values, for example config(ParryRed="false")."""
            text = shipped_text
            for name, value in values.items():
                lines = [line for line in text.splitlines() if line.strip().startswith(name + " = ")]
                assert len(lines) == 1, name
                old = lines[0].split(",", 1)[0]
                text = text.replace(old + ",", f"    {name} = {value},")
            return text

        # --- The mod as players get it.
        r = Run(folder("shipped"))
        e = r.eval
        log = r.log()
        for line in log:
            print("      log: " + line)
        check(list(r.g.DELAYS.values()) == [2000, 5000] and r.g.ASYNC_LOOPS == 0 and r.g.GAME_THREAD_CALLS == 1,
              "game-thread loops: the hook check every 2 s, the config read every 5 s; the hooks are set at start")
        check(any(f"{version} loaded." in line for line in log), f"load line with the version {version} of mod.json")
        shipped = e(f"DESCRIBE(dofile({lua_path(CONFIG)}))")
        check(settings_lines(log) == [shipped] and not any("config.lua" in line for line in log),
              "one settings line with the shipped values, no warning")
        check(e("HOOK_CALLS[QUERY_PATH]") == 1 and e("HOOKS[QUERY_PATH].before ~= nil and HOOKS[QUERY_PATH].after ~= nil")
              and r.count("Hook set on the game's deflect frame query") == 1,
              "one hook on the frame query, with a callback before and one after")
        check(e("HOOK_CALLS[IMPACT_PATH]") == 1 and e("HOOKS[IMPACT_PATH].before == nil")
              and r.count("Hook set on the parry's impact") == 1, "one hook on the parry's On Impact, with one callback")
        finds = e("FINDS")
        r.do("RETRY(3)")
        check(e("HOOK_CALLS[QUERY_PATH]") == 1 and e("HOOK_CALLS[IMPACT_PATH]") == 1 and e("FINDS") == finds,
              "the hooks are set once; the later checks search nothing")

        # --- A dodge and a blue attack.
        r.do("World() W.component.frames = { [7] = Frame(BLUE, false) }")
        check(e("QUERY(W.component, true, 5)") == 7 and e("OUT == W.component.frames[7]"),
              "a dodge with only a blue attack there: the blue frame's handle, and the game's own frame in the output")
        check(e("#NATIVE_CALLS") == 2 and e("NATIVE_CALLS[2].isDodge") is False and e("NATIVE_CALLS[2].angle") == 120
              and e("NATIVE_CALLS[2].maxTime") == 0.5 and e("NATIVE_CALLS[2].currentHandle") == 5,
              "the mod asks the game once more: the other kind, the same angle, time and current handle")
        check(e("FIND_ALLS") == 0, "a dodge never searches for the deflect passive")
        r.do("QUERY(W.component, true)")
        check(r.count("Blue attack: frame 7 given to the perfect dodge.") == 1,
              "one log line for the frame, also when the game asks for it again")
        r.do("W.component.frames = { [0] = Frame(RED, true), [7] = Frame(BLUE, false) }")
        check(e("QUERY(W.component, true)") == 0 and e("#NATIVE_CALLS") == 1 and e("OUT == W.component.frames[0]"),
              "the game found a frame (handle 0): the mod asks nothing and changes nothing")
        for kind, name in (("NORMAL", "a normal"), ("POWER", "a power"), ("RED", "a red")):
            r.do(f"W.component.frames = {{ [7] = Frame({kind}, false) }}")
            check(e("QUERY(W.component, true)") == -1 and e("OUT == nil"),
                  f"a dodge with only {name} attack's parry frame there: no frame")
        r.do("W.component.frames = { [7] = Frame(BLUE, false, 100.2, Object()) }")
        check(e("QUERY(W.component, true)") == -1, "a frame whose action is not an attack of the deflect system: no frame")
        r.do("W.component.frames = { [7] = Frame(BLUE, true) } FORCE = { [true] = -1, [false] = 7 }")
        check(e("QUERY(W.component, true)") == -1, "a frame that is not of the other kind itself: no frame")
        r.do("W.component.frames = {} FORCE = { [false] = 99 }")
        check(e("QUERY(W.component, true)") == -1, "a handle that is not in the component's frame list: no frame")
        r.do("FORCE = {}")
        check(e("QUERY(W.component, true)") == -1 and e("#NATIVE_CALLS") == 2
              and e("QUERY(W.component, false)") == -1 and e("#NATIVE_CALLS") == 2,
              "no frame of either kind: the mod asks the game once, and its own question does not start another one")
        r.do("ENEMY = Component(Object({ class = Object(), controller = Object() })) "
             "ENEMY.frames = { [7] = Frame(BLUE, false) }")
        check(e("QUERY(ENEMY, true)") == -1 and e("#NATIVE_CALLS") == 1,
              "an enemy's component: no frame, and the mod does not ask the game again")
        r.do("World() W.controller.localPlayer = false W.component.frames = { [7] = Frame(BLUE, false) }")
        check(e("QUERY(W.component, true)") == -1 and e("#NATIVE_CALLS") == 1,
              "a player character without the local player's controller: no frame")
        r.do("World() W.pawn.controller = nil W.component.frames = { [7] = Frame(BLUE, false) }")
        check(e("QUERY(W.component, true)") == -1, "a player character without a controller: no frame")

        # --- A parry and a red attack.
        check(e("RED_PARRY()") == 8 and e("OUT == W.component.frames[8]") and e("NATIVE_CALLS[2].isDodge") is True
              and r.count("Red attack: frame 8 given to the perfect parry.") == 1,
              "a parry in the perfect window with only a red attack there: the red frame, one log line")
        r.do("World() W.passive['Stance Key Down'] = false W.component.frames = { [8] = Frame(RED, true) }")
        check(e("QUERY(W.component, false)") == -1 and e("#NATIVE_CALLS") == 1,
              "the parry key is up (a held block's query later): no frame, the game is not asked again")
        r.do("World() GAME_TIME = 100.31 W.component.frames = { [8] = Frame(RED, true) }")
        check(e("QUERY(W.component, false)") == -1, "the perfect window is over: no frame")
        r.do("World() W.passive['Perfect Window'] = 0 W.component.frames = { [8] = Frame(RED, true) }")
        check(e("QUERY(W.component, false)") == -1, "no perfect window (0): no frame")
        check(e("RED_PARRY(100.35)") == -1, "the red attack hits after the perfect window: no frame")
        check(e("RED_PARRY(100.3)") == 8, "the red attack hits at the window's end: the frame")
        for kind, name in (("NORMAL", "a normal"), ("POWER", "a power"), ("BLUE", "a blue")):
            r.do(f"World() W.component.frames = {{ [8] = Frame({kind}, true) }}")
            check(e("QUERY(W.component, false)") == -1 and e("OUT == nil"),
                  f"a parry with only {name} attack's dodge frame there: no frame")
        r.do("World() PASSIVES = {} FIND_ALLS = 0 W.component.frames = { [8] = Frame(RED, true) }")
        check(e("QUERY(W.component, false)") == -1 and e("QUERY(W.component, false)") == -1 and e("FIND_ALLS") == 1,
              "no deflect passive: no frame, and one search for two queries in the same second")
        r.do("CLOCK = CLOCK + 1.5")
        check(e("QUERY(W.component, false)") == -1 and e("FIND_ALLS") == 2, "a second later: the next search")
        r.do("CLOCK = CLOCK + 1.5 PASSIVES = { Object({ avatar = Object(), ['Stance Key Down'] = true, "
             "['Perfect Window'] = 100.3 }) }")
        check(e("QUERY(W.component, false)") == -1 and e("FIND_ALLS") == 3, "another character's passive is not taken")
        r.do("CLOCK = CLOCK + 1.5 PASSIVES = { W.passive }")
        check(e("QUERY(W.component, false)") == 8 and e("QUERY(W.component, false)") == 8 and e("FIND_ALLS") == 4,
              "the passive is found at the next search and kept: no search after that")
        check(not any("Error" in line for line in r.log()) and e("BEFORE_RESULTS") == 0,
              "no error line so far; the callback before the query gives nothing back")

        # --- The counter after a parried red attack.
        check(e("IMPACT_CASE()") == 1 and e("COUNTERS[1].avatar == W.pawn and COUNTERS[1].context == W.pawn")
              and e("COUNTERS[1].data == RESULT and W.component.PerfectDodgeResultData == RESULT")
              and r.count("Red attack: perfect parry of frame 8, the game's counter is called.") == 1,
              "the impact of a perfect parry of the red frame: the result is written, then the game's counter is called")
        r.do("IMPACT(W.ability, 8, RESULT)")
        check(e("#COUNTERS") == 1 and e("IMPACT_RESULTS") == 0,
              "a second impact of the same frame: no second counter; the callback gives nothing back")
        check(e("IMPACT_CASE(nil, 'Deflect.Result.Normal')") == 0 and e("IMPACT_CASE(nil, 'Deflect.Result.Great')") == 0,
              "a block or a nearly timed parry of the red frame: no counter")
        r.do("IMPACT_CASE(nil, 'Deflect.Result.Normal') IMPACT(W.ability, 8, Result(W.component.frames[8]))")
        check(e("#COUNTERS") == 0, "the frame's first impact decides: a later perfect impact of it gets no counter")
        check(e("IMPACT_CASE(nil, nil, true)") == 0, "the parry broke: no counter")
        check(e("IMPACT_CASE(function() W.ability.running = false end)") == 0, "the parry ability ended: no counter")
        check(e("IMPACT_CASE(function(result) result.HitGameTime = 100.25 end)") == 0,
              "an impact with another hit time than the frame's: no counter")
        check(e("IMPACT_CASE(function(result) result.SourceAction = Frame(RED, true).SourceAction end)") == 0,
              "an impact of another attack: no counter")
        check(e("IMPACT_CASE(function(result) result.SourceAction:Get().DeflectBulletType = NORMAL end)") == 0,
              "the attack is no longer a red one at the impact: no counter")
        check(e("IMPACT_CASE(function(result) result.SourceAvatar = Object({ valid = false }) end)") == 0,
              "an impact without a valid attacker: no counter")
        check(e("IMPACT_CASE(function() W.ability.avatar = Object() end)") == 0,
              "a parry ability of another character: no counter")
        check(e("IMPACT_CASE(function() W.controller.localPlayer = false end)") == 0,
              "not the local player's controller at the impact: no counter")
        check(e("IMPACT_CASE(function(result) W.component.PerfectDodgeResultData = "
                "{ SourceAction = result.SourceAction, HitGameTime = result.HitGameTime } end)") == 0
              and e("W.component.PerfectDodgeResultData ~= RESULT"),
              "the game prepared this frame's counter itself: the mod leaves it alone")
        r.do("COUNTERS = {} RED_PARRY() NPC = Object({ avatar = W.pawn, ['Deflect Component'] = Component(W.pawn) }) "
             "IMPACT(NPC, 8, Result(W.component.frames[8]))")
        check(e("#COUNTERS") == 0, "an impact on another deflect component: no counter")
        r.do("COUNTERS = {} RED_PARRY() IMPACT(W.ability, 9, Result(W.component.frames[8]))")
        check(e("#COUNTERS") == 0, "an impact of a frame the mod did not give: no counter")
        r.do("COUNTERS = {} RED_PARRY() OLD = W.component.frames[8] W.passive['Perfect Window'] = 103.5 GAME_TIME = 103 "
             "W.component.frames = { [9] = Frame(RED, true, 103.2) } NEXT = QUERY(W.component, false) "
             "IMPACT(W.ability, 8, Result(OLD))")
        check(e("NEXT") == 9 and e("#COUNTERS") == 1, "a red frame given 3 s before the next one is still known")
        r.do("COUNTERS = {} RED_PARRY() OLD = W.component.frames[8] W.passive['Perfect Window'] = 106.5 GAME_TIME = 106 "
             "W.component.frames = { [9] = Frame(RED, true, 106.3) } NEXT = QUERY(W.component, false) "
             "IMPACT(W.ability, 8, Result(OLD)) AFTER_OLD = #COUNTERS IMPACT(W.ability, 9, Result(W.component.frames[9]))")
        check(e("NEXT") == 9 and e("AFTER_OLD") == 0 and e("#COUNTERS") == 1,
              "a red frame given more than 5 s before the next one is forgotten; the new one gets its counter")
        r.do("COUNTERS = {} World() W.component.frames = { [7] = Frame(BLUE, false) } QUERY(W.component, true) "
             "IMPACT(W.ability, 7, Result(W.component.frames[7]))")
        check(e("#COUNTERS") == 0, "a blue frame given to a dodge is no red frame: its parry impact gets no counter")
        check(not any("Error" in line for line in r.log()), "no error line so far")

        # --- Live settings.
        check(e("PROBE()") == MOD, "both switches on: a dodge gets the blue frame, a parry the red frame")
        r.do("COUNTERS = {} RED_PARRY()")
        r.write_config(config(ParryRed="false"))
        r.do("CONFIG() IMPACT(W.ability, 8, Result(W.component.frames[8]))")
        check(any("ParryRed=false" in line for line in settings_lines(r.log())) and e("#COUNTERS") == 0,
              "a changed config.lua: a settings line; ParryRed = false also stops the counter of a frame given before")
        check(e("PROBE()") == DODGE_ONLY and e("#NATIVE_CALLS") == 1,
              "ParryRed = false: only the dodge part; a parry's query is not asked again")
        r.write_config(config(DodgeBlue="false"))
        r.do("CONFIG()")
        check(e("PROBE()") == PARRY_ONLY, "DodgeBlue = false: only the parry part")
        r.write_config(config(Enable="false"))
        r.do("CONFIG()")
        check(e("PROBE()") == GAME and e("#NATIVE_CALLS") == 1, "Enable = false (live): the game's own answers")
        r.write_config("return {\n    Enable =\n")
        r.do("CONFIG()")
        check(any("config.lua not read (line" in line and "the last settings stay" in line for line in r.log())
              and e("PROBE()") == GAME, "a broken (half-saved) file keeps the last settings")
        r.write_config(shipped_text)
        r.do("CONFIG()")
        check(e("PROBE()") == MOD and e("IMPACT_CASE()") == 1 and not any("Error" in line for line in r.log()),
              "the shipped file again: both parts and the counter again")

        # --- The log lines.
        many_frames = ("World() for i = 1, 22 do W.component.frames = { [i] = Frame(BLUE, false) } "
                       "QUERY(W.component, true) end")
        many_counters = ("for i = 1, 22 do World() W.component.frames = { [i] = Frame(RED, true) } "
                         "QUERY(W.component, false) IMPACT(W.ability, i, Result(W.component.frames[i])) end")
        refused = ("World() W.component.frames = { [7] = Frame(NORMAL, false) } QUERY(W.component, true) "
                   "QUERY(W.component, true)")
        many = Run(folder("many"))
        many.do(many_frames + " " + refused)
        check(many.count("given to the perfect dodge") == 20 and many.count("not taken") == 0,
              "22 frames given: 20 log lines (the limit); no line for a frame that is not taken")
        many.do("COUNTERS = {} " + many_counters)
        check(many.eval("#COUNTERS") == 22 and many.count("the game's counter is called") == 20,
              "22 counters called: 20 log lines (the limit)")
        detail = Run(folder("detail", config(LogDetail="true")))
        detail.do(many_frames + " " + refused + " COUNTERS = {} " + many_counters)
        check(detail.count("given to the perfect dodge") == 22 and detail.count("the game's counter is called") == 22,
              "LogDetail = true: a line for every frame and every counter")
        check(detail.count("not taken (each reason is logged once): a dodge: the nearest parry frame is not a blue "
                           "attack") == 1, "LogDetail = true: why a frame was not taken, once per reason")

        # --- A game that differs from what the mod knows.
        late = Run(folder("late"), "KEPT = OBJECTS[QUERY_PATH] OBJECTS[QUERY_PATH] = nil")
        check(late.eval("HOOK_CALLS[QUERY_PATH]") is None and late.eval("HOOK_CALLS[IMPACT_PATH]") is None
              and late.count("Not ready yet: the game function " + "/Script/PBZDeflectSystem.DeflectComponent:"
                             "GetNearestValidReceivedFrame is not there. The mod looks again every 2 s.") == 1,
              "the frame query is missing at start: no hook yet, one line")
        late.do("RETRY(2)")
        check(late.eval("HOOK_CALLS[QUERY_PATH]") is None and late.count("Not ready yet") == 1,
              "still missing: no new line")
        late.do("OBJECTS[QUERY_PATH] = KEPT RETRY()")
        check(late.eval("HOOK_CALLS[QUERY_PATH]") == 1 and late.eval("HOOK_CALLS[IMPACT_PATH]") == 1
              and late.eval("PROBE()") == MOD, "the function is there at a later check: both hooks are set and work")
        never = Run(folder("never"), "OBJECTS[QUERY_PATH] = nil")
        never.do("RETRY(40)")
        check(never.eval("HOOK_CALLS[QUERY_PATH]") is None and never.count("No hook: the game function") == 1
              and never.eval("FINDS") == 30 and never.eval("PROBE()") == GAME,
              "missing for good: 30 tries, then one line and no more checks; the game's own answers")
        throws = Run(folder("throws"), "HOOK_FAILS[QUERY_PATH] = 1")
        throws.do("RETRY(3)")
        check(throws.eval("HOOK_CALLS[QUERY_PATH]") == 1 and throws.eval("HOOK_CALLS[IMPACT_PATH]") is None
              and throws.count("No hook: Was unable to register a hook") == 1
              and not any("traceback" in line or "UFunction" in line for line in throws.log())
              and throws.eval("PROBE()") == GAME,
              "RegisterHook fails on the query: one line (its first), no second try, no hook on the impact")
        noclass = Run(folder("noclass"), "KEPT = OBJECTS[STANCE_PATH] OBJECTS[STANCE_PATH] = nil")
        noclass.do("RETRY(2)")
        check(noclass.eval("HOOK_CALLS[QUERY_PATH]") == 1 and noclass.eval("HOOK_CALLS[IMPACT_PATH]") is None
              and noclass.count("The parry class is not loaded yet") == 1 and noclass.eval("PROBE()") == DODGE_ONLY,
              "the parry class is not loaded yet: one line; a dodge gets the blue frame, a parry no red frame")
        noclass.do("OBJECTS[STANCE_PATH] = KEPT RETRY()")
        check(noclass.count("Hook set on the parry's impact") == 1 and noclass.eval("PROBE()") == MOD
              and noclass.eval("IMPACT_CASE()") == 1, "the class loads later: the hook is set, the parry part works")
        notready = Run(folder("notready"), "HOOK_FAILS[IMPACT_PATH] = 1")
        check(notready.count("The parry's impact is not ready yet (Was unable to register a hook") == 1
              and notready.eval("PROBE()") == DODGE_ONLY,
              "the parry class is found before its functions are ready: one line, no red frame yet")
        notready.do("RETRY()")
        check(notready.eval("HOOK_CALLS[IMPACT_PATH]") == 2 and notready.eval("PROBE()") == MOD,
              "the next check sets the hook")
        neverready = Run(folder("neverready"), "HOOK_FAILS[IMPACT_PATH] = 99")
        neverready.do("RETRY(10) MAP_LOAD()")
        check(neverready.eval("HOOK_CALLS[IMPACT_PATH]") == 5 and neverready.count("No hook on the parry's impact") == 1
              and not any("traceback" in line for line in neverready.log())
              and neverready.eval("PROBE()") == DODGE_ONLY,
              "RegisterHook on the impact fails 5 times: one line, no more tries, the dodge part works")
        unloaded = Run(folder("unloaded"))
        unloaded.do("OBJECTS[STANCE_PATH].valid = false RETRY(2)")
        check(unloaded.count("The parry class was unloaded") == 1 and unloaded.count("not loaded yet") == 0
              and unloaded.eval("PROBE()") == DODGE_ONLY,
              "the parry class was unloaded: one line, no red frame while its hook is gone")
        unloaded.do("OBJECTS[STANCE_PATH] = Object() RETRY()")
        check(unloaded.eval("HOOK_CALLS[IMPACT_PATH]") == 2 and unloaded.eval("PROBE()") == MOD,
              "the class is back: the hook is set again")
        travel = Run(folder("travel"))
        travel.do("COUNTERS = {} RED_PARRY() MAP_LOAD() IMPACT(W.ability, 8, Result(W.component.frames[8])) FIND_ALLS = 0")
        check(travel.eval("#COUNTERS") == 0 and travel.eval("QUERY(W.component, false)") == 8
              and travel.eval("FIND_ALLS") == 1 and travel.eval("HOOK_CALLS[IMPACT_PATH]") == 1,
              "a map load: the given frames are forgotten, the passive is searched again, the hooks stay")
        nocounter = Run(folder("nocounter"), "KEPT = OBJECTS[COUNTER_PATH] OBJECTS[COUNTER_PATH] = nil")
        check(nocounter.eval("IMPACT_CASE()") == 0 and not any("Error" in line for line in nocounter.log()),
              "the game's deflect library is not loaded: no counter, no error")
        nocounter.do("OBJECTS[COUNTER_PATH] = KEPT")
        check(nocounter.eval("IMPACT_CASE()") == 1, "the library is there at the next parry: the counter is called")
        old = Run(folder("old"), "LoopInGameThreadWithDelay = nil")
        check(old.eval("ASYNC_LOOPS") == 2 and old.count("no game-thread loops") == 1 and old.eval("PROBE()") == MOD,
              "a UE4SS without game-thread loops: LoopAsync, and a log line")

        # --- A callback that fails.
        broken = Run(folder("broken"))
        broken.do("World() W.component.frames = { [7] = Frame(BLUE, false) } "
                  "W.component.GetOwner = function() error('the game changed') end")
        check(broken.eval("QUERY(W.component, true)") == -1
              and sum("Error in the frame query" in line and "the game changed" in line for line in broken.log()) == 1,
              "an error in the query callback: the game's answer stays, one line")
        check(broken.eval("PROBE()") == GAME and broken.eval("#NATIVE_CALLS") == 1 and broken.count("Error") == 1,
              "after that the mod changes nothing more, and logs nothing more")
        fails = Run(folder("fails"))
        fails.do("COUNTER_THROWS = true")
        check(fails.eval("IMPACT_CASE()") == 0
              and sum("Error in the parry impact" in line and "the counter failed" in line for line in fails.log()) == 1,
              "an error in the impact callback: one line")
        fails.do("COUNTER_THROWS = false")
        check(fails.eval("PROBE()") == GAME and fails.eval("IMPACT_CASE()") == "no frame" and fails.count("Error") == 1,
              "after that the mod changes nothing more")

        # --- The settings files a player may have.
        folders = {}
        for case, content, _ in PLAYER_CONFIGS:
            if content == "wrong types":
                content = r.eval(f"""(function()
                    local lines = {{}}
                    for name, value in pairs(dofile({lua_path(CONFIG)})) do
                        lines[#lines + 1] = string.format("    [%q] = %s,", name, type(value) == "string" and "0" or '"wrong"')
                    end
                    return "return {{\\n" .. table.concat(lines, "\\n") .. "\\n}}\\n"
                end)()""")
            folders[case] = folder(f"player{len(folders)}", content)
        defaults = settings_lines(Run(folders["an empty or older config.lua"]).log())
        check(defaults == [shipped], f"config.lua ships exactly the defaults of main.lua ({defaults})")
        count = len(list(r.eval(f"dofile({lua_path(CONFIG)})").keys()))
        for case, _, expected in PLAYER_CONFIGS:
            run = Run(folders[case])
            probe = run.eval("PROBE()")
            run.do("CONFIG()")
            log = run.log()
            fine = (settings_lines(log) == defaults and len(run.g.LOOPS) == 2 and probe == MOD
                    and not any("Error" in line for line in log))
            if expected is None:
                fine = fine and not any("config.lua" in line for line in log)
            else:
                fine = fine and sum(expected in line for line in log) == (count if case.endswith("wrong types") else 1)
            check(fine, f"{case}: starts with the defaults, and both parts work"
                  + (f", logs '{expected}' once per setting" if case.endswith("wrong types")
                     else (f", logs '{expected}' once" if expected else ", no warning")))
            if not fine:
                for line in log:
                    print("      log: " + line)
        off = Run(folder("off", "return { Enable = false }\n"))
        check(len(off.g.LOOPS) == 2 and off.eval("HOOK_CALLS[QUERY_PATH]") == 1 and off.eval("HOOK_CALLS[IMPACT_PATH]") == 1
              and off.eval("PROBE()") == GAME and off.count("changes nothing until it is true") == 1,
              "Enable = false at start: the hooks and the loops are there (live settings), the game's own answers")
        off.write_config(shipped_text)
        off.do("CONFIG()")
        check(off.eval("PROBE()") == MOD, "Enable = true later (live): both parts work")

    print(f"{len(failures)} failed" if failures else "all checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
