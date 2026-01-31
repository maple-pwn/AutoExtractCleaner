# PowerShell build script for AutoExtractCleaner
$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "  压缩包自动清理工具 - 打包脚本"
Write-Host "========================================"
Write-Host ""

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python: $pythonVersion"
} catch {
    Write-Host "[错误] 未找到Python，请先安装Python 3.8+"
    exit 1
}

# Install dependencies
Write-Host "[1/3] 安装依赖..."
pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 安装依赖失败"
    exit 1
}

# Clean old builds
Write-Host "[2/3] 清理旧文件..."
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
Get-ChildItem "*.spec" | Remove-Item -Force

# Build
Write-Host "[3/3] 开始打包..."
$buildArgs = @(
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "AutoExtractCleaner",
    "--hidden-import", "pystray._win32",
    "--hidden-import", "PIL._tkinter_finder",
    "main.py"
)

# Add icon if exists
if (Test-Path "icon.ico") {
    $buildArgs += "--icon", "icon.ico"
    $buildArgs += "--add-data", "icon.ico;."
}

pyinstaller @buildArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 打包失败"
    exit 1
}

Write-Host ""
Write-Host "========================================"
Write-Host "  打包完成！"
Write-Host "  可执行文件: dist\AutoExtractCleaner.exe"
Write-Host "========================================"

# Copy to current directory
Copy-Item "dist\AutoExtractCleaner.exe" "AutoExtractCleaner.exe" -Force
Write-Host "文件已复制到当前目录: AutoExtractCleaner.exe"
