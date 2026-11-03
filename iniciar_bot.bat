@echo off
chcp 65001 >nul
title Caçador de Preços - Discord Bot
cd /d "%~dp0"
echo ==========================================================
echo   Iniciando o Bot Cacador de Precos no Discord...
echo   Para DESLIGAR o bot, pressione Ctrl + C ou feche a janela.
echo ==========================================================
echo.
.\.venv\Scripts\python.exe -m price_tracker.discord_bot
pause
