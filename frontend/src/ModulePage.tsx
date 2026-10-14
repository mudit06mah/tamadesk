// A module tab: whatever the module's YAML describes, drawn with one of the fixed views.
// A feed tab is a ranked list (bookmark, pass, summarize, email, or turn into a todo); a steps tab is a
// path in order (a learning roadmap): items grouped by step, ticked off as you go.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, when, type Mod, type ModItem } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { ItemCard, useItemActions, type Act } from './ItemCard'
import { Bar, Dialog, SegTabs, Win } from './ui'
import { focusEl, focusId, useRefresh, type Toast } from './util'

const PICKS = 5 // a tab shows its best few first: a feed you can finish, not a pile

type Props = { mod: Mod; focus?: string; notify: (t: string, k?: Toast['kind']) => void; onChange: () => void; onDeleted: () => void }

export function ModulePage({ mod, focus = '', notify, onChange, onDeleted }: Props) {
  const fx = useFx()
  const buddy = useCompanion()
  const [tab, setTab] = useState<'new' | 'saved'>('new')
  const [items, setItems] = useState<ModItem[] | null>(null)
  const [more, setMore] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [linked, setLinked] = useState<ModItem | null>(null) // a linked item that's in neither list (skipped, done)
  const [all, setAll] = useState(false) // new items: today's best 5 first, the rest on a click
  const want = focusId(focus, 'i')
  const steps = mod.layout === 'steps'

  const load = useCallback(async () => {
    const r = await api.items(mod.id, steps ? 'path' : tab, 0, steps ? 200 : 30)
    setItems(r.items)
    setMore(r.has_more)
  }, [mod.id, tab, steps])
  useRefresh(load)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on tab switch
    void load()
  }, [load])

  // a link to one item (from Today): show the list it's in, or pin it on top, then bring it into view
  useEffect(() => {
    if (want === null) return
    api.item(want).then(({ item }) => {
      if (item.status === 'new' || item.status === 'saved') setTab(item.status === 'saved' ? 'saved' : 'new')
      else setLinked(item)
    }, () => undefined)
  }, [want])
  useEffect(() => {
    if (want !== null && items) focusEl(`item-${want}`)
  }, [want, items, linked])

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

  const { run, busy, summaries } = useItemActions(notify, (it, status) => {
    if (steps && status === 'done') {
      // a path keeps what you watched, ticked, in its place
      const next = (items ?? []).map((x) => (x.id === it.id ? { ...x, status } : x))
      celebrate(it, next)
      setItems(next)
    } else {
      setItems((xs) => xs?.filter((x) => x.id !== it.id) ?? null)
    }
    onChange()
  })

  /** Finishing a step's first video is a step done; the last step is the whole path. */
  const celebrate = (it: ModItem, next: ModItem[]) => {
    const step = it.data.step
    if (!step || (items ?? []).some((x) => x.data.step === step && x.status === 'done')) return
    const el = document.getElementById(`step-${step}`)
    fx.burstAt(el)
    fx.sound('levelup')
    const left = new Set(next.filter((x) => x.status !== 'done').map((x) => x.data.step))
    const doneSteps = new Set(next.filter((x) => x.status === 'done').map((x) => x.data.step))
    if ([...left].every((s) => doneSteps.has(s))) setTimeout(() => fx.banner({ kind: 'goal', title: 'PATH COMPLETE!', sub: `Every step of ${mod.name} done. Quiz yourself while it's fresh.` }), 500)
  }

  const runFlow = async (w: { label: string; prompt: string }) => {
    let kept = steps ? (items ?? []).filter((x) => x.status === 'done') : (await api.items(mod.id, 'saved')).items
    const note = kept.length ? '' : ' (nothing bookmarked yet, so these are the best new ones)'
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
          {!steps && <SegTabs tabs={[['new', `new ${mod.new}`], ['saved', `bookmarked ${mod.saved}`]]} value={tab} onChange={setTab} />}
          <button className="btn tiny ghost" onClick={refresh} title="Fetch now">
            ↻ {mod.run?.last_run ? when(mod.run.last_run) : 'never'}
          </button>
          <button className="btn tiny ghost" onClick={async () => setEditing((await api.moduleYaml(mod.id)).yaml)}>
            ⚙ edit
          </button>
        </div>
      </header>
      {steps ? <PathProgress items={items} /> : <Taste mod={mod} />}
      {mod.workflows.length > 0 && (
        <div className="workflows">
          <span className="muted small">{steps ? 'with what you’ve watched:' : 'with your bookmarks:'}</span>
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
      {!!mod.run?.dropped && (
        <p className="muted small fit-note">
          left out last time: {leftOut(mod)}.{' '}
          {mod.fit && (
            <button className="btn tiny ghost" onClick={() => askBolt(`My "${mod.name}" tab is too strict or too loose about fit (now: ${JSON.stringify(mod.fit)}). Ask me what I want and adjust it.`)}>
              adjust
            </button>
          )}
        </p>
      )}
      {!!mod.boards && <WatchedBoards mod={mod} onChange={onChange} />}
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

      {linked && (
        <div className="feed linked" id={`item-${linked.id}`}>
          <ItemCard it={linked} mod={mod} run={run} busy={busy === linked.id} summary={summaries[linked.id]} />
        </div>
      )}
      {!items ? (
        <p className="loading">opening {mod.name.toLowerCase()}…</p>
      ) : items.length === 0 ? (
        <Win title={`${mod.id}.empty`} className="empty-win">
          <p className="muted">
            {empty ? <span className="blink">Fetching the first batch…</span> : tab === 'new' ? 'All caught up. New things land here on schedule.' : 'No bookmarks yet.'}
          </p>
        </Win>
      ) : steps ? (
        <Steps items={items} mod={mod} run={run} busy={busy} summaries={summaries} onUndo={async (it) => {
          await api.act(it.id, 'undo')
          fx.sound('undo')
          await load()
        }} />
      ) : (
        // a tab switch is one fade of the whole list on its own GPU layer; cards only animate when one
        // leaves (the rest close the gap), never all at once on arrival
        <motion.ul
          className="feed"
          key={tab}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.16, ease: 'easeOut' }}
          style={{ willChange: 'opacity' }}
        >
          <AnimatePresence initial={false}>
            {(tab === 'new' && !all ? items.slice(0, PICKS) : items).map((it) => (
              <motion.li key={it.id} id={`item-${it.id}`} layout="position" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 60, transition: { duration: 0.18 } }}>
                <ItemCard it={it} mod={mod} run={run} busy={busy === it.id} summary={summaries[it.id]} />
              </motion.li>
            ))}
          </AnimatePresence>
          {tab === 'new' && !all && items.length > PICKS && (
            <button className="btn tiny ghost" onClick={() => setAll(true)}>
              {items.length - PICKS} more below today's picks ▾
            </button>
          )}
          {(all || tab !== 'new') && more && (
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
        </motion.ul>
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

/** "3 closed · 2 poor fit · 1 against your preferences", from the last refresh. */
function leftOut(mod: Mod): string {
  let why: Record<string, number> = {}
  try {
    why = JSON.parse(mod.run?.left_out ?? '{}') as Record<string, number>
  } catch {
    /* an older run without the breakdown */
  }
  const parts = Object.entries(why).map(([k, n]) => `${n} ${k}`)
  return parts.length ? parts.join(' · ') : `${mod.run?.dropped} that didn't fit`
}

/** Company job boards this tab learned from search results: read directly on every refresh. */
function WatchedBoards({ mod, onChange }: { mod: Mod; onChange: () => void }) {
  const fx = useFx()
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<{ board: string; found_from: string | null }[]>([])
  const show = async () => {
    fx.sound(open ? 'close' : 'open')
    if (!open) setRows(await api.boards(mod.id))
    setOpen(!open)
  }
  return (
    <div className="muted small fit-note">
      <button className="btn tiny ghost" aria-expanded={open} onClick={show} title="Found through search; their whole job list is read on every refresh">
        watching {mod.boards} company job board{mod.boards === 1 ? '' : 's'} {open ? '▴' : '▾'}
      </button>
      {open && (
        <span className="chips boards">
          {rows.map((r) => (
            <span key={r.board} className="chip" title={r.found_from ? `found from ${r.found_from}` : undefined}>
              {r.board.split(':')[1]} <span className="muted">· {r.board.split(':')[0]}</span>
              <button
                className="icon-x"
                title="Stop watching"
                onClick={async () => {
                  await api.forgetBoard(mod.id, r.board)
                  fx.sound('drop')
                  setRows(rows.filter((x) => x.board !== r.board))
                  onChange()
                }}
              >
                ×
              </button>
            </span>
          ))}
        </span>
      )}
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

/** What this tab has learned from your bookmarks and passes, so ranking never feels like magic. */
function Taste({ mod }: { mod: Mod }) {
  const n = mod.saved + mod.passed
  const q = (ws: string[]) => ws.map((w) => `“${w}”`).join(', ')
  return (
    <p className="muted small taste">
      {n === 0
        ? 'Bookmark what’s good and pass on the rest: this tab learns what to put first.'
        : `Learning from ${mod.saved} bookmark${mod.saved === 1 ? '' : 's'} and ${mod.passed} pass${mod.passed === 1 ? '' : 'es'}` +
          (mod.taste.more.length ? `: more ${q(mod.taste.more)}` : '') +
          (mod.taste.less.length ? `${mod.taste.more.length ? ';' : ':'} less ${q(mod.taste.less)}` : '') +
          '.'}
    </p>
  )
}

/** How far along the path you are: a step counts once you've watched one of its videos. */
function PathProgress({ items }: { items: ModItem[] | null }) {
  if (!items?.length) return null
  const all = new Set(items.map((x) => x.data.step))
  const done = new Set(items.filter((x) => x.status === 'done').map((x) => x.data.step))
  return (
    <div className="path-progress">
      <Bar value={done.size / all.size} label={`${done.size} of ${all.size} steps`} />
      <span className="muted small">
        {done.size} of {all.size} steps
      </span>
    </div>
  )
}

type StepsProps = {
  items: ModItem[]
  mod: Mod
  run: (it: ModItem, a: Act, el: Element | null) => void
  busy: number | null
  summaries: Record<number, ModItem['data']['summary']>
  onUndo: (it: ModItem) => void
}

/** A path: each step's topic, then its few videos. Watched ones stay, ticked, so you see the way you came. */
function Steps({ items, mod, run, busy, summaries, onUndo }: StepsProps) {
  const groups = new Map<number, ModItem[]>()
  for (const it of items) groups.set(it.data.step ?? 0, [...(groups.get(it.data.step ?? 0) ?? []), it])
  const watched = { ...mod, actions: ['open' as const] }
  return (
    <ol className="path-steps">
      {[...groups].map(([step, its]) => {
        const done = its.filter((x) => x.status === 'done').length
        return (
          <li key={step} className={`path-step ${done ? 'done' : ''}`}>
            <h3 className="path-head" id={`step-${step}`}>
              <span className="path-n">{done ? '✓' : step}</span>
              {its[0].data.topic ?? `Step ${step}`}
              <span className="muted small">
                {done}/{its.length} watched
              </span>
            </h3>
            <ul className="feed">
              <AnimatePresence initial={false}>
                {its.map((it) => (
                  <motion.li key={it.id} id={`item-${it.id}`} layout="position" className={it.status === 'done' ? 'watched' : ''} exit={{ opacity: 0, x: 60, transition: { duration: 0.18 } }}>
                    <ItemCard it={it} mod={it.status === 'done' ? watched : mod} run={run} busy={busy === it.id} summary={summaries[it.id]} />
                    {it.status === 'done' && (
                      <button className="btn tiny ghost unwatch" title="Not watched after all" onClick={() => onUndo(it)}>
                        ✓ watched · undo
                      </button>
                    )}
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          </li>
        )
      })}
    </ol>
  )
}
