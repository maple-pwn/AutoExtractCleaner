@echo off
chcp 65001 >nul
echo ========================================
echo   压缩包自动清理工具 - 打包脚本
echo ========================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [错误] 安装依赖失败
    pause
    exit /b 1
)

REM 清理旧的构建文件
echo [2/3] 清理旧文件...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec

REM 打包
echo [3/3] 开始打包...
pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AutoExtractCleaner" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --hidden-import "pystray._win32" ^
    --hidden-import "PIL._tkinter_finder" ^
    main.py

if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo   打包完成！
echo   可执行文件: dist\AutoExtractCleaner.exe
echo ========================================
echo.

REM 复制到当前目录
copy /y "dist\AutoExtractCleaner.exe" "AutoExtractCleaner.exe" >nul

echo 文件已复制到当前目录: AutoExtractCleaner.exe
echo.
pause
