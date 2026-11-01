@echo off
REM One-click build on Windows. Requires: Python 3.10-3.12 (64-bit) and Inno Setup 6.
REM Output: dist_installer\Setup.exe
setlocal
cd /d "%~dp0"

python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err

if not exist assets\models mkdir assets\models
if not exist assets\models\face_recognition_sface_2021dec.onnx (
  echo Downloading face model for offline use...
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing 'https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx' -OutFile 'assets\models\face_recognition_sface_2021dec.onnx'" || goto :err
)

pyinstaller --noconfirm --clean MyGuard.spec || goto :err

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (echo Inno Setup 6 not found. Install from https://jrsoftware.org/isdl.php & goto :err)
%ISCC% installer\MyGuard.iss || goto :err

echo.
echo DONE: dist_installer\Setup.exe
exit /b 0
:err
echo BUILD FAILED
exit /b 1
