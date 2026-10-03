// Picking a new tab: a gallery of templates (instant, no tokens) or one sentence for the companion
// (one tiny call on the light model). The same TemplateCard is used in New Game.
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api, type Mod, type Template } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { ModIcon } from './icons'
import { Dialog } from './ui'
import type { Toast } from './util'

export type Pick = { template: string; params: Record<string, string> }

export function useTemplates() {
  const [ts, setTs] = useState<Template[]>([])
  useEffect(() => {
    void api.templates().then(setTs)
  }, [])
  return ts
}

export function TemplateCard({
  t,
  on,
  params,
  onToggle,
  onParam,
}: {
  t: Template
  on: boolean
  params: Record<string, string>
  onToggle: () => void
  onParam: (k: string, v: string) => void
}) {
  return (
    <motion.div layout className={`tpl ${on ? 'on' : ''}`}>
      <motion.button type="button" className="tpl-head" onClick={onToggle} whileTap={{ scale: 0.96 }}>
        <span className="tpl-icon">
          <ModIcon name={t.icon} />
        </span>
        <span>
          <b>{t.title}</b>
          <span className="muted small">{t.blurb}</span>
        </span>
        <span className="tpl-check">{on ? '✓' : '+'}</span>
      </motion.button>
      <AnimatePresence>
        {on && (
          <motion.div className="tpl-params" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
            {Object.entries(t.params).map(([k, p]) => (
              <label key={k} className="field">
                <span>{p.label}</span>
                <input value={params[k] ?? ''} placeholder={p.default} onChange={(e) => onParam(k, e.target.value)} />
              </label>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/** Selection state for one or many template cards. Topic fields start from the user's interests. */
export function usePicks(multi: boolean, interests = '') {
  const [picks, setPicks] = useState<Pick[]>([])
  const seed = (t: Template) =>
    Object.fromEntries(Object.entries(t.params).flatMap(([k, p]) => (p.from === 'interests' && interests.trim() ? [[k, interests.trim()]] : [])))
  const toggle = (t: Template) =>
    setPicks((ps) => (ps.some((p) => p.template === t.key) ? ps.filter((p) => p.template !== t.key) : [...(multi ? ps : []), { template: t.key, params: seed(t) }]))
  const setParam = (key: string, k: string, v: string) =>
    setPicks((ps) => ps.map((p) => (p.template === key ? { ...p, params: { ...p.params, [k]: v } } : p)))
  return { picks, toggle, setParam, of: (key: string) => picks.find((p) => p.template === key) }
}

export function NewTabDialog({
  open,
  onClose,
  onCreated,
  notify,
  interests: saved,
}: {
  open: boolean
  onClose: () => void
  onCreated: (m: Mod) => void
  notify: (t: string, k?: Toast['kind']) => void
  interests: string
}) {
  const fx = useFx()
  const buddy = useCompanion()
  const ts = useTemplates()
  const [interests, setInterests] = useState(saved)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start from the saved answer each time
    if (open) setInterests(saved)
  }, [open, saved])
  const { picks, toggle, setParam, of } = usePicks(false, interests)
  const [wish, setWish] = useState('')
  const [busy, setBusy] = useState(false)

  const done = (m: Mod) => {
    fx.sound('hatch')
    fx.banner({ kind: 'goal', title: 'NEW TAB!', sub: `${m.name} hatched. ${buddy.name} is filling it now.` })
    setWish('')
    onCreated(m)
  }

  const create = async () => {
    setBusy(true)
    try {
      if (interests.trim() !== saved.trim()) await api.setAbout('interests', interests)
      done(wish.trim() ? await api.askModule(wish) : await api.createModule(picks[0].template, picks[0].params))
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} title="new_tab.exe" onClose={onClose} wide>
      <div className="dialog-form">
        <p className="dialog-lead">What should {buddy.name} keep an eye on for you?</p>
        <label className="field">
          <span>your interests ({buddy.name} fills topics from these)</span>
          <input value={interests} onChange={(e) => setInterests(e.target.value)} placeholder="devops, quantum computing, game design…" />
        </label>
        <div className="tpl-grid">
          {ts.map((t) => (
            <TemplateCard key={t.key} t={t} on={!!of(t.key)} params={of(t.key)?.params ?? {}} onToggle={() => (setWish(''), toggle(t))} onParam={(k, v) => setParam(t.key, k, v)} />
          ))}
        </div>
        <label className="field">
          <span>…or just describe it ({buddy.name} picks the setup)</span>
          <input value={wish} onChange={(e) => setWish(e.target.value)} placeholder="papers on GPU quantum simulation, every morning" />
        </label>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn solid" disabled={busy || (!wish.trim() && !picks.length)} onClick={create}>
            {busy ? <span className="blink">hatching…</span> : 'Hatch tab'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
