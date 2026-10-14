// Shared retro-OS building blocks: windows with title bars, 7-segment counters, progress bars.
import { AnimatePresence, animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { HALF_HOURS } from './api'
import { play } from './fx/sound'

export function Win({
  title,
  children,
  className = '',
  right,
  id,
}: {
  title: string
  children: ReactNode
  className?: string
  right?: ReactNode
  id?: string
}) {
  return (
    <section className={`win ${className}`} id={id}>
      <div className="titlebar">
        <span className="dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
        <span className="title">{title}</span>
        {right && <span className="tb-right">{right}</span>}
      </div>
      <div className="win-body">{children}</div>
    </section>
  )
}

/** LCD-style number with faint "8" ghost segments behind it; counts up when the value changes. */
export function Seg({ value, digits = 2, suffix }: { value: number; digits?: number; suffix?: string }) {
  const reduce = useReducedMotion()
  const mv = useMotionValue(reduce ? value : 0)
  const shown = useTransform(mv, (v) => String(Math.round(v)).padStart(digits, '!'))

  useEffect(() => {
    if (reduce) {
      mv.set(value)
      return
    }
    const c = animate(mv, value, { duration: 0.9, ease: 'easeOut' })
    return () => c.stop()
  }, [value, mv, reduce])

  return (
    <span className="seg">
      <span className="seg-ghost" aria-hidden>
        {'8'.repeat(Math.max(digits, String(value).length))}
      </span>
      <motion.span className="seg-val">{shown}</motion.span>
      {suffix && <span className="seg-suffix">{suffix}</span>}
    </span>
  )
}

export function Bar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(1, value))
  return (
    <div className="pbar" role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-label={label}>
      <motion.div
        className="pbar-fill"
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(pct * 100, pct > 0 ? 4 : 0)}%` }}
        transition={{ type: 'spring', stiffness: 90, damping: 18 }}
      />
    </div>
  )
}


/** Retro modal window. Esc closes, focus moves into the dialog, backdrop click cancels. */
export function Dialog({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const reduce = useReducedMotion()
  const boxRef = useRef<HTMLDivElement>(null)
  // keep the latest onClose without re-running the open/focus effect on every render
  // (callers pass inline arrows; re-running stole focus from the textarea on each keystroke)
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    play('open')
    const prev = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        closeRef.current()
      }
    }
    window.addEventListener('keydown', onKey, true)
    // focus the dialog's main control: an explicit [data-autofocus], else its first text field.
    // (never the titlebar × button, or Space would close the dialog)
    const t = setTimeout(() => {
      const box = boxRef.current
      const el =
        box?.querySelector<HTMLElement>('[data-autofocus]') ??
        box?.querySelector<HTMLElement>('.win-body textarea, .win-body input') ??
        box?.querySelector<HTMLElement>('.win-body button')
      el?.focus()
    }, 30)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      clearTimeout(t)
      play('close')
      prev?.focus?.()
    }
  }, [open])

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="dialog-scrim"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && closeRef.current()}
        >
          <motion.div
            ref={boxRef}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={`win dialog ${wide ? 'wide' : ''}`}
            initial={reduce ? { opacity: 0 } : { scale: 0.85, y: 24, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { scale: 0.9, y: 12, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 26 }}
          >
            <div className="titlebar">
              <span className="dots" aria-hidden>
                <i />
                <i />
                <i />
              </span>
              <span className="title">{title}</span>
              <button className="dialog-x" tabIndex={-1} onClick={() => closeRef.current()} aria-label="Close">
                ×
              </button>
            </div>
            <div className="win-body">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

/** A pill switch between a few lists (drafts/sent, new/bookmarked). The pill slides with a CSS
 * transition, not a layout animation, so switching never makes the list below re-measure. */
export function SegTabs<T extends string>({ tabs, value, onChange }: { tabs: [T, ReactNode][]; value: T; onChange: (t: T) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null)
  const labels = tabs.map(([k]) => k).join()
  useLayoutEffect(() => {
    const on = box.current?.querySelector<HTMLElement>('[aria-selected="true"]')
    if (on) setPill({ x: on.offsetLeft, w: on.offsetWidth })
  }, [value, labels])
  return (
    <div className="seg-tabs" role="tablist" ref={box}>
      {pill && <span className="seg-pill" style={{ transform: `translateX(${pill.x}px)`, width: pill.w }} />}
      {tabs.map(([k, label]) => (
        <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>
          {label}
        </button>
      ))}
    </div>
  )
}

/** When the user's day starts and ends (setup and Settings): two half-hour pickers, and what they mean. */
export function DayTimes({ wake, bed, onChange }: { wake: string; bed: string; onChange: (wake: string, bed: string) => void }) {
  const late = bed < '05:00' // going to bed after midnight
  return (
    <div className="day-times">
      <div className="field-row">
        <label className="field">
          <span>I usually wake up at</span>
          <select value={wake} onChange={(e) => onChange(e.target.value, bed)}>
            {HALF_HOURS.map((h) => (
              <option key={h}>{h}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>and go to bed at</span>
          <select value={bed} onChange={(e) => onChange(wake, e.target.value)}>
            {HALF_HOURS.map((h) => (
              <option key={h}>{h}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted small">
        Your day runs from {wake} to {bed}
        {late ? ' (after midnight still counts as today)' : ''}. The recap comes at {bed}, and quiet hours cover the night.
      </p>
    </div>
  )
}
