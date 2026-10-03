// A module tab: whatever the module's YAML describes, drawn with one of the fixed views.
// feed = a ranked list you skim; deck = one card at a time you swipe (drag, or y / n / u).
import { AnimatePresence, motion, useMotionValue, useTransform } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, when, type Mod, type ModItem } from './api'
import { useFx } from './fx/Fx'
import { ItemCard, useItemActions } from './ItemCard'
import { Dialog, Win } from './ui'
import { isTyping, type Toast } from './util'

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
      ) : mod.view === 'deck' && tab === 'new' ? (
        <Deck items={items} mod={mod} run={run} busy={busy} summaries={summaries} />
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
            undo <kbd>u</kbd>
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
      <DeckKeys enabled={mod.view === 'deck' && tab === 'new' && !!items?.length && editing === null} onUndo={undo} />
    </div>
  )
}

/** Only `u` (undo) lives here; y / n are handled by the top deck card itself. */
function DeckKeys({ enabled, onUndo }: { enabled: boolean; onUndo: () => void }) {
  useEffect(() => {
    if (!enabled) return
    const k = (e: KeyboardEvent) => !isTyping(e) && e.key === 'u' && onUndo()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [enabled, onUndo])
  return null
}

function Deck({
  items,
  mod,
  run,
  busy,
  summaries,
}: {
  items: ModItem[]
  mod: Mod
  run: ReturnType<typeof useItemActions>['run']
  busy: number | null
  summaries: ReturnType<typeof useItemActions>['summaries']
}) {
  const [reasons, setReasons] = useState(false)
  const top = items[0]
  const x = useMotionValue(0)
  const rotate = useTransform(x, [-220, 220], [-14, 14])
  const keep = useTransform(x, [30, 140], [0, 1])
  const nope = useTransform(x, [-140, -30], [1, 0])

  const decide = useCallback(
    (a: 'save' | 'skip', reason = '') => {
      setReasons(false)
      void run(top, a, document.querySelector('.deck-top'), reason)
    },
    [run, top],
  )
  const skip = useCallback(() => (mod.reasons.length ? setReasons(true) : decide('skip')), [mod.reasons.length, decide])

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey) return
      if (reasons) {
        const n = Number(e.key)
        if (n >= 1 && n <= mod.reasons.length) {
          e.stopImmediatePropagation() // digits also switch tabs app-wide
          decide('skip', mod.reasons[n - 1])
        }
        if (e.key === 'Escape') setReasons(false)
        return
      }
      if (e.key === 'y' || e.key === 'ArrowRight') decide('save')
      if (e.key === 'n' || e.key === 'ArrowLeft') skip()
    }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [reasons, decide, skip, mod.reasons])

  return (
    <div className="deck">
      <div className="deck-stack">
        {items.slice(1, 3).map((it, i) => (
          <div key={it.id} className="deck-under" style={{ transform: `translateY(${(i + 1) * 10}px) scale(${1 - (i + 1) * 0.04})`, zIndex: 2 - i }} />
        ))}
        <AnimatePresence mode="popLayout">
          <motion.div
            key={top.id}
            className="deck-top"
            style={{ x, rotate, zIndex: 5 }}
            drag="x"
            dragSnapToOrigin
            onDragEnd={(_, info) => {
              if (info.offset.x > 120) decide('save')
              else if (info.offset.x < -120) skip()
            }}
            initial={{ scale: 0.92, opacity: 0, y: 14 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ x: x.get() >= 0 ? 420 : -420, opacity: 0, rotate: x.get() >= 0 ? 18 : -18, transition: { duration: 0.28 } }}
            whileDrag={{ cursor: 'grabbing' }}
          >
            <motion.span className="deck-stamp keep" style={{ opacity: keep }}>
              KEEP
            </motion.span>
            <motion.span className="deck-stamp nope" style={{ opacity: nope }}>
              NOPE
            </motion.span>
            <ItemCard it={top} mod={{ actions: mod.actions.filter((a) => a !== 'save' && a !== 'skip') }} run={run} busy={busy === top.id} summary={summaries[top.id]} />
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="deck-buttons">
        {reasons ? (
          <div className="reasons">
            {mod.reasons.map((r, i) => (
              <button key={r} className="chip" onClick={() => decide('skip', r)}>
                <kbd>{i + 1}</kbd> {r}
              </button>
            ))}
            <button className="chip" onClick={() => decide('skip')}>
              just skip
            </button>
          </div>
        ) : (
          <>
            <motion.button className="btn big skip-btn" whileTap={{ scale: 0.9, rotate: -6 }} onClick={skip}>
              ✕ <kbd>n</kbd>
            </motion.button>
            <span className="muted small">{items.length} left · drag the card</span>
            <motion.button className="btn solid big" whileTap={{ scale: 0.9, rotate: 6 }} onClick={() => decide('save')}>
              ♥ <kbd>y</kbd>
            </motion.button>
          </>
        )}
      </div>
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
        <p className="dialog-lead">This tab is just this file. Change sources, schedule (30m, 6h, daily 08:00), view (feed or deck) or buttons.</p>
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
