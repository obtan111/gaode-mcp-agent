<!-- 聊天窗口：消息列表 + 状态提示 + 输入框 -->

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import MessageItem from './MessageItem.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
})
const emit = defineEmits(['send'])

const input = ref('') // 输入框内容（v-model 双向绑定）
const listEl = ref(null) // 消息列表 DOM 引用（ref="listEl"），用于滚动控制

// 计算最后一条助手消息是否正在生成中 → 控制光标动画显示
const isGenerating = computed(
  () =>
    props.streaming &&
    props.messages.length > 0 &&
    props.messages[props.messages.length - 1].role === 'assistant',
)

// watch 侦听器：消息数组变化后，等 DOM 更新完（nextTick）再滚到底部
watch(
  () => props.messages,
  async () => {
    await nextTick()
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  },
  { deep: true },
)

/** 发送：把输入框内容上抛给 App.vue，并清空输入框 */
function submit() {
  const text = input.value.trim()
  if (!text || props.streaming) return
  emit('send', text)
  input.value = ''
}
</script>

<template>
  <main class="chat">
    <div ref="listEl" class="list">
      <!-- 空状态提示 -->
      <div v-if="messages.length === 0" class="empty">
        <h2>私人助手</h2>
        <p>基于 LangGraph + RAG + MCP 的个人智能助手</p>
      </div>

      <MessageItem v-for="(msg, i) in messages" :key="i" :msg="msg" />

      <!-- 正在生成时显示打字光标 -->
      <div v-if="isGenerating" class="cursor">▍</div>
    </div>

    <div class="input-bar">
      <!-- @keydown.enter：回车发送；.enter 是 Vue 的事件修饰符语法 -->
      <input
        v-model="input"
        :disabled="props.streaming"
        placeholder="输入消息，回车发送..."
        @keydown.enter="submit"
      />
      <button :disabled="props.streaming || !input.trim()" @click="submit">
        {{ props.streaming ? '生成中' : '发送' }}
      </button>
    </div>
  </main>
</template>

<style scoped>
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-main);
  min-width: 0;
}

.list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 10%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty {
  text-align: center;
  margin-top: 20vh;
  color: var(--text-sub);
}

.empty h2 {
  color: var(--text-main);
  margin-bottom: 8px;
}

.cursor {
  font-size: 18px;
  color: var(--accent);
  animation: blink 1s step-start infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.input-bar {
  display: flex;
  gap: 10px;
  padding: 16px 10%;
  background: var(--bg-side);
  border-top: 1px solid var(--border);
}

.input-bar input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 14px;
  outline: none;
}

.input-bar input:focus {
  border-color: var(--accent);
}

.input-bar button {
  padding: 0 24px;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
}

.input-bar button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
