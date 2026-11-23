# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
# Orientr: undo what install.ps1 did, for this Windows user (no administrator rights needed).
#   1. this folder out of your user PATH (the "orientr" command)
#   2. the "Orientr" shortcuts in the Start menu and on the desktop (only when they point to this folder)
#   3. Bambu Studio's "single instance" setting switched off again, but only when this tool switched it on
#      (for "Background Bambu Studio"); one you switched on yourself stays on
# Kept: this folder itself, your settings in %LOCALAPPDATA%\orientr, bambu.json in your models, and Bambu Studio's
# other settings. Delete those yourself if you want.
$ErrorActionPreference = 'Stop'
$tool = $PSScriptRoot.TrimEnd('\')
Write-Host "Orientr in $tool`n"

# 1. PATH, read and written as it is in the registry: [Environment]::SetEnvironmentVariable would fill in every
#    %VARIABLE% in it and save it as plain text, so entries like %USERPROFILE%\bin would stop following the variable
$envKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$path = [string]$envKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$parts = @($path -split ';' | Where-Object { $_ })
$keep = @($parts | Where-Object { [Environment]::ExpandEnvironmentVariables($_).Trim().Trim('"').TrimEnd('\') -ne $tool })
if ($keep.Count -ne $parts.Count) {
    $envKey.SetValue('Path', ($keep -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    # tell Windows the environment changed: setting and removing a helper variable the .NET way sends that message
    [Environment]::SetEnvironmentVariable('ORIENTR_REFRESH', '1', 'User')
    [Environment]::SetEnvironmentVariable('ORIENTR_REFRESH', $null, 'User')
    Write-Host "[ok] 'orientr' command: removed from your PATH"
} else {
    Write-Host "[--] 'orientr' command: this folder was not in your PATH"
}

# 2. shortcuts
$shell = New-Object -ComObject WScript.Shell
foreach ($file in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) |
         ForEach-Object { Join-Path $_ 'Orientr.lnk' }) {
    if (-not (Test-Path -LiteralPath $file)) { continue }
    $lnk = $shell.CreateShortcut($file)
    if ($lnk.TargetPath -and (Split-Path $lnk.TargetPath -Parent).TrimEnd('\') -eq $tool) {
        Remove-Item -LiteralPath $file
        Write-Host "[ok] shortcut removed: $file"
    } else {
        Write-Host "[--] shortcut $file points elsewhere, left as it is"
    }
}

# 3. Bambu Studio's "single instance": the tool decides (it knows whether it switched it on) with a SOMA model's Python
$again = $false
$py = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'soma\workspaces\*\.soma\env\Scripts\python.exe') -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if ($py -and (Test-Path -LiteralPath (Join-Path $tool 'orientr.py'))) {
    $result = (& $py -I (Join-Path $tool 'orientr.py') --restore-studio-setting 2>&1 | Select-Object -Last 1) -as [string]
    switch -Wildcard ($result) {
        'restored'    { Write-Host "[ok] Bambu Studio: 'single instance' switched off again (as before Orientr)" }
        'untouched'   { }                                     # never switched by this tool: nothing to say
        'already-off' { Write-Host "[ok] Bambu Studio: 'single instance' is off already" }
        'studio-open' { Write-Host "[!!] Bambu Studio is open: close it and run uninstall.cmd again to switch its 'single instance' setting back off"
                        $again = $true }
        default       { Write-Host "[!!] Bambu Studio's 'single instance' setting left as it is ($result); switch it off in Bambu Studio's preferences if you want" }
    }
} elseif (Get-ChildItem (Join-Path $env:APPDATA 'BambuStudio') -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -eq 'BambuStudio.conf.orientr.bak' }) {
    # the tool's backup: it switched the setting on
    Write-Host "[!!] Bambu Studio's 'single instance' setting left on (no SOMA model to run the tool with): switch it off in Bambu Studio's preferences if you want"
}

if ($again) {
    Write-Host "`nAlmost done: close Bambu Studio and run uninstall.cmd again (or delete $tool now and switch the setting off in Bambu Studio)."
} else {
    Write-Host "`nDone. You can now delete $tool (and $env:LOCALAPPDATA\orientr for your settings)."
}
