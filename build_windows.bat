@echo off
REM Builds dist\Pin\Pin.exe with the screensaver inside. Run on Windows with
REM Python 3.9+ and the .NET 8 SDK installed.
cd /d "%~dp0"
dotnet publish saver\windows\PinSaver.csproj -c Release -o saver\windows\publish || goto :fail
copy /y saver\windows\publish\Pin.exe saver\windows\publish\Pin.scr >nul
py -3 -m venv .venv-build || python -m venv .venv-build
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
pip install pyinstaller certifi -r requirements.txt
pyinstaller --noconfirm --log-level WARN Pin.spec || goto :fail
echo.
echo Done: dist\Pin\Pin.exe
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
