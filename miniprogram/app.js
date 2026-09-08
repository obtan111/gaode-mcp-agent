// AI 旅行助手 - 全局入口
App({
  globalData: {
    // 会话列表页 -> 聊天页的会话切换信号（tabBar 页面无法通过 url 传参）
    pendingSessionId: null,
    // 最近一次生成的行程对象（聊天页 -> 行程详情页）
    lastItinerary: null
  }
})
