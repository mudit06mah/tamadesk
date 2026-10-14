// Sound cues, synthesized live with WebAudio: no audio files, nothing to license. Two palettes:
// - cozy (default): small instruments. A wooden marimba (the bar's fundamental plus its bright 4x
//   partial and a mallet click), FM bells that start bright and settle, soft thumps and filtered air,
//   all through a little room reverb and a gentle compressor so every cue sits at the same level.
// - classic: the first palette, plain sine/triangle blips.
// Good things rise, removals fall, and the same instrument always means the same kind of thing.
// The mute toggle is in the dock; the palette is picked in Settings.

type Ctx = AudioContext
let ctx: Ctx | null = null

const stored = (key: string, fallback: string) => {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
const store = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode: it just won't be remembered */
  }
}

let enabled = stored('sound', 'on') !== 'off'
export const soundOn = () => enabled
export function setSound(on: boolean) {
  enabled = on
  store('sound', on ? 'on' : 'off')
}

export type Pack = 'cozy' | 'classic'
let pack: Pack = stored('sound-pack', 'cozy') === 'classic' ? 'classic' : 'cozy'
export const soundPack = () => pack
export function setSoundPack(p: Pack) {
  pack = p
  store('sound-pack', p)
}

// ------------------------------------------------------------------ the mixing desk (one per context)

type Bus = { dry: AudioNode; wet: AudioNode; noise: AudioBuffer }
const buses = new WeakMap<Ctx, Bus>()

function bus(): Bus {
  const c = ctx!
  let b = buses.get(c)
  if (b) return b
  // a gentle compressor keeps layered cues from stacking up louder than single ones
  const comp = c.createDynamicsCompressor()
  comp.threshold.value = -18
  comp.ratio.value = 3
  comp.attack.value = 0.003
  comp.release.value = 0.15
  comp.connect(c.destination)
  // a small, dark room: noise that dies away over a second, so bells and wood have somewhere to ring
  const len = Math.floor(c.sampleRate * 1.1)
  const ir = c.createBuffer(2, len, c.sampleRate)
  for (let ch = 0; ch < 2; ch++) {
    const d = ir.getChannelData(ch)
    let smooth = 0
    for (let i = 0; i < len; i++) {
      smooth = smooth * 0.55 + (Math.random() * 2 - 1) * 0.45 // a one-pole lowpass: no fizz in the tail
      d[i] = smooth * Math.pow(1 - i / len, 3.2)
    }
  }
  const verb = c.createConvolver()
  verb.buffer = ir
  const wetGain = c.createGain()
  wetGain.gain.value = 0.6
  verb.connect(wetGain).connect(comp)
  const noise = c.createBuffer(1, c.sampleRate, c.sampleRate)
  const nd = noise.getChannelData(0)
  for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1
  b = { dry: comp, wet: verb, noise }
  buses.set(c, b)
  return b
}

/** A gain stage that sends to the mix: `space` is how much goes to the room. */
function voice(space: number): GainNode {
  const c = ctx!
  const g = c.createGain()
  const b = bus()
  g.connect(b.dry)
  if (space > 0) {
    const s = c.createGain()
    s.gain.value = space
    g.connect(s).connect(b.wet)
  }
  return g
}

/** Attack then exponential decay on a gain: soft enough at both ends that nothing clicks. */
function envelope(g: GainNode, t: number, peak: number, attack: number, decay: number) {
  g.gain.setValueAtTime(0.0001, t)
  g.gain.exponentialRampToValueAtTime(peak, t + attack)
  g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay)
}

function osc(type: OscillatorType, freq: number, t: number, end: number, into: AudioNode): OscillatorNode {
  const o = ctx!.createOscillator()
  o.type = type
  o.frequency.setValueAtTime(freq, t)
  o.connect(into)
  o.start(t)
  o.stop(end + 0.05)
  return o
}

// ------------------------------------------------------------------ instruments (times in seconds from now)

