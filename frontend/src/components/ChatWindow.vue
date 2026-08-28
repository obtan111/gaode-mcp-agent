<!-- 聊天窗口：消息列表 + 多模态输入（图片/语音）+ 发送 -->

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import MessageItem from './MessageItem.vue'
import { blobToWav, recognizeSpeech } from '../api/voice.js'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
  model: { type: String, default: 'deepseek' },
})
const emit = defineEmits(['send'])

const MAX_IMAGE_MB = 5

const input = ref('')
const images = ref([]) // base64 data URI 列表（待发送）
const listEl = ref(null)
const fileInput = ref(null) // 隐藏的图片选择 input
const textareaEl = ref(null) // 输入框引用，用于发送后重置高度

// ---------- 录音状态 ----------
const recording = ref(false)
const asrBusy = ref(false)
let mediaRecorder = null
let mediaStream = null
let recordChunks = []

const isGenerating = computed(
  () =>
    props.streaming &&
    props.messages.length > 0 &&
    props.messages[props.messages.length - 1].role === 'assistant',
)

// 光标只在已有内容时显示；内容为空时由气泡内的"正在思考…"占位
const showCursor = computed(
  () => isGenerating.value && (props.messages[props.messages.length - 1]?.content || '').length > 0,
)

watch(
  () => props.messages,
  async () => {
    await nextTick()
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  },
  { deep: true },
)

function submit() {
  const text = input.value.trim()
  if ((!text && images.value.length === 0) || props.streaming) return
  // 图片随消息一起上抛，由 App.vue 组装请求
  emit('send', { text, images: [...images.value] })
  input.value = ''
  images.value = []
  if (textareaEl.value) textareaEl.value.style.height = 'auto'
}

/** 输入内容变化时按内容自动增高（上限 140px） */
function autoResize(event) {
  const el = event.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 140) + 'px'
}

/** 回车发送（Shift+Enter 换行） */
function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault() // 阻止 textarea 换行
    submit()
  }
}

// ---------- 图片上传 ----------
function pickImage() {
  fileInput.value.click()
}

function onImageChange(event) {
  const file = event.target.files[0]
  event.target.value = '' // 允许重复选择同一文件
  if (!file) return
  if (!file.type.startsWith('image/')) {
    alert('请选择图片文件')
    return
  }
  if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
    alert(`图片不能超过 ${MAX_IMAGE_MB}MB`)
    return
  }
  // FileReader 把图片读成 base64 data URI（与后端 images 字段格式一致）
  const reader = new FileReader()
  reader.onload = () => images.value.push(reader.result)
  reader.readAsDataURL(file)
}

function removeImage(index) {
  images.value.splice(index, 1)
}

// ---------- 语音输入（录音 → webm 转 WAV → ASR → 填入输入框） ----------
async function toggleMic() {
  if (props.streaming || asrBusy.value) return

  // 正在录音 → 停止并进入识别
  if (recording.value) {
    mediaRecorder.stop()
    return
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaRecorder = new MediaRecorder(mediaStream)
    recordChunks = []
    mediaRecorder.ondataavailable = (e) => recordChunks.push(e.data)
    mediaRecorder.onstop = onRecordStop
    mediaRecorder.start()
    recording.value = true
  } catch (err) {
    alert('无法访问麦克风：' + err.message)
  }
}

async function onRecordStop() {
  mediaStream.getTracks().forEach((t) => t.stop())
  recording.value = false
  asrBusy.value = true
  try {
    // 浏览器录音是 webm 容器，服务端 ASR 不认，先在本地转 WAV
    const wav = await blobToWav(new Blob(recordChunks))
    const res = await recognizeSpeech(wav, 'record.wav')
    if (res.text) {
      input.value = input.value ? `${input.value} ${res.text}` : res.text
    } else {
      alert('未识别到语音内容')
    }
  } catch (err) {
    alert('语音识别失败：' + err.message)
  } finally {
    asrBusy.value = false
  }
}
</script>

<template>
  <main class="chat">
    <div ref="listEl" class="list">
      <div v-if="messages.length === 0" class="empty">
        <h2>私人助手</h2>
        <p>基于 LangGraph + RAG + MCP 的个人智能助手</p>
      </div>

      <MessageItem
        v-for="(msg, i) in messages"
        :key="i"
        :msg="msg"
        :streaming="props.streaming && i === messages.length - 1 && msg.role === 'assistant'"
      />

      <div v-if="showCursor" class="cursor">▍</div>
    </div>

    <!-- 待发送图片预览条 -->
    <div v-if="images.length" class="preview-bar">
      <div v-for="(img, i) in images" :key="i" class="thumb">
        <img :src="img" alt="预览" />
        <button class="remove" @click="removeImage(i)">✕</button>
      </div>
    </div>

    <div class="input-bar">
      <!-- 图片上传（隐藏 input，由 📎 按钮触发） -->
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onImageChange" />
      <button class="icon-btn" title="上传图片" :disabled="props.streaming" @click="pickImage">📎</button>

      <!-- 麦克风：点击开始录音，再点结束并识别 -->
      <button
        class="icon-btn"
        :class="{ recording }"
        :title="recording ? '停止录音' : '语音输入'"
        :disabled="props.streaming || asrBusy"
        @click="toggleMic"
      >
        {{ asrBusy ? '⏳' : recording ? '⏹' : '🎤' }}
      </button>

      <!-- 自适应高度输入框：长消息不再被横向裁掉；Enter 发送、Shift+Enter 换行 -->
      <textarea
        ref="textareaEl"
        v-model="input"
        class="input-area"
        rows="1"
        :disabled="props.streaming"
        placeholder="输入消息，回车发送（Shift+Enter 换行）..."
        @input="autoResize"
        @keydown="onKeydown"
      ></textarea>
      <button :disabled="props.streaming || (!input.trim() && images.length === 0)" @click="submit">
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

.preview-bar {
  display: flex;
  gap: 8px;
  padding: 8px 10%;
}

.thumb {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb .remove {
  position: absolute;
  top: 0;
  right: 0;
  width: 20px;
  height: 20px;
  border: none;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  line-height: 1;
}

.input-bar {
  display: flex;
  gap: 8px;
  padding: 16px 10%;
  background: var(--bg-side);
  border-top: 1px solid var(--border);
}

.icon-btn {
  width: 44px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  font-size: 16px;
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn.recording {
  background: #ffe9e9;
  border-color: #e5484d;
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.6;
  }
}

.input-bar input:focus {
  border-color: var(--accent);
}

.input-area {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  resize: none; /* 禁止手动拖拽，靠内容自动增高 */
  font-family: inherit;
  line-height: 1.5;
  max-height: 140px; /* 超过后内部滚动，防止输入框无限长 */
  overflow-y: auto;
}

.input-area:focus {
  border-color: var(--accent);
}

.input-bar button[type=''],
.input-bar > button:last-of-type {
  padding: 0 24px;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
}

.input-bar > button:last-of-type:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
