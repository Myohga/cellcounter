@echo off
rem cellcounter の画面を開く。conda が使えるなら cellcounter 環境に切り替えてから起動する。
cd /d "%~dp0"
where conda >nul 2>nul && call conda activate cellcounter
python -m cellcounter %*
if errorlevel 1 pause
