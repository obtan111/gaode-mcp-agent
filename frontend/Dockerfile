# ============================================================
# 前端镜像：多阶段构建
#   阶段1 node:22-alpine  → npm ci + vite build 产出 dist/
#   阶段2 nginx:alpine    → 托管静态文件 + 反向代理 /api
# 最终镜像只含 Nginx 与静态资源，体积小（~25MB）
# ============================================================

# ---------- 构建阶段 ----------
FROM node:22-alpine AS build

WORKDIR /app

# 先拷依赖清单（利用层缓存）
COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com

# 再拷源码并构建
COPY . .
RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
