@echo off
rem Cadastra o Wi-Fi conectado AGORA como rede de casa e grava cadastro.txt nesta pasta.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0home-awake.ps1" -Cadastrar
pause
