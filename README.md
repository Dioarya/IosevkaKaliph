# IosevkaKaliph

IosevkaKaliph is my own configuration for Iosevka.

This repository holds raw IosevkaKaliph fonts, nerdfont patched fonts,
as well as my own Cell variants.

## Configuration file (private-build-plans.toml)

fully lost it... I could probably recreate it but I don't really see the point.
I changed some variants here and there, mostly with the numbers, but probably
also with the letters themselves, but to less of a degree for the letters.

## Cell variant

My cell variants mean that if the default font (non condensed versions, non cell
versions) were rendered at cellWidth = 0.5, cellHeight = 1.0, they should look
exactly the same as the Cell versions rendered at the default cellWidth = 0.6,
cellHeight = 1.2 in Windows Terminal and in OpenConsole.exe. (with Atlas rendering)

Basically, Cell rendered at cellWidth = 0.6, cellHeight = 1.2 looks exactly the
same as non-Cell rendered at cellWidth = 0.5, cellHeight = 1.0 (with Atlas rendering)

For OpenConsole.exe, I ripped mine directly from the Windows Terminal files.
To change it from GDI rendering to Atlas rendering, set "HKCU:\Console"
key UseDx to 1.

Here is powershell code to do exactly that.

```pwsh
Set-ItemProperty -Path 'HKCU:\Console' -Name UseDx -Type DWord -Value 1
```

GDI rendering cuts off at the top of the font, while Atlas doesn't.
