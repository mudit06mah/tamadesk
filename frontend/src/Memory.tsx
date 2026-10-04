// Memory: everything you and your companion did, day by day. Search is instant and free (a local
// full-text index); each finished day is distilled into a summary and facts, kept as a markdown
// file you can read and edit (<tamadesk folder>/memory/YYYY-MM-DD.md).
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, type MemDay, type MemHit } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Win } from './ui'
import type { Toast } from './util'

const KIND: Record<string, string> = {
  fact: 'fact',
  digest: 'day summary',
  chat_user: 'you said',
  chat_assistant: 'reply',
  log: 'log',
  todo: 'todo',
  mail: 'mail',
  kept: 'kept',
}

const pretty = (day: string) => {
  const d = new Date(`${day}T12:00:00`)
  const diff = Math.round((Date.now() - d.getTime()) / 86_400_000)
  const name = d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  return diff <= 0 ? `Today · ${name}` : diff === 1 ? `Yesterday · ${name}` : name
}

/** FTS snippets mark matches with [brackets]; show them highlighted. */
function Snip({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\[[^\]]*\])/).map((p, i) => (p.startsWith('[') && p.endsWith(']') ? <mark key={i}>{p.slice(1, -1)}</mark> : p))}
    </>
  )
}

const chatOf = (ref: string) => (ref.startsWith('m:') ? Number(ref.split(':')[2]) : null)

export function Memory({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<MemHit[] | null>(null)
  const [days, setDays] = useState<MemDay[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [open, setOpen] = useState<Record<string, string>>({})
  const [digesting, setDigesting] = useState(false)

  const load = useCallback(async (offset = 0) => {
    const r = await api.memoryDays(offset)
    setDays((d) => (offset ? [...d, ...r.days] : r.days))
    setPending(r.pending)
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  // instant local search as you type (no tokens)
  useEffect(() => {
    if (!q.trim()) return setHits(null)
    const t = setTimeout(() => void api.memorySearch(q).then(setHits), 220)
    return () => clearTimeout(t)
  }, [q])

  const toggle = async (day: string) => {
    fx.sound('tap')
    if (open[day] !== undefined) {
      return setOpen((o) => Object.fromEntries(Object.entries(o).filter(([k]) => k !== day)))
    }
    const d = await api.memoryDay(day)
    setOpen((o) => ({ ...o, [day]: d.raw }))
  }

  const summarize = async () => {
    setDigesting(true)
    await api.memoryDigest()
    notify(`${buddy.name} is writing up ${pending.length} day${pending.length > 1 ? 's' : ''}…`)
    const t = setInterval(async () => {
      const r = await api.memoryDays()
      setDays(r.days)
      setPending(r.pending)
      if (!r.pending.length) {
        clearInterval(t)
        setDigesting(false)
        fx.sound('levelup')
      }
    }, 4000)
    setTimeout(() => (clearInterval(t), setDigesting(false)), 180_000)
  }

  return (
    <div className="memory">
      <header className="screen-head">
        <h1>Memory</h1>
        {pending.length > 0 && (
          <button className="btn tiny" disabled={digesting} onClick={summarize} title="Uses a little of your budget (cheapest model)">
            {digesting ? <span className="blink">remembering…</span> : `Summarize ${pending.length} day${pending.length > 1 ? 's' : ''} now`}
          </button>
        )}
      </header>

      <form
        className="mem-search"
        onSubmit={(e) => {
          e.preventDefault()
          if (q.trim()) askBolt(`From my memory: ${q.trim()}`, true)
        }}
      >
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="search your memory… e.g. that dish I wanted to try" aria-label="Search memory" />
        <button className="btn solid" disabled={!q.trim()} title={`${buddy.name} digs deeper and answers`}>
          Ask {buddy.name}
        </button>
      </form>

      <AnimatePresence mode="wait">
        {hits ? (
          <motion.div key="hits" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <Win title={`found (${hits.length})`}>
              {hits.length === 0 ? (
                <p className="muted">Nothing matches those words. Press Ask {buddy.name}: it tries other words and broader ideas.</p>
              ) : (
                <ul className="mem-hits">
                  {hits.map((h, i) => (
                    <li key={i}>
                      <span className="mem-day">{pretty(h.day)}</span>
                      <span className={`tag k-${h.kind}`}>{KIND[h.kind] ?? h.kind}</span>
                      <span className="mem-snip">
                        <Snip text={h.text} />
                      </span>
                      {chatOf(h.ref) && (
                        <button className="btn tiny ghost" onClick={() => askBolt('', false, chatOf(h.ref)!)}>
                          open chat →
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Win>
          </motion.div>
        ) : (
          <motion.ul key="days" className="mem-days" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            {days.length === 0 && <p className="muted">Nothing yet. Everything you ask, log or do shows up here, day by day.</p>}
            {days.map((d) => (
              <motion.li key={d.day} layout className="mem-day-card">
                <div className="mem-day-head">
                  <b>{pretty(d.day)}</b>
                  <span className="muted small">{d.things} things</span>
                </div>
                {d.summary ? <p className="mem-summary">{d.summary}</p> : <p className="muted small">{pending.includes(d.day) ? 'not summarized yet' : 'still going'}</p>}
                {d.facts.length > 0 && (
                  <ul className="mem-facts">
                    {d.facts.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                )}
                <div className="item-acts">
                  {d.chats.map((c) => (
                    <button key={c.id} className="chip" onClick={() => askBolt('', false, c.id)} title="Open this chat">
                      › {c.title.slice(0, 48)}
                    </button>
                  ))}
                  <button className="btn tiny ghost" onClick={() => toggle(d.day)}>
                    {open[d.day] !== undefined ? 'hide details' : 'everything that day'}
                  </button>
                </div>
                <AnimatePresence>
                  {open[d.day] !== undefined && (
                    <motion.pre className="pre mem-raw" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                      {open[d.day] || 'nothing indexed'}
                    </motion.pre>
                  )}
                </AnimatePresence>
              </motion.li>
            ))}
            {days.length >= 14 && days.length % 14 === 0 && (
              <button className="btn tiny ghost" onClick={() => load(days.length)}>
                older days
              </button>
            )}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}
