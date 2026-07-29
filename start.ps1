#Requires -Version 5.1
<#
.SYNOPSIS
    私人助手项目启动脚本 (PowerShell)
.DESCRIPTION
    自动检查环境、安装依赖、启动应用
.PARAMETER Port
    服务端口（默认 7860）
.PARAMETER SkipDeps
    跳过依赖检查
.PARAMETER Dev
    开发模式（启用调试）
.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 8080
    .\start.ps1 -Dev
#>

param(
    [int]$Port = 7860,
    [switch]$SkipDeps,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  私人助手项目 - 启动脚本" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Python
Write-Host "[1/4] 检查 Python 环境..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    Write-Host "[错误] 未找到 Python，请安装 Python 3.10+" -ForegroundColor Red
    exit 1
}
$python = $pythonCmd.Source
$version = & $python --version 2>&1
Write-Host "      Python: $version" -ForegroundColor Green

# 2. 检查 .env
Write-Host "[2/4] 检查配置文件..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "      [提示] 从 .env.example 创建 .env" -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "      [提示] 请编辑 .env 填入 API Key" -ForegroundColor Yellow
        Start-Process notepad ".env" -Wait
    } else {
        Write-Host "[错误] 未找到 .env 配置文件" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "      配置文件存在" -ForegroundColor Green
}

# 3. 检查依赖
if (-not $SkipDeps) {
    Write-Host "[3/4] 检查依赖包..." -ForegroundColor Yellow
    $checkResult = & $python -c "import gradio; import langchain; import langgraph" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      安装依赖包..." -ForegroundColor Yellow
        & $python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[错误] 依赖安装失败" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "      依赖检查通过" -ForegroundColor Green
} else {
    Write-Host "[3/4] 跳过依赖检查" -ForegroundColor DarkGray
}

# 4. 启动应用
Write-Host "[4/4] 启动应用..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  访问地址: http://localhost:$Port" -ForegroundColor Cyan
Write-Host "  按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 设置环境变量
$env:HF_ENDPOINT = "https://hf-mirror.com"
$env:HF_HUB_DISABLE_SYMLINKS = "1"

if ($Dev) {
    $env:GRADIO_DEBUG = "1"
    Write-Host "[开发模式] 调试已启用" -ForegroundColor Magenta
}

& $python app.py
