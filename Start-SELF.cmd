@echo off
setlocal
chcp 65001 >nul
title SELF Desktop Service
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-ReconstructionDesktop.ps1"
set "SELF_START_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %SELF_START_EXIT%
