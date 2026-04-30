@echo off
set "PROJECT_DIR=%~dp0"
set "ORIGINAL_DIR=%CD%"
cd /d "%PROJECT_DIR%"
uv run python main.py
cd /d "%ORIGINAL_DIR%"
