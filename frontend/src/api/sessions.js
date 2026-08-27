// 会话管理 API：对应后端 /api/sessions 的增删查
// async/await 语法：await 等待网络请求完成，代码写起来像同步逻辑

/** 获取会话列表 [{id, title, created_at}, ...] */
export async function listSessions() {
  const resp = await fetch('/api/sessions?page=1&page_size=50')
  if (!resp.ok) throw new Error(`加载会话列表失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 加载某个会话的完整消息历史 */
export async function getSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`)
  if (!resp.ok) throw new Error(`加载会话失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 删除会话 */
export async function deleteSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!resp.ok) throw new Error(`删除会话失败: HTTP ${resp.status}`)
  return resp.json()
}
