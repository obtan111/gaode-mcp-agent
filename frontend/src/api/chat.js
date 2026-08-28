// ============================================================
// 流式聊天 API：消费后端 /api/chat/stream 的 SSE 事件流
//
// 为什么不能用浏览器自带的 EventSource？
//   EventSource 只支持 GET 请求，而我们的聊天接口是 POST + JSON body，
//   所以必须用 fetch 手动读取响应流、自己按 SSE 协议切分事件帧。
//   这段解析逻辑是 LLM 前端开发的通用套路，值得读懂每一行。
//
// SSE 协议格式回顾（后端 routers/chat.py 的 _sse 函数生成）：
//   event: token
//   data: {"delta": "增量文本"}
//   （每个事件以一个空行 \n\n 结尾）
// ============================================================

/**
 * 发起一次流式对话。
 *
 * @param {object}   opts
 * @param {string}   opts.message    用户输入
 * @param {string?}  opts.sessionId  会话 ID（为空则后端自动新建）
 * @param {string}   opts.modelType  模型类型 deepseek / deepseek-vl / zhipu / zhipu-4v
 * @param {string[]} opts.images     base64 data URI 图片列表（多模态输入）
 * @param {function} opts.onEvent    事件回调 onEvent(eventName, dataObject)
 * @returns {Promise<string>} 最终会话 ID（供后续请求复用）
 */
export async function streamChat({ message, sessionId, modelType, images, onEvent }) {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId || null,
      model_type: modelType || 'deepseek',
      images: images || [],
      tts: false,
    }),
  })

  if (!resp.ok || !resp.body) {
    throw new Error(`请求失败: HTTP ${resp.status}`)
  }

  // resp.body 是一个可读流（ReadableStream），
  // getReader() 拿到读取器，循环 read() 逐块接收二进制数据
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = '' // 网络分包不保证按事件边界到达，用缓冲区攒齐再切

  while (true) {
    const { done, value } = await reader.read()
    if (done) break // 流结束

    // stream:true 处理"一个汉字的字节被切在两个包里"的情况
    buffer += decoder.decode(value, { stream: true })

    // 循环切出所有完整事件帧（以 \n\n 分隔），剩余半截留在缓冲区
    let sep
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      handleFrame(frame, onEvent)
    }
  }

  return sessionId
}

/** 解析单个事件帧（"event: xxx" + "data: {...}" 两行），转成回调 */
function handleFrame(frame, onEvent) {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data += line.slice(5).trim()
    }
  }
  if (!data) return
  try {
    onEvent(event, JSON.parse(data))
  } catch (err) {
    console.warn('SSE 帧解析失败:', frame, err)
  }
}
