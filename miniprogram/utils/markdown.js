// 轻量 Markdown -> rich-text nodes 渲染器
// 支持：标题(#)、粗体(**)、斜体(*)、行内代码(`)、代码块(```)、
//       无序列表(-)、有序列表(1.)、链接([text](url))、段落
// 全部使用内联样式，保证 rich-text 组件内样式生效。

const SIZE_MAP = { 1: '40rpx', 2: '36rpx', 3: '32rpx', 4: '30rpx' }

function spanNode(text, style) {
  return {
    name: 'span',
    attrs: { style: style || '' },
    children: [{ type: 'text', text: text }]
  }
}

const INLINE_RE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]*\]\([^)]*\))/g

function parseInline(text) {
  const children = []
  let lastIndex = 0
  let match
  while ((match = INLINE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      children.push({ type: 'text', text: text.slice(lastIndex, match.index) })
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**') && token.length > 4) {
      children.push(spanNode(token.slice(2, -2), 'font-weight:600;'))
    } else if (token.startsWith('`') && token.endsWith('`') && token.length > 2) {
      children.push(spanNode(token.slice(1, -1),
        'background:#EEF1F6;font-family:monospace;padding:0 8rpx;border-radius:6rpx;font-size:24rpx;'))
    } else if (token.startsWith('*') && token.endsWith('*') && token.length > 2) {
      children.push(spanNode(token.slice(1, -1), 'font-style:italic;'))
    } else {
      const linkRe = /\[([^\]]*)\]\(([^)]*)\)/.exec(token)
      if (linkRe) {
        children.push({
          name: 'a',
          attrs: { href: linkRe[2], style: 'color:#3D6BFF;text-decoration:underline;' },
          children: [{ type: 'text', text: linkRe[1] }]
        })
      } else {
        children.push({ type: 'text', text: token })
      }
    }
    lastIndex = match.index + token.length
  }
  if (lastIndex < text.length) {
    children.push({ type: 'text', text: text.slice(lastIndex) })
  }
  return children
}

function render(text) {
  if (!text) {
    return [{ name: 'div', attrs: {}, children: [{ type: 'text', text: '' }] }]
  }
  const lines = text.split(/\r?\n/)
  const nodes = []
  let i = 0
  while (i < lines.length) {
    const trimmed = lines[i].trim()
    if (!trimmed) {
      i++
      continue
    }

    // 代码块
    if (trimmed.startsWith('```')) {
      const buf = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过闭合围栏
      nodes.push({
        name: 'div',
        attrs: {
          style: 'background:#F0F2F6;border-radius:12rpx;padding:20rpx;' +
            'margin:12rpx 0;font-family:monospace;font-size:24rpx;line-height:1.6;' +
            'white-space:pre-wrap;word-break:break-all;'
        },
        children: [{ type: 'text', text: buf.join('\n') }]
      })
      continue
    }

    // 标题
    const hMatch = /^(#{1,4})\s+(.*)$/.exec(trimmed)
    if (hMatch) {
      const size = SIZE_MAP[hMatch[1].length] || '30rpx'
      nodes.push({
        name: 'div',
        attrs: { style: 'font-weight:600;font-size:' + size + ';margin:18rpx 0 8rpx;' },
        children: parseInline(hMatch[2])
      })
      i++
      continue
    }

    // 无序列表（连续项合并为一个块）
    if (/^[-*•]\s+/.test(trimmed)) {
      const items = [trimmed.replace(/^[-*•]\s+/, '')]
      i++
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ''))
        i++
      }
      const children = []
      for (let k = 0; k < items.length; k++) {
        children.push({
          name: 'div',
          attrs: { style: 'margin:6rpx 0;padding-left:8rpx;' },
          children: [spanNode('• ', 'color:#3D6BFF;font-weight:600;margin-right:10rpx;')]
            .concat(parseInline(items[k]))
        })
      }
      nodes.push({ name: 'div', attrs: { style: 'margin:8rpx 0;' }, children: children })
      continue
    }

    // 有序列表
    const olMatch = /^\d+[.、)]\s+(.*)$/.exec(trimmed)
    if (olMatch) {
      const items = [olMatch[1]]
      i++
      while (i < lines.length) {
        const m = /^\d+[.、)]\s+(.*)$/.exec(lines[i].trim())
        if (!m) break
        items.push(m[1])
        i++
      }
      const children = []
      for (let k = 0; k < items.length; k++) {
        children.push({
          name: 'div',
          attrs: { style: 'margin:6rpx 0;padding-left:8rpx;' },
          children: parseInline((k + 1) + '. ' + items[k])
        })
      }
      nodes.push({ name: 'div', attrs: { style: 'margin:8rpx 0;' }, children: children })
      continue
    }

    // 普通段落（连续非空行合并为一段）
    const buf = [trimmed]
    i++
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i].trim()) &&
      !/^```/.test(lines[i].trim()) &&
      !/^[-*•]\s/.test(lines[i].trim()) &&
      !/^\d+[.、)]\s/.test(lines[i].trim())
    ) {
      buf.push(lines[i].trim())
      i++
    }
    nodes.push({
      name: 'div',
      attrs: { style: 'margin:10rpx 0;line-height:1.7;' },
      children: parseInline(buf.join(' '))
    })
  }
  return nodes
}

module.exports = { render, parseInline }
