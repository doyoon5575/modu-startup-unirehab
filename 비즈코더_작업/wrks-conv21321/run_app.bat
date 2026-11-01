@echo off
chcp 65001 > nul
title UniRehab — 음성·발화 분석 및 언어재활 지원 플랫폼
echo ============================================================
echo   🏥 UniRehab - 로컬 서버 가동 중 (http://localhost:8000)
echo ============================================================
echo.
start http://localhost:8000
python app.py
pause

