// Mail: drafts your companion wrote (or you started), ready to check and send through your Gmail.
// Pairs with lead tabs: a lead's "email them" button asks the companion to research it and write here.
// Not right? "Redraft" takes your note; notes are remembered as writing rules for every future draft.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, when, type MailBox, type MailDraft, type Sample, type Voice } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { DocsPanel } from './Docs'
import { SendIcon } from './icons'
import { Dialog, Win } from './ui'
import type { Toast } from './util'

type Props = { notify: (t: string, k?: Toast['kind']) => void; onChange: () => void }

export function Mail({ notify, onChange }: Props) {
  const fx = useFx()
  const buddy = useCompanion()
  const [tab, setTab] = useState<'draft' | 'sent'>('draft')
  const [box, setBox] = useState<MailBox | null>(null)
  const [setup, setSetup] = useState(false)

  const load = useCallback(async () => setBox(await api.mail(tab)), [tab])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on tab switch
    void load()
  }, [load])

  return (
    <div className="mail-grid">
      <div className="mail-main">
        <header className="screen-head">
          <h1>Mail</h1>
          <div className="mod-tools">
            <div className="seg-tabs" role="tablist">
              {(['draft', 'sent'] as const).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
                  {t === 'draft' ? 'drafts' : 'sent'}
                  {tab === t && <motion.span layoutId="segtab-mail" className="seg-tab-on" />}
                </button>
              ))}
            </div>
            {box && (
              <button className={`btn tiny ${box.ready ? 'ghost' : 'solid'}`} onClick={() => setSetup(true)}>
                {box.ready ? `${box.dry_run ? 'dry run · ' : ''}${box.sent_today}/${box.daily_cap} today` : 'Connect Gmail'}
              </button>
            )}
          </div>
        </header>

        <div className="mail-ask">
          <span className="muted">Ask {buddy.name}:</span>
          {['Email the leads I kept about what I offer', 'Write a short thank-you note to…', 'Follow up with…'].map((t) => (
            <motion.button key={t} className="chip" whileTap={{ scale: 0.94 }} onClick={() => askBolt(t.endsWith('…') ? t.slice(0, -1) : t)}>
              {t}
            </motion.button>
          ))}
        </div>

        {!box ? (
          <p className="loading">opening mail…</p>
        ) : box.items.length === 0 ? (
          <Win title="mail.empty" className="empty-win">
            <p className="muted">
              {tab === 'draft' ? `No drafts. Ask ${buddy.name} to write one, or press “email them” on a lead.` : 'Nothing sent yet.'}
            </p>
          </Win>
        ) : (
          <ul className="feed">
            <AnimatePresence initial={false}>
              {box.items.map((d) => (
                <motion.li key={d.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 80, rotate: 3 }}>
                  {tab === 'draft' ? (
                    <DraftCard
                      d={d}
                      ready={box.ready}
                      notify={notify}
                      onGone={() => {
                        void load()
                        onChange()
                      }}
                      onSetup={() => setSetup(true)}
                    />
                  ) : (
                    <div className="item sent-row">
                      <b>{d.subject}</b>
                      <span className="muted small">
                        to {d.to_name || d.to_email} · {d.sent_at ? when(d.sent_at) : ''}
                      </span>
                    </div>
                  )}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>

      <div className="mail-side">
        <VoicePanel notify={notify} />
        <Win title="context.dir">
          <DocsPanel notify={notify} />
        </Win>
      </div>
      <SetupDialog
        open={setup}
        box={box}
        onClose={() => setSetup(false)}
        onSaved={() => {
          setSetup(false)
          fx.sound('stamp')
          void load()
        }}
        notify={notify}
      />
    </div>
  )
}

function DraftCard({ d, ready, notify, onGone, onSetup }: { d: MailDraft; ready: boolean; notify: Props['notify']; onGone: () => void; onSetup: () => void }) {
  const fx = useFx()
  const [f, setF] = useState({ subject: d.subject, body: d.body, to_name: d.to_name ?? '', to_email: d.to_email ?? '' })
  const [checked, setChecked] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [rewriting, setRewriting] = useState(false)
  const unsure = !d.email_sure && f.to_email === (d.to_email ?? '')
  const save = () => api.editMail(d.id, f).catch((e: Error) => notify(e.message, 'err'))
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value })

  const send = async (el: Element) => {
    if (!ready) return onSetup()
    try {
      await save()
      const r = await api.sendMail(d.id, checked)
      fx.sound('send')
      fx.burstAt(el, true)
      notify(r.dry_run ? `Dry run: sent to you (${r.to})` : `Sent to ${r.to}`)
      onGone()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  const redraft = async () => {
    if (!note?.trim()) return
    setRewriting(true)
    try {
      await save()
      const r = await api.redraftMail(d.id, note)
      setF((x) => ({ ...x, subject: r.subject, body: r.body }))
      setNote(null)
      fx.sound('check')
      notify('Rewritten. That note is now a writing rule for every draft.')
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setRewriting(false)
    }
  }

  return (
    <div className={`item draft-card ${rewriting ? 'rewriting' : ''}`}>
      <div className="draft-to">
        <span className="to-label">TO</span>
        <input value={f.to_name} onChange={set('to_name')} onBlur={save} placeholder="name" />
        <input className={unsure ? 'unsure' : ''} value={f.to_email} onChange={set('to_email')} onBlur={save} placeholder="email" />
      </div>
      {unsure && (
        <label className="unsure-box">
          <span>
            <b>UNSURE:</b> this address was guessed, not published anywhere. A bounce hurts your Gmail reputation.
          </span>
          <span>
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> I checked this address myself
          </span>
        </label>
      )}
      {d.email_source && !unsure && (
        <span className="muted small">
          address found at{' '}
          <a href={d.email_source} target="_blank" rel="noreferrer">
            {d.email_source.replace(/^https?:\/\/(www\.)?/, '').slice(0, 50)}
          </a>
        </span>
      )}
      <input className="draft-subject" value={f.subject} onChange={set('subject')} onBlur={save} placeholder="subject" />
      <textarea className="draft-body" value={f.body} onChange={set('body')} onBlur={save} rows={8} />
      {d.error && <p className="bad-text small">{d.error}</p>}
      <AnimatePresence>
        {note !== null && (
          <motion.form
            className="redraft"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onSubmit={(e) => {
              e.preventDefault()
              void redraft()
            }}
          >
            <input
              autoFocus
              value={note}
              disabled={rewriting}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setNote(null)}
              placeholder="what should change? e.g. shorter, less formal, mention my resume, drop the second paragraph"
            />
            <button className="btn tiny solid" disabled={rewriting || !note.trim()}>
              {rewriting ? <span className="blink">rewriting…</span> : 'Redraft'}
            </button>
          </motion.form>
        )}
      </AnimatePresence>
      <div className="item-acts">
        <motion.button className="btn tiny ghost" whileTap={{ scale: 0.9 }} onClick={async () => (await api.dropMail(d.id), fx.sound('drop'), onGone())}>
          toss
        </motion.button>
        <motion.button className="btn tiny" whileTap={{ scale: 0.9 }} disabled={rewriting} onClick={() => setNote(note === null ? '' : null)}>
          ✎ redraft
        </motion.button>
        <span className="grow" />
        <motion.button className="btn solid send-btn" whileTap={{ scale: 0.9, rotate: -3 }} disabled={(unsure && !checked) || rewriting} onClick={(e) => send(e.currentTarget)}>
          {ready ? (
            <>
              Send <SendIcon />
            </>
          ) : (
            'Connect Gmail to send'
          )}
        </motion.button>
      </div>
    </div>
  )
}

function SetupDialog({ open, box, onClose, onSaved, notify }: { open: boolean; box: MailBox | null; onClose: () => void; onSaved: () => void; notify: Props['notify'] }) {
  const [f, setF] = useState({ address: '', from_name: '', app_password: '', dry_run: true, daily_cap: 20 })
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start from the saved settings when opened
    if (open && box) setF((x) => ({ ...x, address: box.address, dry_run: box.dry_run, daily_cap: box.daily_cap, app_password: '' }))
  }, [open, box])
  return (
    <Dialog open={open} title="gmail.cfg" onClose={onClose}>
      <form
        className="dialog-form"
        onSubmit={async (e) => {
          e.preventDefault()
          try {
            await api.mailSetup(f)
            onSaved()
          } catch (err) {
            notify((err as Error).message, 'err')
          }
        }}
      >
        <p className="dialog-lead">
          Sends go through your Gmail with an{' '}
          <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">
            app password
          </a>{' '}
          (needs 2-step verification). It's stored only on this computer.
        </p>
        <label className="field">
          <span>Gmail address</span>
          <input data-autofocus value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder="you@gmail.com" />
        </label>
        <label className="field">
          <span>Your name (shown to recipients)</span>
          <input value={f.from_name} onChange={(e) => setF({ ...f, from_name: e.target.value })} />
        </label>
        <label className="field">
          <span>App password {box?.ready ? '(saved; leave blank to keep)' : ''}</span>
          <input type="password" value={f.app_password} onChange={(e) => setF({ ...f, app_password: e.target.value })} placeholder="xxxx xxxx xxxx xxxx" />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={f.dry_run} onChange={(e) => setF({ ...f, dry_run: e.target.checked })} /> Dry run: send everything to myself first
        </label>
        <label className="field">
          <span>Max emails per day</span>
          <input type="number" min={1} max={200} value={f.daily_cap} onChange={(e) => setF({ ...f, daily_cap: Number(e.target.value) })} />
        </label>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn solid" disabled={!f.address.includes('@')}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  )
}

