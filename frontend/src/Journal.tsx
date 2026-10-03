// Journal: every log line you've captured, newest first, grouped by day.
import { useEffect, useState } from 'react'
import { api, clock, dayLabel, type LogEntry } from './api'
import { Win } from './ui'

export function Journal() {
  const [items, setItems] = useState<LogEntry[]>([])
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = async (offset: number) => {
    setLoading(true)
    try {
      const r = await api.log(offset)
      setItems((old) => (offset ? [...old, ...r.items] : r.items))
      setMore(r.has_more)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(0)
  }, [])

  const groups: { day: string; items: LogEntry[] }[] = []
  for (const e of items) {
    const day = dayLabel(e.created_at)
    if (groups.at(-1)?.day !== day) groups.push({ day, items: [] })
    groups.at(-1)!.items.push(e)
  }

  return (
    <Win title="journal.log" className="journal">
      {!loading && items.length === 0 && <p className="muted mono">&gt; your journal is empty. anything you type on Today that isn't a todo lands here_</p>}
      {groups.map((g) => (
        <section key={g.day} className="log-day">
          <div className="log-day-head">-- {g.day} --</div>
          <ul className="timeline">
            {g.items.map((e) => (
              <li key={e.id}>
                <span className="muted mono">[{clock(e.created_at)}]</span> {e.body}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {more && (
        <button className="btn tiny ghost log-more" disabled={loading} onClick={() => load(items.length)}>
          {loading ? 'loading…' : 'load older'}
        </button>
      )}
    </Win>
  )
}
