@echo off
chcp 65001 >nul 2>&1
title 私人助手 - 启动中...

echo ============================================
echo   私人助手项目 - 启动脚本
echo ============================================
echo.

REM 检查 Python 环境
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请确保已安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 .env 文件
if not exist ".env" (
    echo [警告] 未找到 .env 配置文件
    if exist ".env.example" (
        echo [提示] 正在从 .env.example 创建 .env...
        copy .env.example .env >nul
        echo [提示] 请编辑 .env 文件填入你的 API Key
        notepad .env
    ) else (
        echo [错误] .env.example 也不存在，请手动创建 .env 文件
        pause
        exit /b 1
    )
)

REM 检查依赖
echo [1/3] 检查依赖包...
python -c "import gradio; import langchain; import langgraph" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装依赖包...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)
echo       依赖检查通过

REM 环境变量
set HF_ENDPOINT=https://hf-mirror.com
set HF_HUB_DISABLE_SYMLINKS=1

REM 启动应用
echo [2/3] 启动应用...
echo [3/3] 访问地址: http://localhost:7860
echo.
echo 按 Ctrl+C 停止服务
echo ============================================
echo.

python app.py

pause
