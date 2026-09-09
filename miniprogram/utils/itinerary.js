// 行程 JSON 解析与卡片数据归一化
// 对齐后端 src/agent/prompts.py 的 TRAVEL_PLAN_PROMPT 输出 schema：
//   { title, destination, days, budget, weather_summary,
//     daily_itinerary: [{ day, date, weather,
//       morning/afternoon/evening: { activity, location, transport, duration, cost } }],
//     tips: [] }
//
// 两条提取通道（与后端 backend/routers/chat.py 一致）：
//   1) 回答文本中携带 JSON（```json 围栏或裸对象）时直接解析；
//   2) 否则把 agent 的结构化 markdown（## Day N + ### 上午/下午/晚上）解析为行程对象。

const DAY_HEAD_RE = /^#{1,4}\s*[^\u4e00-\u9fa5A-Za-z0-9]*?(?:Day\s*(\d+)|第\s*(\d+)\s*天)\b/i
const SLOT_HEAD_RE = /^#{1,4}\s*((?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐)(?:[、/]?(?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐))*)\s*[：:]\s*(.+?)\s*$/
const BOLD_SLOT_HEAD_RE = /^\s*\*\*((?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐)(?:[、/]?(?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐))*)\s*[|｜：:]\s*(.+?)\s*\*\*(?:[（(][^）)]*[）)])?\s*$/
const NON_SLOT_SECTION_RE = /^#{1,4}\s*(?:💡|🏨|🚇|⚠️)?\s*(?:住宿|交通|小贴士|注意事项|注意|建议|美食|费用|预算|总结)/
const SLOT_MAP = {
  上午: 'morning', 中午: 'morning', 午餐: 'morning', 下午: 'afternoon',
  傍晚: 'evening', 晚上: 'evening', 晚餐: 'evening', 夜间: 'evening', 夜: 'evening'
}
const NON_DEST_CHARS = '的了份为是在至去到来给和与把将帮我你要这那准备安排行程计划攻略如下一份查收请点规划游个'

function looksLikeItinerary(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return false
  if (Array.isArray(obj.daily_itinerary) && obj.daily_itinerary.length) return true
  if (Array.isArray(obj.days) && obj.days.length) return true
  if (obj.destination && typeof obj.days === 'number') return true
  return false
}

// 从回答文本中尽力提取行程 JSON（userMessage 用于更可靠地推断目的地）
function extractItinerary(text, userMessage) {
  if (!text) return null
  const candidates = []
  const fenceRe = /```(?:json)?\s*(\{[\s\S]*?\})\s*```/g
  let m
  while ((m = fenceRe.exec(text)) !== null) {
    candidates.push(m[1])
  }
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start !== -1 && end > start) {
    candidates.push(text.slice(start, end + 1))
  }
  for (let i = 0; i < candidates.length; i++) {
    try {
      const obj = JSON.parse(candidates[i])
      if (looksLikeItinerary(obj)) return obj
    } catch (e) {
      /* try next */
    }
  }
  return extractFromText(text, userMessage)
}

function guessDestination(text) {
  if (!text) return ''
  const m = /([\u4e00-\u9fa5]+)\s*(?:\d+|[一二三四五六七八九十两])\s*[日天]\s*游/.exec(text)
  if (!m) return ''
  const s = m[1]
  for (let i = 0; i < s.length; i++) {
    if (NON_DEST_CHARS.indexOf(s[i]) !== -1) continue
    const cand = s.slice(i)
    return cand.length <= 6 ? cand : cand.slice(0, 6)
  }
  return ''
}

function extractLocation(activity) {
  const pairs = [['【', '】'], ['（', '）'], ['(', ')']]
  for (let p = 0; p < pairs.length; p++) {
    const o = activity.indexOf(pairs[p][0])
    if (o !== -1) {
      const c = activity.indexOf(pairs[p][1], o)
      if (c !== -1) return activity.slice(o + 1, c).trim()
    }
  }
  return ''
}

function cleanDescription(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim()
}

function matchSlot(line) {
  let m = SLOT_HEAD_RE.exec(line)
  if (m) {
    return [SLOT_MAP[m[1].split('/')[0].split('、')[0]], m[2].trim()]
  }
  m = BOLD_SLOT_HEAD_RE.exec(line)
  if (m) {
    const key = SLOT_MAP[m[1].split('/')[0].split('、')[0]]
    let activity = m[2].trim()
    if (activity.indexOf('推荐：') === 0) activity = activity.slice(3)
    return [key, activity]
  }
  return null
}

