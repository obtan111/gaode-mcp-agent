<!-- 侧栏：会话列表 + 新建按钮。纯"展示组件"：数据来自 props，行为通过 emit 上抛 -->

<script setup>
// defineProps / defineEmits 是 <script setup> 下的编译宏，无需 import
const props = defineProps({
  sessions: { type: Array, default: () => [] },
  currentId: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'new', 'delete'])
</script>

<template>
  <aside class="sidebar">
    <button class="new-btn" :disabled="props.disabled" @click="emit('new')">
      + 新建对话
    </button>

    <!-- v-for 渲染列表：key 帮 Vue 高效对比更新 -->
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
</style>
