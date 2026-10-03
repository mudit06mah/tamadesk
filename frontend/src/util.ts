export type Toast = { text: string; kind: 'ok' | 'err' }

export function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  if (!el) return false
  return el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable
}