function extractFromText(answer, userMessage) {
  const lines = answer.split(/\r?\n/)
  const days = []
  let curDay = null
  let curSlot = null

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue
    const dm = DAY_HEAD_RE.exec(line)
    if (dm) {
      const dayNum = parseInt(dm[1] || dm[2], 10)
      const title = line.indexOf('：') !== -1 ? line.split('：')[1].trim() : ''
      let date = ''
      const dmDate = /[（(]([^（()）]{1,20})[）)]/.exec(line)
      if (dmDate && /[\/月日\-]/.test(dmDate[1])) date = dmDate[1]
      // 单行路线型 Day 头（如「岳麓山 → 橘子洲 → 太平街」）存为 route 兜底
      const route = (title.indexOf('→') !== -1 || title.indexOf('->') !== -1 || title.indexOf('｜') !== -1 || title.length > 12) ? title : ''
      curDay = {
        day: dayNum, date, weather: '',
        morning: null, afternoon: null, evening: null, title, route
      }
      days.push(curDay)
      curSlot = null
      continue
    }
    const slot = matchSlot(line)
    if (slot) {
      if (!curDay) {
        curDay = {
          day: days.length + 1, date: '', weather: '',
          morning: null, afternoon: null, evening: null, title: ''
        }
        days.push(curDay)
      }
      const slotKey = slot[0]
      const activity = slot[1]
      if (!curDay[slotKey]) {
        curDay[slotKey] = {
          activity,
          location: extractLocation(activity),
          transport: '', duration: '', cost: '', description: ''
        }
      } else if (activity && curDay[slotKey].activity.indexOf(activity) === -1) {
        curDay[slotKey].activity += '、' + activity
      }
      curSlot = slotKey
      continue
    }
    if (NON_SLOT_SECTION_RE.test(line)) {
      curSlot = null
      continue
    }
    if (curSlot && curDay && curDay[curSlot]) {
      curDay[curSlot].description += line + '\n'
    }
  }

  if (!days.length) return null

  const destination = guessDestination(userMessage) || guessDestination(answer)
  const dailyItinerary = days.map((d) => {
    const entry = { day: d.day, date: d.date, weather: d.weather }
    if (d.route) entry.route = d.route
    const keys = ['morning', 'afternoon', 'evening']
    for (let k = 0; k < keys.length; k++) {
      const slot = d[keys[k]]
      if (!slot) continue
      const clean = {}
      const fields = ['activity', 'location', 'transport', 'duration', 'cost']
      for (let f = 0; f < fields.length; f++) {
        if (slot[fields[f]]) clean[fields[f]] = slot[fields[f]]
      }
      if (slot.description) clean.description = cleanDescription(slot.description)
      entry[keys[k]] = clean
    }
    return entry
  })

  return {
    title: destination ? destination + days.length + '日游' : '旅行计划',
    destination,
    days: days.length,
    budget: '',
    weather_summary: '',
    daily_itinerary: dailyItinerary,
    tips: []
  }
}

// 去掉回答中的 JSON 块，保留给用户看的自然语言正文
function stripJson(text) {
  return text
    .replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/g, '')
    .replace(/\{\s*"title"[\s\S]*?\}\s*$/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

// 生成聊天窗口内的卡片摘要
function summarize(it) {
  if (!it) return null
  const days = Array.isArray(it.daily_itinerary) ? it.daily_itinerary
    : (Array.isArray(it.days) ? it.days : [])
  return {
    title: it.title || (it.destination ? it.destination + ' 旅行计划' : '旅行计划'),
    destination: it.destination || '',
    dayCount: it.days != null ? it.days : days.length,
    budget: it.budget || '',
    weatherSummary: it.weather_summary || ''
  }
}

// 把某一天的行程归一化为插槽数组（只保留存在的时间段）
function getSlots(day) {
  if (!day || typeof day !== 'object') return []
  const order = ['morning', 'afternoon', 'evening']
  const labels = { morning: '上午', afternoon: '下午', evening: '晚上' }
  const slots = []
  for (let i = 0; i < order.length; i++) {
    const key = order[i]
    const slot = day[key]
    if (slot && typeof slot === 'object') {
      slots.push({
        label: labels[key],
        activity: slot.activity || '',
        location: slot.location || '',
        transport: slot.transport || '',
        duration: slot.duration || '',
        cost: slot.cost || '',
        description: slot.description || ''
      })
    }
  }
  // 单行路线型回答兜底：当天无分时段安排时展示全天路线
  if (!slots.length && day.route) {
    slots.push({
      label: '全天',
      activity: day.route,
      location: '',
      transport: '',
      duration: '',
      cost: '',
      description: ''
    })
  }
  return slots
}

// 归一化天数列表（兼容 daily_itinerary 与 days 两种字段）
function getDayList(it) {
  if (!it) return []
  if (Array.isArray(it.daily_itinerary)) return it.daily_itinerary
  if (Array.isArray(it.days)) return it.days
  return []
}

module.exports = {
  looksLikeItinerary,
  extractItinerary,
  extractLocation,
  stripJson,
  summarize,
  getSlots,
  getDayList
}
