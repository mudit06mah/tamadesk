// A module tab: whatever the module's YAML describes, drawn with one of the fixed views.
// Every tab is the same ranked list: keep, skip, summarize, email, or turn into a todo.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, when, type Mod, type ModItem } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { ItemCard, useItemActions } from './ItemCard'
import { Dialog, Win } from './ui'
import type { Toast } from './util'

type Props = { mod: Mod; notify: (t: string, k?: Toast['kind']) => void; onChange: () => void; onDeleted: () => void }

export function ModulePage({ mod, notify, onChange, onDeleted }: Props) {
  const fx = useFx()
  const buddy = useCompanion()
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

  const runFlow = async (w: { label: string; prompt: string }) => {
    let kept = (await api.items(mod.id, 'saved')).items
    const note = kept.length ? '' : ' (nothing kept yet, so these are the best new ones)'
    if (!kept.length) kept = (await api.items(mod.id, 'new')).items.slice(0, 6)
    if (!kept.length) return notify(`Nothing in ${mod.name} yet. Refresh it first.`, 'err')
    const list = kept.slice(0, 15).map((it) => `- ${it.title}${it.url ? ` (${it.url})` : ''}${it.data.email ? ` [published email: ${it.data.email}]` : ''} [item ${it.id}]`)
    askBolt(`${w.prompt}\n\nFrom my "${mod.name}" tab${note}:\n${list.join('\n')}`)
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
        <TabName mod={mod} notify={notify} onChange={onChange} />
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
      {mod.workflows.length > 0 && (
        <div className="workflows">
          <span className="muted small">with what you kept:</span>
          {mod.workflows.map((w, i) => (
            <motion.button
              key={w.label}
              className="chip flow"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, transition: { delay: 0.05 * i } }}
              whileTap={{ scale: 0.92 }}
              onClick={() => runFlow(w)}
            >
              ✦ {w.label}
            </motion.button>
          ))}
        </div>
      )}
      <AnimatePresence>
        {mod.run?.last_error && (
          <motion.div className="source-trouble" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <span title={mod.run.last_error}>
              {mod.run.last_error.split('; ').length} source{mod.run.last_error.includes('; ') ? 's' : ''} had trouble this time:{' '}
              <span className="muted">{mod.run.last_error.split('; ').map((e) => e.split(':')[0]).join(', ')}</span>
            </span>
            <button
              className="btn tiny"
              onClick={() => askBolt(`My "${mod.name}" tab has a source that keeps failing (${mod.run?.last_error}). Replace it with a working one.`)}
            >
              Ask {buddy.name} to fix it
            </button>
            <button
              className="icon-x"
              title="Hide this until something else breaks"
              onClick={async () => {
                await api.dismissError(mod.id)
                fx.sound('close')
                onChange()
              }}
            >
              ×
            </button>
          </motion.div>
        )}
      </AnimatePresence>

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

/** The tab's title is its name field: click, type, Enter (Esc puts it back). */
function TabName({ mod, notify, onChange }: Pick<Props, 'mod' | 'notify' | 'onChange'>) {
  const fx = useFx()
  const [name, setName] = useState(mod.name)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follow renames made elsewhere (e.g. by Bolt)
    setName(mod.name)
  }, [mod.name])
  const save = async () => {
    const n = name.trim()
    if (!n || n === mod.name) return setName(mod.name)
    try {
      await api.renameModule(mod.id, n)
      fx.sound('stamp')
      onChange()
    } catch (e) {
      notify((e as Error).message, 'err')
      setName(mod.name)
    }
  }
  return (
    <h1 className="tab-name">
      <input
        aria-label="Tab name (click to rename)"
        title="Click to rename"
        value={name}
        maxLength={24}
        size={Math.max(4, name.length)}
        onChange={(e) => setName(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') {
            const el = e.currentTarget
            setName(mod.name)
            requestAnimationFrame(() => el.blur())
          }
        }}
      />
      <span className="tab-name-pen" aria-hidden>
        ✎
      </span>
    </h1>
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
  const buddy = useCompanion()
  const [mode, setMode] = useState<'bolt' | 'yaml'>('bolt')
  const [text, setText] = useState('')
  const [wish, setWish] = useState('')
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the file into the editor when opened
    if (yaml !== null) setText(yaml)
    setConfirm(false)
  }, [yaml])

  const submit = async () => {
    if (mode === 'bolt') {
      if (!wish.trim()) return
      askBolt(`Update my "${mod.name}" tab (id ${mod.id}): ${wish.trim()}`, true)
      setWish('')
      onClose()
      return
    }
    try {
      await api.saveModuleYaml(mod.id, text)
      fx.sound('stamp')
      notify('Saved')
      onSaved()
    } catch (err) {
      notify((err as Error).message, 'err')
    }
  }

  return (
    <Dialog open={yaml !== null} title={`${mod.id}.tab`} onClose={onClose} wide>
      <form
        className="dialog-form"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="seg-tabs edit-modes" role="tablist">
          {(['bolt', 'yaml'] as const).map((m) => (
            <button type="button" key={m} role="tab" aria-selected={mode === m} className={mode === m ? 'on' : ''} onClick={() => (fx.sound('tap'), setMode(m))}>
              {m === 'bolt' ? `Tell ${buddy.name}` : 'Edit YAML'}
              {mode === m && <motion.span layoutId="edit-mode" className="seg-tab-on" />}
            </button>
          ))}
        </div>
        <AnimatePresence mode="wait">
          {mode === 'bolt' ? (
            <motion.div key="bolt" className="edit-pane" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }}>
              <p className="dialog-lead">Say what should change, in plain words. {buddy.name} edits the tab and checks the new sources work.</p>
              <textarea
                data-autofocus
                className="edit-wish"
                value={wish}
                onChange={(e) => setWish(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && void submit()}
                placeholder="e.g. only remote roles in Europe · add Linear and Vercel's job boards · refresh every morning at 8 · ping me when something new shows up"
              />
            </motion.div>
          ) : (
            <motion.div key="yaml" className="edit-pane" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }}>
              <p className="dialog-lead">This tab is just this file: sources, schedule (30m, 6h, daily 08:00), buttons and workflows.</p>
              <textarea
                className="yaml"
                spellCheck={false}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Tab') return
                  e.preventDefault() // Tab indents (two spaces) instead of leaving the editor
                  const el = e.currentTarget
                  const at = el.selectionStart
                  setText(text.slice(0, at) + '  ' + text.slice(el.selectionEnd))
                  requestAnimationFrame(() => el.setSelectionRange(at + 2, at + 2))
                }}
              />
            </motion.div>
          )}
        </AnimatePresence>
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
          <span className="grow" />
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn solid" disabled={mode === 'bolt' && !wish.trim()}>
            {mode === 'bolt' ? `Ask ${buddy.name}` : 'Save'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
