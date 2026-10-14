// One themed tooltip for the whole app. Every `title` shows as a small ink-outlined card instead of
// the browser's black box: after a short hover, or straight away on keyboard focus. While it shows,
// the title is held off the element (so the native one never doubles up) and put back on leave.
// "main text · a hint" shows the hint on its own quieter line.

import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

type Tip = { text: string; x: number; top: number; bottom: number; n: number }

const WAIT = 380 // ms of hovering before a tip shows; moving on to the next one soon after is instant
const WARM = 500
const GAP = 9

export function Tips() {
  const [tip, setTip] = useState<Tip | null>(null)
  useEffect(() => {
    let el: HTMLElement | null = null
    let text = ''
    let timer = 0
    let shown = false
    let warmUntil = 0
    let n = 0
    const release = () => {
      clearTimeout(timer)
      if (el && !el.hasAttribute('title')) el.setAttribute('title', text)
      if (shown) warmUntil = performance.now() + WARM
      el = null
      shown = false
      setTip(null)
    }
    const hold = (next: HTMLElement, wait: number) => {
      if (next === el) return
      release()
      const t = next.getAttribute('title')?.trim()
      if (!t) return
      el = next
      text = next.getAttribute('title')!
      next.removeAttribute('title')
      // an icon-only button keeps its name for screen readers
      if (!next.hasAttribute('aria-label') && !next.textContent?.trim()) next.setAttribute('aria-label', t)
      timer = window.setTimeout(
        () => {
          if (!next.isConnected) return release()
          const r = next.getBoundingClientRect()
          shown = true
          setTip({ text: t, x: r.left + r.width / 2, top: r.top, bottom: r.bottom, n: ++n })
        },
        performance.now() < warmUntil ? 0 : wait,
      )
    }
    const over = (e: PointerEvent) => {
      if (e.pointerType === 'touch') return
      const target = e.target as Element
      const found = target.closest?.<HTMLElement>('[title]') ?? null
      if (el?.contains(target) && !(found && el.contains(found))) return // still on the same thing
      if (found) hold(found, WAIT)
      else release()
    }
    const focus = (e: FocusEvent) => {
      const t = e.target as HTMLElement
      if (t.matches?.(':focus-visible[title]')) hold(t, 0)
    }
    const blur = (e: FocusEvent) => e.target === el && release()
    const leave = (e: PointerEvent) => !e.relatedTarget && release()
    const opts = { capture: true, passive: true }
    document.addEventListener('pointerover', over, opts)
    document.addEventListener('pointerout', leave, opts)
    document.addEventListener('focusin', focus, true)
    document.addEventListener('focusout', blur, true)
    for (const ev of ['pointerdown', 'keydown', 'scroll', 'wheel'] as const) document.addEventListener(ev, release, opts)
    return () => {
      release()
      document.removeEventListener('pointerover', over, opts)
      document.removeEventListener('pointerout', leave, opts)
      document.removeEventListener('focusin', focus, true)
      document.removeEventListener('focusout', blur, true)
      for (const ev of ['pointerdown', 'keydown', 'scroll', 'wheel'] as const) document.removeEventListener(ev, release, opts)
    }
  }, [])
  return <AnimatePresence>{tip && <TipCard key={tip.n} tip={tip} />}</AnimatePresence>
}

function TipCard({ tip }: { tip: Tip }) {
  const reduce = useReducedMotion()
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number; arrow: number; below: boolean } | null>(null)
  useLayoutEffect(() => {
    const box = ref.current
    if (!box) return
    const [width, height] = [box.offsetWidth, box.offsetHeight] // unscaled, unlike the bounding box
    const below = tip.top - height - GAP < 8 // no room above: hang it under instead
    const left = Math.min(Math.max(tip.x - width / 2, 8), window.innerWidth - width - 8)
    setPos({ left, top: below ? tip.bottom + GAP : tip.top - height - GAP, arrow: tip.x - left, below })
  }, [tip])
  const [main, ...hints] = tip.text.split(' · ')
  const lift = pos?.below ? -4 : 4
  return (
    <motion.div
      ref={ref}
      role="tooltip"
      className={`tip ${pos?.below ? 'below' : ''}`}
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? 0, ['--arrow' as string]: `${pos?.arrow ?? 0}px`, transformOrigin: `${pos?.arrow ?? 0}px ${pos?.below ? 'top' : 'bottom'}` }}
      initial={reduce ? { opacity: 0 } : { opacity: 0, y: lift, scale: 0.94 }}
      animate={pos ? { opacity: 1, y: 0, scale: 1 } : undefined}
      exit={{ opacity: 0, transition: { duration: 0.08 } }}
      transition={reduce ? { duration: 0.12 } : { type: 'spring', stiffness: 520, damping: 28, mass: 0.6 }}
    >
      {main}
      {hints.length > 0 && <span className="tip-hint">{hints.join(' · ')}</span>}
    </motion.div>
  )
}
