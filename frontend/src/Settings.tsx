// Settings: which brain, when the recap runs, the daily goal, and replaying the New Game setup.
import { useEffect, useState } from 'react'
import { api, type State } from './api'
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

  useEffect(() => {
    void api.brainCheck().then(setCheck)
  }, [])

  const save = async () => {
    try {
      await api.settings({ brain_kind: kind, brain_model: model, recap_hour: hour, todo_goal: goal })
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
      <Win title="brain.sys">
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
