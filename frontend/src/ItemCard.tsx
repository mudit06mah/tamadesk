// One item from a module tab, plus the one hook that performs its actions. Feed, deck and
// Today's picks all render this, so every view gets the same buttons, sounds and motion.
import { AnimatePresence, motion } from 'motion/react'
import { useState, type ReactNode } from 'react'
import { api, askBolt, pad2, type Mod, type ModItem, type Stage } from './api'
import { useFx } from './fx/Fx'
import { BookmarkIcon } from './icons'
import { pressureOf, type Toast } from './util'

export type Act = 'save' | 'skip' | 'done' | 'todo' | 'summarize' | 'draft'

export function useItemActions(notify: (t: string, k?: Toast['kind']) => void, onGone: (it: ModItem, status: string) => void) {
  const fx = useFx()
  const [busy, setBusy] = useState<number | null>(null)
  const [summaries, setSummaries] = useState<Record<number, ModItem['data']['summary']>>({})

  const run = async (it: ModItem, a: Act, el: Element | null, reason = '') => {
    try {
      if (a === 'draft') {
        // outreach is real work (research + writing): hand it to the companion
        const d = it.data
        const contact = d.email ? ` The posting publishes ${d.email} (source: ${d.email_source}).` : ''
        const what = d.apply_url ? 'job posting: draft a short application email in Mail (use my resume)' : 'lead: draft an outreach email to them in Mail'
        askBolt(`Research this ${what} (item ${it.id}): ${it.title} ${it.url ?? ''}.${contact}`.trim())
      } else if (a === 'todo') {
        const r = await api.itemTodo(it.id)
        fx.sound('capture')
        fx.float(el, r.due_at ? '+ todo with its deadline' : '+ todo')
      } else if (a === 'summarize') {
        setBusy(it.id)
        const s = await api.summarize(it.id)
        setSummaries((m) => ({ ...m, [it.id]: s }))
        fx.sound('tap')
      } else {
        const r = await api.act(it.id, a, reason)
        if (a === 'skip') fx.toss(el)
        else fx.sound(a === 'save' ? 'keep' : 'check')
        if (a === 'save') fx.burstAt(el)
        if (r.xp) fx.float(el, `+${r.xp} XP`)
        fx.offerUndo(a === 'save' ? 'Bookmarked' : a === 'skip' ? 'Passed' : 'Marked done', () => api.act(it.id, 'undo'))
        onGone(it, r.status)
      }
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setBusy(null)
    }
  }
  return { run, busy, summaries }
}

const STAGE: Record<Stage, string> = {
  emailed: 'emailed',
  applied: 'applied',
  replied: 'they replied',
  interview: 'interview',
  rejected: 'closed',
  done: 'done',
}

const LABEL: Record<Act, ReactNode> = {
  save: (
    <>
      <BookmarkIcon /> bookmark
    </>
  ),
  skip: 'not for me',
  done: '✓ done',
  todo: '+ todo',
  summarize: '✦ tl;dr',
  draft: '@ email them',
}
const TIP: Partial<Record<Act, string>> = { save: 'Keep it here · the tab learns to rank things like it first', skip: 'Throw it out · the tab learns to show fewer like it' }

