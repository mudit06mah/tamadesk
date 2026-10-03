// Typed client for the tamadesk backend (/api, proxied to :6206 in dev).

export type Todo = { id: number; title: string; due_at: string | null; status: string; done_at: string | null; created_at: string }
export type LogEntry = { id: number; body: string; mood: number | null; created_at: string }
export type Reminder = { id: number; text: string; due_at: string; status: 'pending' | 'fired' | 'dismissed'; fired_at: string | null }
export type Activity = { kind: string; detail: string; xp: number; at: string }
export type Recap = { headline: string; recap: string; tomorrow: string[]; at?: string }
export type Sample = { id: number; kind: string; title: string; body: string; created_at: string }
export type Voice = { summary: string; traits: string[]; do: string[]; dont: string[]; phrases: string[] }
export type Draft = { id: number; ask: string; subject: string; body: string; created_at: string }
export type Question = { key: string; q: string; hint: string }
export type CompanionChoice = { species: string; label: string; blurb: string }

export type Progress = {
  xp: number
  level: number
  level_xp: number
  level_need: number
  streak_days: number
  xp_rules: Record<string, number>
}

export type State = {
  onboarded: boolean
  about: Record<string, string>
  companion: { species: string; name: string } | null
  has_voice: boolean
  samples: number
  brain: { kind: 'claude_code' | 'ollama'; model: string }
  day: { recap_hour: number; todo_goal: number }
  progress: Progress
  today: { open: Todo[]; done: Todo[]; log: LogEntry[] }
  reminders: Reminder[]
  recap: Recap | null
  activity: Activity[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* keep status text */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  state: () => call<State>('/state'),
  activity: (offset: number) => call<{ items: Activity[]; has_more: boolean }>(`/activity?offset=${offset}`),
  onboarding: () => call<{ questions: Question[]; companions: CompanionChoice[] }>('/onboarding'),
  newGame: (about: Record<string, string>, companion: { species: string; name: string }) =>
    post<{ ok: boolean }>('/onboarding', { about, companion }),
  capture: (text: string) =>
    post<{ kind: 'todo' | 'reminder' | 'log'; id: number; text: string; due_at: string | null; xp: number }>('/capture', { text }),
  todo: (id: number, action: 'done' | 'undo' | 'drop') => post<{ ok: boolean; xp: number }>(`/todos/${id}/${action}`),
  dismiss: (id: number) => post<{ ok: boolean; xp: number }>(`/reminders/${id}/dismiss`),
  log: (offset: number) => call<{ items: LogEntry[]; has_more: boolean }>(`/log?offset=${offset}`),
  samples: () => call<Sample[]>('/samples'),
  addSample: (s: { kind: string; title: string; body: string }) => post<{ id: number }>('/samples', s),
  deleteSample: (id: number) => call(`/samples/${id}`, { method: 'DELETE' }),
  voice: () => call<Voice | null>('/voice'),
  buildVoice: () => post<Voice>('/voice/build'),
  drafts: () => call<Draft[]>('/drafts'),
  draft: (ask: string) => post<Draft>('/drafts', { ask }),
  dropDraft: (id: number) => post(`/drafts/${id}/drop`),
  recap: () => post<Recap>('/recap'),
  brainCheck: () => call<{ ok: boolean; name: string; detail: string }>('/brain/check'),
  settings: (s: { brain_kind?: string; brain_model?: string; recap_hour?: number; todo_goal?: number }) =>
    call<{ ok: boolean }>('/settings', { method: 'PUT', body: JSON.stringify(s) }),
}

/** SQLite UTC 'YYYY-MM-DD HH:MM:SS' -> Date */
export const utc = (ts: string) => new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z')

export const clock = (ts: string) => utc(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })

export function dayLabel(ts: string): string {
  const d = utc(ts)
  const today = new Date()
  const y = new Date()
  y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'today'
  if (d.toDateString() === y.toDateString()) return 'yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

export function when(ts: string): string {
  const label = dayLabel(ts)
  return `${label === 'today' ? '' : label + ' '}${clock(ts)}`
}
