@echo off
cd /d "%~dp0.."
"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.12.exe" resumen_semanal.py >> resumen_log.txt 2>&1
