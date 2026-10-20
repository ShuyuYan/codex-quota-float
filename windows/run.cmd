@echo off
rem SPDX-License-Identifier: GPL-3.0-only
rem ExecutionPolicy applies only to this PowerShell process.
if "%~1"=="" (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" --background
) else (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
)
exit /b %errorlevel%
