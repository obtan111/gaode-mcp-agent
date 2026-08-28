// 知识库管理 API：对应后端 /api/kb 系列接口

/** 知识库名称列表 [string] */
export async function listKbs() {
  const resp = await fetch('/api/kb')
  if (!resp.ok) throw new Error(`加载知识库列表失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 知识库分片列表（content 为前 300 字预览，附 content_len 总长） */
export async function listDocuments(kbName) {
  const resp = await fetch(`/api/kb/${encodeURIComponent(kbName)}/documents`)
  if (!resp.ok) throw new Error(`加载文档失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 单个分片完整内容（详情弹窗按需加载） */
export async function getDocument(docId) {
  const resp = await fetch(`/api/kb/documents/${docId}`)
  if (!resp.ok) throw new Error(`加载分片详情失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 上传文档并向量化，返回 {total, success, failed, failures} */
export async function uploadDocuments(kbName, files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const resp = await fetch(`/api/kb/${encodeURIComponent(kbName)}/documents`, {
    method: 'POST',
    body: form,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `上传失败: HTTP ${resp.status}`)
  }
  return resp.json()
}

/** 删除知识库，返回 {ok, deleted_chunks} */
export async function deleteKb(kbName) {
  const resp = await fetch(`/api/kb/${encodeURIComponent(kbName)}`, {
    method: 'DELETE',
  })
  if (!resp.ok) throw new Error(`删除失败: HTTP ${resp.status}`)
  return resp.json()
}

/** 检索调试：直连混合检索管道，不经 LLM，返回 {hits: [{score, content, metadata}]} */
export async function retrieve(query, kbName, topK = 5) {
  const resp = await fetch('/api/kb/retrieve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, kb_name: kbName || null, top_k: topK }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `检索失败: HTTP ${resp.status}`)
  }
  return resp.json()
}
