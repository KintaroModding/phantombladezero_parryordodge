# Parry or Dodge

Perfect-parry red attacks and perfect-dodge blue attacks, each with the game's own counter. Each part has its own switch in config.lua, live in game.

## What it does

In the game a blue attack wants a perfect parry and a red attack wants a perfect dodge. With this mod you choose:

- A perfect parry also answers a red attack, and the game's counter follows (`ParryRed`).
- A perfect dodge also answers a blue attack, and the game's counter follows (`DodgeBlue`).
- The timing, the range and the choice of the counter stay the game's. Normal and power attacks are not changed.
- A held block is not a perfect parry: a red attack still needs the parry key pressed at the right moment.
- Each part has its own switch, and a changed switch works without a game restart.

It is a UE4SS Lua script: when the game looks for the attack that your parry or dodge can answer and finds none, the
mod gives it the attack of the other colour. It replaces no game file and writes nothing into your save.

## Screenshots

![Parry or Dodge](docs/cover.png)

## How to install

1. Install UE4SS for Phantom Blade Zero, for example [UE4SS](https://github.com/KintaroModding/ue4ss) (its zip
   `phantombladezero_ue4ss_<version>.zip`: the official UE4SS build with a config that makes it run in this game).
2. Download the zip of the latest release on GitHub (`phantombladezero_parryordodge_<version>.zip`).
3. Unpack it into the game folder `platform\steam\`, next to the game's exe. It adds the folder
   `ue4ss\Mods\phantombladezero_parryordodge\` (with the file `enabled.txt`, UE4SS starts it by itself).
4. Start the game.

To check that it runs: `platform\steam\ue4ss\UE4SS.log` has the line `[Parry or Dodge] <version> loaded.`

To update the mod, replace the folder with the one of the new release; to keep your settings, put your old
`Scripts\config.lua` back (a setting that it does not have keeps its default). To remove it, delete the folder
`ue4ss\Mods\phantombladezero_parryordodge\`.

## How to use

Nothing to do: parry a red attack at the right moment, or dodge a blue attack at the right moment. `UE4SS.log` names
each attack the mod gave to your move in a line that starts with `[Parry or Dodge] Red attack:` or
`[Parry or Dodge] Blue attack:`.

## Settings

The settings are in `platform\steam\ue4ss\Mods\phantombladezero_parryordodge\Scripts\config.lua`. Open it with a text
editor, change a value and save: the mod reads the file every 5 seconds, so the game does not need a restart. A file
it cannot read (for example a typo) keeps the last settings. `UE4SS.log` shows the settings in use in the line
`[Parry or Dodge] Settings: ...`, and names each value it could not use.

| Setting | Default | What it does |
|---|---|---|
| `Enable` | `true` | `false`: the mod changes nothing, the game as normal |
| `ParryRed` | `true` | `true`: a perfect parry also answers a red attack, with the game's counter |
| `DodgeBlue` | `true` | `true`: a perfect dodge also answers a blue attack, with the game's counter |
| `LogDetail` | `false` | `true`: `UE4SS.log` names every attack the mod gives to your move and why one was not taken (for tests) |

## Compatibility

- Game version: Steam build 26367565 (`CL-302256_JKS-17280`).
- Tested with UE4SS `v4.0.0`.
- [Witch Time](https://github.com/KintaroModding/phantombladezero_witchtime),
  [Heaven or Hell](https://github.com/KintaroModding/phantombladezero_heavenorhell) and
  [Live by the Blade](https://github.com/KintaroModding/phantombladezero_livebytheblade) react to a perfect parry and
  to the game's perfect-dodge counter. With this mod both come on more attacks (a perfect parry of a red attack, a
  perfect dodge of a blue attack), so their effects can come more often. Not tested together yet.
- A mod that changes the perfect parry or dodge windows, for example
  [Easier Parry and Dodge](https://github.com/KintaroModding/phantombladezero_easierparryanddodge), also changes when
  this mod applies: it uses the game's windows.
- Another mod that changes the same game function (the deflect component's frame query) can clash with this one.

## Known issues

None yet.

## How to build

There is nothing to build: `src\phantombladezero_parryordodge\Scripts\main.lua` is the mod. `tests\test_main.py` runs the script
outside the game with Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) and mocks of UE4SS:
`python tests\test_main.py`. `README.md` has the details.

## Credits

Made by Kintaro. MIT license: you may use, change and share this mod. UE4SS is made by the
[UE4SS-RE team](https://github.com/UE4SS-RE/RE-UE4SS). Phantom Blade Zero belongs to its makers.
