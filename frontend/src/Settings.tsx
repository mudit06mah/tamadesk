// Settings: which brain, your day (wake to bed, recap at bedtime), the daily goal, the calendar, and replaying the New Game setup.
import { useEffect, useState } from 'react'
import { api, pad2, when, type CalendarStatus, type Question, type State, type Usage } from './api'
import { DocsPanel } from './Docs'
import { ThemePicker } from './ThemePicker'
import { useFx } from './fx/Fx'
import { setSoundPack, soundPack, type Pack } from './fx/sound'
import { DayTimes, Win } from './ui'
import type { Toast } from './util'

const MODELS = { claude_code: ['sonnet', 'opus', 'haiku'], ollama: ['qwen3:8b', 'llama3.1:8b', 'gemma3:12b'] }

export function Settings({
  state: s,
  refresh,
  notify,
  replay,
  theme,
  setTheme,
}: {
  state: State
  refresh: () => Promise<void>
  notify: (t: string, k?: Toast['kind']) => void
  replay: () => void
  theme: string
  setTheme: (t: string) => void
}) {
  const fx = useFx()
  const [kind, setKind] = useState(s.brain.kind)
  const [model, setModel] = useState(s.brain.model)
  const [day, setDay] = useState({ wake: s.day.wake, bed: s.day.bed })
  const [goal, setGoal] = useState(s.day.todo_goal)
  const [quiet, setQuiet] = useState({ start: s.day.quiet_start ?? -1, end: s.day.quiet_end ?? 8 })
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null)
  const [use, setUse] = useState<Usage | null>(null)
  const [questions, setQuestions] = useState<Question[]>([])
  const [about, setAbout] = useState(s.about)
  const [ai, setAi] = useState({ model: 'sonnet', effort: 'medium', per: 0.5, daily: 3 })

  useEffect(() => {
    void api.brainCheck().then(setCheck)
    void api.onboarding().then((o) => setQuestions(o.questions))
    void api.usage().then((u) => {
      setUse(u)
      setAi({ model: u.model, effort: u.effort, per: u.max_usd_per_ask, daily: u.daily_usd })
    })
  }, [])

  const save = async () => {
    try {
      await api.settings({ quiet_start: quiet.start, quiet_end: quiet.end, brain_kind: kind, brain_model: model, wake: day.wake, bed: day.bed, todo_goal: goal, assistant_model: ai.model, assistant_effort: ai.effort, max_usd_per_ask: ai.per, daily_usd: ai.daily })
      fx.sound('stamp')
      notify('Saved.')
      setCheck(await api.brainCheck())
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  return (
    <div className="settings">
      <Win title="you.txt">
        <p className="muted small">Everything your companion knows about you. Edit anytime; it's used in every ask.</p>
        {questions.map((q) => (
          <label key={q.key} className="field">
            <span>{q.q}</span>
            <textarea
              rows={2}
              value={about[q.key] ?? ''}
              placeholder={q.hint}
              onChange={(e) => setAbout({ ...about, [q.key]: e.target.value })}
              onBlur={async (e) => {
                if ((s.about[q.key] ?? '') === e.target.value) return
                await api.setAbout(q.key, e.target.value)
                fx.sound('tap')
                await refresh()
              }}
            />
          </label>
        ))}
        <DocsPanel notify={notify} />
      </Win>

      <Win title="theme.cfg">
        <ThemePicker
          value={theme}
          onPick={(t) => {
            fx.sound('sparkle')
            setTheme(t)
          }}
        />
        <SoundPicker />
      </Win>

      <Win title="assistant.sys">
        <p className="muted small">
          Everything you ask runs on your own Claude Code. Costs are what the same work would cost on the API, a fair way to see how
          much you use. Today: ≈ ${use?.usd.toFixed(2) ?? '0.00'} over {use?.runs ?? 0} runs, {Math.round((use?.tokens ?? 0) / 1000)}k tokens.
        </p>
        <div className="chips">
          {['haiku', 'sonnet', 'opus'].map((m) => (
            <button key={m} className={`chip ${ai.model === m ? 'on' : ''}`} onClick={() => setAi({ ...ai, model: m })}>
              {m === 'haiku' ? 'haiku (cheapest)' : m === 'opus' ? 'opus (smartest)' : 'sonnet (balanced)'}
            </button>
          ))}
        </div>
        <div className="chips">
          {['low', 'medium', 'high'].map((e) => (
            <button key={e} className={`chip ${ai.effort === e ? 'on' : ''}`} onClick={() => setAi({ ...ai, effort: e })}>
              {e} effort
            </button>
          ))}
        </div>
        <label className="field">
          <span>max per ask ($)</span>
          <input type="number" step="0.05" min={0.05} max={10} value={ai.per} onChange={(e) => setAi({ ...ai, per: Number(e.target.value) })} />
        </label>
        <label className="field">
          <span>daily budget ($)</span>
          <input type="number" step="0.5" min={0.5} max={100} value={ai.daily} onChange={(e) => setAi({ ...ai, daily: Number(e.target.value) })} />
        </label>
      </Win>

      <Win title="brain.sys">
        <p className="muted small">Used for the small background jobs (summaries, recap, voice study).</p>
        <div className="chips">
          {(['claude_code', 'ollama'] as const).map((k) => (
            <button
              key={k}
              className={`chip ${kind === k ? 'on' : ''}`}
              onClick={() => {
                setKind(k)
                setModel(MODELS[k][0])
              }}
            >
              {k === 'claude_code' ? 'Claude Code (your login)' : 'Ollama (local)'}
            </button>
          ))}
        </div>
        <label className="field">
          <span>model</span>
          <input list="models" value={model} onChange={(e) => setModel(e.target.value)} />
          <datalist id="models">
            {MODELS[kind].map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        <p className={`brain-status ${check ? (check.ok ? 'ok' : 'bad') : ''}`}>{check ? `${check.ok ? '✓' : '✗'} ${check.detail}` : 'checking…'}</p>
      </Win>

      <Win title="day.cfg">
        <DayTimes wake={day.wake} bed={day.bed} onChange={(wake, bed) => setDay({ wake, bed })} />
        <div className="field-row">
          <label className="field">
            <span>quiet hours from (only reminders and meetings ring)</span>
            <select value={quiet.start} onChange={(e) => setQuiet({ ...quiet, start: Number(e.target.value) })}>
              <option value={-1}>off</option>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {pad2(h)}:00
                </option>
              ))}
            </select>
          </label>
          {quiet.start >= 0 && (
            <label className="field">
              <span>until</span>
              <select value={quiet.end} onChange={(e) => setQuiet({ ...quiet, end: Number(e.target.value) })}>
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {pad2(h)}:00
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <label className="field">
          <span>todos for a "good day"</span>
          <input type="number" min={1} max={20} value={goal} onChange={(e) => setGoal(Number(e.target.value))} />
        </label>
      </Win>

      <CalendarPanel notify={notify} />

      <div className="dialog-actions">
        <button className="btn ghost" onClick={replay}>
          Replay New Game (edit answers, companion)
        </button>
        <button className="btn solid" onClick={save}>
          Save settings
        </button>
      </div>
    </div>
  )
}

/** Meetings on Today: invites read from the mail tamadesk already checks, plus an optional private
 * iCal address. The address is a password to your calendar, so it's write-only here. Saves itself. */
function CalendarPanel({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const [cal, setCal] = useState<CalendarStatus | null>(null)
  const [feed, setFeed] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    void api.calendar().then(setCal)
  }, [])
  const put = async (b: Parameters<typeof api.calendarSetup>[0], msg?: string) => {
    setBusy(true)
    try {
      setCal(await api.calendarSetup(b))
      fx.sound('stamp')
      if (msg) notify(msg)
    } catch (e) {
      notify((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }
  if (!cal) return null
  return (
    <Win title="calendar.ics">
      <p className="muted small">
        Meetings show up on Today with a ring before each one. Nothing is sent anywhere: tamadesk only reads.
      </p>
      <label className="check-row">
        <input type="checkbox" checked={cal.from_mail} onChange={(e) => put({ from_mail: e.target.checked })} /> Read calendar invites in my mail
        (only the event: title, time, link, organizer; never the email itself)
      </label>
      <label className="field">
        <span>ring before a meeting (minutes)</span>
        <input type="number" min={0} max={120} value={cal.remind_min} onChange={(e) => setCal({ ...cal, remind_min: Number(e.target.value) })} onBlur={() => put({ remind_min: cal.remind_min })} />
      </label>
      <form
        className="field"
        onSubmit={(e) => {
          e.preventDefault()
          if (feed.trim()) void put({ feed: feed.trim() }, 'Saved. Reading your calendar now.').then(() => setFeed(''))
        }}
      >
        <span>
          private calendar address (iCal), optional ·{' '}
          <a href="https://support.google.com/calendar/answer/37648#zippy=%2Cget-your-calendar-view-only" target="_blank" rel="noreferrer">
            where to find it
          </a>
        </span>
        <div className="rule-add">
          <input type="password" autoComplete="off" value={feed} onChange={(e) => setFeed(e.target.value)} placeholder={cal.feed_set ? 'saved (paste a new one to replace it)' : 'https://calendar.google.com/calendar/ical/…/basic.ics'} />
          <button className="btn tiny" disabled={busy || !feed.trim()}>
            save
          </button>
        </div>
      </form>
      <DeadlineFeeds cal={cal} put={put} />
      {cal.feed_set && (
        <div className="item-acts">
          <span className="muted small">{cal.error ? <span className="bad-text">{cal.error}</span> : cal.synced ? `read ${when(cal.synced)} · ${cal.events} events` : 'not read yet'}</span>
          <span className="grow" />
          <button
            className="btn tiny ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                const r = await api.calendarSync()
                setCal(r)
                fx.sound(r.error ? 'drop' : 'tap')
              } finally {
                setBusy(false)
              }
            }}
          >
            ↻ read now
          </button>
          <button className="btn tiny ghost" disabled={busy} onClick={() => put({ feed: '' }, 'Calendar address removed.')}>
            remove
          </button>
        </div>
      )}
    </Win>
  )
}

