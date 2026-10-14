// Small helpers shared across pages: typing detection, focusing a linked row, deadline pressure, reload on refresh.
import { useEffect } from 'react'

export type Toast = { text: string; kind: 'ok' | 'err' }

export function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  if (!el) return false
  return el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable
}

/** Bring a linked element into view and flash it once (a link from Today to one draft or item). */
export function focusEl(id: string): boolean {
  const el = document.getElementById(id)
  if (!el) return false
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' })
  el.classList.remove('focus-flash')
  void el.offsetWidth // restart the animation
  el.classList.add('focus-flash')
  return true
}

/** The numeric id in a page focus like `d12` or `i4`, if it has that prefix. */
export const focusId = (focus: string, prefix: string): number | null => {
  const m = new RegExp(`^${prefix}(\\d+)$`).exec(focus)
  return m ? Number(m[1]) : null
}

/** How close a deadline is: 0 calm, 1 within a day, 2 within 3 hours, 3 within the hour, 4 due or late.
 * The same steps the companion's pings use (life/pressure.py). */
export function pressureOf(due: string, now = Date.now()): { stage: number; text: string } {
  const at = new Date(due.includes('T') ? due : due.replace(' ', 'T') + 'Z').getTime()
  const mins = Math.round((at - now) / 60_000)
  const span = (m: number) => (m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h` : `${Math.floor(m / 1440)}d`)
  if (mins <= 0) return { stage: 4, text: `late ${span(Math.max(1, -mins))}` }
  return { stage: mins <= 60 ? 3 : mins <= 180 ? 2 : mins <= 1440 ? 1 : 0, text: `in ${span(mins)}` }
}

/** Reload when something changed elsewhere (an undo, the companion switch). */
export function useRefresh(load: () => unknown) {
  useEffect(() => {
    const f = () => void load()
    window.addEventListener('tamadesk:refresh', f)
    return () => window.removeEventListener('tamadesk:refresh', f)
  }, [load])
}
