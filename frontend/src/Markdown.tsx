// The small slice of markdown the assistant writes (paragraphs, lists, headings, **bold**,
// `code`, [links](url), bare URLs), rendered as React elements: never raw HTML.
import { useState, type ReactNode } from 'react'

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+)/g

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <b key={i}>{part.slice(2, -2)}</b>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/)
    const url = link?.[2] ?? (/^https?:\/\//.test(part) ? part : null)
    if (url) {
      return (
        <a key={i} href={url} target="_blank" rel="noreferrer">
          {link?.[1] ?? url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}
        </a>
      )
    }
    return part
  })
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(
      <Tag key={blocks.length}>
        {list.items.map((t, i) => (
          <li key={i}>{inline(t)}</li>
        ))}
      </Tag>,
    )
    list = null
  }
  let code: { lang: string; lines: string[] } | null = null
  for (const raw of text.split('\n')) {
    // ``` fences: code kept exactly as written (indentation, blank lines), with a copy button
    const fence = raw.match(/^\s*```\s*([\w+#.-]*)\s*$/)
    if (fence) {
      if (code) {
        blocks.push(<CodeBlock key={blocks.length} lang={code.lang} text={code.lines.join('\n')} />)
        code = null
      } else {
        flush()
        code = { lang: fence[1], lines: [] }
      }
      continue
    }
    if (code) {
      code.lines.push(raw)
      continue
    }
    const line = raw.trimEnd()
    const item = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/)
    if (item) {
      const ordered = !!item[1]
      if (!list || list.ordered !== ordered) flush()
      list ??= { ordered, items: [] }
      list.items.push(item[2])
      continue
    }
    flush()
    const h = line.match(/^#{1,4}\s+(.*)$/)
    if (h) blocks.push(<h4 key={blocks.length}>{inline(h[1])}</h4>)
    else if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>)
  }
  flush()
  if (code) blocks.push(<CodeBlock key={blocks.length} lang={code.lang} text={code.lines.join('\n')} />) // still streaming in
  return <div className="md">{blocks}</div>
}

function CodeBlock({ lang, text }: { lang: string; text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="code-block">
      <div className="code-bar">
        <span>{lang || 'code'}</span>
        <button
          className="btn tiny ghost"
          onClick={async () => {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1400)
          }}
        >
          {copied ? '✓ copied' : 'copy'}
        </button>
      </div>
      <pre>
        <code>{text}</code>
      </pre>
    </div>
  )
}