/** A wooden bar: fundamental, the bright partial a real bar has near 4x, and a tiny mallet tick. */
function marimba(freq: number, at: number, vol: number, dur = 0.45, space = 0.12) {
  const t = ctx!.currentTime + at
  const body = voice(space)
  envelope(body, t, vol, 0.004, dur)
  osc('sine', freq, t, t + dur, body)
  const bright = voice(space)
  envelope(bright, t, vol * 0.32, 0.002, dur * 0.22)
  osc('sine', freq * 3.98, t, t + dur, bright)
  noiseBurst(at, 0.006, freq * 6, 2, vol * 0.5, 0)
}

/** An FM bell: the modulator starts strong (a bright, glassy strike) and fades, leaving a clean tone.
 * `ratio` 3.5 is a glass bell; inharmonic ratios (2.76) sound like struck metal. */
function bell(freq: number, at: number, vol: number, dur = 1.1, { ratio = 3.5, bright = 2.2, space = 0.35 } = {}) {
  const c = ctx!
  const t = c.currentTime + at
  const out = voice(space)
  envelope(out, t, vol, 0.003, dur)
  const carrier = osc('sine', freq, t, t + dur, out)
  const depth = c.createGain()
  depth.gain.setValueAtTime(freq * bright, t)
  depth.gain.exponentialRampToValueAtTime(1, t + dur * 0.55)
  osc('sine', freq * ratio, t, t + dur, depth)
  depth.connect(carrier.frequency)
}

/** A rounded pop that glides: opening, closing, a poke. */
function pop(from: number, to: number, at: number, vol: number, dur = 0.11, space = 0.08) {
  const t = ctx!.currentTime + at
  const g = voice(space)
  envelope(g, t, vol, 0.008, dur)
  const o = osc('sine', from, t, t + dur, g)
  o.frequency.exponentialRampToValueAtTime(to, t + dur * 0.8)
}

/** Weight under a cue: a low sine that drops in pitch, like something landing. */
function thump(at: number, vol: number, from = 150, to = 48, dur = 0.14) {
  const t = ctx!.currentTime + at
  const g = voice(0.05)
  envelope(g, t, vol, 0.003, dur)
  const o = osc('sine', from, t, t + dur, g)
  o.frequency.exponentialRampToValueAtTime(to, t + dur)
}

/** Filtered noise: a click when short and narrow, air or paper when long and wide. */
function noiseBurst(at: number, dur: number, freq: number, q: number, vol: number, space = 0.05, sweepTo?: number) {
  const c = ctx!
  const t = c.currentTime + at
  const src = c.createBufferSource()
  src.buffer = bus().noise
  const f = c.createBiquadFilter()
  f.type = 'bandpass'
  f.frequency.setValueAtTime(freq, t)
  if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, t + dur)
  f.Q.value = q
  const g = voice(space)
  envelope(g, t, vol, Math.min(0.004, dur / 3), dur)
  src.connect(f).connect(g)
  src.start(t, Math.random() * 0.5)
  src.stop(t + dur + 0.05)
}

/** Crumpling paper: `grains` tiny crackles of noise at random pitches, `gap` seconds apart (with a
 * little jitter), each a bit quieter. */
function crackle(at: number, grains: number, vol = 0.07, gap = 0.021) {
  for (let i = 0; i < grains; i++) {
    const freq = 1500 + Math.random() * 3600
    noiseBurst(at + i * gap + Math.random() * gap * 0.57, 0.012 + Math.random() * 0.02, freq, 1.6, vol * (1 - i * 0.057), 0.02)
  }
}

/** One notch of a wind-up key, kept soft and modern: two clean little clicks (the catch, then it
 * settling) with the crumple's airy texture, and a faint, short metallic glint over them (two
 * partials that don't line up as a chord, which is what reads as metal). `tension` (1 and up)
 * lifts it slightly as the spring tightens. */
function ratchet(at: number, tension = 1, vol = 0.05) {
  noiseBurst(at, 0.006, 3200 * tension, 2, vol, 0.01)
  noiseBurst(at + 0.009 + Math.random() * 0.003, 0.005, 3900 * tension, 2, vol * 0.45, 0.01)
  const t = ctx!.currentTime + at
  ;[[2900, 1], [6650, 0.5]].forEach(([freq, level]) => {
    const g = voice(0.02)
    envelope(g, t, vol * 0.12 * level, 0.001, 0.028)
    osc('sine', freq * tension, t, t + 0.03, g)
  })
}

