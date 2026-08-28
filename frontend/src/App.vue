<!-- ============================================================
App.vue：根组件。Vue 单文件组件（.vue）= 三段结构：
  <template>  界面模板（类 HTML，支持插值 {{ }} 和指令）
  <script setup>  组件逻辑（Vue3 推荐写法，顶层变量直接在模板可用）
  <style scoped>  样式（scoped 表示只作用于本组件，不污染全局）

本组件负责"状态管理"：所有数据（会话列表/当前消息/模型/视图）都定义
在这里，子组件通过 props 接收数据、通过 emit 事件通知变化。
这是 Vue 的单向数据流：数据向下流动，事件向上冒泡。
============================================================ -->

<script setup>
import { onMounted, ref } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatWindow from './components/ChatWindow.vue'
import KbPanel from './components/KbPanel.vue'
import { streamChat } from './api/chat.js'
import { deleteSession, getSession, listSessions } from './api/sessions.js'

// ref() 创建响应式数据：.value 变化时，用到它的界面部分自动更新
const view = ref('chat') // chat | kb 两个视图
const sessions = ref([]) // 侧栏会话列表
const currentSessionId = ref('') // 当前会话
const messages = ref([]) // 消息数组 [{role:'user'|'assistant', content:'...'}]
const streaming = ref(false) // 是否正在生成回复（控制输入框禁用状态）
const model = ref('deepseek') // 当前选择的模型

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

/** 导出当前会话为 Markdown 文件（纯前端，Blob 下载） */
function onExport() {
  if (messages.value.length === 0) {
    alert('当前会话为空，没有可导出的内容')
    return
  }
  let md = '# 会话导出\n\n'
  for (const m of messages.value) {
    md += (m.role === 'user' ? '## 用户\n' : '## 助手\n') + m.content + '\n\n'
  }
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `会话导出_${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '')}.md`
  link.click()
  URL.revokeObjectURL(link.href)
}

/** 发送消息：核心流程 —— 先放用户消息占位，再消费 SSE 事件流增量更新 */
async function onSend({ text, images }) {
  if (streaming.value) return
  streaming.value = true

  // 显示的消息：图片以 Markdown 语法附在消息末尾（后端也会拼接图片提示）
  const displayContent = images.length
    ? `${text}\n\n[图片×${images.length}]`
    : text
  messages.value = [
    ...messages.value,
    { role: 'user', content: displayContent },
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
  }

  try {
    await streamChat({
      message: text || '[图片]',
      sessionId: currentSessionId.value,
      modelType: model.value,
      images,
      onEvent,
    })
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
      v-model:model="model"
      :sessions="sessions"
      :current-id="currentSessionId"
      :disabled="streaming"
      :view="view"
      @select="onSelectSession"
      @new="onNewSession"
      @delete="onDeleteSession"
      @export="onExport"
      @change-view="view = $event"
    />
    <!-- 视图切换：知识库面板 / 聊天窗口 -->
    <KbPanel v-if="view === 'kb'" />
    <ChatWindow
      v-else
      :messages="messages"
      :streaming="streaming"
      :model="model"
      @send="onSend"
    />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}
</style>
