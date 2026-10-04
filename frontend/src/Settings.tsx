// Settings: which brain, when the recap runs, the daily goal, and replaying the New Game setup.
import { useEffect, useState } from 'react'
import { api, type State, type Usage } from './api'
import { useFx } from './fx/Fx'
import { Win } from './ui'
import type { Toast } from './util'

const MODELS = { claude_code: ['sonnet', 'opus', 'haiku'], ollama: ['qwen3:8b', 'llama3.1:8b', 'gemma3:12b'] }

export function Settings({
  state: s,
  refresh,
  notify,
  replay,
}: {
  state: State
  refresh: () => Promise<void>
  notify: (t: string, k?: Toast['kind']) => void
  replay: () => void
}) {
  const fx = useFx()
  const [kind, setKind] = useState(s.brain.kind)
  const [model, setModel] = useState(s.brain.model)
  const [hour, setHour] = useState(s.day.recap_hour)
  const [goal, setGoal] = useState(s.day.todo_goal)
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null)
  const [use, setUse] = useState<Usage | null>(null)
  const [ai, setAi] = useState({ model: 'sonnet', effort: 'medium', per: 0.5, daily: 3 })

  useEffect(() => {
    void api.brainCheck().then(setCheck)
    void api.usage().then((u) => {
      setUse(u)
      setAi({ model: u.model, effort: u.effort, per: u.max_usd_per_ask, daily: u.daily_usd })
    })
  }, [])

  const save = async () => {
    try {
      await api.settings({ brain_kind: kind, brain_model: model, recap_hour: hour, todo_goal: goal, assistant_model: ai.model, assistant_effort: ai.effort, max_usd_per_ask: ai.per, daily_usd: ai.daily })
      fx.sound('stamp')
      notify('Saved. Restart tamadesk for a new recap time to take effect.')
      setCheck(await api.brainCheck())
      await refresh()
    } catch (e) {
      notify((e as Error).message, 'err')
    }
  }

  return (
    <div className="settings">
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
        <label className="field">
          <span>evening recap at</span>
          <select value={hour} onChange={(e) => setHour(Number(e.target.value))}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, '0')}:00
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>todos for a "good day"</span>
          <input type="number" min={1} max={20} value={goal} onChange={(e) => setGoal(Number(e.target.value))} />
        </label>
      </Win>

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
