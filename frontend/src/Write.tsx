// Write: drafts in your own voice. The voice comes from samples you paste in, studied once by
// the brain and reused for every draft.
import { useEffect, useState } from 'react'
import { api, when, type Draft, type Sample, type Voice } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Dialog, Win } from './ui'
import type { Toast } from './util'

export function Write({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [ask, setAsk] = useState('')
  const [busy, setBusy] = useState(false)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [samples, setSamples] = useState<Sample[]>([])
  const [voice, setVoice] = useState<Voice | null>(null)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [sample, setSample] = useState({ kind: 'email', title: '', body: '' })

  const load = async () => {
    const [d, s, v] = await Promise.all([api.drafts(), api.samples(), api.voice()])
    setDrafts(d)
    setSamples(s)
    setVoice(v)
  }
  useEffect(() => {
    void load()
  }, [])

  const draft = async () => {
    setBusy(true)
    try {
      await api.draft(ask)
      fx.sound('send')
      setAsk('')
      await load()
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const study = async () => {
    setVoiceBusy(true)
    try {
      setVoice(await api.buildVoice())
      fx.sound('levelup')
      notify(`${buddy.name} learned your voice`)
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setVoiceBusy(false)
    }
  }

  const copy = async (d: Draft) => {
    await navigator.clipboard.writeText(`${d.subject}\n\n${d.body}`)
    fx.sound('tap')
    notify('Copied. Paste it into your mail app.')
  }

  return (
    <div className="write-grid">
      <div className="write-main">
        <Win title="compose.exe">
          <form
            className="dialog-form"
            onSubmit={(e) => {
              e.preventDefault()
              void draft()
            }}
          >
            <p className="dialog-lead">What should the email do? Who's it to, what do you want, anything they should know.</p>
            <textarea
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
              placeholder="ask my professor for a 2-day extension on the lab report, I was sick on Monday"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && ask.trim().length >= 5) void draft()
              }}
            />
            <div className="dialog-actions">
              {!voice && <span className="muted small">tip: add samples on the right so drafts sound like you</span>}
              <button className="btn solid" disabled={busy || ask.trim().length < 5}>
                {busy ? <span className="blink">{buddy.name} is writing…</span> : 'Draft it'}
              </button>
            </div>
          </form>
        </Win>

        {drafts.map((d) => (
          <Win
            key={d.id}
            title={`draft_${d.id}.eml`}
            right={<span className="muted small">{when(d.created_at)}</span>}
          >
            <div className="draft">
              <div className="draft-ask muted small">“{d.ask}”</div>
              <div className="draft-subject">{d.subject}</div>
              <pre className="pre draft-body">{d.body}</pre>
              <div className="dialog-actions">
                <button
                  className="btn ghost tiny"
                  onClick={async () => {
                    await api.dropDraft(d.id)
                    fx.sound('drop')
                    await load()
                  }}
                >
                  Toss
                </button>
                <button className="btn tiny" onClick={() => setAsk(d.ask)}>
                  Redo
                </button>
                <button className="btn solid tiny" onClick={() => copy(d)}>
                  Copy
                </button>
              </div>
            </div>
          </Win>
        ))}
      </div>

      <Win title="voice.cfg" className="write-side">
        {voice ? (
          <div className="voice">
            <p>{voice.summary}</p>
            <div className="chips">
              {voice.traits.map((t) => (
                <span key={t} className="chip on">
                  {t}
                </span>
              ))}
            </div>
            {voice.phrases.length > 0 && <p className="muted small">sounds like: “{voice.phrases.slice(0, 3).join('”, “')}”</p>}
          </div>
        ) : (
          <p className="muted">No voice yet. Add 2 or 3 things you wrote, then let {buddy.name} study them.</p>
        )}
        <div className="field-label">samples ({samples.length})</div>
        <ul className="sample-list">
          {samples.map((s) => (
            <li key={s.id}>
              <span className="tag">{s.kind}</span>
              <span className="todo-text">{s.title || s.body.slice(0, 60)}</span>
              <button
                className="icon-x"
                title="Remove"
                onClick={async () => {
                  await api.deleteSample(s.id)
                  await load()
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <div className="dialog-actions">
          <button className="btn tiny" onClick={() => setAdding(true)}>
            + sample
          </button>
          <button className="btn solid tiny" disabled={!samples.length || voiceBusy} onClick={study}>
            {voiceBusy ? <span className="blink">studying…</span> : voice ? 'Re-study' : 'Study my voice'}
          </button>
        </div>
      </Win>

      <Dialog open={adding} title="add_sample.txt" onClose={() => setAdding(false)}>
        <form
          className="dialog-form"
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              await api.addSample(sample)
              fx.sound('capture')
              setSample({ kind: 'email', title: '', body: '' })
              setAdding(false)
              await load()
            } catch (err) {
              notify((err as Error).message, 'err')
            }
          }}
        >
          <div className="chips">
            {['email', 'essay', 'chat', 'other'].map((k) => (
              <button type="button" key={k} className={`chip ${sample.kind === k ? 'on' : ''}`} onClick={() => setSample({ ...sample, kind: k })}>
                {k}
              </button>
            ))}
          </div>
          <input className="ng-input" placeholder="title (optional)" value={sample.title} onChange={(e) => setSample({ ...sample, title: e.target.value })} />
          <textarea data-autofocus value={sample.body} onChange={(e) => setSample({ ...sample, body: e.target.value })} placeholder="paste something you wrote (40+ characters)" />
          <div className="dialog-actions">
            <button type="button" className="btn ghost" onClick={() => setAdding(false)}>
              Cancel
            </button>
            <button className="btn solid" disabled={sample.body.trim().length < 40}>
              Save
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
