// One item from a module tab, plus the one hook that performs its actions. Feed, deck and
// Today's picks all render this, so every view gets the same buttons, sounds and motion.
import { motion } from 'motion/react'
import { useState } from 'react'
import { api, askBolt, type Mod, type ModItem } from './api'
import { useFx } from './fx/Fx'
import type { Toast } from './util'

export type Act = 'save' | 'skip' | 'done' | 'todo' | 'summarize' | 'draft'

export function useItemActions(notify: (t: string, k?: Toast['kind']) => void, onGone: (it: ModItem, status: string) => void) {
  const fx = useFx()
  const [busy, setBusy] = useState<number | null>(null)
  const [summaries, setSummaries] = useState<Record<number, ModItem['data']['summary']>>({})

  const run = async (it: ModItem, a: Act, el: Element | null, reason = '') => {
    try {
      if (a === 'draft') {
        // outreach is real work (research + writing): hand it to the companion
        askBolt(`Research this lead and draft an outreach email to them in Mail (item ${it.id}): ${it.title} ${it.url ?? ''}`.trim(), true)
      } else if (a === 'todo') {
        await api.itemTodo(it.id)
        fx.sound('capture')
        fx.float(el, '+ todo')
      } else if (a === 'summarize') {
        setBusy(it.id)
        const s = await api.summarize(it.id)
        setSummaries((m) => ({ ...m, [it.id]: s }))
        fx.sound('tap')
      } else {
        const r = await api.act(it.id, a, reason)
        fx.sound(a === 'skip' ? 'undo' : 'check')
        if (a === 'save') fx.burstAt(el)
        if (r.xp) fx.float(el, `+${r.xp} XP`)
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

const LABEL: Record<Act, string> = { save: '♥ keep', skip: '✕ skip', done: '✓ done', todo: '+ todo', summarize: '✦ tl;dr', draft: '@ email them' }

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
  const sum = summary ?? it.data.summary
  const acts = mod.actions.filter((a): a is Act => a !== 'open' && (it.status === 'new' || (a !== 'save' && a !== 'skip')))
  return (
    <div className="item">
      <div className="item-top">
        <span className="tag">{it.source}</span>
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
      {sum ? (
        <motion.div className="item-sum" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
          <p>{sum.summary}</p>
          {sum.why_you && <p className="muted">→ {sum.why_you}</p>}
        </motion.div>
      ) : (
        it.body && <p className="item-body">{it.body}</p>
      )}
      <div className="item-acts">
        {acts.map((a) => (
          <motion.button
            key={a}
            className={`btn tiny act-${a}`}
            whileTap={{ scale: 0.86, rotate: a === 'skip' ? -4 : 4 }}
            disabled={busy || (a === 'summarize' && !!sum)}
            onClick={(e) => run(it, a, e.currentTarget)}
          >
            {busy && a === 'summarize' ? <span className="blink">reading…</span> : LABEL[a]}
          </motion.button>
        ))}
        {it.data.discussion && (
          <a className="btn tiny ghost" href={it.data.discussion} target="_blank" rel="noreferrer">
            discussion ↗
          </a>
        )}
      </div>
    </div>
  )
}
