// Celebration layer: pixel confetti bursts, floating "+XP" text, a note that flies into a
// window, and full-screen banners (level up, goal reached). Everything is pointer-events: none
// except the banner, and it all collapses to simple fades when the user prefers reduced motion.

import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { Companion } from '../Companion'
import { play, type Sound } from './sound'

type Burst = { id: number; x: number; y: number; big: boolean }
type Floater = { id: number; x: number; y: number; text: string }
type Flight = { id: number; from: DOMRect; to: DOMRect }
type Banner = { title: string; sub: string; kind: 'level' | 'goal' | 'recap' }

type FxApi = {
  burst: (x: number, y: number, big?: boolean) => void
  burstAt: (el: Element | null, big?: boolean) => void
  float: (el: Element | null, text: string) => void
  fly: (from: Element | null, toId: string) => Promise<void>
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
