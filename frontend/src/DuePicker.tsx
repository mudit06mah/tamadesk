// Pick a deadline by winding a clock: drag the hand round (one turn is twelve hours, and winding past
// midnight moves on to the next day), tap a day, or type it in words. Arrow keys and the mouse wheel
// step 15 minutes, Page Up/Down an hour. Sends an exact local time ('YYYY-MM-DD HH:MM').
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { localMinute, pad2, utc } from './api'
import { useFx } from './fx/Fx'
import { pressureOf } from './util'

const STEP = 15 // minutes per notch
const addMin = (d: Date, m: number) => new Date(d.getTime() + m * 60_000)
const midnight = (offset = 0) => {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + offset)
  return d
}
const snap = (d: Date) => {
  const x = new Date(d)
  x.setSeconds(0, 0)
  x.setMinutes(Math.round(x.getMinutes() / STEP) * STEP)
  return x
}
/** The first notch still to come: a deadline can't be in the past. */
const earliest = () => snap(addMin(new Date(), STEP / 2 + 1))
const atLeast = (d: Date) => (d < earliest() ? earliest() : d)
/** Where the hand points on a 12-hour face: 0 at the top, clockwise, in degrees. */
const angleOf = (d: Date) => ((d.getHours() % 12) * 60 + d.getMinutes()) / 2
const wrap = (deg: number) => ((deg + 540) % 360) - 180 // the short way round, -180..180
const isNight = (d: Date) => d.getHours() < 6 || d.getHours() >= 18
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()

/** Where the hand starts: the deadline it has, else today at 5pm, else (that's under an hour away)
 * the top of the hour after next, still today. Only past 11pm does it start on tomorrow. */
function startAt(due: string | null): Date {
  if (due) return atLeast(utc(due))
  const five = midnight()
  five.setHours(17)
  if (five.getTime() - Date.now() > 3_600_000) return five
  const soon = new Date()
  soon.setHours(soon.getHours() + 2, 0, 0, 0)
  return sameDay(soon, new Date()) ? soon : earliest()
}

