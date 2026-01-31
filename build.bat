@echo off
echo ========================================
echo   AutoExtractCleaner - Build Script
echo ========================================
echo.

REM Check Python
echo [0/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please download from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)
echo [OK] Python found
echo.

REM Install dependencies with China mirror
echo [1/4] Installing dependencies (using China mirror)...
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pystray Pillow watchdog py7zr rarfile pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    echo Try running: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pystray Pillow watchdog py7zr rarfile pyinstaller
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

REM Clean old builds
echo [2/4] Cleaning old files...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec 2>nul
echo [OK] Cleaned
echo.

REM Generate icon
echo [3/4] Generating icon...
if not exist "icon.ico" (
    python create_icon.py
    if errorlevel 1 (
        echo [WARN] Icon generation failed, using default
    ) else (
        echo [OK] Icon created
    )
) else (
    echo [OK] Icon exists
)
echo.

REM Build
echo [4/4] Building executable...
echo This may take 1-2 minutes...
pyinstaller --noconfirm --onefile --windowed --name "AutoExtractCleaner" --hidden-import "pystray._win32" --hidden-import "PIL._tkinter_finder" main.py

if errorlevel 1 (
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo   SUCCESS! Build complete!
echo ========================================
echo.

copy /y "dist\AutoExtractCleaner.exe" "AutoExtractCleaner.exe" >nul 2>&1

echo Output file: AutoExtractCleaner.exe
echo.
echo You can now double-click AutoExtractCleaner.exe to run!
echo.
pause
