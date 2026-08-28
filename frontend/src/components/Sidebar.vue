<!-- 侧栏：视图切换 + 会话列表 + 模型选择。纯展示组件：props 进、emit 出 -->

<script setup>
const props = defineProps({
  sessions: { type: Array, default: () => [] },
  currentId: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  view: { type: String, default: 'chat' }, // chat | kb
  model: { type: String, default: 'deepseek' },
})
const emit = defineEmits(['select', 'new', 'delete', 'export', 'change-view', 'update:model'])

// 与后端 ModelFactory 支持的模型保持一致
const MODELS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'deepseek-vl', label: 'DeepSeek 视觉' },
  { value: 'zhipu', label: '智谱 GLM-4' },
  { value: 'zhipu-4v', label: '智谱 GLM-4V 视觉' },
]
</script>

<template>
  <aside class="sidebar">
    <!-- 顶部视图切换 -->
    <div class="view-tabs">
      <button :class="{ active: props.view === 'chat' }" @click="emit('change-view', 'chat')">
        对话
      </button>
      <button :class="{ active: props.view === 'kb' }" @click="emit('change-view', 'kb')">
        知识库
      </button>
    </div>

    <!-- 对话视图的操作区 -->
    <template v-if="props.view === 'chat'">
      <button class="new-btn" :disabled="props.disabled" @click="emit('new')">
        + 新建对话
      </button>

      <ul class="session-list">
        <li
          v-for="s in props.sessions"
          :key="s.id"
          :class="['item', { active: s.id === props.currentId }]"
          @click="emit('select', s.id)"
        >
          <span class="title">{{ s.title || '新对话' }}</span>
          <button class="del" title="删除" @click.stop="emit('delete', s.id)">✕</button>
        </li>
      </ul>

      <button class="export-btn" :disabled="props.disabled" @click="emit('export')">
        📤 导出当前会话
      </button>

      <div class="model-box">
        <label>模型</label>
        <!-- select 的 value 变化时 emit 给父组件修改 model 状态 -->
        <select :value="props.model" :disabled="props.disabled" @change="emit('update:model', $event.target.value)">
          <option v-for="m in MODELS" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 250px;
  background: var(--bg-side);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 10px;
}

.view-tabs {
  display: flex;
  gap: 6px;
}

.view-tabs button {
  flex: 1;
  padding: 8px 0;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-sub);
}

.view-tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.new-btn {
  padding: 10px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
}

.new-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.session-list {
  list-style: none;
  overflow-y: auto;
  flex: 1;
}

.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  margin-bottom: 4px;
}

.item:hover {
  background: #f0f2f5;
}

.item.active {
  background: #e8efff;
}

.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del {
  border: none;
  background: none;
  color: var(--text-sub);
  visibility: hidden;
}

.item:hover .del {
  visibility: visible;
}

.del:hover {
  color: #e5484d;
}

.export-btn {
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  font-size: 13px;
  color: var(--text-main);
}

.export-btn:disabled {
  opacity: 0.5;
}

.model-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.model-box label {
  font-size: 12px;
  color: var(--text-sub);
}

.model-box select {
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  background: #fff;
}
</style>
