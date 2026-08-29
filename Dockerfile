# ============================================================
# 后端镜像：python:3.11-slim + uvicorn
#
# 说明：
# - 依赖层单独 COPY + pip install，利用 Docker 层缓存加速重建
#   （改业务代码不重装依赖）
# - sentence-transformers 首次使用会下载 Cross-Encoder 模型，
#   HF_ENDPOINT 走国内镜像（与本地 app.py 的配置一致）
# - 生产模式不带 --reload，单进程即可（个人项目规模）
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_DISABLE_SYMLINKS=1

WORKDIR /app

# 1) 先装依赖（层缓存：只有 requirements.txt 变化才重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2) 再拷贝代码（业务改动不触发依赖重装）
COPY backend/ ./backend/
COPY src/ ./src/
COPY scripts/ ./scripts/

# 3) 运行（端口由 compose 内部暴露，入口统一走 Nginx）
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
