// Celebration layer: pixel confetti bursts, floating "+XP" text, a note that flies into a
// window, a tossed card that crumples into the bin, and full-screen banners (level up, goal reached). Everything is pointer-events: none
// except the banner, and it all collapses to simple fades when the user prefers reduced motion.

import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Companion } from '../Companion'
import { play, type Sound } from './sound'

type Burst = { id: number; x: number; y: number; big: boolean }
type Floater = { id: number; x: number; y: number; text: string }
type Flight = { id: number; from: DOMRect; to: DOMRect }
type Toss = { id: number; from: DOMRect }
type Banner = { title: string; sub: string; kind: 'level' | 'goal' | 'recap' }

type FxApi = {
  burst: (x: number, y: number, big?: boolean) => void
  burstAt: (el: Element | null, big?: boolean) => void
  float: (el: Element | null, text: string) => void
  fly: (from: Element | null, toId: string) => Promise<void>
  /** Throw something away: the card it's on crumples into a ball and lands in a bin. */
  toss: (el: Element | null) => void
  /** After anything a misclick could do (done, removed, tossed, a deadline moved): a bar with Undo
   * for a few seconds, and Ctrl/Cmd+Z. `run` puts it back; every page then reloads. */
  offerUndo: (label: string, run: () => Promise<unknown> | void) => void
  banner: (b: Banner) => void
  sound: (s: Sound, n?: number) => void
}

const Ctx = createContext<FxApi | null>(null)

export function useFx(): FxApi {
  const v = useContext(Ctx)
  if (!v) throw new Error('useFx outside FxProvider')
  return v
}

const COLORS = ['var(--accent)', 'var(--butter)', 'var(--coral)', 'var(--sage-strong)', 'var(--line)']

function center(el: Element | null): { x: number; y: number } {
  if (!el) return { x: window.innerWidth / 2, y: window.innerHeight / 2 }
  const r = el.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}

function bump(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.classList.remove('bump')
  void (el as HTMLElement).offsetWidth // restart the CSS animation
  el.classList.add('bump')
}