export function DuePicker({ anchor, due, onSet, onClose }: { anchor: HTMLElement; due: string | null; onSet: (when: string) => Promise<void>; onClose: () => void }) {
  const fx = useFx()
  const reduce = useReducedMotion()
  const [at, setAt] = useState(() => startAt(due))
  const [words, setWords] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number; up: boolean } | null>(null)
  const pop = useRef<HTMLDivElement>(null)
  const dial = useRef<SVGSVGElement>(null)
  const atRef = useRef(at)
  atRef.current = at
  const drag = useRef<{ last: number; turned: number; from: Date } | null>(null)

  // the hand's angle, unwrapped so stepping past 12 never spins it the long way back
  const prevRot = useRef(angleOf(at))
  const target = angleOf(at)
  const rot = target + 360 * Math.round((prevRot.current - target) / 360)
  prevRot.current = rot

  const go = (next: Date) => {
    const d = atLeast(next)
    if (d.getTime() === atRef.current.getTime()) return
    fx.sound('tick')
    setAt(d)
  }

  // hang under the chip (over it if there's no room), inside the window; follow it on scroll
  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.getBoundingClientRect()
      const box = pop.current
      if (!box) return
      // offset sizes, not the bounding box: that one is still scaled down while it springs open
      const [w, h] = [box.offsetWidth, box.offsetHeight]
      const up = a.bottom + h + 12 > window.innerHeight && a.top - h - 12 > 0
      const left = Math.min(Math.max(a.right - w, 8), window.innerWidth - w - 8)
      setPos({ left, top: up ? a.top - h - 8 : a.bottom + 8, up })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchor])

  useEffect(() => {
    dial.current?.focus({ preventScroll: true })
    const outside = (e: PointerEvent) => {
      const t = e.target as Node
      if (!pop.current?.contains(t) && !anchor.contains(t)) onClose()
    }
    // the wheel winds the clock instead of scrolling the page (needs a non-passive listener)
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      go(addMin(atRef.current, e.deltaY < 0 ? STEP : -STEP))
    }
    const svg = dial.current
    document.addEventListener('pointerdown', outside, true)
    svg?.addEventListener('wheel', wheel, { passive: false })
    return () => {
      document.removeEventListener('pointerdown', outside, true)
      svg?.removeEventListener('wheel', wheel)
    }
  }, [anchor, onClose])

  // a day further out than the strip shows gets its own chip: keep it in view
  const day = at.toDateString()
  useEffect(() => {
    // by hand: scrollIntoView would scroll the page too, and the clock would move under the pointer
    const strip = pop.current?.querySelector<HTMLElement>('.due-days')
    const on = strip?.querySelector<HTMLElement>('.due-day.on')
    if (!strip || !on) return
    if (on.offsetLeft < strip.scrollLeft) strip.scrollLeft = on.offsetLeft
    else if (on.offsetLeft + on.offsetWidth > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = on.offsetLeft + on.offsetWidth - strip.clientWidth
  }, [day])

  const pointerAngle = (e: React.PointerEvent): number | null => {
    const r = dial.current!.getBoundingClientRect()
    const dx = e.clientX - (r.left + r.width / 2)
    const dy = e.clientY - (r.top + r.height / 2)
    if (Math.hypot(dx, dy) < r.width * 0.08) return null // too close to the middle to tell
    return ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360
  }
  const down = (e: React.PointerEvent<SVGSVGElement>) => {
    const a = pointerAngle(e)
    if (a === null) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    // a tap moves the hand there (the short way round), then dragging winds on from it
    const turned = wrap(a - angleOf(atRef.current))
    drag.current = { last: a, turned, from: atRef.current }
    setDragging(true)
    go(snap(addMin(atRef.current, turned * 2)))
  }
  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    const a = d && pointerAngle(e)
    if (!d || a === null || a === undefined) return
    d.turned += wrap(a - d.last)
    d.last = a
    go(snap(addMin(d.from, d.turned * 2))) // 360 degrees = 720 minutes
  }
  const up = () => {
    drag.current = null
    setDragging(false)
  }
  const key = (e: React.KeyboardEvent) => {
    const steps: Record<string, number> = { ArrowUp: STEP, ArrowRight: STEP, ArrowDown: -STEP, ArrowLeft: -STEP, PageUp: 60, PageDown: -60 }
    if (e.key in steps) {
      e.preventDefault()
      go(addMin(at, steps[e.key] * (e.shiftKey ? 4 : 1)))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      void save(localMinute(at))
    }
  }
  const save = async (when: string) => {
    setBusy(true)
    try {
      await onSet(when)
    } finally {
      setBusy(false)
    }
  }

  const days = Array.from({ length: 8 }, (_, i) => midnight(i))
  if (!days.some((d) => sameDay(d, at))) days.push(new Date(at.getFullYear(), at.getMonth(), at.getDate()))
  const pickDay = (d: Date) => {
    const x = new Date(d)
    x.setHours(at.getHours(), at.getMinutes())
    go(x)
  }
  const now = new Date()
  const half = at.getHours() < 12 ? 0 : 12
  const label = `${at.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}, ${pad2(at.getHours())}:${pad2(at.getMinutes())}`
  const away = pressureOf(at.toISOString(), now.getTime()).text

  return createPortal(
    <motion.div
      ref={pop}
      className="due-pop"
      role="dialog"
      aria-label="Deadline"
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? 0, transformOrigin: pos?.up ? 'bottom right' : 'top right' }}
      initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.92, y: pos?.up ? 6 : -6 }}
      animate={pos ? { opacity: 1, scale: 1, y: 0 } : undefined}
      exit={{ opacity: 0, scale: reduce ? 1 : 0.96, transition: { duration: 0.1 } }}
      transition={reduce ? { duration: 0.12 } : { type: 'spring', stiffness: 460, damping: 30 }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onClose()
          anchor.focus()
        }
      }}
    >
      <div className="due-days" role="group" aria-label="Day">
        {days.map((d, i) => (
          <button key={d.toDateString()} type="button" className={`due-day ${sameDay(d, at) ? 'on' : ''} ${i === 0 ? 'today' : ''}`} title={i === 0 ? 'today' : i === 1 ? 'tomorrow' : undefined} onClick={() => pickDay(d)} disabled={i === 0 && earliest() >= midnight(1)}>
            <span>{d.toLocaleDateString(undefined, { weekday: 'short' }).toLowerCase()}</span>
            <b>{d.getDate()}</b>
          </button>
        ))}
      </div>
      <svg
        ref={dial}
        className={`due-dial ${isNight(at) ? 'night' : ''} ${dragging ? 'dragging' : ''}`}
        viewBox="-80 -80 160 160"
        tabIndex={0}
        role="slider"
        aria-label="Deadline time: drag the hand round, or use the arrow keys"
        aria-valuetext={label}
        aria-valuenow={at.getHours() * 60 + at.getMinutes()}
        aria-valuemin={0}
        aria-valuemax={1439}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onKeyDown={key}
      >
        <circle className="face" r="74" />
        {Array.from({ length: 48 }, (_, i) => (
          <line key={i} className={i % 4 === 0 ? 'hour' : 'notch'} y1={i % 12 === 0 ? -58 : i % 4 === 0 ? -61 : -65} y2={-69} transform={`rotate(${i * 7.5})`} />
        ))}
        {[0, 3, 6, 9].map((h, i) => {
          const a = (i * Math.PI) / 2
          return (
            <text key={h} className="num" x={Math.sin(a) * 46} y={-Math.cos(a) * 46 + 5}>
              {h + half}
            </text>
          )
        })}
        {sameDay(at, now) && at.getHours() < 12 === now.getHours() < 12 && <circle className="now" r="3.5" cy={-69} transform={`rotate(${angleOf(now)})`} />}
        <text className="ampm" y="26">
          {at.getHours() < 12 ? 'am' : 'pm'}
        </text>
        <g className="hand" style={{ transform: `rotate(${rot}deg)`, transition: dragging || reduce ? 'none' : undefined }}>
          <line y1={6} y2={-43} />
          {/* a spade: a rounded point with two curved lobes, the hand's line as its stem */}
          <path className="knob" d="M0 -56 C1.6 -52.6 5.4 -50.4 5.4 -47.4 C5.4 -45 3 -44.2 1.2 -45.6 L0 -43.6 L-1.2 -45.6 C-3 -44.2 -5.4 -45 -5.4 -47.4 C-5.4 -50.4 -1.6 -52.6 0 -56 Z" strokeLinejoin="round" />
        </g>
        <circle className="hub" r="4.5" />
      </svg>
      <p className="due-read" aria-live="polite">
        <b>{label}</b> <span className="muted">{away}</span>
      </p>
      <form
        className="due-words"
        onSubmit={(e) => {
          e.preventDefault()
          if (words.trim()) void save(words.trim())
        }}
      >
        <input value={words} onChange={(e) => setWords(e.target.value)} placeholder="or type: in 2 weeks, mon 9am" aria-label="Deadline in words" />
      </form>
      <div className="due-acts">
        {due && (
          <button type="button" className="btn tiny" disabled={busy} onClick={() => void save('')}>
            no deadline
          </button>
        )}
        <button type="button" className="btn tiny solid" disabled={busy} onClick={() => void save(words.trim() || localMinute(at))}>
          set
        </button>
      </div>
    </motion.div>,
    document.body,
  )
}
