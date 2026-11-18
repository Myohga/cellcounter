@echo off
rem Updates cellcounter: git pull, then pip install -e . in the conda environment 'cellcounter'.
rem Keep this file ASCII-only with CRLF line endings (see launch.bat).
setlocal
cd /d "%~dp0"
set "ENV_NAME=cellcounter"
call :find_conda
if not defined CONDA_ROOT echo FAILED: conda was not found. Run install.bat first.
if not defined CONDA_ROOT goto fail
call "%CONDA_ROOT%\condabin\conda.bat" activate %ENV_NAME%
if errorlevel 1 echo FAILED: the conda environment "%ENV_NAME%" was not found. Run install.bat first.
if errorlevel 1 goto fail

rem git pull may rewrite this file while it runs, and cmd.exe reads a .bat file as it goes.
rem So everything from the pull onward is one block, which cmd.exe reads whole before running it.
rem Do not use goto or call :label inside it: they would read the rewritten file.
(
    echo Getting the new version...
    git pull
    if errorlevel 1 (
        echo.
        echo FAILED: git pull. Read the messages above and README.md, then run update.bat again.
        pause
        exit /b 1
    )
    echo.
    echo Installing new Python packages, if any...
    python -m pip install -e .
    if errorlevel 1 (
        echo.
        echo FAILED: pip install. Read the messages above and README.md, then run update.bat again.
        pause
        exit /b 1
    )
    echo.
    echo Done. cellcounter is up to date.
    pause
    exit /b 0
)

:fail
pause
exit /b 1

:find_conda
rem Sets CONDA_ROOT to an installed conda: one that is already on PATH, or a usual place.
rem The same as in install.bat.
set "CONDA_ROOT="
if defined CONDA_EXE call :use_conda_root "%CONDA_EXE%\..\.."
for /f "delims=" %%P in ('where conda.bat 2^>nul') do call :use_conda_root "%%~dpP.."
for %%D in ("%USERPROFILE%\miniforge3" "C:\miniforge3" "%LOCALAPPDATA%\miniforge3" "%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "C:\ProgramData\miniforge3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do call :use_conda_root "%%~D"
goto :eof

:use_conda_root
if defined CONDA_ROOT goto :eof
if exist "%~1\condabin\conda.bat" set "CONDA_ROOT=%~f1"
goto :eof
