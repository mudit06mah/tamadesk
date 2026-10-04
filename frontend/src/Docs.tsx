// Your documents: resume, product brief, notes. The companion reads one only when a task needs it.
import { useEffect, useRef, useState } from 'react'
import { api, type Doc } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import type { Toast } from './util'

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

export function DocsPanel({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [docs, setDocs] = useState<Doc[]>([])
  const [kind, setKind] = useState<string>('resume')
  const file = useRef<HTMLInputElement>(null)
  const load = () => void api.docs().then(setDocs)
  useEffect(load, [])

  const upload = async (f: File) => {
    try {
      await api.addDoc(f.name, kind, await toB64(f))
      fx.sound('capture')
      notify(`${buddy.name} can now read ${f.name} when it helps`)
      load()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  return (
    <div className="docs">
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