/** A chiptune note: a square wave through a lowpass, so it's retro without being harsh. */
function chip(freq: number, at: number, vol: number, dur = 0.16) {
  const c = ctx!
  const t = c.currentTime + at
  const lp = c.createBiquadFilter()
  lp.type = 'lowpass'
  lp.frequency.value = 2600
  const g = voice(0.15)
  envelope(g, t, vol, 0.004, dur)
  lp.connect(g)
  osc('square', freq, t, t + dur, lp)
}

// note names for the cozy palette: C major pentatonic, so any cues that overlap still sound good
const N = { A4: 440, C5: 523.25, D5: 587.33, E5: 659.26, G5: 783.99, A5: 880, C6: 1046.5, D6: 1174.66, E6: 1318.51,
  G6: 1567.98, A6: 1760, C7: 2093, E7: 2637, G7: 3136 } // prettier-ignore
const CLIMB = [N.C6, N.D6, N.E6, N.G6, N.A6, N.C7, N.E7, N.G7]

// the wind-up key: how far it has been wound in this go (it relaxes after a pause), for the spring's tension
let wound = 0
let lastWind = 0

// ------------------------------------------------------------------ cozy: the default palette

const COZY = {
  tap: () => marimba(N.D6, 0, 0.035, 0.18, 0.05),
  // a note landed in its window: two wooden notes, up
  capture: () => {
    marimba(N.E6, 0, 0.05, 0.3)
    marimba(N.A6, 0.065, 0.045, 0.35)
  },
  // a todo done: a soft landing, three quick wooden notes up, and a bell to finish
  check: () => {
    thump(0, 0.06, 170, 60, 0.12)
    ;[N.C6, N.E6, N.G6].forEach((f, i) => marimba(f, 0.02 + 0.05 * i, 0.045, 0.3))
    bell(N.C7, 0.17, 0.03, 0.9)
  },
  undo: () => {
    marimba(N.G5, 0, 0.045, 0.25)
    marimba(N.D5, 0.08, 0.04, 0.3)
  },
  // something saved: a rubber stamp, with a pad of air under it
  stamp: () => {
    noiseBurst(0, 0.02, 1800, 1.5, 0.05, 0.02)
    thump(0.005, 0.09, 130, 50, 0.13)
  },
  // mail away: air rushing up, a quick wooden run, a bell as it leaves
  send: () => {
    noiseBurst(0, 0.3, 600, 1.2, 0.035, 0.1, 3200)
    ;[N.G5, N.C6, N.E6].forEach((f, i) => marimba(f, 0.04 + 0.05 * i, 0.04, 0.25))
    bell(N.G6, 0.22, 0.028, 1)
  },
  drop: () => {
    noiseBurst(0, 0.16, 1400, 1.2, 0.02, 0.05, 500)
    marimba(N.D5, 0, 0.04, 0.25)
    marimba(N.A4, 0.09, 0.035, 0.35)
  },
  // the New Game typewriter and typing in the Ask box: tiny keys
  type: () => noiseBurst(0, 0.005, 2800 + Math.random() * 900, 3, 0.03, 0),
  key: () => noiseBurst(0, 0.004, 3200 + Math.random() * 900, 3, 0.018, 0),
  // a reminder: a music-box phrase on glass bells, twice
  ring: () =>
    [0, 0.95].forEach((o) => [N.E6, N.G6, N.D6, N.A6].forEach((f, i) => bell(f, o + 0.16 * i, 0.045, 0.9, { space: 0.3 }))),
  // the companion, poked: a springy boing (a pop with a wobble)
  poke: () => {
    const c = ctx!
    const t = c.currentTime
    const g = voice(0.1)
    envelope(g, t, 0.06, 0.006, 0.28)
    const o = osc('sine', 300 + Math.random() * 80, t, t + 0.28, g)
    o.frequency.exponentialRampToValueAtTime(560, t + 0.12)
    const wobble = c.createGain()
    wobble.gain.setValueAtTime(30, t)
    wobble.gain.exponentialRampToValueAtTime(1, t + 0.28)
    osc('sine', 17, t, t + 0.28, wobble)
    wobble.connect(o.frequency)
  },
  hatch: () => {
    ;[N.C5, N.E5, N.G5, N.C6, N.E6].forEach((f, i) => marimba(f, 0.06 * i, 0.045, 0.35))
    bell(N.G6, 0.32, 0.035, 1.2)
  },
  // GAME START, a focus session: a short chiptune fanfare, then a bell
  start: () => {
    ;[N.C5, N.C5, N.G5, N.E5, N.G5, N.C6].forEach((f, i) => chip(f, [0, 0.11, 0.22, 0.38, 0.49, 0.62][i], 0.028, i === 5 ? 0.3 : 0.12))
    bell(N.C7, 0.62, 0.025, 1.1)
  },
  // a level, a goal, a finished focus session: a wooden run up and a bright chord ringing out
  levelup: () => {
    ;[N.C6, N.E6, N.G6, N.C7].forEach((f, i) => marimba(f, 0.08 * i, 0.045, 0.35))
    bell(N.C7, 0.32, 0.03, 1.5, { space: 0.45 })
    bell(N.E7, 0.34, 0.02, 1.4, { space: 0.45 })
  },
  // moving between pages: a small tactile click, a crisp tick with a little body under it
  click: () => {
    noiseBurst(0, 0.005, 2300, 2.2, 0.09, 0)
    pop(620, 330, 0, 0.03, 0.03, 0.02)
  },
  // a bookmark: wood and a little glass, up
  keep: () => {
    marimba(N.A5, 0, 0.045, 0.3)
    bell(N.E6, 0.06, 0.028, 0.8)
  },
  skip: () => {
    noiseBurst(0, 0.14, 1300, 1.2, 0.03, 0.04, 420)
    marimba(N.E5, 0.02, 0.025, 0.2)
  },
  // each step the companion takes while working climbs the scale (n = step number)
  step: (n = 0) => marimba(CLIMB[Math.min(n, CLIMB.length - 1)], 0, 0.022, 0.22, 0.1),
  // the answer arrived: a warm rolled chord of bells over a low wooden note
  arrive: () => {
    marimba(N.C5, 0, 0.035, 0.5)
    ;[N.C6, N.E6, N.A6].forEach((f, i) => bell(f, 0.05 * i, 0.028, 1.4, { space: 0.4 }))
  },
  // a new theme: glitter
  sparkle: () => [N.C7, N.E7, N.G7, 3520].forEach((f, i) => bell(f, 0.05 * i, 0.015, 0.5, { bright: 1.4, space: 0.4 })),
  open: () => {
    pop(380, 720, 0, 0.04)
    noiseBurst(0, 0.08, 1500, 1, 0.012, 0.02, 3000)
  },
  close: () => {
    pop(700, 360, 0, 0.035)
    noiseBurst(0, 0.08, 3000, 1, 0.01, 0.02, 1200)
  },
  // winding the deadline clock: a wind-up toy's key, krrk by krrk, tightening as you keep winding
  tick: () => {
    const now = ctx!.currentTime
    wound = now - lastWind > 0.8 ? 0 : wound + 1 // a pause lets the spring relax
    lastWind = now
    ratchet(0, 1 + Math.min(wound, 24) * 0.008)
  },
  // a deadline is set: the key's last few notches, the latch drops, a small bell
  lock: () => {
    ;[0, 0.04, 0.075].forEach((o, i) => ratchet(o, 1.04 + i * 0.03, 0.045))
    noiseBurst(0.09, 0.03, 900, 1.5, 0.06, 0.02)
    thump(0.09, 0.08, 110, 45, 0.12)
    bell(N.C7, 0.15, 0.03, 1, { space: 0.4 })
    bell(N.G7, 0.21, 0.016, 0.8, { space: 0.4 })
  },
  // tossing: a crumple of paper (many tiny crackles), then it lands in the bin
  crumple: () => {
    crackle(0, 14)
    noiseBurst(0, 0.3, 700, 0.8, 0.012, 0, 1600)
  },
  bin: () => {
    thump(0, 0.09, 125, 45, 0.15)
    bell(520, 0.03, 0.022, 0.3, { ratio: 2.76, bright: 2.5, space: 0.15 }) // the tin can
    noiseBurst(0.09, 0.012, 2600, 4, 0.05, 0.05) // the lid
  },
} as const

