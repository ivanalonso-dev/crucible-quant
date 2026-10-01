@echo off
REM Arranca el bot de suscripciones de Crucible (dejar esta ventana abierta)
cd /d "%~dp0.."
"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.12.exe" crucible_bot.py
pause
