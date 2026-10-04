// Tiny synth cues via WebAudio: no audio files, nothing to license. Toggle in the dock.

let ctx: AudioContext | null = null
let enabled = (() => {
  try {
    return localStorage.getItem('sound') !== 'off'
  } catch {
    return true
  }
})()

export const soundOn = () => enabled
export function setSound(on: boolean) {
  enabled = on
  try {
    localStorage.setItem('sound', on ? 'on' : 'off')
  } catch {
    /* ignore */
  }
}

function tone(freq: number, start: number, dur: number, type: OscillatorType = 'square', vol = 0.035) {
  if (!ctx) return
  const o = ctx.createOscillator()
  const g = ctx.createGain()
  o.type = type
  o.frequency.setValueAtTime(freq, ctx.currentTime + start)
  g.gain.setValueAtTime(vol, ctx.currentTime + start)
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur)
  o.connect(g).connect(ctx.destination)
  o.start(ctx.currentTime + start)
  o.stop(ctx.currentTime + start + dur + 0.02)
}

// soft "bubble" blip: a quiet sine that glides upward, rounded attack, no click
function bubble(from: number, to: number, dur = 0.09, vol = 0.05) {
  if (!ctx) return
  const t = ctx.currentTime
  const o = ctx.createOscillator()
  const g = ctx.createGain()
  o.type = 'sine'
  o.frequency.setValueAtTime(from, t)
  o.frequency.exponentialRampToValueAtTime(to, t + dur * 0.8)
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(vol, t + 0.012) // soft attack avoids the "pop"
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  o.connect(g).connect(ctx.destination)
  o.start(t)
  o.stop(t + dur + 0.02)
}

// A soft palette: sine/triangle only, quiet, rounded attacks. Each cue rises when something good
// happens and falls when something goes away, so the ear learns the meaning without looking.
const SOUNDS = {
  // UI: navigation, tabs, opening things
  tap: () => bubble(420, 760),
  // quick capture landed
  capture: () => {
    bubble(520, 880, 0.08, 0.045)
    setTimeout(() => bubble(700, 1180, 0.07, 0.03), 70)
  },
  // todo checked off: a bright two-note "ding-ding" plus a soft thud underneath
  check: () => {
    tone(80, 0, 0.12, 'triangle', 0.04)
    ;[784, 1175].forEach((f, i) => tone(f, 0.06 + 0.08 * i, 0.22, 'triangle', 0.03))
  },
  // undo / drop: the same shape, falling
  undo: () => [523, 392].forEach((f, i) => tone(f, 0.08 * i, 0.16, 'triangle', 0.022)),
  stamp: () => tone(70, 0, 0.18, 'triangle', 0.05),
  send: () => [523, 659, 784].forEach((f, i) => tone(f, 0.09 * i, 0.22, 'triangle', 0.025)),
  drop: () => [262, 196].forEach((f, i) => tone(f, 0.1 * i, 0.18, 'triangle', 0.025)),
  // typewriter tick for the New Game text, very quiet so it can repeat
  type: () => bubble(1400 + Math.random() * 300, 1800, 0.03, 0.012),
  // reminder: a little music-box phrase, played twice
  ring: () =>
    [0, 0.9].forEach((o) => [988, 1319, 1175, 1568].forEach((f, i) => tone(f, o + 0.13 * i, 0.4, 'sine', 0.04))),
  // companion poked
  poke: () => bubble(300 + Math.random() * 200, 620, 0.12, 0.05),
  hatch: () => [392, 523, 659, 784, 1047].forEach((f, i) => tone(f, 0.07 * i, 0.25, 'triangle', 0.028)),
  start: () =>
    [523, 523, 784, 659, 784, 1047].forEach((f, i) => tone(f, [0, 0.12, 0.24, 0.42, 0.54, 0.7][i], 0.3, 'square', 0.018)),
  levelup: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.12 * i, 0.3, 'triangle', 0.03)),
  // switching pages: a soft airy swoop downward
  whoosh: () => bubble(900, 380, 0.14, 0.022),
  // keep an item: a little "aww" upward pair; skip: a quick soft swipe down
  keep: () => [740, 988].forEach((f, i) => tone(f, 0.06 * i, 0.18, 'sine', 0.035)),
  skip: () => bubble(480, 260, 0.1, 0.028),
  // each step the companion takes while working climbs a little higher (n = step number)
  step: (n = 0) => bubble(520 + Math.min(n, 10) * 45, 760 + Math.min(n, 10) * 60, 0.07, 0.022),
  // the answer arrived: a warm three-note chord, rolled
  arrive: () => [523, 659, 988].forEach((f, i) => tone(f, 0.05 * i, 0.5, 'sine', 0.028)),
  // a new theme: a quick shimmer
  sparkle: () => [1319, 1568, 1760, 2093].forEach((f, i) => tone(f, 0.045 * i, 0.16, 'sine', 0.016)),
  // dialogs open with a rising bubble and close with a falling one
  open: () => bubble(380, 640, 0.1, 0.035),
  close: () => bubble(640, 360, 0.09, 0.03),
  // typing in the Ask box: barely-there clicks
  key: () => bubble(1800 + Math.random() * 500, 2300, 0.02, 0.006),
} as const

export type Sound = keyof typeof SOUNDS

let lastKey = 0

export function play(s: Sound, n?: number) {
  if (!enabled) return
  if (s === 'key') {
    const now = performance.now()
    if (now - lastKey < 45) return // typing fast shouldn't become a buzz
    lastKey = now
  }
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') void ctx.resume()
    ;(SOUNDS[s] as (n?: number) => void)(n)
  } catch {
    /* audio unavailable */
  }
}
