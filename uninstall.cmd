@echo off
rem Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
rem Orientr: undo the setup (double-click). See uninstall.ps1 for what it does.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
pause
