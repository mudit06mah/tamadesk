// "Only you": the small things on a mail or draft that the user should do themselves (answer the
// question they asked, check a guessed address, say why this company). Found by plain rules; Claude
// is asked only when you press "anything else?". Ticked ones land on Today's timeline with any XP.
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { api, when, type Suggestion } from './api'
import { useFx } from './fx/Fx'
import type { Toast } from './util'

type Props = {
  items: Suggestion[]
  target: 'draft' | 'inbox'
  id: number
  canAsk?: boolean
  notify: (t: string, k?: Toast['kind']) => void
  onChange: () => void
}

export function OnlyYou({ items, target, id, canAsk = false, notify, onChange }: Props) {
  const fx = useFx()
  const [asking, setAsking] = useState(false)
  if (!items.length && !canAsk) return null

  const act = async (s: Suggestion, action: 'done' | 'dismiss' | 'remind', el: Element) => {
    try {
      const r = await api.suggestion(s.id, action)
      if (action === 'done') {
        fx.sound(r.xp ? 'check' : 'stamp')
        fx.burstAt(el)
        if (r.xp) fx.float(el, `+${r.xp} XP`)
      } else if (action === 'remind') {
        fx.sound('capture')
        notify(`I'll remind you ${r.reminder_at ? when(r.reminder_at) : 'before then'}.`)
      } else {
        fx.sound('drop')
      }
      if (action !== 'remind') fx.offerUndo(action === 'done' ? 'Marked done' : 'Dismissed', () => api.suggestion(s.id, 'undo'))
      onChange()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  const ask = async () => {
    setAsking(true)
    try {
      const got = await api.askTips(target, id)
      fx.sound(got.length ? 'arrive' : 'tap')
      if (!got.length) notify('Nothing else only you need to do here.')
      onChange()
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="only-you">
      <span className="only-you-head">only you</span>
      <ul>
        <AnimatePresence initial={false}>
          {items.map((s) => (
            <motion.li key={s.id} layout initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 30, height: 0 }}>
              <button className="check-box" aria-label={`Done: ${s.text}`} onClick={(e) => act(s, 'done', e.currentTarget)} />
              <span className="only-you-text">
                {s.text}
                {s.rule === 'guessed_address' && s.data.source && (
                  <>
                    {' '}
                    <a href={s.data.source} target="_blank" rel="noreferrer">
                      where it came from ↗
                    </a>
                  </>
                )}
              </span>
              {s.rule === 'deadline' && (
                <button className="btn tiny ghost" onClick={(e) => act(s, 'remind', e.currentTarget)}>
                  + remind me
                </button>
              )}
              {!s.required && (
                <button className="icon-x" title="Not needed: don't suggest it again" onClick={(e) => act(s, 'dismiss', e.currentTarget)}>
                  ×
                </button>
              )}
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      {canAsk && !items.length && (
        <button className="btn tiny ghost" disabled={asking} onClick={ask} title="One small, capped Claude call">
          {asking ? <span className="blink">thinking…</span> : '✦ anything else only I should do?'}
        </button>
      )}
    </div>
  )
}
