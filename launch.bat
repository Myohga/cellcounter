@echo off
rem Opens the cellcounter window. Uses the conda environment 'cellcounter' when conda is available.
rem Keep this file ASCII-only with CRLF line endings. cmd.exe reads .bat files in the system
rem code page, so UTF-8 Japanese text or LF-only lines break the commands that follow.
cd /d "%~dp0"
where conda >nul 2>nul
if not errorlevel 1 call conda activate cellcounter
python -m cellcounter %*
if errorlevel 1 pause
