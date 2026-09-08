// 聊天页：WebSocket 流式打字机对话 + 行程卡片
const app = getApp()
const ws = require('../../utils/ws')
const api = require('../../utils/api')
const markdown = require('../../utils/markdown')
const itineraryUtil = require('../../utils/itinerary')

let msgSeq = 0
const FLUSH_INTERVAL = 20 // token 节流刷新间隔（ms），小于后端 TOKEN_INTERVAL 30ms 保证逐块显示
// 后端 status 事件 node → 用户可见的处理进度文案
const NODE_LABELS = {
  llm_inference: '正在理解你的需求…',
  tool_execution: '正在查询天气和景点…',
  answer_generation: '正在规划行程路线…',
  rag_retrieval: '正在检索资料…',
  memory: '正在回忆上下文…'
}

Page({
  data: {
    sessionId: '',
    messages: [],
    inputValue: '',
    connected: false,
    wsStatus: '',
    showRetry: false,
    busy: false,
    scrollInto: '',
    recording: false,
    recCls: '',
    recTip: '按住说话'
  },

  onLoad(options) {
    console.log('[chat] onLoad options=', JSON.stringify(options || {}))
    if (options && options.sessionId) {
      app.globalData.pendingSessionId = options.sessionId
    }
    this._flushTimer = null
    this._pendingDelta = ''
    this._scrollKey = ''
    this._initRecorder()
    this._initAudio()
    ws.resetHandlers()
    this._bindWS()
    console.log('[chat] onLoad done, data.messages=', this.data.messages.length)
  },

  onShow() {
    console.log('[chat] onShow, pendingSessionId=', app.globalData.pendingSessionId)
    this._connect()
    const pending = app.globalData.pendingSessionId
    if (pending === '__new__') {
      app.globalData.pendingSessionId = null
      this.setData({ messages: [], sessionId: '', busy: false })
    } else if (pending) {
      app.globalData.pendingSessionId = null
      this._loadSession(pending)
    }
  },

  onUnload() {
    if (this._flushTimer) {
      clearTimeout(this._flushTimer)
      this._flushTimer = null
    }
    ws.close()
  },

  _bindWS() {
    console.log('[chat] _bindWS register handlers')
    ws.on('__open__', () => {
      console.log('[chat] WS open')
      this.setData({ connected: true, wsStatus: '', showRetry: false })
    })
    ws.on('__error__', (data) => {
      console.log('[chat] WS error:', data && data.message)
      this.setData({ connected: false, wsStatus: (data && data.message) || '连接失败', showRetry: true })
    })
    ws.on('__close__', () => {
      console.log('[chat] WS closed')
      this.setData({ connected: false, wsStatus: '连接已断开', showRetry: true })
    })
    ws.on('start', (data) => {
      console.log('[chat] event start, session_id=', data && data.session_id)
      if (data && data.session_id) {
        this.setData({ sessionId: data.session_id })
      }
    })
    ws.on('token', (data) => {
      console.log('[chat] event token, len=', data && data.delta && data.delta.length)
      if (data && data.delta) this._appendDelta(data.delta)
    })
    ws.on('status', (data) => {
      console.log('[chat] event status node=', data && data.node)
      const node = (data && data.node) || ''
      const text = NODE_LABELS[node] || '正在处理…'
      const messages = this.data.messages
      const last = messages[messages.length - 1]
      if (last && last.showThinking) {
        this.setData({ ['messages[' + (messages.length - 1) + '].thinking']: text })
      }
    })
    ws.on('done', (data) => {
      console.log('[chat] event done, answer_len=', data && data.answer && data.answer.length)
      this._finishTurn((data && data.answer) || '')
    })
    ws.on('itinerary', (data) => {
      console.log('[chat] event itinerary')
      if (data) this._attachItinerary(data)
    })
    ws.on('error', (data) => {
      console.log('[chat] event error:', data && data.message)
      this._failTurn((data && data.message) || '处理请求时出错')
    })
  },

  async _connect() {
    if (this.data.connected) return
    try {
      await ws.connect()
    } catch (e) {
      this.setData({ wsStatus: (e && e.message) || '连接失败' })
    }
  },

  onInput(e) {
    this.setData({ inputValue: e.detail.value })
  },

  sendMessage() {
    const text = (this.data.inputValue || '').trim()
    console.log('[chat] sendMessage text=', JSON.stringify(text), 'busy=', this.data.busy)
    if (!text || this.data.busy) return
    this.setData({ inputValue: '' })
    const messages = this.data.messages
    console.log('[chat] messages before push isArray=', Array.isArray(messages), 'len=', messages && messages.length)
    messages.push(this._newMsg('user', text, false))
    messages.push(this._newMsg('assistant', '', true))
    console.log('[chat] messages after push=', messages.map(m => m.id + ':' + m.role))
    this.setData({ messages, busy: true })
    console.log('[chat] setData messages done, len=', this.data.messages.length)
    this._scrollBottom()
    const sent = ws.sendChat({
      message: text,
      sessionId: this.data.sessionId || null,
      modelType: 'deepseek',
      tts: false
    })
    if (!sent) {
      // 未连接：给出明确提示并自动重连；队列中的消息会在连接建立后自动补发
      this.setData({ wsStatus: '正在连接服务器…' })
      this._connect().catch(() => {
        this._failTurn('连接服务器失败，请确认后端已启动（8100 端口）后重试')
      })
    } else {
      // busy 超时兜底：90 秒无 done/error 自动解除，避免永久卡住
      this._startBusyGuard()
    }
  },

  _startBusyGuard() {
    if (this._busyGuard) clearTimeout(this._busyGuard)
    this._busyGuard = setTimeout(() => {
      this._busyGuard = null
      if (!this.data.busy) return
      this._failTurn('响应超时，请稍后重试')
    }, 90000)
  },

  openItinerary(e) {
    const index = e.currentTarget.dataset.index
    const msg = this.data.messages[index]
    if (!msg || !msg.itinerary) return
    app.globalData.lastItinerary = msg.itinerary
    wx.navigateTo({ url: '/pages/itinerary/itinerary' })
  },

  _newMsg(role, content, streaming) {
    msgSeq += 1
    const isUser = role === 'user'
    return {
      id: (isUser ? 'u' : 'a') + msgSeq,
      role,
      isUser,
      cls: isUser ? 'msg-item user' : 'msg-item assistant',
      avatarText: isUser ? '我' : 'AI',
      content,
      streaming: !!streaming,
      // 渲染层条件全部预计算，WXML 只做纯数据绑定（基础库版本差异下最稳）
      showThinking: !!streaming && !content,
      showCursor: !!streaming && !!content,
      thinking: isUser ? '' : '正在理解你的需求…',
      nodes: [],
      itinerary: null,
      summary: null,
      error: false,
      errorClass: '',
      // 语音播报（渲染层预计算：canVoice 控制按钮显隐，voiceIcon 控制图标）
      canVoice: false,
      playing: '',
      voiceIcon: '🔊'
    }
  },

  // ---------- 语音输入（录音 → ASR） ----------

  _initRecorder() {
    this._recorder = wx.getRecorderManager()
    this._recorder.onStop((res) => {
      if (!res || !res.tempFilePath) return
      wx.showLoading({ title: '识别中...', mask: true })
      api.asr(res.tempFilePath)
        .then((data) => {
          const text = (((data || {}).text) || '').trim()
          if (text) {
            this.setData({ inputValue: text })
          } else {
            wx.showToast({ title: '未识别到内容', icon: 'none' })
          }
        })
        .catch((err) => {
          wx.showToast({ title: (err && err.message) || '识别失败', icon: 'none' })
        })
        .finally(() => wx.hideLoading())
    })
    this._recorder.onError((err) => {
      this.setData({ recording: false, recCls: '' })
      wx.showToast({ title: '录音失败', icon: 'none' })
      console.warn('[chat] recorder error', err)
    })
  },

  startRecord() {
    if (this.data.recording || this.data.busy) return
    wx.getSetting({
      success: (res) => {
        const auth = res.authSetting && res.authSetting['scope.record']
        if (auth === false) {
          wx.showModal({
            title: '需要麦克风权限',
            content: '请在设置中允许使用麦克风',
            confirmText: '去设置',
            success: (r) => { if (r.confirm) wx.openSetting() }
          })
          return
        }
        if (auth === undefined) {
          wx.authorize({
            scope: 'scope.record',
            success: () => this._beginRecord(),
            fail: () => wx.showToast({ title: '未授权麦克风', icon: 'none' })
          })
          return
        }
        this._beginRecord()
      }
    })
  },

  _beginRecord() {
    this.setData({ recording: true, recCls: 'recording', recTip: '松开结束' })
    this._recorder.start({
      format: 'mp3',
      duration: 60000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000
    })
  },

  stopRecord() {
    if (!this.data.recording) return
    this.setData({ recording: false, recCls: '', recTip: '按住说话' })
    this._recorder.stop()
  },

  // ---------- 语音播报（按需 TTS） ----------

  _initAudio() {
    this._audioCtx = wx.createInnerAudioContext()
    this._audioCtx.onEnded(() => this._clearVoiceState())
    this._audioCtx.onError(() => {
      this._clearVoiceState()
      wx.showToast({ title: '播放失败', icon: 'none' })
    })
  },

  _setVoiceState(index, playing, icon) {
    this.setData({
      ['messages[' + index + '].playing']: playing,
      ['messages[' + index + '].voiceIcon']: icon
    })
  },

  _clearVoiceState() {
    const messages = this.data.messages
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].playing) {
        this._setVoiceState(i, '', '🔊')
        break
      }
    }
  },

  playVoice(e) {
    const index = e.currentTarget.dataset.index
    const msg = this.data.messages[index]
    if (!msg || msg.role !== 'assistant' || !msg.content) return
    if (msg.playing === 'playing') {
      // 再次点击：停止播放
      if (this._audioCtx) this._audioCtx.stop()
      this._setVoiceState(index, '', '🔊')
      return
    }
    if (msg.playing === 'loading') return
    this._setVoiceState(index, 'loading', '⏳')
    api.tts(msg.content)
      .then((res) => {
        const dataUri = (res && res.audio) || ''
        const comma = dataUri.indexOf(',')
        if (comma < 0) throw new Error('无音频数据')
        const base64 = dataUri.slice(comma + 1)
        const mime = (dataUri.slice(0, comma).split(';')[0] || '').split(':')[1] || ''
        const ext = mime.indexOf('mpeg') >= 0 ? 'mp3' : 'wav'
        const filePath = wx.env.USER_DATA_PATH + '/tts_' + Date.now() + '.' + ext
        wx.getFileSystemManager().writeFile({
          filePath,
          data: wx.base64ToArrayBuffer(base64),
          success: () => {
            this._audioCtx.src = filePath
            this._audioCtx.play()
            this._setVoiceState(index, 'playing', '⏸')
          },
          fail: () => {
            this._setVoiceState(index, '', '🔊')
            wx.showToast({ title: '音频写入失败', icon: 'none' })
          }
        })
      })
      .catch((err) => {
        this._setVoiceState(index, '', '🔊')
        wx.showToast({ title: (err && err.message) || '语音合成失败', icon: 'none' })
      })
  },

  _appendDelta(delta) {
    this._pendingDelta += delta
    if (this._flushTimer) return
    this._flushTimer = setTimeout(() => {
      this._flushTimer = null
      const text = this._pendingDelta
      this._pendingDelta = ''
      if (!text) return
      const messages = this.data.messages
      const last = messages[messages.length - 1]
      if (!last || last.role !== 'assistant') return
      last.content += text
      last.showThinking = false
      last.showCursor = true
      this.setData({
        ['messages[' + (messages.length - 1) + '].content']: last.content,
        ['messages[' + (messages.length - 1) + '].showThinking']: false,
        ['messages[' + (messages.length - 1) + '].showCursor']: true
      })
      this._scrollBottom()
    }, FLUSH_INTERVAL)
  },

  _finishTurn(answer) {
    // done 已携带完整答案：清掉尚未触发的 token 节流器，防止残留 token 重复追加/重新点亮光标
    if (this._flushTimer) {
      clearTimeout(this._flushTimer)
      this._flushTimer = null
    }
    this._pendingDelta = ''
    if (this._busyGuard) {
      clearTimeout(this._busyGuard)
      this._busyGuard = null
    }
    const messages = this.data.messages
    let last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant') {
      last = this._newMsg('assistant', '', false)
      messages.push(last)
    }
    last.streaming = false
    last.error = false
    last.showThinking = false
    last.showCursor = false
    last.content = answer || last.content || '（空回复）'
    last.canVoice = !!last.content
    // 取本轮用户问题辅助推断行程目的地
    let userMessage = ''
    for (let i = messages.length - 2; i >= 0; i--) {
      if (messages[i].role === 'user') {
        userMessage = messages[i].content
        break
      }
    }
    try {
      const it = itineraryUtil.extractItinerary(last.content, userMessage)
      if (it) {
        last.itinerary = it
        last.summary = itineraryUtil.summarize(it)
        const stripped = itineraryUtil.stripJson(last.content)
        last.content = stripped || '已生成行程卡片，点击上方卡片查看详细行程'
      }
    } catch (e) {
      console.warn('[chat] itinerary extract failed', e)
    }
    try {
      last.nodes = markdown.render(last.content)
    } catch (e) {
      console.warn('[chat] markdown render failed', e)
      last.nodes = []
    }
    this.setData({ messages, busy: false })
    this._scrollBottom()
  },

  // 后端额外推送的 itinerary 事件（幂等：仅当消息尚未挂载行程时使用）
  _attachItinerary(it) {
    const messages = this.data.messages
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant' || last.itinerary) return
    last.itinerary = it
    last.summary = itineraryUtil.summarize(it)
    if (last.content) {
      const stripped = itineraryUtil.stripJson(last.content)
      if (stripped) last.content = stripped
    }
    if (!last.content) {
      last.content = '已生成行程卡片，点击上方卡片查看详细行程'
    }
    last.canVoice = !!last.content
    try {
      last.nodes = markdown.render(last.content)
    } catch (e) {
      console.warn('[chat] markdown render failed', e)
      last.nodes = []
    }
    this.setData({ ['messages[' + (messages.length - 1) + ']']: last })
  },

  _failTurn(message) {
    const messages = this.data.messages
    const last = messages[messages.length - 1]
    if (last && last.role === 'assistant' && last.streaming) {
      last.streaming = false
      last.error = true
      last.errorClass = 'bubble-error'
      last.showThinking = false
      last.showCursor = false
      last.content = (last.content ? last.content + '\n' : '') + '⚠️ ' + message
    } else {
      const msg = this._newMsg('assistant', '⚠️ ' + message, false)
      msg.error = true
      msg.errorClass = 'bubble-error'
      messages.push(msg)
    }
    this.setData({ messages, busy: false })
    this._scrollBottom()
  },

  async _loadSession(sessionId) {
    this.setData({ messages: [], sessionId, busy: false })
    wx.showLoading({ title: '加载中...', mask: true })
    try {
      const session = await api.getSession(sessionId)
      const raw = (session && session.messages) || []
      const messages = []
      let lastUserText = ''
      for (let i = 0; i < raw.length; i++) {
        const item = raw[i]
        if (item.role !== 'user' && item.role !== 'assistant') continue
        const content = typeof item.content === 'string' ? item.content : ''
        const msg = this._newMsg(item.role, content, false)
        if (item.role === 'user') {
          lastUserText = content
        } else {
          const it = itineraryUtil.extractItinerary(content, lastUserText)
          if (it) {
            msg.itinerary = it
            msg.summary = itineraryUtil.summarize(it)
            const stripped = itineraryUtil.stripJson(content)
            if (stripped) msg.content = stripped
          }
          msg.nodes = markdown.render(msg.content)
          msg.canVoice = !!msg.content
        }
        messages.push(msg)
      }
      this.setData({ messages })
      const title = (session && session.title) || 'AI 旅行助手'
      wx.setNavigationBarTitle({ title: title.length > 12 ? title.slice(0, 12) + '…' : title })
      this._scrollBottom()
    } catch (e) {
      wx.showToast({ title: (e && e.message) || '加载失败', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },

  _scrollBottom() {
    const messages = this.data.messages
    if (!messages.length) return
    const id = 'msg-' + messages[messages.length - 1].id
    if (this._scrollKey === id) {
      // 相同目标先清空再赋值，强制触发滚动
      this.setData({ scrollInto: '' }, () => {
        this.setData({ scrollInto: id })
      })
    } else {
      this._scrollKey = id
      this.setData({ scrollInto: id })
    }
  }
})
