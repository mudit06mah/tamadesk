// A module tab: whatever the module's YAML describes, drawn with one of the fixed views.
// Every tab is the same ranked list: keep, skip, summarize, email, or turn into a todo.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, when, type Mod, type ModItem } from './api'
import { useFx } from './fx/Fx'
import { ItemCard, useItemActions } from './ItemCard'
import { Dialog, Win } from './ui'
import type { Toast } from './util'

type Props = { mod: Mod; notify: (t: string, k?: Toast['kind']) => void; onChange: () => void; onDeleted: () => void }

export function ModulePage({ mod, notify, onChange, onDeleted }: Props) {
  const fx = useFx()
  const [tab, setTab] = useState<'new' | 'saved'>('new')
  const [items, setItems] = useState<ModItem[] | null>(null)
  const [more, setMore] = useState(false)
  const [last, setLast] = useState<ModItem | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await api.items(mod.id, tab)
    setItems(r.items)
    setMore(r.has_more)
  }, [mod.id, tab])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on tab switch
    void load()
  }, [load])

  // a fresh tab fills in the background: poll until its first run lands
  const empty = items?.length === 0 && !mod.run
  useEffect(() => {
    if (!empty) return
    const t = setInterval(() => {
      void load()
      onChange()
    }, 2500)
    return () => clearInterval(t)
  }, [empty, load, onChange])

  const { run, busy, summaries } = useItemActions(notify, (it) => {
    setItems((xs) => xs?.filter((x) => x.id !== it.id) ?? null)
    setLast(it)
    onChange()
  })

  const undo = async () => {
    if (!last) return
    await api.act(last.id, 'undo')
    fx.sound('tap')
    setLast(null)
    await load()
    onChange()
  }

  const refresh = async () => {
    await api.runModule(mod.id)
    fx.sound('tap')
    notify(`Checking ${mod.sources.length} source${mod.sources.length > 1 ? 's' : ''}…`)
    setTimeout(() => {
      void load()
      onChange()
    }, 4000)
  }

  return (
    <div className="modpage">
      <header className="screen-head">
        <h1>{mod.name}</h1>
        <div className="mod-tools">
          <div className="seg-tabs" role="tablist">
            {(['new', 'saved'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
                {t === 'new' ? `new ${mod.new}` : `kept ${mod.saved}`}
                {tab === t && <motion.span layoutId={`segtab-${mod.id}`} className="seg-tab-on" />}
              </button>
            ))}
          </div>
          <button className="btn tiny ghost" onClick={refresh} title="Fetch now">
            ↻ {mod.run?.last_run ? when(mod.run.last_run) : 'never'}
          </button>
          <button className="btn tiny ghost" onClick={async () => setEditing((await api.moduleYaml(mod.id)).yaml)}>
            ⚙ edit
          </button>
        </div>
      </header>
      {mod.run?.last_error && <p className="bad-text small">Some sources failed: {mod.run.last_error}</p>}

      {!items ? (
        <p className="loading">opening {mod.name.toLowerCase()}…</p>
      ) : items.length === 0 ? (
        <Win title={`${mod.id}.empty`} className="empty-win">
          <p className="muted">
            {empty ? <span className="blink">Fetching the first batch…</span> : tab === 'new' ? 'All caught up. New things land here on schedule.' : 'Nothing kept yet.'}
          </p>
        </Win>
      ) : (
        <ul className="feed">
          <AnimatePresence initial={false}>
            {items.map((it) => (
              <motion.li key={it.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 60, height: 0, marginBottom: 0 }}>
                <ItemCard it={it} mod={mod} run={run} busy={busy === it.id} summary={summaries[it.id]} />
              </motion.li>
            ))}
          </AnimatePresence>
          {more && (
            <button
              className="btn tiny ghost"
              onClick={async () => {
                const r = await api.items(mod.id, tab, items.length)
                setItems([...items, ...r.items])
                setMore(r.has_more)
              }}
            >
              load more
            </button>
          )}
        </ul>
      )}

      {last && (
        <p className="undo-line muted small">
          {last.title.slice(0, 60)} moved.{' '}
          <button className="btn tiny ghost" onClick={undo}>
            undo
          </button>
        </p>
      )}

      <YamlDialog
        mod={mod}
        yaml={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null)
          onChange()
          void load()
        }}
        onDeleted={onDeleted}
        notify={notify}
      />
    </div>
  )
}

function YamlDialog({
  mod,
  yaml,
  onClose,
  onSaved,
  onDeleted,
  notify,
}: {
  mod: Mod
  yaml: string | null
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
  notify: Props['notify']
}) {
  const fx = useFx()
  const [text, setText] = useState('')
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the file into the editor when opened
    if (yaml !== null) setText(yaml)
    setConfirm(false)
  }, [yaml])
  return (
    <Dialog open={yaml !== null} title={`${mod.id}.yaml`} onClose={onClose}>
      <form
        className="dialog-form"
        onSubmit={async (e) => {
          e.preventDefault()
          try {
            await api.saveModuleYaml(mod.id, text)
            fx.sound('stamp')
            notify('Saved')
            onSaved()
          } catch (err) {
            notify((err as Error).message, 'err')
          }
        }}
      >
        <p className="dialog-lead">This tab is just this file. Change sources, schedule (30m, 6h, daily 08:00) or buttons. Or just ask your companion to change it.</p>
        <textarea className="yaml" data-autofocus spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="dialog-actions">
          <button
            type="button"
            className={`btn ghost ${confirm ? 'bad-text' : ''}`}
            onClick={async () => {
              if (!confirm) return setConfirm(true)
              await api.deleteModule(mod.id)
              fx.sound('drop')
              onClose()
              onDeleted()
            }}
          >
            {confirm ? 'Really delete this tab?' : 'Delete tab'}
          </button>
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn solid">Save</button>
        </div>
      </form>
    </Dialog>
  )
}