/** The writing samples the voice profile is built from (moved here from the old Write tab). */
function VoicePanel({ notify }: { notify: Props['notify'] }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [samples, setSamples] = useState<Sample[]>([])
  const [voice, setVoice] = useState<Voice | null>(null)
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [sample, setSample] = useState({ kind: 'email', title: '', body: '' })

  const load = async () => {
    const [s, v] = await Promise.all([api.samples(), api.voice()])
    setSamples(s)
    setVoice(v)
  }
  useEffect(() => {
    void load()
  }, [])

  return (
    <Win title="voice.cfg">
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
        </div>
      ) : (
        <p className="muted">Add 2 or 3 things you wrote and let {buddy.name} study them, so emails sound like you.</p>
      )}
      <div className="field-label">samples ({samples.length})</div>
      <ul className="sample-list">
        {samples.map((s) => (
          <li key={s.id}>
            <span className="tag">{s.kind}</span>
            <span className="todo-text">{s.title || s.body.slice(0, 50)}</span>
            <button className="icon-x" title="Remove" onClick={async () => (await api.deleteSample(s.id), void load())}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <div className="item-acts">
        <button className="btn tiny" onClick={() => setAdding(true)}>
          + sample
        </button>
        <button
          className="btn solid tiny"
          disabled={!samples.length || busy}
          onClick={async () => {
            setBusy(true)
            try {
              setVoice(await api.buildVoice())
              fx.sound('levelup')
            } catch (e) {
              notify((e as Error).message, 'err')
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? <span className="blink">studying…</span> : voice ? 'Re-study' : 'Study my voice'}
        </button>
      </div>
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
    </Win>
  )
}
