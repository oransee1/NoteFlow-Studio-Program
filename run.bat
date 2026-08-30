@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo NoteFlow Studio를 실행합니다...
python main.py
if errorlevel 1 (
    echo.
    echo 오류가 발생했습니다.
    pause
)
