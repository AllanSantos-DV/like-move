@echo off
rem Inicia o Home Awake sem janela (conhost --headless). Para parar: 4-parar.cmd
start "" conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0home-awake.ps1" -Executar
echo Home Awake iniciado. Ele so mantem a tela acordada na rede de casa cadastrada.
echo Registro: %LOCALAPPDATA%\like-move-home-awake\home-awake.log
pause
