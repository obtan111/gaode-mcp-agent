// 会话历史列表页
const app = getApp()
const api = require('../../utils/api')

function pad(n) {
  return n < 10 ? '0' + n : '' + n
}

// 数据库时间为 UTC ISO 字符串，转为本地显示
function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfDay = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes())
  const diffDays = Math.round((startOfToday - startOfDay) / 86400000)
  if (diffDays === 0) return '今天 ' + hm
  if (diffDays === 1) return '昨天 ' + hm
  if (d.getFullYear() === now.getFullYear()) return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + hm
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

Page({
  data: {
    sessions: [],
    loading: true,
    errorMsg: ''
  },

  onShow() {
    this._load()
  },

  async onPullDownRefresh() {
    await this._load()
    wx.stopPullDownRefresh()
  },

  async _load() {
    this.setData({ loading: true, errorMsg: '' })
    try {
      const list = await api.listSessions(1, 50)
      const sessions = (list || []).map((s) => ({
        id: s.id,
        title: s.title || '新对话',
        timeText: formatTime(s.updated_at || s.created_at),
        preview: this._preview(s)
      }))
      this.setData({ sessions, loading: false })
    } catch (e) {
      this.setData({
        loading: false,
        errorMsg: (e && e.message) || '加载失败，请确认后端已启动'
      })
    }
  },

  _preview(session) {
    const messages = session.messages || []
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m.role === 'user' && typeof m.content === 'string' && m.content.trim()) {
        return m.content.length > 24 ? m.content.slice(0, 24) + '…' : m.content
      }
    }
    return ''
  },

  openSession(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    app.globalData.pendingSessionId = id
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  // 长按会话：弹出删除操作
  onLongPress(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.showActionSheet({
      itemList: ['删除该会话'],
      success: (res) => {
        if (res.tapIndex === 0) {
          this._confirmDelete(id)
        }
      },
      fail: () => { /* 用户取消 */ }
    })
  },

  _confirmDelete(id) {
    wx.showModal({
      title: '删除会话',
      content: '删除后聊天记录将无法恢复，确定删除？',
      confirmColor: '#E54D42',
      success: async (res) => {
        if (!res.confirm) return
        wx.showLoading({ title: '删除中...', mask: true })
        try {
          await api.deleteSession(id)
          wx.hideLoading()
          wx.showToast({ title: '已删除', icon: 'success' })
          this._load()
        } catch (e) {
          wx.hideLoading()
          wx.showToast({ title: (e && e.message) || '删除失败', icon: 'none' })
        }
      }
    })
  },

  newSession() {
    app.globalData.pendingSessionId = '__new__'
    wx.switchTab({ url: '/pages/chat/chat' })
  }
})
