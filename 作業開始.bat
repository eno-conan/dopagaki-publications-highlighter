@echo off
rem Double-click entry: open the local web page (upload PDFs, see progress). See docs/workflow.md.
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0app"
uv run python web.py
echo.
pause