export type Sound = keyof typeof COZY

// ------------------------------------------------------------------ classic: the first palette

function tone(freq: number, at: number, dur: number, type: OscillatorType, vol: number) {
  const t = ctx!.currentTime + at
  const g = voice(0)
  envelope(g, t, vol, 0.004, dur)
  osc(type, freq, t, t + dur, g)
}

const CLASSIC: Record<Sound, (n?: number) => void> = {
  tap: () => pop(420, 760, 0, 0.05, 0.09, 0),
  capture: () => {
    pop(520, 880, 0, 0.045, 0.08, 0)
    pop(700, 1180, 0.07, 0.03, 0.07, 0)
  },
  check: () => {
    tone(80, 0, 0.12, 'triangle', 0.04)
    ;[784, 1175].forEach((f, i) => tone(f, 0.06 + 0.08 * i, 0.22, 'triangle', 0.03))
  },
  undo: () => [523, 392].forEach((f, i) => tone(f, 0.08 * i, 0.16, 'triangle', 0.022)),
  stamp: () => tone(70, 0, 0.18, 'triangle', 0.05),
  send: () => [523, 659, 784].forEach((f, i) => tone(f, 0.09 * i, 0.22, 'triangle', 0.025)),
  drop: () => [262, 196].forEach((f, i) => tone(f, 0.1 * i, 0.18, 'triangle', 0.025)),
  type: () => pop(1400 + Math.random() * 300, 1800, 0, 0.012, 0.03, 0),
  ring: () => [0, 0.9].forEach((o) => [988, 1319, 1175, 1568].forEach((f, i) => tone(f, o + 0.13 * i, 0.4, 'sine', 0.04))),
  poke: () => pop(300 + Math.random() * 200, 620, 0, 0.05, 0.12, 0),
  hatch: () => [392, 523, 659, 784, 1047].forEach((f, i) => tone(f, 0.07 * i, 0.25, 'triangle', 0.028)),
  start: () => [523, 523, 784, 659, 784, 1047].forEach((f, i) => tone(f, [0, 0.12, 0.24, 0.42, 0.54, 0.7][i], 0.3, 'square', 0.018)),
  levelup: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.12 * i, 0.3, 'triangle', 0.03)),
  click: () => pop(900, 380, 0, 0.022, 0.14, 0),
  keep: () => [740, 988].forEach((f, i) => tone(f, 0.06 * i, 0.18, 'sine', 0.035)),
  skip: () => pop(480, 260, 0, 0.028, 0.1, 0),
  step: (n = 0) => pop(520 + Math.min(n, 10) * 45, 760 + Math.min(n, 10) * 60, 0, 0.022, 0.07, 0),
  arrive: () => [523, 659, 988].forEach((f, i) => tone(f, 0.05 * i, 0.5, 'sine', 0.028)),
  sparkle: () => [1319, 1568, 1760, 2093].forEach((f, i) => tone(f, 0.045 * i, 0.16, 'sine', 0.016)),
  open: () => pop(380, 640, 0, 0.035, 0.1, 0),
  close: () => pop(640, 360, 0, 0.03, 0.09, 0),
  key: () => pop(1800 + Math.random() * 500, 2300, 0, 0.006, 0.02, 0),
  tick: COZY.tick,
  lock: COZY.lock,
  crumple: COZY.crumple,
  bin: COZY.bin,
}

// ------------------------------------------------------------------ playing

const PACKS: Record<Pack, Record<Sound, (n?: number) => void>> = { cozy: COZY, classic: CLASSIC }
let lastKey = 0

export function play(s: Sound, n?: number) {
  if (!enabled) return
  if (s === 'key' || s === 'tick') {
    const now = performance.now()
    if (now - lastKey < 45) return // typing (or winding) fast shouldn't become a buzz
    lastKey = now
  }
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') void ctx.resume()
    PACKS[pack][s](n)
  } catch {
    /* audio unavailable */
  }
}
