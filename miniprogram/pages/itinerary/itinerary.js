// 行程卡片详情页（含地图可视化：按天着色 markers + 路线连线 + 天切换）
const app = getApp()
const api = require('../../utils/api')
const itineraryUtil = require('../../utils/itinerary')

// 按天着色的 marker 与路线颜色（与 images/marker_dayN.png 对应）
const DAY_COLORS = ['#E54D42', '#2F80ED', '#27AE60', '#F2994A', '#9B51E0']

Page({
  data: {
    it: null,
    days: [],
    tips: [],
    // 地图
    mapReady: false,
    tabs: [],
    activeDay: 0,
    markers: [],
    polylines: [],
    includePoints: [],
    center: { latitude: 39.9, longitude: 116.4 }
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
    this._loadMap(days, it.destination || '')
  },

  // ---------- 地图可视化 ----------

  // 地点文本拆分：'天安门→故宫→景山' -> ['天安门','故宫','景山']
  _splitPlaces(text) {
    return (text || '')
      .split(/[→、，,；;\/|&]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && /[\u4e00-\u9fa5A-Za-z]/.test(s))
  },

  async _loadMap(days, city) {
    // 收集地点：activity 括号内的地点串优先（可拆多个），slot.location 兜底；按天/时段记录
    const placeMap = {}
    const placeNames = []
    days.forEach((d) => {
      const dayNo = d.day
      d.slots.forEach((s) => {
        let locs = []
        const bracket = itineraryUtil.extractLocation(s.activity || '')
        if (bracket) {
          locs = this._splitPlaces(bracket)
        } else if (s.location) {
          locs = [s.location.trim()]
        }
        if (!locs.length) return
        locs.forEach((loc) => {
          if (!placeMap[loc]) {
            placeMap[loc] = {
              name: loc,
              day: dayNo,
              dayLabel: 'Day' + dayNo,
              slotLabel: s.label || '',
              activity: s.activity || ''
            }
            placeNames.push(loc)
          }
        })
      })
    })
    if (!placeNames.length) return

    // 批量坐标（后端代理高德，密钥不暴露前端）
    let coordMap = {}
    try {
      const res = await api.getCoords(placeNames.map((n) => ({ name: n, city: city || undefined })))
      ;(res.coords || []).forEach((c) => {
        if (c.lng != null) coordMap[c.name] = c
      })
    } catch (e) {
      console.warn('[itinerary] coords failed', e)
    }

    const markers = []
    const polyByDay = {}
    const allPoints = []
    placeNames.forEach((name) => {
      const c = coordMap[name]
      const info = placeMap[name]
      if (!c) return
      const dayIdx = Math.min(info.day, DAY_COLORS.length) - 1
      const marker = {
        id: markers.length,
        latitude: c.lat,
        longitude: c.lng,
        iconPath: '/images/marker_day' + (dayIdx + 1) + '.png',
        width: 30,
        height: 30,
        label: {
          content: info.dayLabel + '·' + (info.slotLabel || ''),
          color: DAY_COLORS[dayIdx],
          fontSize: 10,
          anchorX: -22,
          anchorY: -38
        },
        extra: {
          name: name,
          day: info.day,
          dayLabel: info.dayLabel,
          slotLabel: info.slotLabel,
          activity: info.activity,
          address: c.address || ''
        }
      }
      markers.push(marker)
      allPoints.push({ latitude: c.lat, longitude: c.lng })
      if (!polyByDay[info.day]) polyByDay[info.day] = []
      polyByDay[info.day].push(marker)
    })
    if (!markers.length) return

    // 按天路线连线（当天游玩顺序）
    const polylines = Object.keys(polyByDay)
      .sort((a, b) => a - b)
      .map((d) => ({
        day: parseInt(d, 10),
        points: polyByDay[d].map((m) => ({ latitude: m.latitude, longitude: m.longitude })),
        color: DAY_COLORS[Math.min(parseInt(d, 10), DAY_COLORS.length) - 1],
        width: 4,
        arrowLine: true
      }))

    // 天切换 tabs
    const daySet = Array.from(new Set(markers.map((m) => m.extra.day))).sort((a, b) => a - b)
    const tabs = [{ label: '全部', day: 0, cls: 'tab active' }]
    daySet.forEach((d) => tabs.push({ label: 'Day' + d, day: d, cls: 'tab' }))

    this._allMarkers = markers
    this._allPolylines = polylines
    this._allPoints = allPoints
    this._tabs = tabs

    this.setData({
      mapReady: true,
      tabs: tabs,
      activeDay: 0,
      markers: markers,
      polylines: polylines,
      includePoints: allPoints,
      center: { latitude: markers[0].latitude, longitude: markers[0].longitude }
    })
  },

  switchDay(e) {
    const day = Number(e.currentTarget.dataset.day || 0)
    const tabs = this._tabs.map((t) => ({
      label: t.label,
      day: t.day,
      cls: t.day === day ? 'tab active' : 'tab'
    }))
    if (day === 0) {
      this.setData({
        tabs,
        activeDay: 0,
        markers: this._allMarkers,
        polylines: this._allPolylines,
        includePoints: this._allPoints
      })
    } else {
      const markers = this._allMarkers.filter((m) => m.extra.day === day)
      const polylines = this._allPolylines.filter((p) => p.day === day)
      this.setData({
        tabs,
        activeDay: day,
        markers: markers,
        polylines: polylines,
        includePoints: markers.map((m) => ({ latitude: m.latitude, longitude: m.longitude }))
      })
    }
  },

  onMarkerTap(e) {
    const id = e.detail.markerId
    const m = this.data.markers.find((x) => x.id === id)
    if (!m || !m.extra) return
    const ex = m.extra
    let content = ''
    if (ex.dayLabel || ex.slotLabel) content += (ex.dayLabel || '') + (ex.slotLabel ? '·' + ex.slotLabel : '')
    if (ex.activity) content += '\n' + ex.activity
    if (ex.address) content += '\n📍 ' + ex.address
    wx.showModal({
      title: ex.name,
      content: content || ex.name,
      showCancel: false,
      confirmText: '知道了'
    })
  }
})
