@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 用带 numpy + Pillow 的解释器，否则高程瓦片无法渲染
"C:\Program Files\Python311\python.exe" -X utf8 app.py
pause
