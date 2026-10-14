// Companions: tiny pixel creatures drawn from character maps, so they stay crisp at any size and
// anyone can add a new species by drawing one in text (see docs/plan.md, "Add a companion").
//
// Motion: idle = slow squash-and-stretch breathing + random blinks; happy = hop with a squash on
// landing; sleepy = slow breathing + floating z's; `cheer` (bump the number) = one big jump-spin;
// poke (click) = wiggle. Everything collapses to stillness under prefers-reduced-motion.
import { AnimatePresence, motion, useAnimate, useReducedMotion } from 'motion/react'
import { createContext, useContext, useEffect, useRef, useState } from 'react'

export type Mood = 'idle' | 'happy' | 'sleepy'
type Eyes = Record<Mood | 'blink', [string, string]>
type Species = { top: string[]; eyes: Eyes; bottom: string[]; fill: Record<string, string> }

// companions keep their own colours in every theme, like characters do
const INK = '#2c2934'

const SPECIES: Record<string, Species> = {
  blob: {
    top: [
      '.....xxxx.....',
      '...xxbbbbxx...',
      '..xbbwwbbbbx..',
      '.xbbwbbbbbbbx.',
      '.xbbbbbbbbbbx.',
      'xbbbbbbbbbbbbx',
    ],
    eyes: {
      idle: ['xbbbebbbbebbbx', 'xbbbebbbbebbbx'],
      happy: ['xbbbebbbbebbbx', 'xbbebebbebebbx'],
      sleepy: ['xbbbbbbbbbbbbx', 'xbbeeebbeeebbx'],
      blink: ['xbbbbbbbbbbbbx', 'xbbbebbbbebbbx'],
    },
    bottom: ['xbpbbbeebbbpbx', 'xbbbbbbbbbbbbx', '.xbbbbbbbbbbx.', '..xxxxxxxxxx..'],
    fill: { x: INK, b: '#a48ed9', w: '#fffaf0', e: INK, p: '#f3a9ba' },
  },
  sprout: {
    top: [
      '...xx....xx...',
      '..xllx..xllx..',
      '...xllxxllx...',
      '.....xxxx.....',
      '...xxxxxxxx...',
      '..xgwggggggx..',
    ],
    eyes: {
      idle: ['.xggeggggeggx.', '.xggeggggeggx.'],
      happy: ['.xggeggggeggx.', '.xgegeggegegx.'],
      sleepy: ['.xggggggggggx.', '.xgeeeggeeegx.'],
      blink: ['.xggggggggggx.', '.xggeggggeggx.'],
    },
    bottom: [
      '.xgpggmmggpgx.',
      '..xggggggggx..',
      '...xxxxxxxx...',
      '..xoooooooox..',
      '...xoooooox...',
      '...xxxxxxxx...',
    ],
    fill: { x: INK, l: '#8dbd98', g: '#cfe2d1', w: '#fffaf0', e: INK, p: '#f3a9ba', m: INK, o: '#e98c7b' },
  },
  bot: {
    top: [
      '.....xaax.....',
      '......xx......',
      '.xxxxxxxxxxxx.',
      '.xmmmmmmmmmmx.',
      '.xmssssssssmx.',
    ],
    eyes: {
      idle: ['.xmsgssssgsmx.', '.xmsgssssgsmx.'],
      happy: ['.xmsgssssgsmx.', '.xmgsgssgsgmx.'],
      sleepy: ['.xmssssssssmx.', '.xmgggssgggmx.'],
      blink: ['.xmssssssssmx.', '.xmsgssssgsmx.'],
    },
    bottom: [
      '.xmsssggsssmx.',
      '.xmssssssssmx.',
      '.xmmmmmmmmmmx.',
      '.xxxxxxxxxxxx.',
      '...xx....xx...',
      '..xxx....xxx..',
    ],
    fill: { x: INK, a: '#e98c7b', m: '#f1d27e', s: '#2c2934', g: '#8fd39f' },
  },
}


