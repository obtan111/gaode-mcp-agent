<!-- 知识库管理面板：列表 / 上传向量化 / 内容查看 / 删除 / 检索调试 -->
<!-- 对应 Gradio 版的"知识库管理"标签页 -->

<script setup>
import { onMounted, ref } from 'vue'
import { deleteKb, listDocuments, listKbs, retrieve, uploadDocuments } from '../api/kb.js'

const kbs = ref([])
const currentKb = ref('') // 当前选中的知识库
const newKbName = ref('') // 新建/上传目标名称
const docs = ref([]) // 当前知识库的分片列表
const loading = ref(false)
const statusMsg = ref('')

// 上传与检索
const fileInput = ref(null)
const uploadResult = ref('')
const uploading = ref(false)

const query = ref('')
const topK = ref(5)
const hits = ref([])
const retrieving = ref(false)

onMounted(refreshKbs)

async function refreshKbs() {
  try {
    kbs.value = await listKbs()
  } catch (err) {
    statusMsg.value = '❌ ' + err.message
  }
}

function selectKb(name) {
  currentKb.value = name
  newKbName.value = name
  docs.value = []
  hits.value = []
  loadDocs()
}

async function loadDocs() {
  if (!currentKb.value) return
  loading.value = true
  try {
    docs.value = await listDocuments(currentKb.value)
  } catch (err) {
    statusMsg.value = '❌ ' + err.message
  } finally {
    loading.value = false
  }
}

async function onUploadChange(event) {
  const files = [...event.target.files]
  event.target.value = ''
  // 目标知识库名：优先用输入框里的名字（可上传到新知识库）
  const target = (newKbName.value || currentKb.value || '').trim()
  if (!files.length) return
  if (!target) {
    alert('请先填写目标知识库名称')
    return
  }
  uploading.value = true
  uploadResult.value = '⏳ 上传并向量化中...'
  try {
    const res = await uploadDocuments(target, files)
    uploadResult.value = `✅ 成功 ${res.success} 个，失败 ${res.failed} 个` +
      (res.failures.length ? `\n${res.failures.join('\n')}` : '')
    currentKb.value = target
    await refreshKbs()
    await loadDocs()
  } catch (err) {
    uploadResult.value = '❌ ' + err.message
  } finally {
    uploading.value = false
  }
}

async function onDeleteKb() {
  if (!currentKb.value) return
  if (!confirm(`确定删除知识库「${currentKb.value}」及其全部分片？`)) return
  try {
    const res = await deleteKb(currentKb.value)
    statusMsg.value = `已删除 ${currentKb.value}（${res.deleted_chunks} 个分片）`
    currentKb.value = ''
    docs.value = []
    await refreshKbs()
  } catch (err) {
    statusMsg.value = '❌ ' + err.message
  }
}

async function doRetrieve() {
  if (!query.value.trim()) return
  retrieving.value = true
  try {
    const res = await retrieve(query.value, currentKb.value || null, topK.value)
    hits.value = res.hits
  } catch (err) {
    alert(err.message)
  } finally {
    retrieving.value = false
  }
}
</script>

