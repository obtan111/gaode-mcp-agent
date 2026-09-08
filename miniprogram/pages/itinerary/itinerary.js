// 行程卡片详情页
const app = getApp()
const itineraryUtil = require('../../utils/itinerary')

Page({
  data: {
    it: null,
    days: [],
    tips: []
  },

  onLoad() {
    const it = app.globalData.lastItinerary
    if (!it) {
      wx.showToast({ title: '暂无行程数据', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 800)
      return
    }
    const days = itineraryUtil.getDayList(it).map((d, idx) => ({
      day: d.day != null ? d.day : idx + 1,
      date: d.date || '',
      weather: d.weather || '',
      route: d.route || '',
      slots: itineraryUtil.getSlots(d)
    }))
    this.setData({
      it: {
        title: it.title || (it.destination ? it.destination + ' 旅行计划' : '旅行计划'),
        destination: it.destination || '',
        dayCount: it.days != null ? it.days : days.length,
        budget: it.budget || '',
        weatherSummary: it.weather_summary || ''
      },
      days,
      tips: Array.isArray(it.tips) ? it.tips : []
    })
    const title = this.data.it.title
    wx.setNavigationBarTitle({ title: title.length > 10 ? title.slice(0, 10) + '…' : title })
  }
})
