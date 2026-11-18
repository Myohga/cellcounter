@echo off
rem Installs cellcounter on a Windows PC, the same as steps 1-6 of README.md:
rem Miniforge, the conda environment 'cellcounter', the source (git clone to C:\cellcounter),
rem the GPU version of PyTorch when an NVIDIA GPU is present, and the Python packages.
rem Safe to run again: steps that are already done are skipped.
rem
rem Keep this file ASCII-only with CRLF line endings. cmd.exe reads .bat files in the system
rem code page, so UTF-8 Japanese text or LF-only lines break the commands that follow.
rem This file is also downloaded on its own from GitHub, so git stores it as it is, with CRLF
rem (.gitattributes: install.bat -text).
setlocal
set "REPO_URL=https://github.com/Myohga/cellcounter.git"
set "MINIFORGE_URL=https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"
set "TORCH_GPU_URL=https://download.pytorch.org/whl/cu128"
set "ENV_NAME=cellcounter"
set "APP_DIR=C:\cellcounter"
rem Started from inside a copy of cellcounter (C:\cellcounter\install.bat): use that copy.
if exist "%~dp0pyproject.toml" if exist "%~dp0cellcounter\__init__.py" for %%I in ("%~dp0.") do set "APP_DIR=%%~fI"

echo.
echo [1/6] Miniforge - Python and conda
set "STEP=download and install Miniforge"
call :find_conda
if not defined CONDA_ROOT call :install_miniforge
if not defined CONDA_ROOT goto fail
set "CONDA_BAT=%CONDA_ROOT%\condabin\conda.bat"
echo Using conda in "%CONDA_ROOT%"
rem Lets launch.bat find conda: adds conda to every new cmd.exe window of this user.
set "STEP=run conda init cmd.exe"
call "%CONDA_BAT%" init cmd.exe >nul
if errorlevel 1 goto fail

echo.
echo [2/6] Conda environment "%ENV_NAME%"
set "STEP=create the conda environment"
call "%CONDA_BAT%" activate %ENV_NAME% >nul 2>nul
if not errorlevel 1 goto env_ready
call "%CONDA_BAT%" create -n %ENV_NAME% -c conda-forge --override-channels python=3.12 git -y
if errorlevel 1 goto fail
call "%CONDA_BAT%" activate %ENV_NAME%
if errorlevel 1 goto fail
:env_ready
set "STEP=use Python 3.12 or later in the environment"
python -c "import sys; sys.exit(sys.version_info[:2] < (3, 12))"
if errorlevel 1 goto fail
set "STEP=install git in the environment"
where git >nul 2>nul
if errorlevel 1 call "%CONDA_BAT%" install -n %ENV_NAME% -c conda-forge --override-channels git -y
where git >nul 2>nul
if errorlevel 1 goto fail

echo.
echo [3/6] cellcounter itself, in "%APP_DIR%"
set "STEP=get cellcounter with git clone"
if exist "%APP_DIR%\pyproject.toml" goto source_ready
git clone "%REPO_URL%" "%APP_DIR%"
if errorlevel 1 goto fail
:source_ready
echo To update cellcounter later, double-click update.bat in "%APP_DIR%".

echo.
echo [4/6] GPU version of PyTorch - only for NVIDIA GPUs
set "STEP=install the GPU version of PyTorch"
set "HAS_GPU="
where nvidia-smi >nul 2>nul && set "HAS_GPU=1"
if not defined HAS_GPU echo No NVIDIA GPU found. Skipped: cellcounter will use the CPU.
if not defined HAS_GPU goto torch_ready
python -c "import sys, torch; sys.exit(torch.version.cuda is None)" >nul 2>nul
if not errorlevel 1 echo Already installed.
if not errorlevel 1 goto torch_ready
rem pip keeps a CPU build of PyTorch that is already there, so remove it first.
python -m pip uninstall -y torch torchvision >nul 2>nul
python -m pip install torch torchvision --index-url %TORCH_GPU_URL%
if errorlevel 1 goto fail
:torch_ready

echo.
echo [5/6] Python packages - napari, Cellpose and others. This takes 10-30 minutes.
set "STEP=install the Python packages with pip"
python -m pip install -e "%APP_DIR%"
if errorlevel 1 goto fail

echo.
echo [6/6] Check, and a shortcut on the desktop
set "STEP=start cellcounter"
python -c "import cellcounter, torch; print('cellcounter', cellcounter.__version__, '/ GPU:', 'yes' if torch.cuda.is_available() else 'no')"
if errorlevel 1 goto fail
set "GPU_WARNING="
if defined HAS_GPU python -c "import sys, torch; sys.exit(not torch.cuda.is_available())" || set "GPU_WARNING=1"
powershell -NoProfile -Command "$l = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\cellcounter.lnk'); $l.TargetPath = '%APP_DIR%\launch.bat'; $l.WorkingDirectory = '%APP_DIR%'; $l.Save()" >nul 2>nul
if errorlevel 1 echo Could not make a desktop shortcut. Make one from launch.bat by hand.
if not errorlevel 1 echo Made a shortcut "cellcounter" on the desktop.

echo.
echo ============================================================
echo  Done. To start cellcounter, double-click "cellcounter" on
echo  the desktop, or "%APP_DIR%\launch.bat".
if defined GPU_WARNING echo.
if defined GPU_WARNING echo  WARNING: An NVIDIA GPU was found, but PyTorch cannot use it.
if defined GPU_WARNING echo  Update the NVIDIA driver, restart the PC, and run install.bat again.
if defined GPU_WARNING echo  Until then, cellcounter uses the CPU.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ============================================================
echo  FAILED: could not %STEP%.
echo  Read the messages above, and the table for install.bat
echo  in README.md. After fixing the problem, run install.bat
echo  again: the steps that are already done are skipped.
echo ============================================================
pause
exit /b 1

rem ---- Subroutines ----

:find_conda
rem Sets CONDA_ROOT to an installed conda: one that is already on PATH, or a usual place.
set "CONDA_ROOT="
if defined CONDA_EXE call :use_conda_root "%CONDA_EXE%\..\.."
for /f "delims=" %%P in ('where conda.bat 2^>nul') do call :use_conda_root "%%~dpP.."
for %%D in ("%USERPROFILE%\miniforge3" "C:\miniforge3" "%LOCALAPPDATA%\miniforge3" "%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "C:\ProgramData\miniforge3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do call :use_conda_root "%%~D"
goto :eof

:use_conda_root
if defined CONDA_ROOT goto :eof
if exist "%~1\condabin\conda.bat" set "CONDA_ROOT=%~f1"
goto :eof

:install_miniforge
rem conda breaks when its folder has spaces or non-ASCII letters, such as a Japanese user
rem name. Then install to C:\miniforge3 instead of the user folder, as README.md says.
set "TARGET=%USERPROFILE%\miniforge3"
powershell -NoProfile -Command "exit [int]($env:USERPROFILE -match '[^\x21-\x7E]')" >nul 2>nul
if errorlevel 1 set "TARGET=C:\miniforge3"
set "INSTALLER=%TEMP%\Miniforge3-Windows-x86_64.exe"
echo Downloading Miniforge...
curl.exe -L --fail --retry 3 -o "%INSTALLER%" "%MINIFORGE_URL%"
if errorlevel 1 exit /b 1
echo Installing Miniforge to "%TARGET%". This takes a few minutes...
start "" /wait "%INSTALLER%" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%TARGET%
del "%INSTALLER%" >nul 2>nul
call :use_conda_root "%TARGET%"
goto :eof
