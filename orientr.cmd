@echo off
rem Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
rem Orientr. In a SOMA model folder: "orientr" opens the form; "orientr --help" lists the options.
rem It runs with the model's own Python (.soma\env); elsewhere with the Python of any SOMA model, so that
rem "orientr --status", "orientr --models" and "orientr --recent" work anywhere.
rem "--shortcut" (only from the Start menu and desktop shortcut, which starts minimized): when it cannot start, the
rem message is shown in a message box, since the minimized window closes at once.
setlocal
set "SHORTCUT="
if /i "%~1"=="--shortcut" set "SHORTCUT=1"
set "PY=.soma\env\Scripts\python.exe"
if exist "%PY%" goto run
set "PY="
for /d %%W in ("%LOCALAPPDATA%\soma\workspaces\*") do if not defined PY if exist "%%W\.soma\env\Scripts\python.exe" set "PY=%%W\.soma\env\Scripts\python.exe"
if not defined PY (
  echo orientr: no SOMA model found. Install SOMA and build a model first. 1>&2
  if defined SHORTCUT call :box "No built SOMA model found. Install SOMA, open a model and build it once with soma build, then try again."
  exit /b 2
)
:run
if not defined SHORTCUT (
  "%PY%" -I "%~dp0orientr.py" %*
  exit /b
)
rem the tool writes why it could not start into this file (its output stays on the console: the form needs one)
set "ORIENTR_ERROR_FILE=%TEMP%\orientr-start.txt"
del "%ORIENTR_ERROR_FILE%" 2>nul
"%PY%" -I "%~dp0orientr.py"
if errorlevel 1 (
  if exist "%ORIENTR_ERROR_FILE%" (call :box "" "%ORIENTR_ERROR_FILE%") else call :box "Orientr could not start. Open a terminal and type orientr to see why."
)
del "%ORIENTR_ERROR_FILE%" 2>nul
exit /b

:box
rem a message box with the text %1, or with the contents of the file %2 (handed over as variables: no quoting trouble)
set "BOX_TEXT=%~1"
set "BOX_FILE=%~2"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName PresentationFramework; $t = if ($env:BOX_FILE) { (Get-Content -Raw -Encoding UTF8 -LiteralPath $env:BOX_FILE).Trim() } else { $env:BOX_TEXT }; if (-not $t) { $t = 'Orientr could not start.' }; [void][System.Windows.MessageBox]::Show($t, 'Orientr', 'OK', 'Warning')"
exit /b
