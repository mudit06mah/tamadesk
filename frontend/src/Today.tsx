// Today: ask your companion anything at the top; below, what's left to do (todos, alarms) and what got
// done (today's log, where finished todos land with a ✓), plus the evening recap.
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState } from 'react'
import { api, clock, when, type State, type Todo } from './api'
import { AskPanel } from './Ask'
import { type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { Win } from './ui'
import type { Toast } from './util'

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
  const [recapBusy, setRecapBusy] = useState(false)
  const [cheerN, setCheerN] = useState(0)
  const companion = s.companion ?? { species: 'blob', name: 'buddy' }
  const { mood, text: say } = useMemo(() => line(s, companion.name), [s, companion.name])

  const doTodo = async (t: Todo, action: 'done' | 'undo' | 'drop', el: Element | null) => {
    try {
      const r = await api.todo(t.id, action)
      if (action === 'done') {
        fx.sound('check')
        fx.burstAt(el)
        if (r.xp) fx.float(el, `+${r.xp} XP`)
        setCheerN((n) => n + 1) // the companion up top does a little jump
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
  // what got done today, newest last: log lines and finished todos together
  const story = [
    ...s.today.log.map((e) => ({ key: `l${e.id}`, at: e.created_at, text: e.body, todo: null as Todo | null })),
    ...s.today.done.map((t) => ({ key: `t${t.id}`, at: t.done_at ?? t.created_at, text: t.title, todo: t })),
  ].sort((x, y) => x.at.localeCompare(y.at))

  return (
    <div className="today">
      <AskPanel
        greeting={say}
        mood={mood}
        interests={s.about.interests ?? ''}
        level={{ level: p.level, xp: p.xp, into: p.level_xp, need: p.level_need }}
        stats={{ done, goal: s.day.todo_goal, streak: p.streak_days }}
        cheer={cheerN}
      />

      <div className="day-grid">
        <div className="day-col">
          <Win title={`todo.lst${s.today.open.length ? ` (${s.today.open.length})` : ''}`} id="win-todos">
            {s.today.open.length === 0 ? (
              <p className="muted mono">&gt; {done ? 'all clear. nice.' : 'no todos. type "todo …" above'}_</p>
            ) : (
              <ul className="todo">
                <AnimatePresence initial={false}>
                  {s.today.open.map((t) => (
                    <motion.li key={t.id} layout initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40, height: 0 }}>
                      <button className="check-box" aria-label={`Done: ${t.title}`} onClick={(e) => doTodo(t, 'done', e.currentTarget)} />
                      <span className="todo-text">{t.title}</span>
                      {t.due_at && <span className="tag">{when(t.due_at)}</span>}
                      <button className="icon-x" title="Drop it" onClick={(e) => doTodo(t, 'drop', e.currentTarget)}>
                        ×
                      </button>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </Win>
          <Win title="recap.txt">
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

        <div className="day-col">
          <Win title="alarms.clk" id="win-reminders">
            {s.reminders.length === 0 ? (
              <p className="muted mono">&gt; "remind me to … in 10 minutes"_</p>
            ) : (
              <ul className="rem-list">
                {s.reminders.map((r) => (
                  <li key={r.id} className={r.status === 'fired' ? 'ringing' : ''}>
                    <span className="rem-time">{when(r.due_at)}</span>
                    <span className="todo-text">{r.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </Win>

          <Win title="today.log" id="win-log">
            {story.length === 0 ? (
              <p className="muted mono">&gt; nothing yet today. finished todos and "log …" lines land here_</p>
            ) : (
              <ul className="timeline">
                <AnimatePresence initial={false}>
                  {story.map((e) => (
                    <motion.li key={e.key} className={e.todo ? 'did' : ''} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                      <span className="muted mono">[{clock(e.at)}]</span> {e.todo && <span className="did-mark">✓</span>} {e.text}
                      {e.todo && (
                        <button className="icon-x" title="Not done after all" onClick={(ev) => doTodo(e.todo!, 'undo', ev.currentTarget)}>
                          undo
                        </button>
                      )}
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </Win>
        </div>
      </div>
    </div>
  )
}