export type CompanionInfo = { species: string; name: string }
export const CompanionCtx = createContext<CompanionInfo>({ species: 'blob', name: 'buddy' })
export const useCompanion = () => useContext(CompanionCtx)

export function Companion({
  species,
  mood = 'idle',
  size = 84,
  cheer = 0,
  onPoke,
  still = false,
}: {
  /** a picture only (e.g. inside the companion wheel): no poke, so it can sit inside another button */
  still?: boolean
  species?: string
  mood?: Mood
  size?: number
  /** bump this number to play a one-off celebration */
  cheer?: number
  onPoke?: () => void
}) {
  const ctx = useCompanion()
  const sp = SPECIES[species ?? ctx.species] ?? SPECIES.blob
  const reduce = useReducedMotion()
  const [blink, setBlink] = useState(false)
  const [scope, animate] = useAnimate()
  const firstCheer = useRef(cheer)

  // blink at random intervals (not on a metronome, or it looks mechanical)
  useEffect(() => {
    if (reduce || mood === 'sleepy') return
    let t: number
    const loop = () => {
      t = window.setTimeout(() => {
        setBlink(true)
        window.setTimeout(() => setBlink(false), 130)
        loop()
      }, 2200 + Math.random() * 3800)
    }
    loop()
    return () => window.clearTimeout(t)
  }, [reduce, mood])

  useEffect(() => {
    if (reduce || cheer === firstCheer.current) return
    void animate(
      scope.current,
      { y: [0, 4, -28, 0, 2, 0], scaleY: [1, 0.8, 1.12, 1, 0.9, 1], scaleX: [1, 1.15, 0.92, 1, 1.08, 1], rotate: [0, 0, 360, 360, 360, 360] },
      { duration: 0.9, ease: 'easeOut' },
    ).then(() => animate(scope.current, { rotate: 0 }, { duration: 0 }))
  }, [cheer, reduce, animate, scope])

  const poke = () => {
    onPoke?.()
    if (!reduce) void animate(scope.current, { rotate: [0, -10, 9, -6, 4, 0], scaleY: [1, 0.88, 1.05, 1] }, { duration: 0.5 })
  }

  const Hit = still ? 'span' : 'button'
  const eyes = sp.eyes[blink && mood !== 'sleepy' ? 'blink' : mood]
  const rows = [...sp.top, ...eyes, ...sp.bottom]
  const w = rows[0].length
  const h = rows.length
  // the idle loops (breathe, a little hop when happy) are CSS animations on transform: the GPU runs
  // them, so a companion sitting on the desk costs the page nothing frame to frame
  const loop = reduce ? '' : mood === 'happy' ? 'loop-hop' : mood === 'sleepy' ? 'loop-breathe slow' : 'loop-breathe'

  return (
    <div className="companion" style={{ width: size }}>
      <AnimatePresence>
        {mood === 'sleepy' && !reduce && (
          <motion.div className="zzz" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            {[0, 1, 2].map((i) => (
              <span key={i} className="z-rise" style={{ animationDelay: `${i * 0.8}s`, ['--zx' as string]: `${8 + i * 3}px` }}>
                z
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      <Hit className="companion-hit" {...(still ? {} : { onClick: poke, 'aria-label': 'Poke your companion', type: 'button' as const })}>
        <motion.div ref={scope} style={{ transformOrigin: '50% 100%' }}>
          <svg
            className={`companion-sprite ${loop}`}
            width={size}
            height={(size * h) / w}
            viewBox={`0 0 ${w} ${h}`}
            shapeRendering="crispEdges"
            role="img"
            aria-label="your companion"
          >
            {rows.flatMap((row, y) =>
              [...row].map((c, x) =>
                c === '.' ? null : <rect key={`${x}-${y}`} x={x} y={y} width="1.02" height="1.02" fill={sp.fill[c]} />,
              ),
            )}
          </svg>
        </motion.div>
      </Hit>
      <div className={`companion-shadow ${!reduce && mood === 'happy' ? 'loop-hop-shadow' : ''}`} />
    </div>
  )
}
