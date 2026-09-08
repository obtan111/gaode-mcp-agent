import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置：dev 服务器 + 代理
// proxy 的作用：浏览器请求 /api/xxx 时，由 Vite 开发服务器转发给
// 后端 FastAPI(8100端口)，从而绕过浏览器的同源策略（开发期不再需要 CORS）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
      },
    },
  },
})
