<!-- 单条消息：用户右侧蓝底气泡；助手左侧白底 + Markdown 渲染 + TTS 播放按钮 -->

<script setup>
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { synthesizeSpeech } from '../api/voice.js'

const props = defineProps({
  msg: { type: Object, required: true }, // {role, content}
})

const md = new MarkdownIt({ breaks: true })
const renderedHtml = computed(() => md.render(props.msg.content || ''))

// ---------- TTS 播放 ----------
// 状态机：未合成 → 合成中(ttsLoading) → 可播放 → 播放中(playing)
const ttsLoading = ref(false)
const playing = ref(false)
let audioEl = null

async function toggleTts() {
  // 播放中再点 = 暂停
  if (playing.value && audioEl) {
    audioEl.pause()
    playing.value = false
    return
  }
  // 已合成过 → 直接复用缓存，不重复调接口
  if (audioEl) {
    audioEl.play()
    playing.value = true
    return
  }
  if (!props.msg.content || props.msg.content.length < 2) return
  ttsLoading.value = true
  try {
    const res = await synthesizeSpeech(props.msg.content)
    audioEl = new Audio(res.audio)
    audioEl.onended = () => (playing.value = false)
    await audioEl.play()
    playing.value = true
  } catch (err) {
    alert('语音合成失败：' + err.message)
  } finally {
    ttsLoading.value = false
  }
}
</script>

<template>
  <div class="row" :class="props.msg.role">
    <div class="bubble-wrap">
      <div class="bubble">
        <div v-if="props.msg.role === 'assistant'" class="md" v-html="renderedHtml" />
        <div v-else class="plain">{{ props.msg.content }}</div>
      </div>

      <!-- 助手消息下方悬浮工具条 -->
      <div v-if="props.msg.role === 'assistant' && props.msg.content" class="tools">
        <button
          class="tool-btn"
          :title="playing ? '暂停' : '播放语音'"
          :disabled="ttsLoading"
          @click="toggleTts"
        >
          {{ ttsLoading ? '⏳' : playing ? '⏸' : '🔊' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
}

.row.user {
  justify-content: flex-end;
}

.bubble-wrap {
  max-width: 80%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user .bubble-wrap {
  align-items: flex-end;
}

.bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.user .bubble {
  background: var(--bg-user-bubble);
  color: #fff;
  white-space: pre-wrap;
}

.assistant .bubble {
  background: var(--bg-ai-bubble);
  border: 1px solid var(--border);
}

.tools {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.bubble-wrap:hover .tools {
  opacity: 1;
}

.tool-btn {
  border: none;
  background: none;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 6px;
  color: var(--text-sub);
}

.tool-btn:hover:not(:disabled) {
  background: #eef1f5;
  color: var(--text-main);
}

.tool-btn:disabled {
  cursor: wait;
}

/* markdown 渲染出来的元素间距微调（:deep 穿透 scoped 作用域） */
.md :deep(p) {
  margin: 0 0 8px;
}

.md :deep(p:last-child) {
  margin-bottom: 0;
}

.md :deep(pre) {
  background: #f6f8fa;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}

.md :deep(code) {
  font-family: Consolas, monospace;
  font-size: 13px;
}

.md :deep(ul),
.md :deep(ol) {
  padding-left: 20px;
}
</style>