<template>
  <main class="kb">
    <!-- 左栏：知识库选择 / 上传 / 管理 -->
    <aside class="panel">
      <h3>知识库管理</h3>

      <div class="field">
        <label>知识库名称（上传目标，可填新名字创建）</label>
        <input v-model="newKbName" placeholder="例如：长沙攻略" />
      </div>

      <input ref="fileInput" type="file" accept=".txt,.md,.markdown,.pdf,.json,.csv" multiple hidden @change="onUploadChange" />
      <button class="primary" :disabled="uploading" @click="fileInput.click()">
        {{ uploading ? '处理中...' : '📤 选择文件并上传向量化' }}
      </button>
      <pre v-if="uploadResult" class="status">{{ uploadResult }}</pre>

      <h4>已有知识库（点击查看内容）</h4>
      <ul class="kb-list">
        <li
          v-for="name in kbs"
          :key="name"
          :class="{ active: name === currentKb }"
          @click="selectKb(name)"
        >
          {{ name }}
        </li>
      </ul>
      <button class="ghost" :disabled="!currentKb" @click="onDeleteKb">🗑 删除当前知识库</button>
      <p v-if="statusMsg" class="status">{{ statusMsg }}</p>
    </aside>

    <!-- 右栏：内容查看 + 检索调试 -->
    <section class="content">
      <div class="card">
        <h3>知识库内容 {{ currentKb ? `「${currentKb}」` : '' }}</h3>
        <p v-if="!currentKb" class="hint">← 请先选择一个知识库</p>
        <p v-else-if="loading" class="hint">加载中...</p>
        <p v-else-if="docs.length === 0" class="hint">该知识库暂无内容</p>
        <table v-else class="doc-table">
          <thead>
            <tr>
              <th style="width: 40px">#</th>
              <th style="width: 180px">文件</th>
              <th>内容预览</th>
              <th style="width: 60px">页码</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in docs" :key="i">
              <td>{{ i + 1 }}</td>
              <td>{{ d.filename }}</td>
              <td class="preview">{{ d.content.slice(0, 120) }}{{ d.content.length > 120 ? '...' : '' }}</td>
              <td>{{ d.page_number || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>检索调试 <span class="hint-inline">（不经过 LLM，直接测试混合检索效果）</span></h3>
        <div class="retrieve-bar">
          <input v-model="query" placeholder="输入测试查询..." @keydown.enter="doRetrieve" />
          <select v-model.number="topK" style="width: 90px">
            <option :value="3">Top 3</option>
            <option :value="5">Top 5</option>
            <option :value="10">Top 10</option>
          </select>
          <button class="primary" :disabled="retrieving || !query.trim()" @click="doRetrieve">
            {{ retrieving ? '检索中' : '检索' }}
          </button>
        </div>
        <div v-for="(hit, i) in hits" :key="i" class="hit">
          <div class="hit-head">
            #{{ i + 1 }} · 分数 {{ hit.score.toFixed(4) }}
            <span v-if="hit.metadata && hit.metadata.file_name"> · {{ hit.metadata.file_name }}</span>
          </div>
          <div class="hit-body">{{ hit.content.slice(0, 300) }}{{ hit.content.length > 300 ? '...' : '' }}</div>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.kb {
  flex: 1;
  display: flex;
  gap: 16px;
  padding: 16px;
  background: var(--bg-main);
  overflow: hidden;
}

.panel {
  width: 280px;
  background: var(--bg-side);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}

.panel h3 {
  font-size: 15px;
}

.panel h4 {
  font-size: 13px;
  color: var(--text-sub);
  margin-top: 8px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 12px;
  color: var(--text-sub);
}

.field input,
.retrieve-bar input {
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  outline: none;
}

button.primary {
  padding: 9px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
}

button.primary:disabled {
  opacity: 0.5;
}

button.ghost {
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  font-size: 13px;
  color: #c73a3f;
}

button.ghost:disabled {
  opacity: 0.4;
}

.kb-list {
  list-style: none;
  flex: 1;
  overflow-y: auto;
}

.kb-list li {
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  margin-bottom: 2px;
}

.kb-list li:hover {
  background: #f0f2f5;
}

.kb-list li.active {
  background: #e8efff;
}

.status {
  font-size: 12px;
  color: var(--text-sub);
  white-space: pre-wrap;
  background: #f7f8fa;
  border-radius: 8px;
  padding: 8px;
}

.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  min-width: 0;
}

.card {
  background: var(--bg-side);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
}

.card h3 {
  font-size: 14px;
  margin-bottom: 12px;
}

.hint {
  font-size: 13px;
  color: var(--text-sub);
}

.hint-inline {
  font-size: 12px;
  font-weight: normal;
  color: var(--text-sub);
}

.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.doc-table th,
.doc-table td {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

.doc-table .preview {
  color: var(--text-sub);
  word-break: break-all;
}

.retrieve-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.retrieve-bar select {
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
}

.hit {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.hit-head {
  font-size: 12px;
  color: var(--accent);
  margin-bottom: 6px;
}

.hit-body {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-main);
  word-break: break-all;
}
</style>
