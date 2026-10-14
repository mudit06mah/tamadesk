// Today: ask your companion anything at the top; below, your day as one list. What's waiting on you
// comes first, then the timeline (meetings, reminders, todos due, and what you already did, folded
// away under "earlier"), then undated todos. Every row links to its draft, thread or tab, and a few
// open in place, so the rest of the app is a drill-down from here.
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, askBolt, clock, dayPlus, localMinute, utc, when, type DayEntry, type DayView, type MailDraft, type Mod, type ModItem, type State } from './api'
import { AskPanel } from './Ask'
import { type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { ItemCard, useItemActions } from './ItemCard'
import { DuePicker } from './DuePicker'
import { DraftCard } from './Mail'
import { OnlyYou } from './OnlyYou'
import { FocusBar, FocusStart, ReviewDialog } from './Play'
import { Win } from './ui'
import { pressureOf, useRefresh, type Toast } from './util'

type Notify = (t: string, k?: Toast['kind']) => void

function line(s: State, name: string, view: DayView | null): { mood: Mood; text: string } {
  const h = new Date().getHours()
  const done = s.today.done.length
  const goal = s.day.todo_goal
  const who = s.about.name ? `, ${s.about.name}` : ''
  const soon = view?.is_today ? nextMeeting(view) : null
  const press = view?.pressure
  if (s.reminders.some((r) => r.status === 'fired')) return { mood: 'happy', text: 'Psst! A reminder is ringing.' }
  // a deadline within the hour (or missed) is louder than anything else; within 3 hours, louder than a meeting later
  if (press && (press.stage >= 3 || (press.stage === 2 && !(soon && soon.mins <= 60)))) return { mood: 'idle', text: press.text }
  if (soon && soon.mins <= 60) return { mood: 'idle', text: `${soon.e.title} ${soon.mins <= 1 ? 'is starting' : `in ${soon.mins} min`}.` }
  if (done >= goal) return { mood: 'happy', text: `${done} done today. That's a good day${who}!` }
  if (h >= 23 || h < 5) return { mood: 'sleepy', text: 'It is very late… log one thing and rest?' }
  if (press) return { mood: 'idle', text: press.text }
  if (view?.needs_you.length) return { mood: 'idle', text: `${view.needs_you.length} thing${view.needs_you.length > 1 ? 's' : ''} need you. Top one first?` }
  if (s.progress.streak_days >= 3) return { mood: 'happy', text: `${s.progress.streak_days}-day streak! Keep the chain going.` }
  if (done > 0) return { mood: 'idle', text: `${done}/${goal} today. ${goal - done} more and we celebrate.` }
  if (s.today.open.length) return { mood: 'idle', text: `Pick one small thing${who}. I'll cheer.` }
  if (h < 12) return { mood: 'idle', text: `Morning${who}! What's the plan today?` }
  return { mood: 'idle', text: `Hi${who}, I'm ${name}. Tell me what you're up to.` }
}

function nextMeeting(view: DayView): { e: DayEntry; mins: number } | null {
  const now = Date.now()
  const e = view.timeline.find((x) => x.kind === 'meeting' && !x.all_day && x.state !== 'cancelled' && x.at && utc(x.at).getTime() > now - 60_000)
  return e?.at ? { e, mins: Math.max(0, Math.round((utc(e.at).getTime() - now) / 60_000)) } : null
}

const isPast = (e: DayEntry, now: number) => {
  if (!e.at || e.kind === 'recap') return false
  if (e.kind === 'meeting') return utc(e.end ?? e.at).getTime() < now
  if (e.kind === 'reminder') return e.state === 'dismissed'
  return utc(e.at).getTime() <= now
}

function dayTitle(v: DayView, offset: number) {
  if (offset === 0) return 'today'
  if (offset === 1) return 'tomorrow'
  if (offset === -1) return 'yesterday'
  return new Date(`${v.date}T12:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }).toLowerCase()
}

export function Today({ state: s, refresh, notify }: { state: State; refresh: () => Promise<void>; notify: Notify }) {
  const fx = useFx()
  const [offset, setOffset] = useState(0)
  const [dir, setDir] = useState(0) // -1 going back a day, 1 going forward: which way the day slides
  const still = useReducedMotion()
  const [view, setView] = useState<DayView | null>(null)
  // days already seen, and the ones either side, so moving a day shows it at once (then refreshes)
  const days = useRef(new Map<number, DayView>())
  const at = useRef(offset)
  const toDay = (o: number) => {
    fx.sound('tap')
    setDir(Math.sign(o - offset))
    setOffset(o)
    at.current = o
    const seen = days.current.get(o)
    if (seen) setView(seen)
  }
  const [failed, setFailed] = useState<string | null>(null)
  const [cheerN, setCheerN] = useState(0)
  const [review, setReview] = useState<'standup' | 'week' | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const companion = s.companion ?? { species: 'blob', name: 'buddy' }
  const { mood, text: say } = useMemo(() => line(s, companion.name, view), [s, companion.name, view])

  const load = useCallback(async () => {
    const day = (o: number) => api.today(o ? dayPlus(s.day.today, o) : '')
    try {
      const v = await day(offset)
      days.current.set(offset, v)
      if (at.current === offset) setView(v) // a quicker click may already have moved on
      setFailed(null)
      for (const o of [offset - 1, offset + 1]) {
        if (!days.current.has(o)) void day(o).then((n) => days.current.set(o, n), () => undefined)
      }
    } catch (e) {
      setFailed((e as Error).message) // shown in place: a toast alone would leave "reading your day…" forever
    }
  }, [offset])
  useRefresh(load)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- refetch when the desk changes or the day flips
    void load()
  }, [load, s])
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000) // the now-line moves once a minute
    return () => clearInterval(t)
  }, [])

  const changed = async () => {
    await refresh()
    await load()
  }

  const doTodo = async (id: number, action: 'done' | 'undo' | 'drop', el: Element | null, stop = false) => {
    try {
      const r = await api.todo(id, action, stop)
      if (action === 'done') {
        fx.sound('check')
        fx.burstAt(el)
        if (r.xp) fx.float(el, r.xp > 10 ? `+${r.xp} XP · beat the deadline!` : `+${r.xp} XP`)
        setCheerN((n) => n + 1) // the companion up top does a little jump
        if (r.milestone) {
          fx.burstAt(el, true)
          setTimeout(() => fx.banner({ kind: 'goal', title: `${r.chain} IN A ROW!`, sub: 'That habit is sticking. Keep the chain alive.' }), 400)
        }
        if (s.today.done.length + 1 === s.day.todo_goal) {
          setTimeout(() => fx.banner({ kind: 'goal', title: 'GOOD DAY!', sub: `${s.day.todo_goal} things done. ${companion.name} is very proud.` }), 600)
        }
      } else if (action === 'drop') {
        fx.toss(el)
      } else {
        fx.sound('undo')
      }
      if (action !== 'undo') fx.offerUndo(action === 'done' ? 'Ticked off' : 'Removed', () => api.todo(id, 'undo'))
      await changed()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  const p = s.progress
  const done = s.today.done.length
  return (
    <div className="today">
      <AskPanel
        greeting={say}
        mood={mood}
        interests={s.about.interests ?? ''}
        level={{ level: p.level, xp: p.xp, into: p.level_xp, need: p.level_need }}
        stats={{ done, goal: s.day.todo_goal, streak: p.streak_days, freezes: p.freezes }}
        cheer={cheerN}
      />
      <AnimatePresence>{s.focus && <FocusBar key={s.focus.id} focus={s.focus} onChange={() => void changed()} notify={notify} />}</AnimatePresence>
      <Win title={view ? `${dayTitle(view, offset)}.log` : 'today.log'} id="win-today" className="day-win">
        <div className="day-nav">
          <button className="btn tiny ghost" onClick={() => toDay(offset - 1)} aria-label="Previous day">
            ◂
          </button>
          <span className="day-date">{view ? new Date(`${view.date}T12:00`).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' }) : '…'}</span>
          <button className="btn tiny ghost" onClick={() => toDay(offset + 1)} aria-label="Next day">
            ▸
          </button>
          {offset !== 0 && (
            <button className="btn tiny" onClick={() => toDay(0)}>
              back to today
            </button>
          )}
          <span className="grow" />
          {offset === 0 && !s.focus && <FocusStart onChange={() => void changed()} notify={notify} />}
          <button className="btn tiny ghost" onClick={() => setReview('standup')} title="Yesterday, today, blockers: ready to paste">
            standup
          </button>
          <button className="btn tiny ghost" onClick={() => setReview('week')} title="Your week card">
            week ★
          </button>
        </div>
        {!view ? (
          failed ? (
            <p className="bad-text">
              Couldn't read your day ({failed}). If you just updated tamadesk, restart it (<code>systemctl --user restart tamadesk</code> or
              stop and run <code>uv run tamadesk serve</code> again).
            </p>
          ) : (
            <p className="loading">reading your day…</p>
          )
        ) : (
          // one slide per day: the old day leaves completely before the new one comes in, so rows
          // never animate against each other; the rows inside don't animate on a day change
          <div className="day-stage">
            <AnimatePresence mode="wait" initial={false} custom={dir}>
              <motion.div
                key={view.date}
                custom={dir}
                style={{ willChange: 'transform, opacity' }} // its own GPU layer: the slide never repaints the day
                variants={{
                  enter: (d: number) => ({ x: still ? 0 : d * 48, opacity: 0 }),
                  center: { x: 0, opacity: 1 },
                  exit: (d: number) => ({ x: still ? 0 : d * -48, opacity: 0 }),
                }}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: still ? 0.12 : 0.2, ease: 'easeInOut' }}
              >
                <Day view={view} now={now} s={s} notify={notify} doTodo={doTodo} changed={changed} />
              </motion.div>
            </AnimatePresence>
          </div>
        )}
      </Win>
      <ReviewDialog kind={review} onClose={() => setReview(null)} notify={notify} />
    </div>
  )
}

type RowProps = { notify: Notify; doTodo: (id: number, a: 'done' | 'undo' | 'drop', el: Element | null, stop?: boolean) => void; changed: () => Promise<void> }

function Day({ view, now, s, ...rp }: { view: DayView; now: number; s: State } & RowProps) {
  const [earlier, setEarlier] = useState(false)
  const [allNeeds, setAllNeeds] = useState(false)
  const past = view.is_today ? view.timeline.filter((e) => isPast(e, now)) : []
  const rest = view.is_today ? view.timeline.filter((e) => !isPast(e, now)) : view.timeline
  const needs = allNeeds ? view.needs_you : view.needs_you.slice(0, 5)
  const empty = !view.needs_you.length && !view.timeline.some((e) => e.kind !== 'recap') && !view.anytime.length
  return (
    <div className="day">
      {view.needs_you.length > 0 && (
        <section>
          <div className="field-label">needs you ({view.needs_you.length})</div>
          <ul className="day-list">
            <AnimatePresence initial={false}>
              {needs.map((e, i) => (
                <Row key={e.key} e={e} i={i} needs {...rp} recapAt={s.day.bed} />
              ))}
            </AnimatePresence>
          </ul>
          {view.needs_you.length > 5 && (
            <button className="btn tiny ghost more" onClick={() => setAllNeeds(!allNeeds)}>
              {allNeeds ? '▴ fewer' : `+${view.needs_you.length - 5} more`}
            </button>
          )}
        </section>
      )}
      <section>
        {past.length > 0 && (
          <button className="earlier" aria-expanded={earlier} onClick={() => setEarlier(!earlier)}>
            earlier · {past.length} {earlier ? '▴' : '▸'}
          </button>
        )}
        <ul className="day-list timeline-list">
          <AnimatePresence initial={false}>
            {earlier && past.map((e, i) => <Row key={e.key} e={e} i={i} {...rp} recapAt={s.day.bed} />)}
            {view.is_today && (
              <motion.li key="now" layout className="now-line" aria-label="now">
                <span>{clock(new Date(now).toISOString())} now</span>
              </motion.li>
            )}
            {rest.map((e, i) => (
              <Row key={e.key} e={e} i={i} {...rp} recapAt={s.day.bed} />
            ))}
          </AnimatePresence>
        </ul>
        {empty && <p className="muted mono">&gt; {view.is_today ? 'a clear day. type "todo …" or "remind me … at 3pm" above' : 'nothing on this day'}_</p>}
      </section>
      {view.anytime.length > 0 && (
        <section>
          <div className="field-label">anytime</div>
          <ul className="day-list">
            <AnimatePresence initial={false}>
              {view.anytime.map((e, i) => (
                <Row key={e.key} e={e} i={i} {...rp} recapAt={s.day.bed} />
              ))}
            </AnimatePresence>
          </ul>
        </section>
      )}
    </div>
  )
}

const VERB = { answer: 'draft a reply', seen: 'got it', followup: 'write follow-up', mail: 'open draft', tab: 'open tab', open: 'open ↗' } as const
const MARK: Record<DayEntry['kind'], string> = { meeting: '◆', reminder: '◷', log: '·', did: '✓', recap: '✎', next: '●', todo: '', promise: '✦' }

/** One row of the day. Todos tick, meetings join, waiting things take their one next step;
 * rows that belong to an item or a draft open it in place with the same card the pages use. */
function Row({ e, i, needs = false, notify, doTodo, changed, recapAt }: { e: DayEntry; i: number; needs?: boolean; recapAt: string } & RowProps) {
  const fx = useFx()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false) // × on a repeating todo: skip once or stop it?
  const done = e.state === 'done'
  const draftId = e.next?.kind === 'draft' ? e.next.id : null
  const opens = (e.kind === 'meeting' && !!e.ref.item) || draftId !== null || (e.kind === 'recap' && done)
  const time = e.all_day ? 'all day' : e.at ? (needs || e.detail === 'due later' ? when(e.at) : clock(e.at)) : ''

  const go = async () => {
    const r = e.next!
    setBusy(true)
    try {
      if (r.action === 'answer') {
        const thread = r.draft_id ? ` Reply in the same thread (reply_to ${r.draft_id}).` : ` Write to ${r.from}.`
        askBolt(`${r.title}: "${r.detail}"\n\n${r.snippet}\n\nDraft my answer in Mail.${thread} If they're asking to meet, offer two or three times and keep it short.`)
        await api.inboxDone(r.id)
      } else if (r.action === 'seen') {
        await api.inboxDone(r.id)
        fx.sound('check')
      } else if (r.action === 'open' && r.url) {
        window.open(r.url, '_blank', 'noopener')
        if (r.key) await api.seen('gh', r.key) // seen here; nothing changes on GitHub
        fx.sound('tap')
      } else if (r.action === 'followup') {
        await api.followup(r.id)
        fx.sound('send')
        notify('Follow-up drafted in the same thread. Check it in Mail.')
      } else {
        location.hash = e.link
      }
      await changed()
    } catch (err) {
      notify((err as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.li
      layout
      className={`day-row k-${e.kind} s-${e.state} ${e.next ? `next-${e.next.kind}` : ''} ${open ? 'open' : ''}`}
      data-toss
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0, transition: { delay: Math.min(i, 8) * 0.03 } }}
      exit={{ opacity: 0, x: 40, height: 0 }}
    >
      <div className="day-line">
        <span className="day-time">{time}</span>
        {e.kind === 'todo' ? (
          <button
            className="check-box"
            aria-label={`${done ? 'Not done' : 'Done'}: ${e.title}`}
            onClick={(ev) => doTodo(e.ref.todo!, done ? 'undo' : 'done', ev.currentTarget)}
          >
            {done ? '✓' : ''}
          </button>
        ) : e.kind === 'next' ? (
          <span className="next-dot" aria-hidden />
        ) : (
          <span className="day-mark" aria-hidden>
            {MARK[e.kind]}
          </span>
        )}
        <span className="day-text">
          {e.link && !e.next ? (
            <a href={`#${e.link}`} className="day-title">
              {e.title}
            </a>
          ) : (
            <span className="day-title">{e.title}</span>
          )}
          {e.kind === 'todo' && (!!e.repeat || (e.chain ?? 0) > 1 || !!e.tags?.length || e.waiting) && <TodoChips e={e} changed={changed} />}
          {(e.detail || (e.kind === 'meeting' && e.end && !e.all_day)) && (
            <span className="muted small">
              {e.kind === 'meeting' && e.at && e.end && !e.all_day ? `${clock(e.at)}–${clock(e.end)}` : ''}
              {e.kind === 'meeting' && e.detail ? ' · ' : ''}
              {e.state === 'cancelled' ? 'cancelled' : e.detail}
            </span>
          )}
        </span>
        <span className="day-acts">
          {opens && (
            <button className="btn tiny ghost" aria-expanded={open} onClick={() => (fx.sound(open ? 'close' : 'open'), setOpen(!open))}>
              {open ? '▴' : '▾'}
            </button>
          )}
          {e.kind === 'meeting' && e.meet_url && e.state !== 'cancelled' && (
            <a className="btn tiny solid" href={e.meet_url} target="_blank" rel="noreferrer">
              join ↗
            </a>
          )}
          {e.kind === 'todo' && !done && <Deadline id={e.ref.todo!} due={e.due ?? null} notify={notify} changed={changed} />}
          {e.kind === 'todo' && !done && !e.repeat && (
            <button className="icon-x" title="Remove it" onClick={(ev) => doTodo(e.ref.todo!, 'drop', ev.currentTarget)}>
              ×
            </button>
          )}
          {e.kind === 'todo' && !done && e.repeat && (
            // a repeating todo: skip this time, or stop the habit altogether
            <span className="drop-ask">
              {asking ? (
                <>
                  <button className="btn tiny ghost" onClick={(ev) => (setAsking(false), doTodo(e.ref.todo!, 'drop', ev.currentTarget))}>
                    skip once
                  </button>
                  <button className="btn tiny" onClick={(ev) => (setAsking(false), doTodo(e.ref.todo!, 'drop', ev.currentTarget, true))}>
                    stop it
                  </button>
                </>
              ) : (
                <button className="icon-x" title="Skip once, or stop it repeating" onClick={() => setAsking(true)}>
                  ×
                </button>
              )}
            </span>
          )}
          {e.kind === 'todo' && e.waiting && e.state === 'overdue' && (
            <button className="btn tiny ghost" title="Not yet: ask me again in 3 days" onClick={async () => (await api.todoDue(e.ref.todo!, 'in 3 days'), fx.sound('tap'), await changed())}>
              +3 days
            </button>
          )}
          {e.next?.kind === 'github' && e.next.key && (
            <button className="icon-x" title="Seen it (only here: nothing changes on GitHub)" onClick={async () => (await api.seen('gh', e.next!.key!), fx.sound('drop'), await changed())}>
              ×
            </button>
          )}
          {e.next?.action === 'followup' && (
            <button
              className="icon-x"
              title="No follow-up for this one"
              onClick={async () => (await api.noFollowup(e.next!.id), fx.sound('drop'), await changed())}
            >
              ×
            </button>
          )}
          {e.next && (
            <motion.button className={`btn tiny ${e.next.action === 'answer' ? 'solid' : ''}`} whileTap={{ scale: 0.9 }} disabled={busy} onClick={go}>
              {busy ? <span className="blink">…</span> : VERB[e.next.action]}
            </motion.button>
          )}
          {e.kind === 'recap' && !done && <RecapButton notify={notify} changed={changed} at={recapAt} />}
          {e.ref.suggestion && (
            <button
              className="icon-x"
              title="Not done after all"
              onClick={async () => {
                const r = await api.suggestion(e.ref.suggestion!, 'undo')
                fx.sound('undo')
                if (r.xp) notify(`${r.xp} XP taken back.`)
                await changed()
              }}
            >
              undo
            </button>
          )}
        </span>
      </div>
      {e.kind === 'promise' && e.ref.cal_key && <Promises calKey={e.ref.cal_key} notify={notify} changed={changed} />}
      {/* "anything else?" (the Claude fallback) lives in Mail; Today shows only what the rules found */}
      {e.target && e.next && !open && (
        <OnlyYou items={e.suggestions ?? []} target={e.target} id={e.next.id} notify={notify} onChange={() => void changed()} />
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div className="day-open" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
            {e.kind === 'meeting' && e.ref.item && <ItemInline id={e.ref.item} notify={notify} changed={changed} />}
            {draftId !== null && <DraftInline id={draftId} notify={notify} changed={changed} />}
            {e.kind === 'recap' && e.recap && <RecapText recap={e.recap} notify={notify} changed={changed} />}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

/** What makes a todo more than a line: its repeat (click to stop it), its habit chain, its #tags, who it waits on. */
function TodoChips({ e, changed }: { e: DayEntry; changed: () => Promise<void> }) {
  const fx = useFx()
  const [sure, setSure] = useState(false)
  return (
    <span className="todo-chips">
      {(e.chain ?? 0) > 1 && (
        <span className="chain" title={`${e.chain} on time in a row`}>
          ×{e.chain} chain
        </span>
      )}
      {e.repeat &&
        (sure ? (
          <button className="chip on" onClick={async () => (await api.todoRepeat(e.ref.todo!, null), fx.sound('drop'), await changed())}>
            stop repeating?
          </button>
        ) : (
          <button className="chip" title="Repeats · click to stop" onClick={() => (setSure(true), setTimeout(() => setSure(false), 3000))}>
            ↻ {e.repeat}
          </button>
        ))}
      {e.waiting && <span className="chip waiting">⧗ {e.who ?? 'waiting'}</span>}
      {e.tags?.map((t) => (
        <span key={t} className="tag-chip">
          #{t}
        </span>
      ))}
    </span>
  )
}

/** Right after a meeting: what did you promise? Each line becomes a todo linked to the meeting. */
function Promises({ calKey, notify, changed }: { calKey: string; notify: Notify; changed: () => Promise<void> }) {
  const fx = useFx()
  const [text, setText] = useState('')
  const send = async (lines: string[]) => {
    try {
      const r = await api.promises(calKey, lines)
      fx.sound(r.todos.length ? 'capture' : 'close')
      if (r.todos.length) notify(`${r.todos.length} promise${r.todos.length > 1 ? 's' : ''} on your list.`)
      await changed()
    } catch (err) {
      notify((err as Error).message, 'err')
    }
  }
  return (
    <form
      className="promises"
      onSubmit={(ev) => {
        ev.preventDefault()
        void send(text.split(/\n|;/))
      }}
    >
      <textarea rows={2} value={text} onChange={(ev) => setText(ev.target.value)} placeholder="one per line: send Alex the deck, book the follow-up…" aria-label="Promises" />
      <span className="promise-acts">
        <button type="button" className="btn tiny ghost" onClick={() => send([])}>
          nothing
        </button>
        <button className="btn tiny solid" disabled={!text.trim()}>
          add
        </button>
      </span>
    </form>
  )
}

/** A todo's deadline: a countdown that heats up as it gets close. Click to wind the clock to a new
 * time, type one in words, or clear it. Due within 3 hours: "focus till then" starts a focus session
 * that ends right at the deadline; any other todo offers 25 minutes of focus on hover. */
function Deadline({ id, due, notify, changed }: { id: number; due: string | null; notify: Notify; changed: () => Promise<void> }) {
  const fx = useFx()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const close = useCallback(() => setAnchor(null), [])
  const set = async (at: string) => {
    try {
      await api.todoDue(id, at)
      fx.sound(at ? 'lock' : 'drop')
      // the old deadline comes back as it was (one that already passed can't be set again, so it clears)
      const before = due && utc(due) > new Date() ? localMinute(utc(due)) : ''
      fx.offerUndo(at ? (due ? 'Deadline moved' : 'Deadline set') : 'Deadline cleared', () => api.todoDue(id, before))
      setAnchor(null)
      await changed()
    } catch (err) {
      notify((err as Error).message, 'err')
    }
  }
  const left = due ? Math.round((utc(due).getTime() - Date.now()) / 60_000) : null
  const close3h = left !== null && left >= 10 && left <= 180
  const focus = async () => {
    try {
      await api.focusStart(close3h ? left! : 25)
      fx.sound('start')
      await changed()
    } catch (err) {
      notify((err as Error).message, 'err')
    }
  }
  const p = due ? pressureOf(due) : null
  const span = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`)
  return (
    <>
      <AnimatePresence initial={false}>
        {close3h && (
          <motion.button
            key="till"
            className="btn tiny solid focus-till"
            initial={{ opacity: 0, x: 8, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ type: 'spring', stiffness: 420, damping: 26 }}
            title={`Focus till it's due (${span(left!)}) · quiet notifications until then`}
            onClick={(ev) => {
              ev.stopPropagation()
              void focus()
            }}
          >
            ▶ focus till then
          </motion.button>
        )}
      </AnimatePresence>
      {!close3h && (
        <button
          className="btn tiny ghost focus-quick"
          title="Focus on this for 25 minutes"
          onClick={(ev) => {
            ev.stopPropagation()
            void focus()
          }}
        >
          ▶ 25m
        </button>
      )}
      <button
        className={`due-chip ${p ? `p${p.stage}` : 'unset'} ${anchor ? 'open' : ''}`}
        title={due ? `due ${when(due)} · click to move or clear it` : 'Give it a deadline'}
        aria-expanded={!!anchor}
        onClick={(ev) => {
          ev.stopPropagation()
          fx.sound(anchor ? 'close' : 'open')
          setAnchor(anchor ? null : ev.currentTarget)
        }}
      >
        {p ? p.text : '+ deadline'}
      </button>
      <AnimatePresence>{anchor && <DuePicker anchor={anchor} due={due} onSet={set} onClose={close} />}</AnimatePresence>
    </>
  )
}

function RecapButton({ notify, changed, at }: { notify: Notify; changed: () => Promise<void>; at: string }) {
  const fx = useFx()
  const [busy, setBusy] = useState(false)
  return (
    <button
      className="btn tiny"
      disabled={busy}
      title={`Written for you at bedtime (${at}), or now`}
      onClick={async () => {
        setBusy(true)
        try {
          await api.recap()
          fx.sound('send')
          await changed()
        } catch (err) {
          notify((err as Error).message, 'err')
        } finally {
          setBusy(false)
        }
      }}
    >
      {busy ? <span className="blink">thinking…</span> : 'write it now'}
    </button>
  )
}

function RecapText({ recap, notify, changed }: { recap: NonNullable<DayEntry['recap']>; notify: Notify; changed: () => Promise<void> }) {
  const fx = useFx()
  const addTomorrow = async (t: string, el: Element | null) => {
    try {
      await api.capture(`todo ${t}`)
      fx.sound('capture')
      await fx.fly(el, 'win-today')
      await changed()
    } catch (err) {
      notify((err as Error).message, 'err')
    }
  }
  return (
    <div className="recap">
      <div className="recap-head">{recap.headline}</div>
      {recap.so_far && <div className="muted small">so far today</div>}
      <p>{recap.recap}</p>
      {recap.tomorrow.length > 0 && (
        <>
          <div className="field-label">for tomorrow</div>
          <ul className="todo">
            {recap.tomorrow
              .map((x) => (typeof x === 'string' ? { text: x, todo_id: null } : x))
              .map((x) => (
                <li key={x.text} className={x.status === 'done' ? 'did' : ''}>
                  <span className="todo-text">{x.text}</span>
                  {x.status === 'done' ? (
                    <span className="muted small">✓ done</span>
                  ) : x.todo_id ? (
                    <span className="muted small" title="It's already one of your todos, so there's nothing to add">
                      on your list
                    </span>
                  ) : (
                    <button className="btn tiny" onClick={(ev) => addTomorrow(x.text, ev.currentTarget)}>
                      + todo
                    </button>
                  )}
                </li>
              ))}
          </ul>
        </>
      )}
    </div>
  )
}

/** The item a meeting is about, with the same card and buttons as its tab. */
function ItemInline({ id, notify, changed }: { id: number; notify: Notify; changed: () => Promise<void> }) {
  const [got, setGot] = useState<{ item: ModItem; actions: Mod['actions'] } | null>(null)
  const { run, busy, summaries } = useItemActions(notify, () => void changed())
  useEffect(() => {
    api.item(id).then(setGot, (e: Error) => notify(e.message, 'err'))
  }, [id, notify])
  if (!got) return <p className="loading small">opening…</p>
  return <ItemCard it={got.item} mod={{ actions: got.actions }} run={run} busy={busy === got.item.id} summary={summaries[got.item.id]} />
}

/** A waiting draft, editable and sendable right here, with the same card as Mail. */
function DraftInline({ id, notify, changed }: { id: number; notify: Notify; changed: () => Promise<void> }) {
  const [got, setGot] = useState<{ draft: MailDraft; ready: boolean } | null>(null)
  const load = useCallback(() => api.draft(id).then(setGot, (e: Error) => notify(e.message, 'err')), [id, notify])
  useEffect(() => {
    void load()
  }, [load])
  if (!got) return <p className="loading small">opening…</p>
  if (got.draft.status !== 'draft') return <p className="muted small">sent.</p>
  return <DraftCard d={got.draft} ready={got.ready} notify={notify} onGone={() => void load().then(changed)} onSetup={() => (location.hash = 'mail')} />
}
