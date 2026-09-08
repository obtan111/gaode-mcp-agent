// HTTP 接口封装（会话列表 / 会话详情 / 新建会话）
const { BASE_URL } = require('./config')

function request(path, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + path,
      method: method || 'GET',
      data: data || undefined,
      header: { 'Content-Type': 'application/json' },
      timeout: 15000,
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
  }
}