/** Calendars whose events are deadlines (school assignments from Canvas or Moodle, a release plan):
 * each one becomes a todo with that deadline, tagged with the feed's name, and follows the feed. */
function DeadlineFeeds({ cal, put }: { cal: CalendarStatus; put: (b: Parameters<typeof api.calendarSetup>[0], msg?: string) => Promise<void> }) {
  const [f, setF] = useState({ url: '', tag: '' })
  return (
    <div className="field">
      <span>deadline calendars: each event becomes a todo due then (school assignments, a release plan…)</span>
      <ul className="voice-points rules">
        {cal.deadline_feeds.map((d) => (
          <li key={d.tag}>
            <span>
              #{d.tag} <span className="muted small">· {d.host}</span>
            </span>
            <button className="icon-x" title="Remove" onClick={() => put({ remove_deadline_feed: d.tag }, `#${d.tag} removed.`)}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <form
        className="rule-add"
        onSubmit={(e) => {
          e.preventDefault()
          if (f.url.trim() && f.tag.trim()) void put({ add_deadline_feed: f }, `#${f.tag} added. Reading it now.`).then(() => setF({ url: '', tag: '' }))
        }}
      >
        <input value={f.tag} onChange={(e) => setF({ ...f, tag: e.target.value })} placeholder="name (e.g. school)" style={{ maxWidth: 140 }} />
        <input type="password" autoComplete="off" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="calendar address (iCal)" />
        <button className="btn tiny" disabled={!f.url.trim() || !f.tag.trim()}>
          add
        </button>
      </form>
    </div>
  )
}

const PACKS: [Pack, string, string][] = [
  ['cozy', 'cozy', 'little instruments: a wooden marimba, glass bells, soft thumps and air'],
  ['classic', 'classic', 'the first sounds: plain soft blips'],
]

/** Which sounds the desk makes. Picking one plays a sample of it. */
function SoundPicker() {
  const fx = useFx()
  const [pack, setPack] = useState(soundPack())
  return (
    <div className="sound-pick">
      <div className="field-label">sounds</div>
      <div className="chips">
        {PACKS.map(([key, label, about]) => (
          <button
            key={key}
            className={`chip ${pack === key ? 'on' : ''}`}
            title={about}
            onClick={() => {
              setSoundPack(key)
              setPack(key)
              fx.sound('check')
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
