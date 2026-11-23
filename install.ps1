# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
# Orientr: one-time setup for this Windows user (no administrator rights needed).
# Run it again after moving the folder: it points everything to where it is now.
#   1. the "orientr" command: this folder in your user PATH. Every other Orientr folder is taken out (an older
#      version unpacked elsewhere would otherwise still answer to "orientr"), and so are removed old locations
#   2. an "Orientr" shortcut in the Start menu and on the desktop
#   3. a check that SOMA (with a built model) and Bambu Studio 2.9 or newer are there; "Ready" only when all is found
#   4. Bambu Studio's profiles read into the tool's cache (about 2 minutes once), so the form opens at once
$ErrorActionPreference = 'Stop'
$tool = $PSScriptRoot
$problems = 0
Write-Host "Orientr in $tool`n"

# 1. PATH, read and written as it is in the registry: [Environment]::SetEnvironmentVariable would fill in every
#    %VARIABLE% in it and save it as plain text, so entries like %USERPROFILE%\bin would stop following the variable
$envKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$path = [string]$envKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$parts = @($path -split ';' | Where-Object { $_ })
$others = @()
$keep = @($parts | Where-Object {
    $p = [Environment]::ExpandEnvironmentVariables($_).Trim().Trim('"').TrimEnd('\')   # "quoted" entries too
    $stale = -not (Test-Path -LiteralPath $p) -and ((Split-Path $p -Leaf) -eq 'orientr')
    # another copy of Orientr: orientr.cmd and orientr.py
    $other = $p -ne $tool.TrimEnd('\') -and
             (Test-Path -LiteralPath (Join-Path $p 'orientr.cmd')) -and (Test-Path -LiteralPath (Join-Path $p 'orientr.py'))
    if ($other) { $script:others += $p }
    -not $stale -and -not $other -and $p -ne $tool.TrimEnd('\')
})
foreach ($o in $others) {
    Write-Host "[ok] 'orientr' command: other Orientr folder taken out of your PATH: $o"
}
$new = (@($keep) + $tool) -join ';'
if ($new -ne $path) {
    $envKey.SetValue('Path', $new, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    # tell Windows the environment changed (new terminals and shortcuts see it): setting and removing a helper
    # variable the .NET way sends that message
    [Environment]::SetEnvironmentVariable('ORIENTR_REFRESH', '1', 'User')
    [Environment]::SetEnvironmentVariable('ORIENTR_REFRESH', $null, 'User')
    Write-Host "[ok] 'orientr' command: points to this folder (restart SOMA and open a new terminal to use it)"
} else {
    Write-Host "[ok] 'orientr' command: already points to this folder"
}

# 2. shortcuts: orientr.cmd from the user folder (not a model folder, so it starts with the model list). It opens
#    Orientr in its own window and ends at once, so its own window closes again: started minimized, it is
#    barely seen. Made again on every run, so they follow the folder when it moves.
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    try {
        $lnk = $shell.CreateShortcut((Join-Path $dir 'Orientr.lnk'))
        $lnk.TargetPath = Join-Path $tool 'orientr.cmd'
        $lnk.Arguments = '--shortcut'                       # orientr.cmd: a message box when it cannot start
        $lnk.WorkingDirectory = $HOME
        # A new file name for every new icon: Windows keeps icons by path and would go on showing the old one
        $lnk.IconLocation = (Join-Path $tool 'orientr-logo.ico') + ',0'
        $lnk.WindowStyle = 7                                # minimized
        $lnk.Description = 'Orientr: a Bambu Studio project from a SOMA model'
        $lnk.Save()
        Write-Host "[ok] shortcut: $($lnk.FullName)"
    } catch {
        Write-Host "[!!] shortcut in ${dir}: $($_.Exception.Message)"
        $problems++
    }
}

# 3. checks: a SOMA model that was built (it has its own Python, which the tool runs with), and Bambu Studio 2.9+
$soma = Join-Path $env:LOCALAPPDATA 'soma\workspaces'
$built = @(Get-ChildItem (Join-Path $soma '*\.soma\env\Scripts\python.exe') -ErrorAction SilentlyContinue)
if ($built.Count) {
    Write-Host "[ok] SOMA: $($built.Count) built model(s) in $soma"
} elseif (Test-Path $soma) {
    Write-Host "[!!] SOMA: no built model yet in ${soma}: open a model in SOMA and build it once (soma build)"
    $problems++
} else {
    Write-Host "[!!] SOMA not found ($soma): install SOMA and build a model first"
    $problems++
}
$studio = if ($env:BAMBU_STUDIO) { $env:BAMBU_STUDIO } else { 'C:\Program Files\Bambu Studio\bambu-studio.exe' }
if (-not $env:BAMBU_STUDIO -and -not (Test-Path -LiteralPath $studio)) {
    # installed elsewhere: where its installer recorded it (the tool itself looks the same way)
    $keys = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    $hit = Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { "$($_.DisplayName)" -like 'Bambu Studio*' } |
        ForEach-Object {
            if ($_.DisplayIcon) { ("$($_.DisplayIcon)" -split ',')[0].Trim('"') }
            if ($_.InstallLocation) { Join-Path "$($_.InstallLocation)".Trim('"') 'bambu-studio.exe' }
        } | Where-Object { $_ -and (Split-Path $_ -Leaf) -eq 'bambu-studio.exe' -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
    if ($hit) { $studio = $hit }
}
if (Test-Path -LiteralPath $studio) {
    $v = (Get-Item -LiteralPath $studio).VersionInfo
    if ($v.FileMajorPart -gt 2 -or ($v.FileMajorPart -eq 2 -and $v.FileMinorPart -ge 9)) {
        Write-Host "[ok] Bambu Studio $($v.FileVersion): $studio"
    } elseif ($v.FileMajorPart -eq 0) {                       # no version in the file: let the form's status say it
        Write-Host "[ok] Bambu Studio found (version unknown): $studio"
    } else {
        Write-Host "[!!] Bambu Studio $($v.FileVersion) is too old: update it to 2.9 or newer"
        $problems++
    }
} else {
    Write-Host "[!!] Bambu Studio not found at ${studio}: install it, or set BAMBU_STUDIO to its bambu-studio.exe"
    $problems++
}
# 4. Bambu Studio's presets read once now (about 2 minutes), so the form opens at once the first time. The tool says
#    "about 2 minutes" itself, and only when they are not in its cache yet (installed again: they usually are)
if (-not $problems) {
    & $built[0].FullName -I (Join-Path $tool 'orientr.py') --warm-profiles
    if ($LASTEXITCODE) {                                    # not fatal: the form reads them itself and says so
        Write-Host "[--] Bambu Studio's presets not read now: the first start of the form does it (about 2 minutes)"
    } else {
        Write-Host "[ok] Bambu Studio's presets read"
    }
}
if ($problems) {
    Write-Host "`nNot ready yet: fix the lines with [!!] above, then run install.cmd again."
} else {
    Write-Host "`nReady. Restart SOMA, then type orientr in a model's terminal (or use the Orientr shortcut)."
}
