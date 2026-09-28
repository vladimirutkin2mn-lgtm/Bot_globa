@echo off
setlocal
cd /d %~dp0
py -m pip install -r requirements_fsa.txt
if errorlevel 1 exit /b 1
py enrich_fsa_1000.py
if errorlevel 1 exit /b 1
echo.
echo Done. Results: output_fsa_1000\fsa_1000.csv
pause
