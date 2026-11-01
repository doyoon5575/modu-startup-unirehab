@echo off
chcp 65001 > nul
title UniRehab — 음성·발화 분석 및 언어재활 지원 플랫폼
echo ============================================================
echo   🏥 UniRehab - 음성·발화 분석 및 언어재활 지원 플랫폼 가동기
echo   접속 주소: http://localhost:8000
echo ============================================================
echo.
start http://localhost:8000
cd /d "%~dp0wrks-conv21321"
python app.py
pause

