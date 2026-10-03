// Today: one capture box, your companion, and the day's todos, reminders, log and recap.
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, clock, when, type State, type Todo } from './api'
import { Companion, type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { FlameIcon } from './icons'
import { Bar, Seg, Win } from './ui'
import type { Toast } from './util'

const POKES = ['hehe', 'that tickles!', "I'm awake, I'm awake", 'one thing at a time :)', '*happy wiggle*', 'boop']

/** Mirrors backend/life/capture.py closely enough to preview what Enter will do. */
function guessKind(t: string): 'todo' | 'reminder' | 'log' | null {
  if (!t.trim()) return null
  if (/^\s*remind\s+me\b/i.test(t)) return 'reminder'
  if (/^\s*(todo\b|t:|\[\s?\]|-\s*\[\s?\])/i.test(t)) return 'todo'
  return 'log'
}

function line(s: State, name: string): { mood: Mood; text: string } {
  const h = new Date().getHours()
  const done = s.today.done.length
  const goal = s.day.todo_goal
  const who = s.about.name ? `, ${s.about.name}` : ''
  if (s.reminders.some((r) => r.status === 'fired')) return { mood: 'happy', text: 'Psst! A reminder is ringing.' }
  if (done >= goal) return { mood: 'happy', text: `${done} done today. That's a good day${who}!` }
  if (h >= 23 || h < 5) return { mood: 'sleepy', text: 'It is very late… log one thing and rest?' }
  if (s.progress.streak_days >= 3) return { mood: 'happy', text: `${s.progress.streak_days}-day streak! Keep the chain going.` }
  if (done > 0) return { mood: 'idle', text: `${done}/${goal} today. ${goal - done} more and we celebrate.` }
  if (s.today.open.length) return { mood: 'idle', text: `Pick one small thing${who}. I'll cheer.` }
  if (h < 12) return { mood: 'idle', text: `Morning${who}! What's the plan today?` }
  return { mood: 'idle', text: `Hi${who}, I'm ${name}. Tell me what you're up to.` }
}

export function Today({
  state: s,
  refresh,
  notify,
}: {
  state: State
  refresh: () => Promise<void>
  notify: (t: string, k?: Toast['kind']) => void
}) {
  const fx = useFx()
  const [text, setText] = useState('')
  const [poke, setPoke] = useState<string | null>(null)
  const [recapBusy, setRecapBusy] = useState(false)
  const [cheerN, setCheerN] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const kind = guessKind(text)
  const companion = s.companion ?? { species: 'blob', name: 'buddy' }
  const { mood, text: say } = useMemo(() => line(s, companion.name), [s, companion.name])

  // "/" or "n" jumps to the capture box from anywhere on the page
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === '/' || e.key === 'n') && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = async () => {
    if (!text.trim()) return
    try {
      const r = await api.capture(text)
      fx.sound('capture')
      const target = r.kind === 'todo' ? 'win-todos' : r.kind === 'reminder' ? 'win-reminders' : 'win-log'
      setText('')
      await fx.fly(inputRef.current, target)
      if (r.xp) fx.float(document.getElementById(target), `+${r.xp} XP`)
      if (r.kind === 'reminder' && r.due_at) notify(`Reminder set for ${when(r.due_at)}`)
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  const doTodo = async (t: Todo, action: 'done' | 'undo' | 'drop', el: Element | null) => {
    try {
      const r = await api.todo(t.id, action)
      if (action === 'done') {
        fx.sound('check')
        fx.burstAt(el)
        if (r.xp) fx.float(el, `+${r.xp} XP`)
        setCheerN((n) => n + 1)
        if (s.today.done.length + 1 === s.day.todo_goal) {
          setTimeout(() => fx.banner({ kind: 'goal', title: 'GOOD DAY!', sub: `${s.day.todo_goal} things done. ${companion.name} is very proud.` }), 600)
        }
      } else {
        fx.sound('undo')
      }
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  const writeRecap = async () => {
    setRecapBusy(true)
    try {
      await api.recap()
      fx.sound('send')
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setRecapBusy(false)
    }
  }

  const addTomorrow = async (t: string, el: Element | null) => {
    await api.capture(`todo ${t}`)
    fx.sound('capture')
    await fx.fly(el, 'win-todos')
    await refresh()
  }

  const p = s.progress
  const done = s.today.done.length
  const upcoming = s.reminders

  return (
    <div className="today">
      <form
        className={`capture ${kind ?? ''}`}
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <span className="capture-prompt">&gt;</span>
        <input
          ref={inputRef}
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="what's up?  try: todo send the invoice · remind me to stretch in 20 min · fixed the bug!"
          aria-label="Quick capture"
        />
        <AnimatePresence mode="wait">
          {kind && (
            <motion.span key={kind} className={`capture-kind k-${kind}`} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }}>
              {kind === 'log' ? 'log it' : kind}
            </motion.span>
          )}
        </AnimatePresence>
        <button className="btn solid" disabled={!text.trim()}>
          ↵
        </button>
      </form>

      <div className="widgets">
        <Win title={`${companion.name.toLowerCase()}.exe`} className="w-buddy">
          <div className="pip-row">
            <Companion
              species={companion.species}
              mood={poke ? 'happy' : mood}
              size={96}
              cheer={cheerN}
              onPoke={() => {
                fx.sound('poke')
                setPoke(POKES[Math.floor(Math.random() * POKES.length)])
                setTimeout(() => setPoke(null), 1800)
              }}
            />
            <motion.div key={poke ?? say} className="bubble" initial={{ opacity: 0, scale: 0.9, x: -6 }} animate={{ opacity: 1, scale: 1, x: 0 }}>
              {poke ?? say}
            </motion.div>
          </div>
          <div className="level-row">
            <div className="lv">
              <span className="lv-label">LV</span>
              <Seg value={p.level} digits={2} />
            </div>
            <div className="xp-col">
              <div className="xp-text">
                <span>{p.xp} XP</span>
                <span className="muted">{p.level_need - p.level_xp} to next</span>
              </div>
              <Bar value={p.level_xp / Math.max(1, p.level_need)} label="XP to next level" />
            </div>
          </div>
        </Win>

        <div className="stat-col">
          <div className={`stat-tile ${done >= s.day.todo_goal ? 'inverse' : ''}`}>
            <span className="stat-name">done today</span>
            <Seg value={done} digits={2} suffix={`/${s.day.todo_goal}`} />
          </div>
          <div className="stat-tile">
            <span className="stat-name">
              <FlameIcon /> streak
            </span>
            <Seg value={p.streak_days} digits={2} suffix="d" />
          </div>
          <div className="stat-tile">
            <span className="stat-name">logged today</span>
            <Seg value={s.today.log.length} digits={2} />
          </div>
        </div>

        <Win title="todo.lst" className="w-todos" id="win-todos">
          {s.today.open.length === 0 && done === 0 ? (
            <p className="muted mono">&gt; no todos. type "todo …" above_</p>
          ) : (
            <ul className="todo">
              <AnimatePresence initial={false}>
                {s.today.open.map((t) => (
                  <motion.li key={t.id} layout initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }}>
                    <button className="check-box" aria-label={`Done: ${t.title}`} onClick={(e) => doTodo(t, 'done', e.currentTarget)} />
                    <span className="todo-text">{t.title}</span>
                    {t.due_at && <span className="tag">{when(t.due_at)}</span>}
                    <button className="icon-x" title="Drop it" onClick={(e) => doTodo(t, 'drop', e.currentTarget)}>
                      ×
                    </button>
                  </motion.li>
                ))}
                {s.today.done.map((t) => (
                  <motion.li key={t.id} layout className="done" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                    <button className="check-box" aria-label={`Undo: ${t.title}`} onClick={(e) => doTodo(t, 'undo', e.currentTarget)}>
                      ✓
                    </button>
                    <span className="todo-text">{t.title}</span>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
        </Win>

        <Win title="alarms.clk" className="w-rem" id="win-reminders">
          {upcoming.length === 0 ? (
            <p className="muted mono">&gt; "remind me to … at 6pm"_</p>
          ) : (
            <ul className="rem-list">
              {upcoming.map((r) => (
                <li key={r.id} className={r.status === 'fired' ? 'ringing' : ''}>
                  <span className="rem-time">{when(r.due_at)}</span>
                  <span className="todo-text">{r.text}</span>
                </li>
              ))}
            </ul>
          )}
        </Win>

        <Win title="today.log" className="w-log" id="win-log">
          {s.today.log.length === 0 ? (
            <p className="muted mono">&gt; nothing logged yet today. what did you do?_</p>
          ) : (
            <ul className="timeline">
              {s.today.log.map((e) => (
                <motion.li key={e.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                  <span className="muted mono">[{clock(e.created_at)}]</span> {e.body}
                </motion.li>
              ))}
            </ul>
          )}
        </Win>

        <Win title="recap.txt" className="w-recap">
          {s.recap ? (
            <div className="recap">
              <div className="recap-head">{s.recap.headline}</div>
              <p>{s.recap.recap}</p>
              {s.recap.tomorrow.length > 0 && (
                <>
                  <div className="field-label">for tomorrow</div>
                  <ul className="todo">
                    {s.recap.tomorrow.map((t) => (
                      <li key={t}>
                        <span className="todo-text">{t}</span>
                        <button className="btn tiny" onClick={(e) => addTomorrow(t, e.currentTarget)}>
                          + todo
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <button className="btn tiny ghost" disabled={recapBusy} onClick={writeRecap}>
                {recapBusy ? 'rewriting…' : '↻ rewrite'}
              </button>
            </div>
          ) : (
            <div className="recap-empty">
              <p className="muted">
                {companion.name} writes up your day at {String(s.day.recap_hour).padStart(2, '0')}:00, or whenever you ask.
              </p>
              <button className="btn" disabled={recapBusy} onClick={writeRecap}>
                {recapBusy ? <span className="blink">{companion.name} is thinking…</span> : "Recap today's adventure"}
              </button>
            </div>
          )}
        </Win>
      </div>
    </div>
  )
}
