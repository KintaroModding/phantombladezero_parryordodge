-- Settings of Parry or Dodge. Change a value and save the file: the mod reads it again every 5 seconds, so a change
-- works without a game restart.
-- A file it cannot read (for example while it is saved) keeps the last settings.
-- A setting that this file does not have keeps its default, so an older copy of the file still works after an update.
return {
    Enable = true,       -- false: the mod changes nothing, the game as normal
    ParryRed = true,     -- true: a perfect parry also answers a red attack, with the game's counter
    DodgeBlue = true,    -- true: a perfect dodge also answers a blue attack, with the game's counter
    LogDetail = false,   -- true: ue4ss\UE4SS.log names every frame the mod gives and why one was not taken (for tests)
}
