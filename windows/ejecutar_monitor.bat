@echo off
REM Lanzador diario de Crucible (lo usa el Programador de tareas de Windows)
cd /d "%~dp0.."
"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.12.exe" crucible_monitor.py >> monitor_log.txt 2>&1
