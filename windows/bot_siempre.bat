@echo off
REM Bot de Crucible 24/7: si se cae, se reinicia a los 10 segundos
cd /d "%~dp0.."
:bucle
echo %date% %time% arrancando bot >> bot_log.txt
"%LOCALAPPDATA%\Microsoft\WindowsApps\python3.12.exe" -u crucible_bot.py >> bot_log.txt 2>&1
timeout /t 10 /nobreak > nul
goto bucle
