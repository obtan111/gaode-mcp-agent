<!-- ============================================================
App.vue：根组件。Vue 单文件组件（.vue）= 三段结构：
  <template>  界面模板（类 HTML，支持插值 {{ }} 和指令）
  <script setup>  组件逻辑（Vue3 推荐写法，顶层变量直接在模板可用）
  <style scoped>  样式（scoped 表示只作用于本组件，不污染全局）

本组件负责"状态管理"：所有数据（会话列表/当前消息）都定义在
这里，子组件通过 props 接收数据、通过 emit 事件通知变化。
这是 Vue 的单向数据流：数据向下流动，事件向上冒泡。
============================================================ -->

<script setup>
import { onMounted, ref } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatWindow from './components/ChatWindow.vue'
import { streamChat } from './api/chat.js'
import { deleteSession, getSession, listSessions } from './api/sessions.js'

// ref() 创建响应式数据：.value 变化时，用到它的界面部分自动更新
const sessions = ref([]) // 侧栏会话列表
const currentSessionId = ref('') // 当前会话
const messages = ref([]) // 消息数组 [{role:'user'|'assistant', content:'...'}]
const streaming = ref(false) // 是否正在生成回复（控制输入框禁用状态）

// 页面加载完成后（生命周期钩子）拉取会话列表
onMounted(loadSessions)

async function loadSessions() {
  try {
    sessions.value = await listSessions()
  } catch (err) {
    console.error(err)
  }
}

/** 点击侧栏会话：加载该会话历史消息 */
async function onSelectSession(id) {
  if (streaming.value || id === currentSessionId.value) return
  try {
    const session = await getSession(id)
    currentSessionId.value = id
    messages.value = (session.messages || []).filter(
      (m) => m.role === 'user' || m.role === 'assistant',
    )
  } catch (err) {
    console.error(err)
  }
}

/** 新建对话：只清空本地状态，新会话由后端在首次发消息时自动创建 */
function onNewSession() {
  if (streaming.value) return
  currentSessionId.value = ''
  messages.value = []
}

async function onDeleteSession(id) {
  try {
    await deleteSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (id === currentSessionId.value) onNewSession()
  } catch (err) {
    console.error(err)
  }
}

/** 发送消息：核心流程 —— 先放用户消息占位，再消费 SSE 事件流增量更新 */
async function onSend(text) {
  if (streaming.value || !text.trim()) return
  streaming.value = true

  // [...数组] 展开再追加：必须整体替换 ref 的 .value 内部内容才能被侦测到
  // （这里直接 push 也可以，因为 ref 深层响应式，但重赋值写法意图更清晰）
  messages.value = [
    ...messages.value,
    { role: 'user', content: text },
    { role: 'assistant', content: '' }, // 助手消息占位，token 到达时填充
  ]

  // onEvent 回调里拿到的 data 由后端 iter_chat_events 的事件协议决定
  const onEvent = (event, data) => {
    if (event === 'token') {
      // 把增量文本追加到最后一条（占位的助手）消息上 → 界面自动跟着变
      const last = messages.value[messages.value.length - 1]
      last.content += data.delta
    } else if (event === 'done') {
      // 用后端返回的完整回答覆盖，保证最终一致性
      messages.value[messages.value.length - 1].content = data.answer
      currentSessionId.value = data.session_id
    } else if (event === 'error') {
      messages.value[messages.value.length - 1].content = `⚠️ ${data.message}`
    }
    // status 事件（节点切换）由 ChatWindow 内部展示，见其组件
  }

  try {
    await streamChat({ message: text, sessionId: currentSessionId.value, onEvent })
    // 对话完成后刷新侧栏（新会话出现在列表里、标题已生成）
    await loadSessions()
  } catch (err) {
    messages.value[messages.value.length - 1].content = `⚠️ 连接失败：${err.message}`
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <div class="layout">
    <!-- 子组件标签上的属性=props 传数据，@事件=监听子组件 emit 的事件 -->
    <Sidebar
      :sessions="sessions"
      :current-id="currentSessionId"
      :disabled="streaming"
      @select="onSelectSession"
      @new="onNewSession"
      @delete="onDeleteSession"
    />
    <ChatWindow :messages="messages" :streaming="streaming" @send="onSend" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}
</style>
