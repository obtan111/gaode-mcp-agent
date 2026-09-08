// WebSocket 单例封装：连接管理、消息发送、事件分发、心跳
const { WS_URL } = require('./config')

class ChatWS {
  constructor() {
    this.socket = null
    this.connected = false
    this._handlers = {}      // eventName -> [fn, ...]
    this._queue = []         // 未连接时暂存的待发消息
    this._heartbeat = null
  }

  connect() {
    return new Promise((resolve, reject) => {
      if (this.connected && this.socket) {
        resolve()
        return
      }
      let settled = false
      // 代际标识：防止旧 socket 的迟到事件污染新连接状态
      const gen = (this._gen = (this._gen || 0) + 1)
      const socket = wx.connectSocket({
        url: WS_URL,
        timeout: 15000
      })
      this.socket = socket

      socket.onOpen(() => {
        if (gen !== this._gen) return
        this.connected = true
        settled = true
        this._flush()
        this._startHeartbeat()
        this._emit('__open__', {})
        resolve()
      })
      socket.onMessage((res) => {
        if (gen !== this._gen) return
        let msg
        try {
          msg = JSON.parse(res.data)
        } catch (e) {
          console.warn('[ws] 无法解析的消息:', res.data)
          return
        }
        this._emit(msg.event, msg.data || {})
      })
      socket.onError((err) => {
        if (gen !== this._gen) return
        this.connected = false
        this._stopHeartbeat()
        if (!settled) {
          settled = true
          reject(new Error('WebSocket 连接失败：' + (err.errMsg || '未知错误')))
        } else {
          this._emit('__error__', { message: err.errMsg || '连接异常' })
        }
      })
      socket.onClose(() => {
        if (gen !== this._gen) return
        this.connected = false
        this._stopHeartbeat()
        this._emit('__close__', {})
      })
    })
  }

  // 发送一条聊天请求；返回是否已连接（未连接则进入待发队列）
  sendChat(payload) {
    return this.send({
      action: 'chat',
      message: payload.message,
      session_id: payload.sessionId || null,
      model_type: payload.modelType || 'deepseek',
      tts: !!payload.tts
    })
  }

  sendPing() {
    this.send({ action: 'ping' })
  }

  // 返回 true 表示已通过连接发出；false 表示进入待发队列（连接建立后自动补发）
  send(obj) {
    const text = JSON.stringify(obj)
    if (this.connected && this.socket) {
      try {
        this.socket.send({ data: text })
        return true
      } catch (e) {
        console.warn('[ws] send failed', e)
        this.connected = false
        this._queue.push(text)
        return false
      }
    }
    this._queue.push(text)
    return false
  }

  _flush() {
    while (this._queue.length && this.connected && this.socket) {
      this.socket.send({ data: this._queue.shift() })
    }
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this._heartbeat = setInterval(() => {
      if (this.connected) this.sendPing()
    }, 25000)
  }

  _stopHeartbeat() {
    if (this._heartbeat) {
      clearInterval(this._heartbeat)
      this._heartbeat = null
    }
  }

  // 事件订阅
  on(event, fn) {
    if (!this._handlers[event]) this._handlers[event] = []
    this._handlers[event].push(fn)
  }

  // 清空所有订阅（页面 onLoad 时调用，避免旧页面回调残留）
  resetHandlers() {
    this._handlers = {}
  }

  _emit(event, data) {
    const list = this._handlers[event] || []
    for (let i = 0; i < list.length; i++) {
      try {
        list[i](data)
      } catch (e) {
        console.warn('[ws] 事件回调出错:', event, e)
      }
    }
  }

  close() {
    this._stopHeartbeat()
    if (this.socket) {
      try {
        this.socket.close({ code: 1000 })
      } catch (e) { /* ignore */ }
      this.socket = null
    }
    this.connected = false
  }
}

// 模块级单例：tab 切换页面时连接不销毁
module.exports = new ChatWS()
