// "New Game": the first-run setup, played like the opening of an RPG.
// Title screen -> a few questions (typed out, one at a time) -> choose and name a companion ->
// optional writing samples -> brain check -> GAME START.
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { api, type CompanionChoice, type Question } from './api'
import { Companion } from './Companion'
import { useFx } from './fx/Fx'
import { play } from './fx/sound'
import { Win } from './ui'

function Typewriter({ text, onDone }: { text: string; onDone?: () => void }) {
  const reduce = useReducedMotion()
  const [n, setN] = useState(reduce ? text.length : 0)
  const done = useRef(onDone)
  done.current = onDone
  useEffect(() => {
    if (reduce) {
      done.current?.()
      return
    }
    setN(0)
    let i = 0
    const t = setInterval(() => {
      i++
      setN(i)
      if (i % 2 === 0) play('type')
      if (i >= text.length) {
        clearInterval(t)
        done.current?.()
      }
    }, 28)
    return () => clearInterval(t)
  }, [text, reduce])
  return (
    <span>
      {text.slice(0, n)}
      <span className="caret">▌</span>
    </span>
  )
}

type Step = { k: 'title' } | { k: 'q'; i: number } | { k: 'pick' } | { k: 'samples' } | { k: 'brain' }

export function NewGame({ onReady, replay }: { onReady: () => void; replay?: boolean }) {
  const fx = useFx()
  const [questions, setQuestions] = useState<Question[]>([])
  const [companions, setCompanions] = useState<CompanionChoice[]>([])
  const [step, setStep] = useState<Step>({ k: replay ? 'q' : 'title', i: 0 } as Step)
  const [about, setAbout] = useState<Record<string, string>>({})
  const [species, setSpecies] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [cheer, setCheer] = useState(0)
  const [typed, setTyped] = useState(false)
  const [sample, setSample] = useState('')
  const [samples, setSamples] = useState(0)
  const [brain, setBrain] = useState<{ ok: boolean; name: string; detail: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    void api.onboarding().then((o) => {
      setQuestions(o.questions)
      setCompanions(o.companions)
    })
    void api.state().then((s) => {
      setAbout(s.about)
      setSamples(s.samples)
      if (s.companion) {
        setSpecies(s.companion.species)
        setName(s.companion.name)
      }
    })
  }, [])

  // title screen: any key starts
  useEffect(() => {
    if (step.k !== 'title') return
    const go = () => {
      play('start')
      setStep({ k: 'q', i: 0 })
    }
    window.addEventListener('keydown', go, { once: true })
    return () => window.removeEventListener('keydown', go)
  }, [step.k])

  useEffect(() => {
    if (step.k === 'brain') void api.brainCheck().then(setBrain)
  }, [step.k])

  const next = () => {
    play('tap')
    setTyped(false)
    if (step.k === 'q') setStep(step.i + 1 < questions.length ? { k: 'q', i: step.i + 1 } : { k: 'pick' })
    else if (step.k === 'pick') setStep({ k: 'samples' })
    else if (step.k === 'samples') setStep({ k: 'brain' })
  }
  const back = () => {
    play('tap')
    if (step.k === 'q' && step.i > 0) setStep({ k: 'q', i: step.i - 1 })
    else if (step.k === 'pick') setStep({ k: 'q', i: questions.length - 1 })
    else if (step.k === 'samples') setStep({ k: 'pick' })
    else if (step.k === 'brain') setStep({ k: 'samples' })
  }

  const finish = async () => {
    if (!species) return
    setBusy(true)
    try {
      await api.newGame(about, { species, name: name.trim() || 'buddy' })
      play('start')
      fx.banner({ kind: 'goal', title: replay ? 'SAVED!' : 'GAME START!', sub: `${name || 'Your companion'} moved onto your desk. Let's get things done.` })
      onReady()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const addSample = async () => {
    try {
      await api.addSample({ kind: 'email', title: '', body: sample })
      play('capture')
      setSamples((n) => n + 1)
      setSample('')
      setErr('')
    } catch (e) {
      setErr((e as Error).message.includes('40') ? 'A sample needs at least 40 characters.' : (e as Error).message)
    }
  }

  const total = questions.length + 3
  const at = step.k === 'q' ? step.i : step.k === 'pick' ? questions.length : step.k === 'samples' ? questions.length + 1 : questions.length + 2

  if (step.k === 'title') {
    return (
      <div className="newgame title-screen" onClick={() => window.dispatchEvent(new KeyboardEvent('keydown'))}>
        <motion.div initial={{ y: -40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ type: 'spring', stiffness: 120, damping: 12 }}>
          <div className="title-logo">TAMADESK</div>
          <div className="title-sub">a tiny companion for getting things done</div>
        </motion.div>
        <div className="title-crew">
          {['sprout', 'blob', 'bot'].map((s, i) => (
            <motion.div key={s} initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.3 + i * 0.15, type: 'spring' }}>
              <Companion species={s} mood={i === 1 ? 'happy' : 'idle'} size={i === 1 ? 110 : 80} />
            </motion.div>
          ))}
        </div>
        <div className="press-start blink">PRESS ANY KEY</div>
      </div>
    )
  }

  return (
    <div className="newgame">
      <div className="ng-progress" aria-label={`step ${at + 1} of ${total}`}>
        {Array.from({ length: total }, (_, i) => (
          <i key={i} className={i < at ? 'done' : i === at ? 'on' : ''} />
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={step.k + (step.k === 'q' ? step.i : '')}
          initial={{ opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -40 }}
          transition={{ duration: 0.22 }}
        >
          {step.k === 'q' && questions[step.i] && (
            <Win title={`question_${step.i + 1}.txt`} className="ng-win">
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (step.i === 0 && !about.name?.trim()) return
                  next()
                }}
              >
                <h2 className="ng-q">
                  <Typewriter text={questions[step.i].q} onDone={() => setTyped(true)} />
                </h2>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: typed ? 1 : 0.3 }}>
                  {step.i === 0 ? (
                    <input
                      autoFocus
                      className="ng-input"
                      value={about[questions[step.i].key] ?? ''}
                      placeholder={questions[step.i].hint}
                      onChange={(e) => setAbout({ ...about, [questions[step.i].key]: e.target.value })}
                    />
                  ) : (
                    <textarea
                      autoFocus
                      className="ng-input"
                      rows={3}
                      value={about[questions[step.i].key] ?? ''}
                      placeholder={questions[step.i].hint}
                      onChange={(e) => setAbout({ ...about, [questions[step.i].key]: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          next()
                        }
                      }}
                    />
                  )}
                </motion.div>
                <div className="ng-actions">
                  {step.i > 0 && (
                    <button type="button" className="btn ghost" onClick={back}>
                      ← back
                    </button>
                  )}
                  <span className="muted small">
                    <kbd>Enter</kbd> next{step.i > 0 ? ' · blank is fine' : ''}
                  </span>
                  <button type="submit" className="btn solid" disabled={step.i === 0 && !about.name?.trim()}>
                    Next →
                  </button>
                </div>
              </form>
            </Win>
          )}

          {step.k === 'pick' && (
            <Win title="choose_companion.exe" className="ng-win wide">
              <h2 className="ng-q">Choose your companion.</h2>
              <div className="pick-row">
                {companions.map((c) => (
                  <button
                    key={c.species}
                    className={`pick-card ${species === c.species ? 'on' : ''}`}
                    onClick={() => {
                      play('hatch')
                      setSpecies(c.species)
                      if (!name || companions.some((x) => x.label === name)) setName(c.label)
                      setCheer((n) => n + 1)
                    }}
                  >
                    <Companion species={c.species} size={92} mood={species === c.species ? 'happy' : 'idle'} cheer={species === c.species ? cheer : 0} />
                    <b>{c.label}</b>
                    <span className="muted small">{c.blurb}</span>
                  </button>
                ))}
              </div>
              {species && (
                <motion.label className="field name-field" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                  <span>Give it a name</span>
                  <input value={name} maxLength={24} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && next()} />
                </motion.label>
              )}
              <div className="ng-actions">
                <button className="btn ghost" onClick={back}>
                  ← back
                </button>
                <span />
                <button className="btn solid" disabled={!species || !name.trim()} onClick={next}>
                  That's the one →
                </button>
              </div>
            </Win>
          )}

          {step.k === 'samples' && (
            <Win title="your_voice.txt" className="ng-win wide">
              <h2 className="ng-q">Paste something you wrote.</h2>
              <p className="muted">
                An email, a message, a short essay. {name || 'Your companion'} studies these so drafts sound like you, not like a chatbot.
                Two or three is plenty, and you can add more later in Write.
              </p>
              <textarea className="ng-input tall" value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Hey Sam, quick one about Thursday…" />
              {err && <p className="bad-text small">{err}</p>}
              <div className="ng-actions">
                <button className="btn ghost" onClick={back}>
                  ← back
                </button>
                <span className="muted small">{samples} sample{samples === 1 ? '' : 's'} saved</span>
                <button className="btn" disabled={sample.trim().length < 40} onClick={addSample}>
                  + Save sample
                </button>
                <button className="btn solid" onClick={next}>
                  {samples ? 'Next →' : 'Skip for now →'}
                </button>
              </div>
            </Win>
          )}

          {step.k === 'brain' && (
            <Win title="brain.sys" className="ng-win wide">
              <h2 className="ng-q">Connecting a brain…</h2>
              <p className="muted">
                {name || 'Your companion'} writes drafts and recaps with <b>your own</b> Claude Code, running on this computer under your login. No
                keys are stored here. You can switch to a local Ollama model in Settings.
              </p>
              <div className={`brain-status ${brain ? (brain.ok ? 'ok' : 'bad') : ''}`}>
                {!brain ? (
                  <span className="blink">checking…</span>
                ) : brain.ok ? (
                  <>✓ {brain.detail}</>
                ) : (
                  <>
                    ✗ {brain.detail}
                    <span className="muted small"> Logging and todos work without it, so you can fix this later.</span>
                  </>
                )}
              </div>
              {err && <p className="bad-text small">{err}</p>}
              <div className="ng-actions">
                <button className="btn ghost" onClick={back}>
                  ← back
                </button>
                <span />
                {brain && !brain.ok && (
                  <button className="btn" onClick={() => api.brainCheck().then(setBrain)}>
                    Check again
                  </button>
                )}
                <button className="btn solid big" disabled={busy || !species} onClick={finish}>
                  {replay ? 'Save' : 'START ▶'}
                </button>
              </div>
            </Win>
          )}
        </motion.div>
      </AnimatePresence>

      {species && step.k !== 'pick' && (
        <div className="ng-buddy">
          <Companion species={species} size={64} mood="happy" />
        </div>
      )}
    </div>
  )
}
