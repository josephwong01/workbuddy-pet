@echo off
REM Launch Desktop Pet (WorkBuddy-pet)
REM Uses the project's venv python so tkinter + Pillow are available.
cd /d "%~dp0"
"C:/Users/win/WorkBuddy/2026-08-25-11-10-41/WorkBuddy-pet/.venv/Scripts/python.exe" scripts\pet_launch.py
