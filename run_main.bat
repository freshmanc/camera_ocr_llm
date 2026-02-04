@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\Lenovo\anaconda3\envs\ocr310\python.exe" main.py
if errorlevel 1 pause