const YT = /(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([\w-]{11})/
const clockOf = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}:${pad2(Math.floor((s % 3600) / 60))}` : `${Math.floor(s / 60)}`) + `:${pad2(Math.floor(s % 60))}`

/** When it was published: "today", "3d ago", or a date once it's older than a week. */
function dated(ts: string | null): string | null {
  if (!ts) return null
  const d = new Date(ts)
  if (isNaN(d.getTime())) return null
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  if (days < 1) return 'today'
  if (days < 2) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(d.getFullYear() !== new Date().getFullYear() && { year: 'numeric' }) })
}

export function ItemCard({
  it,
  mod,
  run,
  busy,
  summary,
}: {
  it: ModItem
  mod: Pick<Mod, 'actions'>
  run: (it: ModItem, a: Act, el: Element | null) => void
  busy: boolean
  summary?: ModItem['data']['summary']
}) {
  const fx = useFx()
  const sum = summary ?? it.data.summary
  const [stage, setStage] = useState<Stage | null>(it.stage)
  const [asking, setAsking] = useState(false) // after "apply ↗": did you?
  const mark = async (s: Stage) => {
    await api.itemStage(it.id, s)
    setStage(s)
    setAsking(false)
    fx.sound('stamp')
  }
  const job = !!it.data.apply_url
  const vid = it.url?.match(YT)?.[1]
  const thumb = it.data.thumb ?? (vid ? `https://i.ytimg.com/vi/${vid}/mqdefault.jpg` : null)
  const date = dated(it.published_at)
  // a job's next steps are email or apply, so a todo would only be a third way to say the same thing
  const acts = mod.actions.filter((a): a is Act => a !== 'open' && !(job && a === 'todo') && (it.status === 'new' || (a !== 'save' && a !== 'skip')))
  const btn = (a: Act) => (
    <motion.button
      key={a}
      className={`btn tiny act-${a}`}
      whileTap={{ scale: 0.86, rotate: a === 'skip' ? -4 : 4 }}
      disabled={busy || (a === 'summarize' && !!sum)}
      title={TIP[a]}
      onClick={(e) => run(it, a, e.currentTarget)}
    >
      {busy && a === 'summarize' ? <span className="blink">reading…</span> : LABEL[a]}
    </motion.button>
  )
  return (
    <div className={`item ${thumb ? 'has-thumb' : ''}`} data-toss>
      {thumb && (
        <a className="item-thumb" href={it.url ?? undefined} target="_blank" rel="noreferrer" tabIndex={-1}>
          <img src={thumb} alt="" loading="lazy" referrerPolicy="no-referrer" />
          {it.data.duration ? <span className="item-len">{clockOf(it.data.duration)}</span> : null}
        </a>
      )}
      <div className="item-top">
        <span className="tag">{it.source}</span>
        {date && (
          <span className="item-date" title={`published ${new Date(it.published_at!).toLocaleString()}`}>
            {date}
          </span>
        )}
        {stage && <span className={`stage stage-${stage}`}>{STAGE[stage]}</span>}
        {it.data.closed_at && (
          <span className="stage stage-rejected" title="This posting stopped taking applications">
            posting closed
          </span>
        )}
        {it.data.deadline && (
          <span className={`due-chip p${pressureOf(`${it.data.deadline} 23:59:00`).stage}`} title={`closes ${it.data.deadline}: “+ todo” makes it due then`}>
            closes {pressureOf(`${it.data.deadline} 23:59:00`).text}
          </span>
        )}
        {it.data.fit && (
          <span className="fit" title={`how well it matches what you're after: ${it.data.fit.why.join(', ') || 'no details'}`}>
            fit {Math.round(it.data.fit.score * 100)}%
          </span>
        )}
        {it.why.map((w) => (
          <span key={w} className="why" title="why it ranked up">
            {w}
          </span>
        ))}
      </div>
      {it.url && mod.actions.includes('open') ? (
        <a className="item-title" href={it.url} target="_blank" rel="noreferrer">
          {it.title}
        </a>
      ) : (
        <div className="item-title">{it.title}</div>
      )}
      {it.subtitle && <div className="item-sub muted small">{it.subtitle}</div>}
      {it.data.screen && <div className="item-sub muted small">✓ suits you: {it.data.screen}</div>}
      {sum ? (
        <motion.div className="item-sum" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
          <p>{sum.summary}</p>
          {sum.why_you && <p className="muted">→ {sum.why_you}</p>}
        </motion.div>
      ) : (
        it.body && <p className="item-body">{it.body}</p>
      )}
      <div className="item-acts">
        {acts.filter((a) => a !== 'draft').map((a) => btn(a))}
        <span className="grow" />
        {it.data.discussion && (
          <a className="btn tiny ghost" href={it.data.discussion} target="_blank" rel="noreferrer">
            discussion ↗
          </a>
        )}
        {acts.includes('draft') && btn('draft')}
        {job && (
          <a className="btn tiny solid apply" href={it.data.apply_url} target="_blank" rel="noreferrer" onClick={() => !stage && setTimeout(() => setAsking(true), 800)}>
            apply ↗
          </a>
        )}
      </div>
      <AnimatePresence>
        {asking && (
          <motion.div className="applied-ask" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <span>Did you apply?</span>
            <button className="btn tiny solid" onClick={() => mark('applied')}>
              yes, applied
            </button>
            <button className="btn tiny ghost" onClick={() => setAsking(false)}>
              not yet
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
