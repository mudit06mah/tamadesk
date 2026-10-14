// The game layer on Today: a focus session the companion sits through with you, and the look-back
// screens (standup note, week card). All of it is free: no AI.
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { api, pad2, type Focus, type Review, type WeekCard } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Markdown } from './Markdown'
import { Bar, Dialog, Seg } from './ui'
import type { Toast } from './util'

type Notify = (t: string, k?: Toast['kind']) => void
const utcMs = (ts: string) => new Date(ts.replace(' ', 'T') + 'Z').getTime()

/** A running focus session: a draining bar, the time left, and the companion keeping you company.
 * Finishing it rings, bursts and pays XP; stopping early is fine but pays nothing. */
export function FocusBar({ focus, onChange, notify }: { focus: Focus; onChange: () => void; notify: Notify }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [now, setNow] = useState(() => Date.now())
  const finishing = useRef(false)
  const start = utcMs(focus.started_at)
  const end = utcMs(focus.ends_at)
  const left = Math.max(0, end - now)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    if (left > 0 || finishing.current) return
    finishing.current = true
    void api.focusEnd('finish').then((r) => {
      const el = document.querySelector('.focus-bar')
      fx.sound('levelup')
      fx.burstAt(el, true)
      if (r.xp) fx.float(el, `+${r.xp} XP`)
      fx.banner({ kind: 'goal', title: 'FOCUS COMPLETE!', sub: `${focus.minutes} minutes${focus.tag ? ` on #${focus.tag}` : ''}. ${buddy.name} is impressed. Stretch?` })
      onChange()
    })
  }, [left, focus, fx, buddy.name, onChange])
  const mm = pad2(Math.floor(left / 60000))
  const ss = pad2(Math.floor((left % 60000) / 1000))
  return (
    <motion.div className="focus-bar" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
      <span className="focus-time" aria-label={`${mm} minutes ${ss} seconds left`}>
        {mm}:{ss}
      </span>
      <span className="focus-text">
        <b>focusing{focus.tag ? ` on #${focus.tag}` : ''}</b>
        <span className="muted small">
          {buddy.name} is sitting with you · quiet till it's done · +{2 * Math.floor(focus.minutes / 5)} XP at the end
        </span>
        <Bar value={1 - left / Math.max(1, end - start)} label="focus progress" />
      </span>
      <button
        className="btn tiny ghost"
        onClick={async () => {
          await api.focusEnd('stop')
          fx.sound('drop')
          notify('Stopped. The minutes still count, the XP waits for a full session.')
          onChange()
        }}
      >
        stop
      </button>
    </motion.div>
  )
}

/** Start a focus session: 25 or 50 minutes, optionally on a #tag (a client, a project). */
export function FocusStart({ onChange, notify }: { onChange: () => void; notify: Notify }) {
  const fx = useFx()
  const [open, setOpen] = useState(false)
  const [tag, setTag] = useState('')
  const go = async (minutes: number) => {
    try {
      await api.focusStart(minutes, tag)
      fx.sound('start')
      setOpen(false)
      onChange()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }
  return (
    <span className="focus-start">
      <button className="btn tiny" aria-expanded={open} onClick={() => (fx.sound(open ? 'close' : 'open'), setOpen(!open))}>
        ▶ focus
      </button>
      <AnimatePresence>
        {open && (
          <motion.span className="focus-pop" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}>
            <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="#tag (optional)" aria-label="Tag" maxLength={30} />
            {[25, 50].map((m) => (
              <button key={m} className="btn tiny solid" onClick={() => go(m)}>
                {m} min
              </button>
            ))}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}

/** Look back: the standup note (paste it anywhere) or the week card, the end-of-round screen. */
export function ReviewDialog({ kind, onClose, notify }: { kind: 'standup' | 'week' | null; onClose: () => void; notify: Notify }) {
  const fx = useFx()
  const [r, setR] = useState<Review | null>(null)
  useEffect(() => {
    if (!kind) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch when opened
    setR(null)
    void api.review(kind).then((x) => (setR(x), fx.sound(kind === 'week' ? 'levelup' : 'open')), (e: Error) => notify(e.message, 'err'))
  }, [kind, fx, notify])
  const copy = async () => {
    if (!r) return
    await navigator.clipboard.writeText(r.markdown).catch(() => undefined)
    fx.sound('stamp')
    notify('Copied.')
  }
  const save = async () => {
    if (!r) return
    await api.newNote(kind === 'week' ? `Week of ${(r as WeekCard).from}` : `Standup ${new Date().toISOString().slice(0, 10)}`, r.markdown)
    fx.sound('capture')
    notify('Saved to Notes.')
  }
  return (
    <Dialog open={kind !== null} title={kind === 'week' ? 'week.card' : 'standup.md'} onClose={onClose} wide={kind === 'week'}>
      {!r ? (
        <p className="loading">looking back…</p>
      ) : r.kind === 'week' ? (
        <WeekView w={r} />
      ) : (
        <div className="review-md">
          <Markdown text={r.markdown} />
        </div>
      )}
      <div className="dialog-actions">
        <button className="btn ghost" onClick={save} disabled={!r}>
          save to Notes
        </button>
        <button className="btn solid" onClick={copy} disabled={!r}>
          copy
        </button>
      </div>
    </Dialog>
  )
}

function WeekView({ w }: { w: WeekCard }) {
  const hours = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`)
  const stats: [string, number][] = [
    ['XP', w.xp],
    ['done', w.done],
    ['beat the deadline', w.on_time],
    ['days you showed up', w.active_days],
    ['best habit chain', w.best_chain],
    ['emails sent', w.sent],
  ]
  return (
    <div className="week-card">
      <motion.div className="week-title" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: 'spring', stiffness: 380, damping: 14, delay: 0.1 }}>
        <span className="muted small">this week you were</span>
        <b>{w.title}</b>
        <span className="muted small">{w.title_why}</span>
      </motion.div>
      <div className="week-stats">
        {stats.map(([label, v], i) => (
          <motion.div key={label} className="week-stat" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0, transition: { delay: 0.25 + i * 0.06 } }}>
            <Seg value={v} digits={Math.max(2, String(v).length)} />
            <span className="muted small">{label}</span>
          </motion.div>
        ))}
      </div>
      {w.focus_minutes > 0 && (
        <div className="week-focus">
          <div className="field-label">focus · {hours(w.focus_minutes)}</div>
          {Object.entries(w.focus_by_tag).map(([tag, m]) => (
            <div key={tag} className="week-focus-row">
              <span>{tag === 'untagged' ? 'other' : `#${tag}`}</span>
              <Bar value={m / Math.max(1, w.focus_minutes)} label={`${tag} share of focus`} />
              <span className="muted small">{hours(m)}</span>
            </div>
          ))}
        </div>
      )}
      {w.highlights.length > 0 && (
        <div>
          <div className="field-label">highlights</div>
          <ul className="week-highlights">
            {w.highlights.map((h) => (
              <li key={h}>✓ {h}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
