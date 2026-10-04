// Today: ask your companion anything at the top; below, what's left to do (todos, alarms) and what got
// done (today's log, where finished todos land with a ✓), plus the evening recap.
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import { api, askBolt, clock, when, type NextUp, type State, type Todo } from './api'
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
  // finished todos stay ticked in the list until the day closes (recap hour), then move into the log
  const closed = new Date().getHours() >= s.day.recap_hour
  const story = [
    ...s.today.log.map((e) => ({ key: `l${e.id}`, at: e.created_at, text: e.body, todo: null as Todo | null })),
    ...(closed ? s.today.done.map((t) => ({ key: `t${t.id}`, at: t.done_at ?? t.created_at, text: t.title, todo: t })) : []),
  ].sort((x, y) => x.at.localeCompare(y.at))
  const ticked = closed ? [] : s.today.done

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
          <UpNext state={s} notify={notify} refresh={refresh} />
          <Win title={`todo.lst${s.today.open.length ? ` (${s.today.open.length})` : ''}`} id="win-todos">
            {s.today.open.length === 0 && ticked.length === 0 ? (
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
                  {ticked.map((t) => (
                    <motion.li key={t.id} layout className="done" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}>
                      <button className="check-box" aria-label={`Not done: ${t.title}`} onClick={(e) => doTodo(t, 'undo', e.currentTarget)}>
                        ✓
                      </button>
                      <span className="todo-text">{t.title}</span>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
            {ticked.length > 0 && (
              <p className="muted small todo-note">
                ticked ones move to today.log at {String(s.day.recap_hour).padStart(2, '0')}:00
              </p>
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

const VERB: Record<NextUp['action'], string> = { answer: 'draft a reply', seen: 'got it', followup: 'write follow-up', mail: 'open Mail', tab: 'open tab' }

/** Everything waiting on you, from every journey: replies, interviews, follow-ups, drafts, stale kept items.
 * Each row is one click to the next step. Refetched whenever the day's state changes. */
function UpNext({ state, notify, refresh }: { state: State; notify: (t: string, k?: Toast['kind']) => void; refresh: () => Promise<void> }) {
  const fx = useFx()
  const [rows, setRows] = useState<NextUp[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => {
    void api.next().then(setRows).catch(() => setRows([]))
  }, [state])
  if (!rows.length) return null
  const key = (r: NextUp) => `${r.kind}${r.id}${r.module ?? ''}`

  const go = async (r: NextUp) => {
    setBusy(key(r))
    try {
      if (r.action === 'answer') {
        const thread = r.draft_id ? ` Reply in the same thread (reply_to ${r.draft_id}).` : ` Write to ${r.from}.`
        askBolt(`${r.title}: "${r.detail}"\n\n${r.snippet}\n\nDraft my answer in Mail.${thread} If they're asking to meet, offer two or three times and keep it short.`)
        await api.inboxDone(r.id)
      } else if (r.action === 'seen') {
        await api.inboxDone(r.id)
        fx.sound('check')
      } else if (r.action === 'followup') {
        await api.followup(r.id)
        fx.sound('send')
        notify('Follow-up drafted in the same thread. Check it in Mail.')
        location.hash = 'mail'
      } else {
        location.hash = r.action === 'mail' ? 'mail' : `m:${r.module}`
      }
      setRows(await api.next())
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Win title={`up_next.q (${rows.length})`} id="win-next">
      <ul className="next-list">
        <AnimatePresence initial={false}>
          {rows.map((r, i) => (
            <motion.li
              key={key(r)}
              className={`next-${r.kind}`}
              layout
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0, transition: { delay: 0.04 * i } }}
              exit={{ opacity: 0, x: 40, height: 0 }}
            >
              <span className="next-dot" aria-hidden />
              <span className="next-text">
                <b>{r.title}</b>
                {r.detail && <span className="muted small">{r.detail}</span>}
              </span>
              {r.action === 'followup' && (
                <button className="icon-x" title="No follow-up for this one" onClick={async () => (await api.noFollowup(r.id), fx.sound('drop'), setRows(await api.next()))}>
                  ×
                </button>
              )}
              <motion.button className={`btn tiny ${r.action === 'answer' ? 'solid' : ''}`} whileTap={{ scale: 0.9 }} disabled={busy === key(r)} onClick={() => go(r)}>
                {busy === key(r) ? <span className="blink">…</span> : VERB[r.action]}
              </motion.button>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </Win>
  )
}
