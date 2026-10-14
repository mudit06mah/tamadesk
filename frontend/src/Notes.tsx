// Notes: what your companion wrote for you from your tabs (blog drafts, study notes, digests,
// comparisons). Read it rendered, edit the markdown, copy or download it, or ask for a revision.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, dayLabel, type Note } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Markdown } from './Markdown'
import { Win } from './ui'
import type { Toast } from './util'

export function Notes({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [notes, setNotes] = useState<Note[] | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ name: '', text: '' })
  const [confirm, setConfirm] = useState(false)

  const load = useCallback(async () => {
    const n = await api.notes()
    setNotes(n)
    setSel((cur) => (cur && n.some((x) => x.id === cur) ? cur : (n[0]?.id ?? null)))
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  const note = notes?.find((n) => n.id === sel) ?? null
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the editor when switching notes
    if (note) setDraft({ name: note.name, text: note.text })
    setEditing(false)
    setConfirm(false)
  }, [note?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!note || (draft.name === note.name && draft.text === note.text)) return
    await api.saveNote(note.id, draft.name, draft.text)
    fx.sound('tap')
    await load()
  }

  const download = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([draft.text], { type: 'text/markdown' }))
    a.download = `${draft.name.replace(/[^\w-]+/g, '-').toLowerCase() || 'note'}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (!notes) return <p className="loading">opening notes…</p>

  return (
    <div className="notes">
      <header className="screen-head">
        <h1>Notes</h1>
      </header>
      {notes.length === 0 ? (
        <Win title="notes.empty" className="empty-win">
          <p className="muted">
            Nothing yet. Open a tab and press one of its ✦ buttons (like "Write a blog post" on papers), or just ask {buddy.name} to write
            something up. It lands here.
          </p>
        </Win>
      ) : (
        <div className="notes-grid">
          <ul className="notes-list">
            {notes.map((n) => (
              <li key={n.id}>
                <button className={`nav-row ${n.id === sel ? 'on' : ''}`} onClick={() => (fx.sound('tap'), setSel(n.id))}>
                  {n.id === sel && <motion.span layoutId="note-on" className="nav-glow" />}
                  <span className="nav-label">{n.name}</span>
                  <span className="muted small">{dayLabel(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
          <AnimatePresence mode="wait">
            {note && (
              <motion.div key={note.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Win
                  title={`${draft.name.toLowerCase().replace(/\s+/g, '_').slice(0, 30)}.md`}
                  right={
                    <span className="note-tools">
                      <button className="btn tiny ghost" onClick={() => (editing ? void save().then(() => setEditing(false)) : setEditing(true))}>
                        {editing ? 'done' : 'edit'}
                      </button>
                      <button className="btn tiny ghost" onClick={() => (navigator.clipboard.writeText(draft.text), fx.sound('tap'), notify('Copied as markdown'))}>
                        copy
                      </button>
                      <button className="btn tiny ghost" onClick={download}>
                        .md ↓
                      </button>
                    </span>
                  }
                >
                  {editing ? (
                    <div className="note-edit">
                      <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} onBlur={save} />
                      <textarea value={draft.text} onChange={(e) => setDraft({ ...draft, text: e.target.value })} onBlur={save} spellCheck />
                    </div>
                  ) : (
                    <div className="note-read">
                      <Markdown text={draft.text} />
                    </div>
                  )}
                  <div className="item-acts note-foot">
                    <button className="btn tiny" onClick={() => askBolt(`Revise my note "${note.name}" (read it, then save the new version with write_note under the same title): `)}>
                      ✎ ask {buddy.name} to revise
                    </button>
                    <span className="grow" />
                    <button
                      className={`btn tiny ghost ${confirm ? 'bad-text' : ''}`}
                      onClick={async () => {
                        if (!confirm) return setConfirm(true)
                        await api.deleteDoc(note.id)
                        fx.sound('drop')
                        await load()
                      }}
                    >
                      {confirm ? 'really delete?' : 'delete'}
                    </button>
                  </div>
                </Win>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
