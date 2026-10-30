@echo off
rem Mostra se, na rede de casa, a tela deixou de bloquear de verdade (autoverificacao do 3-iniciar.cmd).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0home-awake.ps1" -Verificar
pause
