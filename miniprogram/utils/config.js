// 后端服务地址配置
//
// ENV 三档：
//   'dev'  -> 开发者工具模拟器：127.0.0.1（详情 -> 本地设置 -> 勾选「不校验合法域名」）
//   'lan'  -> 真机预览：电脑局域网 IP（后端需 --host 0.0.0.0，手机同 WiFi，防火墙放行 8100）
//   'prod' -> 线上体验版/正式版：备案域名 + HTTPS/WSS（见 README「公网部署」章节）
//
// 上线步骤：把 ENV 改为 'prod'，并将 api.example.com 替换为你的真实备案域名。

const ENV = 'lan'

const HOSTS = {
  dev: {
    base: 'http://127.0.0.1:8100',
    ws: 'ws://127.0.0.1:8100/api/chat/ws'
  },
  lan: {
    base: 'http://192.168.1.232:8100',
    ws: 'ws://192.168.1.232:8100/api/chat/ws'
  },
  prod: {
    base: 'https://api.example.com',
    ws: 'wss://api.example.com/api/chat/ws'
  }
}

const BASE_URL = HOSTS[ENV].base
const WS_URL = HOSTS[ENV].ws

module.exports = {
  BASE_URL,
  WS_URL
}
