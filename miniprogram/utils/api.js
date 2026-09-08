// HTTP 接口封装（会话 / 语音 / 地理坐标）
const { BASE_URL } = require('./config')

function request(path, method, data, timeout) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + path,
      method: method || 'GET',
      data: data || undefined,
      header: { 'Content-Type': 'application/json' },
      timeout: timeout || 15000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          const detail = res.data && (res.data.detail || JSON.stringify(res.data))
          reject(new Error('HTTP ' + res.statusCode + (detail ? ': ' + detail : '')))
        }
      },
      fail(err) {
        reject(new Error('网络请求失败：' + (err.errMsg || '未知错误')))
      }
    })
  })
}

module.exports = {
  // 会话历史列表（倒序）
  listSessions(page, pageSize) {
    return request('/api/sessions?page=' + (page || 1) + '&page_size=' + (pageSize || 50))
  },
  // 单个会话详情（含消息历史）
  getSession(sessionId) {
    return request('/api/sessions/' + encodeURIComponent(sessionId))
  },
  // 新建空会话
  createSession() {
    return request('/api/sessions', 'POST', { title: '新对话' })
  },
  // 删除会话
  deleteSession(sessionId) {
    return request('/api/sessions/' + encodeURIComponent(sessionId), 'DELETE')
  },
  // 批量地点坐标解析（行程地图 markers，后端代理高德，密钥不暴露）
  getCoords(places) {
    return request('/api/geo/coords', 'POST', { places }, 30000)
  },
  // 语音识别：上传录音文件 → { text }
  asr(filePath) {
    return new Promise((resolve, reject) => {
      wx.uploadFile({
        url: BASE_URL + '/api/voice/asr',
        filePath: filePath,
        name: 'file',
        timeout: 30000,
        success(res) {
          let data = null
          try {
            data = JSON.parse(res.data)
          } catch (e) {
            reject(new Error('识别响应解析失败'))
            return
          }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(data)
          } else {
            reject(new Error((data && data.detail) || '识别失败'))
          }
        },
        fail(err) {
          reject(new Error('语音上传失败：' + (err.errMsg || '未知错误')))
        }
      })
    })
  },
  // 文字转语音 → { audio: "data:audio/mp3;base64,..." }
  tts(text) {
    return request('/api/voice/tts', 'POST', { text }, 60000)
  }
}