export function FxProvider({ children }: { children: ReactNode }) {
  const reduce = useReducedMotion()
  const [bursts, setBursts] = useState<Burst[]>([])
  const [floaters, setFloaters] = useState<Floater[]>([])
  const [flights, setFlights] = useState<Flight[]>([])
  const [tosses, setTosses] = useState<Toss[]>([])
  const [undo, setUndo] = useState<{ id: number; label: string; run: () => Promise<unknown> | void } | null>(null)
  const undoRef = useRef(undo)
  undoRef.current = undo
  const doUndo = useCallback(async () => {
    const u = undoRef.current
    if (!u) return
    setUndo(null)
    await u.run()
    play('undo')
    window.dispatchEvent(new Event('tamadesk:refresh'))
  }, [])
  useEffect(() => {
    if (!undo) return
    const t = setTimeout(() => setUndo((u) => (u?.id === undo.id ? null : u)), 7000)
    return () => clearTimeout(t)
  }, [undo])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.('input, textarea, [contenteditable="true"]')
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'z' && !typing && undoRef.current) {
        e.preventDefault()
        void doUndo()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [doUndo])
  const [banner, setBanner] = useState<Banner | null>(null)
  const nextId = useRef(1)
  const landed = useRef(new Map<number, () => void>())

  const burst = useCallback(
    (x: number, y: number, big = false) => {
      if (reduce) return
      const id = nextId.current++
      setBursts((b) => [...b, { id, x, y, big }])
      setTimeout(() => setBursts((b) => b.filter((p) => p.id !== id)), 1400)
    },
    [reduce],
  )

  const api = useMemo<FxApi>(
    () => ({
      burst,
      burstAt: (el, big) => {
        const c = center(el)
        burst(c.x, c.y, big)
      },
      float: (el, text) => {
        const c = center(el)
        const id = nextId.current++
        setFloaters((f) => [...f, { id, x: c.x, y: c.y, text }])
        setTimeout(() => setFloaters((f) => f.filter((p) => p.id !== id)), 1600)
      },
      fly: (fromEl, toId) =>
        new Promise<void>((resolve) => {
          const to = document.getElementById(toId)
          if (!fromEl || !to || reduce) {
            bump(toId)
            resolve()
            return
          }
          const id = nextId.current++
          landed.current.set(id, () => {
            bump(toId)
            resolve()
          })
          setFlights((f) => [...f, { id, from: fromEl.getBoundingClientRect(), to: to.getBoundingClientRect() }])
        }),
      toss: (el) => {
        play('crumple')
        const card = (el?.closest('[data-toss]') as HTMLElement | null) ?? (el as HTMLElement | null)
        if (!card || reduce) return
        const id = nextId.current++
        setTosses((x) => [...x, { id, from: card.getBoundingClientRect() }])
        card.style.visibility = 'hidden' // the paper lifts off; the list closes the gap after
        setTimeout(() => play('bin'), TOSS_MS - 40)
        setTimeout(() => setTosses((x) => x.filter((t) => t.id !== id)), TOSS_MS + 700)
      },
      offerUndo: (label, run) => setUndo({ id: nextId.current++, label, run }),
      banner: (b) => {
        setBanner(b)
        play('levelup')
        if (!reduce) setTimeout(() => burst(window.innerWidth / 2, window.innerHeight / 2 - 60, true), 150)
      },
      sound: play,
    }),
    [burst, reduce],
  )

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="fx-layer" aria-hidden>
        {bursts.map((b) => (
          <BurstView key={b.id} {...b} />
        ))}
        <AnimatePresence>
          {floaters.map((f) => (
            <motion.div
              key={f.id}
              className="floater"
              style={{ left: f.x, top: f.y }}
              initial={{ opacity: 0, y: 0, scale: 0.6 }}
              animate={{ opacity: [0, 1, 1, 0], y: -70, scale: 1 }}
              transition={{ duration: 1.4, ease: 'easeOut' }}
            >
              {f.text}
            </motion.div>
          ))}
        </AnimatePresence>
        {flights.map((f) => {
          const fx = f.from.left + f.from.width / 2
          const fy = f.from.top + f.from.height / 2
          const tx = f.to.left + f.to.width / 2
          const ty = f.to.top + f.to.height / 2
          return (
            <motion.div
              key={f.id}
              className="flight"
              initial={{ x: fx, y: fy, scale: 2.2, rotate: -8, opacity: 1 }}
              animate={{
                x: [fx, (fx + tx) / 2, tx],
                y: [fy, Math.min(fy, ty) - 140, ty],
                scale: [2.2, 1.4, 0.6],
                rotate: [-8, 12, 0],
              }}
              transition={{ duration: 0.85, ease: [0.45, 0, 0.25, 1] }}
              onAnimationComplete={() => {
                setFlights((all) => all.filter((x) => x.id !== f.id))
                landed.current.get(f.id)?.()
                landed.current.delete(f.id)
              }}
            >
              <Note />
            </motion.div>
          )
        })}
      </div>
      <AnimatePresence>{tosses.length > 0 && <Bin key="bin" />}</AnimatePresence>
      <AnimatePresence>
        {undo && (
          <motion.div
            key={undo.id}
            className="undo-bar"
            role="status"
            initial={{ opacity: 0, y: 24, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: 16, x: '-50%', transition: { duration: 0.15 } }}
            transition={{ type: 'spring', stiffness: 460, damping: 30 }}
          >
            <span>{undo.label}</span>
            <button className="btn tiny solid" onClick={() => void doUndo()}>
              undo
            </button>
            <kbd>{navigator.platform.startsWith('Mac') ? '⌘' : 'Ctrl'}+Z</kbd>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="fx-layer toss-layer" aria-hidden>
        {tosses.map((t) => (
          <Paper key={t.id} from={t.from} />
        ))}
      </div>
      <AnimatePresence>
        {banner && (
          <motion.div
            className="banner-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setBanner(null)}
          >
            <motion.div
              className="win banner"
              initial={{ scale: reduce ? 1 : 0.4, rotate: reduce ? 0 : -6, y: 40 }}
              animate={{ scale: 1, rotate: 0, y: 0 }}
              exit={{ scale: 0.8, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 380, damping: 16 }}
            >
              <div className="titlebar">
                <span className="dots">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="title">{banner.kind === 'recap' ? 'recap.txt' : 'achievement.exe'}</span>
              </div>
              <div className="banner-body">
                <Companion mood="happy" size={96} />
                <div>
                  <div className="banner-title">{banner.title}</div>
                  <p>{banner.sub}</p>
                  <button className="btn solid" onClick={() => setBanner(null)}>
                    Nice!
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Ctx.Provider>
  )
}

function BurstView({ x, y, big }: Burst) {
  const [pieces] = useState(() =>
      Array.from({ length: big ? 42 : 22 }, (_, i) => {
        const angle = (Math.PI * 2 * i) / (big ? 42 : 22) + Math.random() * 0.4
        const dist = (big ? 180 : 90) + Math.random() * (big ? 160 : 70)
        return {
          dx: Math.cos(angle) * dist,
          dy: Math.sin(angle) * dist,
          size: 5 + Math.round(Math.random() * 5),
          color: COLORS[i % COLORS.length],
          spin: Math.random() * 360,
        }
      }),
  )
  return (
    <>
      {pieces.map((p, i) => (
        <motion.span
          key={i}
          className="px"
          style={{ left: x, top: y, width: p.size, height: p.size, background: p.color }}
          initial={{ x: 0, y: 0, opacity: 1, rotate: 0 }}
          animate={{ x: p.dx, y: [0, p.dy * 0.6, p.dy + 90], opacity: [1, 1, 0], rotate: p.spin }}
          transition={{ duration: big ? 1.3 : 0.9, ease: 'easeOut' }}
        />
      ))}
    </>
  )
}

// a little folded sticky note: what a captured thought looks like in flight
function Note() {
  return (
    <svg width="24" height="24" viewBox="0 0 12 12" shapeRendering="crispEdges">
      <rect x="0" y="0" width="12" height="12" fill="var(--line)" />
      <rect x="1" y="1" width="10" height="10" fill="var(--butter)" />
      <rect x="8" y="8" width="3" height="3" fill="var(--line)" />
      <rect x="8" y="8" width="2" height="2" fill="var(--paper)" />
      <rect x="3" y="3" width="6" height="1" fill="var(--line)" />
      <rect x="3" y="5" width="4" height="1" fill="var(--line)" />
    </svg>
  )
}

const TOSS_MS = 950
const BALL = 34
// the bin sits 28px from the right and 24px from the bottom of the page (not the window: the
// scrollbar would push the ball off to the side); its mouth is under the lid, 16px from its top
const BIN = { w: 64, h: 72, right: 28, bottom: 24, lid: 16 }
const binMouth = () => {
  const { clientWidth: w, clientHeight: h } = document.documentElement
  return { x: w - BIN.right - BIN.w / 2, y: h - BIN.bottom - BIN.h + BIN.lid }
}

/** The thrown card: a paper ghost of it scrunches into a ball, then arcs into the bin. */
function Paper({ from }: { from: DOMRect }) {
  const bin = binMouth()
  const cx = from.left + from.width / 2 - BALL / 2
  const cy = from.top + from.height / 2 - BALL / 2
  const peak = Math.min(cy, bin.y) - 150
  const times = [0, 0.22, 0.32, 0.7, 1]
  const t = { duration: TOSS_MS / 1000, times, ease: 'easeInOut' as const }
  return (
    <motion.div
      className="paper"
      initial={{ x: from.left, y: from.top, width: from.width, height: from.height }}
      animate={{
        x: [from.left, cx, cx, (cx + bin.x - BALL / 2) / 2, bin.x - BALL / 2],
        y: [from.top, cy, cy - 26, peak, bin.y + 6], // drops in behind the bin's front
        width: [from.width, BALL, BALL, BALL, BALL],
        height: [from.height, BALL, BALL, BALL, BALL],
        rotate: [0, -14, -30, 190, 380],
        borderRadius: [10, BALL / 2, BALL / 2, BALL / 2, BALL / 2],
      }}
      transition={t}
    >
      <motion.svg className="ball" viewBox="0 0 10 10" shapeRendering="crispEdges" initial={{ opacity: 0 }} animate={{ opacity: [0, 0, 1, 1, 1] }} transition={t}>
        <rect x="2" y="2" width="3" height="1" fill="var(--line)" />
        <rect x="5" y="4" width="3" height="1" fill="var(--line)" />
        <rect x="2" y="6" width="2" height="1" fill="var(--line)" />
        <rect x="6" y="7" width="2" height="1" fill="var(--line)" />
        <rect x="4" y="1" width="1" height="2" fill="var(--muted)" />
        <rect x="1" y="4" width="1" height="2" fill="var(--muted)" />
      </motion.svg>
    </motion.div>
  )
}

/** A pixel dustbin that pops up in the corner while something is thrown away. Its lid swings open on
 * a hinge at its left end, waits, and shuts as the ball lands; then the bin gives a little wobble. */
function Bin() {
  return (
    <motion.div
      className="bin"
      aria-hidden
      style={{ width: BIN.w, height: BIN.h, right: BIN.right, bottom: BIN.bottom }}
      initial={{ y: 130, rotate: 0 }}
      animate={{ y: 0, rotate: [0, 0, 0, -6, 4, -2, 0] }}
      exit={{ y: 130, transition: { duration: 0.25, ease: 'easeIn' } }}
      transition={{ y: { type: 'spring', stiffness: 420, damping: 24 }, rotate: { duration: TOSS_MS / 1000 + 0.35, times: [0, 0.5, 0.86, 0.9, 0.94, 0.97, 1] } }}
    >
      <svg className="bin-lid" width="64" height="16" viewBox="0 0 16 4" shapeRendering="crispEdges">
        <rect x="6" y="0" width="4" height="1" fill="var(--line)" />
        <rect x="6" y="1" width="1" height="1" fill="var(--line)" />
        <rect x="9" y="1" width="1" height="1" fill="var(--line)" />
        <rect x="0" y="2" width="16" height="2" fill="var(--line)" />
        <rect x="1" y="2" width="14" height="1" fill="var(--accent)" />
      </svg>
      <svg className="bin-body" width="64" height="56" viewBox="0 0 16 14" shapeRendering="crispEdges">
        <rect x="1" y="0" width="14" height="14" fill="var(--line)" />
        <rect x="2" y="0" width="12" height="13" fill="var(--win-2)" />
        <rect x="2" y="0" width="12" height="1" fill="var(--muted)" />
        <rect x="4" y="3" width="1" height="8" fill="var(--muted)" />
        <rect x="7" y="3" width="2" height="8" fill="var(--muted)" />
        <rect x="11" y="3" width="1" height="8" fill="var(--muted)" />
        <rect x="2" y="12" width="12" height="1" fill="var(--line)" />
      </svg>
    </motion.div>
  )
}
