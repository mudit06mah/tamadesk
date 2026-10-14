// Your companion in a ring: the ring fills with XP towards the next level, and the day's numbers sit
// on it (streak, todos, freezes) instead of in a row of pills. The ⇄ button (or a right-click) opens
// a wheel of companions to switch who sits on your desk.
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'
import { api, type CompanionChoice } from './api'
import { Companion, useCompanion, type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { FlameIcon } from './icons'

type Props = {
  mood: Mood
  cheer: number
  onPoke: () => void
  level: { level: number; xp: number; into: number; need: number }
  stats: { done: number; goal: number; streak: number; freezes?: number }
  lean?: boolean // the user is typing: lean towards the box
  working?: boolean // the assistant is busy: a slow bob
}

const SIZE = 96 // the sprite
const RING = SIZE + 34 // the ring around it

export function BuddyRing({ mood, cheer, onPoke, level, stats, lean = false, working = false }: Props) {
  const fx = useFx()
  const reduce = useReducedMotion()
  const [wheel, setWheel] = useState(false)
  const r = RING / 2 - 5
  const circ = 2 * Math.PI * r
  const filled = Math.min(1, level.into / Math.max(1, level.need))
  const toggle = (open: boolean) => {
    fx.sound(open ? 'open' : 'close')
    setWheel(open)
  }
  return (
    <div
      className="buddy-ring"
      style={{ width: RING, height: RING }}
      onContextMenu={(e) => {
        e.preventDefault()
        toggle(!wheel)
      }}
    >
      <svg className="ring-svg" width={RING} height={RING} aria-hidden>
        <circle cx={RING / 2} cy={RING / 2} r={r} className="ring-track" />
        <motion.circle
          cx={RING / 2}
          cy={RING / 2}
          r={r}
          className="ring-fill"
          strokeDasharray={circ}
          initial={false}
          animate={{ strokeDashoffset: circ * (1 - filled) }}
          transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 60, damping: 18 }}
          transform={`rotate(-90 ${RING / 2} ${RING / 2})`}
        />
      </svg>
      <motion.div
        className="ring-buddy"
        animate={working && !reduce ? { y: [0, -2, 0] } : lean ? { rotate: -6, y: -2 } : { rotate: 0, y: 0 }}
        transition={working ? { duration: 1.6, repeat: Infinity, ease: 'easeInOut' } : { type: 'spring', stiffness: 260, damping: 16 }}
      >
        <Companion mood={mood} size={SIZE * 0.78} cheer={cheer} onPoke={onPoke} />
      </motion.div>
      <span className="ring-lv" title={`${level.xp} XP · ${level.need - level.into} to level ${level.level + 1}`}>
        LV {level.level}
      </span>
      {stats.streak > 0 && (
        <Badge at="ne" title="days in a row">
          <FlameIcon /> {stats.streak}
        </Badge>
      )}
      <Badge at="se" title="todos done today / your daily goal" hit={stats.done >= stats.goal}>
        ✓ {stats.done}/{stats.goal}
      </Badge>
      {!!stats.freezes && (
        <Badge at="nw" title={`${stats.freezes} streak freeze${stats.freezes > 1 ? 's' : ''}: a missed day spends one instead of your streak`}>
          ❄{stats.freezes}
        </Badge>
      )}
      <button className="ring-swap" title="Switch companion" aria-label="Switch companion" aria-expanded={wheel} onClick={() => toggle(!wheel)}>
        ⇄
      </button>
      <AnimatePresence>{wheel && <Wheel onClose={() => toggle(false)} />}</AnimatePresence>
    </div>
  )
}

function Badge({ at, title, hit = false, children }: { at: 'ne' | 'se' | 'nw'; title: string; hit?: boolean; children: ReactNode }) {
  return (
    <span className={`ring-badge ${at} ${hit ? 'hit' : ''}`} title={title}>
      {children}
    </span>
  )
}

/** The companions around the ring: pick one and it moves onto your desk. */
function Wheel({ onClose }: { onClose: () => void }) {
  const fx = useFx()
  const current = useCompanion()
  const [choices, setChoices] = useState<CompanionChoice[]>([])
  useEffect(() => {
    void api.onboarding().then((o) => setChoices(o.companions))
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  const pick = async (species: string) => {
    if (species === current.species) return onClose()
    await api.setCompanion(species)
    fx.sound('hatch')
    window.dispatchEvent(new Event('tamadesk:refresh'))
    onClose()
  }
  // an arc below the companion (the desk's top edge and the dock are too close for a full circle)
  const radius = RING / 2 + 40
  return (
    <>
      <motion.div className="wheel-backdrop" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
      {choices.map((c, i) => {
        const a = (30 + (120 / Math.max(1, choices.length - 1)) * i) * (Math.PI / 180)
        return (
          <motion.button
            key={c.species}
            className={`wheel-pick ${c.species === current.species ? 'on' : ''}`}
            title={c.blurb}
            onClick={() => pick(c.species)}
            initial={{ x: 0, y: 0, scale: 0.3, opacity: 0 }}
            animate={{ x: Math.cos(a) * radius, y: Math.sin(a) * radius, scale: 1, opacity: 1 }}
            exit={{ x: 0, y: 0, scale: 0.3, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 24, delay: i * 0.03 }}
            whileHover={{ scale: 1.08 }}
            whileTap={{ scale: 0.92 }}
          >
            <Companion species={c.species} mood="idle" size={40} still />
            <span>{c.label}</span>
          </motion.button>
        )
      })}
    </>
  )
}
