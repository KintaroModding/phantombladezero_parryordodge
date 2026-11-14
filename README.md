# Parry or Dodge

A perfect parry also answers red attacks, and a perfect dodge also answers blue attacks, each with the game's own counter. Each part has its own switch in config.lua, live in game.

A [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) Lua mod for Phantom Blade Zero (Unreal Engine 5.7), made with
game version `CL-302256_JKS-17280` and UE4SS `v3.0.1-1195-g1ceefac8`, tested in game with UE4SS `v4.0.0` (1.0, 2026-11-13). This README is for developers; what the mod does and
how to install it are in [openmods.md](openmods.md), the mod page on [openmods](https://openmods.nexus).

## How it works

In the game a blue attack wants a perfect parry and a red attack wants a perfect dodge. When the player parries or
dodges, the game asks `DeflectComponent:GetNearestValidReceivedFrame` which enemy attack frame the move can answer;
its `IsDodge` parameter names the kind of frame. `Scripts/main.lua` hooks that function (`RegisterHook` with a
callback after the function, `AfterQuery`). When the game found no frame, the mod asks the same function for the other
kind, with the same angle, time and current handle (`Supplement`). It takes that frame only when its attack is a blue
one for a dodge (`DodgeBlue`) or a red one for a parry (`ParryRed`), copies the game's own frame struct into the
function's output and gives back its handle. The timing, the range and the choice of the counter stay the game's.

| | Game | Mod |
|---|---|---|
| Perfect dodge of a blue attack | no frame for the dodge | the blue attack's frame (`DodgeBlue`) |
| Perfect parry of a red attack | no frame for the parry | the red attack's frame, then the game's counter (`ParryRed`) |

Enemies ask the same function, so the mod changes only the answer for the local player's component (a
`PBZCharacter_Player` with the local player's controller). A red frame goes to a parry only while the parry key is
down and the perfect window of the player's deflect passive (`BP_PlayerDeflectPassive_C`: `Stance Key Down`,
`Perfect Window`) is open, and only when the attack hits inside that window (`PerfectDeadline`): a held block gets
nothing.

A perfect dodge starts its counter by itself. For a parried red attack the mod does what the game does after a blue
one: a second hook on the parry's `BP_StanceAction_Base_Player_C:On Impact` (`AfterImpact`, `CounterRed`) waits for
the impact of a frame the mod gave. When its result is `Deflect.Result.Perfect`, the attack and the hit time are the
frame's, and the game did not prepare that frame itself, the mod writes the result into the component's
`PerfectDodgeResultData` and calls `Dodge After Deflect` of the game's `BPL_DeflectUtils`. Without the hook on the
impact, no red frame goes to a parry.

The hooks are set on the game thread (`SetHooks`): at start, after each map load and every 2 seconds while one is
missing (the parry's Blueprint class loads some seconds after the game's start). The mod's own call of the query runs
the hook again; the `busy` flag keeps that call out of the callback. After an error in one of the two callbacks the
mod changes nothing more until the game starts again (`Stop`). The search for the player's deflect passive
(`FindAllOf`) runs at most once per second while none is found, and the found one is kept while it is valid.

## Deploy and test

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1     # copy the mod folder into the game's ue4ss\Mods
python tests\test_main.py                                 # offline test of main.lua (needs lupa)
```

`deploy.ps1` copies `src\phantombladezero_parryordodge\` to `<game folder>\platform\steam\ue4ss\Mods\phantombladezero_parryordodge\`. The game
folder is `$env:UE5_GAMES_DIR\PBZ`; `-GameDir` or `-ModsDir` override it. The mod folder holds
`enabled.txt`, so UE4SS starts it without an entry in `mods.txt`. An existing `Scripts\config.lua` in the game stays
(the tester's settings); `-ResetConfig` copies the shipped one. UE4SS loads Lua mods at game start. The mod writes
its lines into `ue4ss\UE4SS.log`, for example `[Parry or Dodge] 1.0 loaded.`

`tests\test_main.py` runs `main.lua` in Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) with mocks of the UE4SS
functions that the script uses. It finds syntax and logic errors before a game start.

Versioning: every change raises the second number (1.0 -> 1.1) in `mod.json` and in `main.lua`:
`python scripts\bump_version.py`.

## Settings

`Scripts/config.lua` holds the player's settings (`Enable`, `ParryRed`, `DodgeBlue`, `LogDetail`), `DEFAULTS` in
`main.lua` every setting with its default. The mod reads the file at start and again every 5 seconds (`ReadConfig`):
a changed file is used at once, a broken or half-saved one keeps the last settings, a missing one means the defaults.
Both hooks are set also with `Enable = false`, so every switch works without a game restart. `LogDetail = true` logs
every frame the mod gives and, once each, the reason a frame was not taken; without it the first 20 frames and the
first 20 counter calls are logged. Players and mod managers keep their own `config.lua` across updates, so a new
`main.lua` can meet an older file: a setting that the file lacks, or has with another type, keeps its default, and
the log says so (`ParseConfig`). Add each setting to both files with the same value, and read it only from
`Settings`, never as `config.X or default` (for a true/false setting, `false or true` is true). `tests\test_main.py`
checks that `config.lua` ships exactly the defaults, and runs `main.lua` with a missing, empty, broken and wrong
`config.lua`.

## Project layout

```
src/phantombladezero_parryordodge/   The UE4SS mod folder: Scripts/main.lua, Scripts/config.lua, enabled.txt
tests/test_main.py    Offline test of main.lua with mocks of UE4SS and the game
docs/                 Cover and screenshots
scripts/              bump_version.py
deploy.ps1            Copies the mod folder into the game's ue4ss\Mods
mod.json              Name, version, game, engine and UE4SS version
```

## License

MIT, see [LICENSE](LICENSE).
