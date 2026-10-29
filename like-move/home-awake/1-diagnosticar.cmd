@echo off
rem Somente leitura: mostra o que bloqueia a tela e grava diagnostico.txt nesta pasta.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0home-awake.ps1" -Diagnosticar
pause
