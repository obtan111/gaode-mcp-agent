// ============================================================
// 语音 API：TTS 合成 + ASR 识别 + 浏览器录音格式转换
//
// 关键知识点：浏览器 MediaRecorder 录出来的通常是 audio/webm（opus 编码），
// 服务端智谱 ASR 不认识这个容器格式，所以必须在浏览器里先解码再
// 重新编码成 WAV（PCM 16bit / 16kHz 单声道）。
// 流程：Blob → ArrayBuffer → AudioContext 解码 → 线性重采样 → WAV 字节流
// ============================================================

/** 文本合成语音，返回 {audio: "data:audio/mp3;base64,..."} */
export async function synthesizeSpeech(text) {
  const resp = await fetch('/api/voice/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `语音合成失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

/** 上传音频识别文字，返回 {text: "..."} */
export async function recognizeSpeech(blob, filename = 'record.wav') {
  const form = new FormData()
  form.append('file', blob, filename)
  const resp = await fetch('/api/voice/asr', { method: 'POST', body: form })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `语音识别失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

/** 把 MediaRecorder 产出的录音 Blob 转成 16kHz 单声道 WAV Blob */
export async function blobToWav(blob) {
  // decodeAudioData 会根据容器格式自动解析（webm/mp3/ogg 都支持）
  const arrayBuffer = await blob.arrayBuffer()
  const ctx = new (window.AudioContext || window.webkitAudioContext)()
  let audioBuffer
  try {
    audioBuffer = await ctx.decodeAudioData(arrayBuffer)
  } finally {
    ctx.close()
  }

  // 多声道取平均混成单声道
  const channels = audioBuffer.numberOfChannels
  const src = audioBuffer.getChannelData(0)
  if (channels > 1) {
    const ch1 = audioBuffer.getChannelData(1)
    for (let i = 0; i < src.length; i++) src[i] = (src[i] + ch1[i]) / 2
  }

  // 线性插值重采样到 16kHz（语音识别的标准采样率）
  const TARGET_RATE = 16000
  const ratio = audioBuffer.sampleRate / TARGET_RATE
  const outLength = Math.floor(src.length / ratio)
  const resampled = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) resampled[i] = src[Math.floor(i * ratio)]

  return new Blob([encodeWav(resampled, TARGET_RATE)], { type: 'audio/wav' })
}

/** 按RIFF 规范把 Float32 采样写成 WAV（PCM 16bit）字节流 */
function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const writeStr = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }

  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 块长度
  view.setUint16(20, 1, true) // PCM 格式
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 字节率 = 采样率 × 2字节
  view.setUint16(32, 2, true) // 块对齐
  view.setUint16(34, 16, true) // 位深
  writeStr(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  // Float32 [-1,1] → Int16
  let offset = 44
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buffer
}
