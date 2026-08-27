<!-- 单条消息：用户消息右侧蓝底气泡，助手消息左侧白底气泡 + Markdown 渲染 -->

<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  msg: { type: Object, required: true }, // {role, content}
})

// markdown-it：把助手的 Markdown 文本转成 HTML（默认会转义 HTML 标签，防注入）
const md = new MarkdownIt({ breaks: true })

// computed 计算属性：依赖变化时自动重算——流式过程中 content 不断追加，
// 这里每次都会重新渲染 Markdown，实现"边生成边格式化"的效果
const renderedHtml = computed(() => md.render(props.msg.content || ''))
</script>

<template>
  <div class="row" :class="props.msg.role">
    <div class="bubble">
      <!-- 助手消息渲染 HTML；用户消息按纯文本保留换行 -->
      <div v-if="props.msg.role === 'assistant'" class="md" v-html="renderedHtml" />
      <div v-else class="plain">{{ props.msg.content }}</div>
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

.bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
}

.user .bubble {
  background: var(--bg-user-bubble);
  color: #fff;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant .bubble {
  background: var(--bg-ai-bubble);
  border: 1px solid var(--border);
}

/* markdown 渲染出来的元素间距微调（:deep 穿透 scoped 样式作用域） */
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
