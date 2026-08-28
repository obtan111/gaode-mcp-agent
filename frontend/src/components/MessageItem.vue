<!-- 单条消息：用户右侧蓝底气泡；助手左侧白底 + Markdown 渲染 + TTS 播放按钮 -->

<script setup>
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { synthesizeSpeech } from '../api/voice.js'

const props = defineProps({
  msg: { type: Object, required: true }, // {role, content}
  streaming: { type: Boolean, default: false }, // 本条是否正在流式生成
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
        <!-- 流式生成中按纯文本渲染：未闭合的代码围栏/表格会让
             markdown 半成品形态残缺，纯文本保证动画过程始终完整可读，
             生成完成后一次性切换为 markdown 排版 -->
        <div v-if="props.msg.role === 'assistant' && !props.streaming" class="md" v-html="renderedHtml" />
        <div v-else class="plain">{{ props.msg.content }}</div>
        <!-- 用户消息附带的上传图片缩略图 -->
        <div v-if="props.msg.role === 'user' && props.msg.images && props.msg.images.length" class="msg-imgs">
          <img v-for="(img, i) in props.msg.images" :key="i" :src="img" alt="上传图片" />
        </div>
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

.msg-imgs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.msg-imgs img {
  max-width: 180px;
  max-height: 180px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  display: block;
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

/* ---------- markdown 渲染样式 ----------
   大模型回答常包含表格/标题/引用/代码，markdown-it 只输出裸标签，
   没有这套样式时页面会挤成一团，观感残缺。 */

.md {
  overflow-wrap: anywhere; /* 长 URL/长单词强制换行，防撑破气泡 */
}

.md :deep(p) {
  margin: 0 0 10px;
}

.md :deep(p:last-child) {
  margin-bottom: 0;
}

.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: 14px 0 8px;
  line-height: 1.4;
}

.md :deep(h1) {
  font-size: 20px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}

.md :deep(h2) {
  font-size: 17px;
}

.md :deep(h3) {
  font-size: 15px;
}

.md :deep(h4) {
  font-size: 14px;
}

/* 表格：默认无边框，需显式补全 */
.md :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  width: 100%;
  font-size: 13px;
  display: block; /* 窄屏允许横向滚动 */
  overflow-x: auto;
}

.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap; /* 表格列不折行，配合横向滚动保持对齐 */
}

.md :deep(th) {
  background: #f6f8fa;
  font-weight: 600;
}

/* 引用块 */
.md :deep(blockquote) {
  margin: 10px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--accent);
  background: #f6f9ff;
  color: var(--text-sub);
  border-radius: 0 6px 6px 0;
}

.md :deep(blockquote p) {
  margin: 4px 0;
}

/* 链接 */
.md :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.md :deep(a:hover) {
  text-decoration: underline;
}

/* 行内代码 */
.md :deep(code:not(pre code)) {
  background: #eef1f5;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  color: #d63384;
}

/* 代码块 */
.md :deep(pre) {
  background: #f6f8fa;
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
}

.md :deep(pre code) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  color: inherit;
  background: none;
  padding: 0;
}

/* 列表 */
.md :deep(ul),
.md :deep(ol) {
  padding-left: 22px;
  margin: 6px 0;
}

.md :deep(li) {
  margin: 3px 0;
}

/* 分隔线 */
.md :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 12px 0;
}

/* 图片限制在气泡内 */
.md :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}

/* 加粗强调 */
.md :deep(strong) {
  font-weight: 600;
}
</style>
