// Your documents: resume, product brief, notes. The companion reads one only when a task needs it,
// and turns your resume into a one-page profile card that every ask reads (yours to edit).
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Doc, type ProfileCard } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Markdown } from './Markdown'
import type { Toast } from './util'

type Notify = (t: string, k?: Toast['kind']) => void

const KINDS = [
  ['resume', 'resume / CV'],
  ['product', 'product brief'],
  ['notes', 'notes'],
  ['other', 'other'],
] as const

const toB64 = (f: File) =>
  new Promise<string>((ok, bad) => {
    const r = new FileReader()
    r.onload = () => ok(String(r.result).split(',', 2)[1] ?? '')
    r.onerror = () => bad(r.error)
    r.readAsDataURL(f)
  })

/** What your companion knows about you from your resume, plus your notes: one page, read in every ask. */
function Card({ bump, notify }: { bump: number; notify: Notify }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [card, setCard] = useState<ProfileCard | null>(null)
  const [edit, setEdit] = useState<string | null>(null)
  const was = useRef<ProfileCard['state'] | null>(null)
  const load = useCallback(async () => {
    const c = await api.profile()
    if (was.current === 'building' && c.state === 'ready') {
      fx.sound('arrive')
      notify(`${buddy.name} wrote your profile card. Have a look, and fix anything it got wrong.`)
    }
    was.current = c.state
    setCard(c)
  }, [fx, notify, buddy.name])
  useEffect(() => void load(), [load, bump])
  useEffect(() => {
    if (card?.state !== 'building') return
    const t = setInterval(() => void load(), 2000) // it's being written in the background
    return () => clearInterval(t)
  }, [card?.state, load])
  if (!card) return null
  const building = card.state === 'building'

  const save = async () => {
    if (edit === null) return
    await api.saveProfile(edit)
    fx.sound('stamp')
    setEdit(null)
    await load()
  }
  const rebuild = async () => {
    try {
      await api.rebuildProfile()
      fx.sound('tap')
      await load()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  return (
    <div className="profile-card">
      <div className="field-label">profile card</div>
      {building && <p className="muted small reading">{buddy.name} is reading your resume</p>}
      {card.state === 'error' && <p className="small bad-text">Couldn't write it this time: {card.error}</p>}
      {edit !== null ? (
        <>
          <textarea rows={16} value={edit} onChange={(e) => setEdit(e.target.value)} aria-label="Profile card" />
          <div className="card-acts">
            <button className="btn tiny" onClick={() => setEdit(null)}>
              cancel
            </button>
            <button className="btn tiny solid" onClick={() => void save()}>
              save
            </button>
          </div>
        </>
      ) : card.text ? (
        <div className="profile-page">
          <Markdown text={card.text} />
        </div>
      ) : (
        !building && (
          <p className="muted small">
            Add your resume below and {buddy.name} writes a one-page card from it: who you are, your skills, projects and links. Every ask reads the card, so
            job searches fit and emails sound like someone who knows you. Things you ask {buddy.name} to remember land in its Notes.
          </p>
        )
      )}
      {edit === null && !building && (card.text || card.has_resume) && (
        <div className="card-acts">
          {card.text && (
            <button className="btn tiny" onClick={() => setEdit(card.text)}>
              edit
            </button>
          )}
          {card.has_resume && (
            <button className="btn tiny" title="Write it again from your newest resume · your Notes stay" onClick={() => void rebuild()}>
              {card.text ? 'rebuild from resume' : 'write it from my resume'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function DocsPanel({ notify }: { notify: Notify }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [docs, setDocs] = useState<Doc[]>([])
  const [kind, setKind] = useState<string>('resume')
  const [bump, setBump] = useState(0)
  const file = useRef<HTMLInputElement>(null)
  const load = () => void api.docs().then(setDocs)
  useEffect(load, [])

  const upload = async (f: File) => {
    try {
      await api.addDoc(f.name, kind, await toB64(f))
      fx.sound('capture')
      notify(kind === 'resume' ? `${buddy.name} is reading ${f.name} to write your profile card` : `${buddy.name} can now read ${f.name} when it helps`)
      load()
      setBump((b) => b + 1)
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  return (
    <div className="docs">
      <Card bump={bump} notify={notify} />
      <div className="field-label">your documents</div>
      <p className="muted small">
        {buddy.name} reads these only when a task needs them: your resume for a job email, a product brief for outreach.
      </p>
      <ul className="sample-list">
        {docs.map((d) => (
          <li key={d.id}>
            <span className="tag">{d.kind}</span>
            <span className="todo-text">{d.name}</span>
            <span className="muted small">{Math.ceil(d.chars / 1000)}k</span>
            <button className="icon-x" title="Remove" onClick={async () => (await api.deleteDoc(d.id), load())}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <div className="chips">
        {KINDS.map(([k, label]) => (
          <button key={k} className={`chip ${kind === k ? 'on' : ''}`} onClick={() => setKind(k)}>
            {label}
          </button>
        ))}
      </div>
      <input ref={file} type="file" accept=".pdf,.md,.txt" hidden onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
      <button className="btn tiny" onClick={() => file.current?.click()}>
        + add PDF, .md or .txt
      </button>
    </div>
  )
}
