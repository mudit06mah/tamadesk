// Typed client for the tamadesk backend (/api, proxied to :6206 in dev).

export type Todo = { id: number; title: string; due_at: string | null; status: string; done_at: string | null; created_at: string }
export type LogEntry = { id: number; body: string; mood: number | null; created_at: string }
export type Reminder = { id: number; text: string; due_at: string; status: 'pending' | 'fired' | 'dismissed'; fired_at: string | null }
export type Activity = { kind: string; detail: string; xp: number; at: string }
export type Recap = { headline: string; recap: string; tomorrow: string[]; at?: string }
export type Sample = { id: number; kind: string; title: string; body: string; created_at: string }
export type Voice = { summary: string; traits: string[]; do: string[]; dont: string[]; phrases: string[] }
export type MailDraft = {
  id: number
  subject: string
  body: string
  to_name: string | null
  to_email: string | null
  email_source: string | null
  email_sure: number
  item_id: number | null
  status: 'draft' | 'sent'
  kind: 'first' | 'followup' | 'reply'
  parent_id: number | null
  item_title: string | null
  item_module: string | null
  heard: InboxKind | null
  sent_at: string | null
  error: string | null
  created_at: string
}
export type InboxKind = 'reply' | 'interview' | 'applied' | 'rejected' | 'bounce' | 'update'
export type NextUp = {
  kind: InboxKind | 'followup' | 'drafts' | 'kept'
  id: number
  title: string
  detail: string
  snippet?: string
  draft_id?: number | null
  module?: string
  from?: string
  action: 'answer' | 'seen' | 'followup' | 'mail' | 'tab'
}
export type Stage = 'emailed' | 'applied' | 'replied' | 'interview' | 'rejected' | 'done'
export type VoiceView = { voice: Voice | null; rules: string[] }
export type MailBox = { items: MailDraft[]; ready: boolean; address: string; dry_run: boolean; daily_cap: number; sent_today: number }
export type Step = { name: string; input: Record<string, unknown> }
export type ChatMsg = { id?: number; role: 'user' | 'assistant'; text: string; steps?: Step[]; cost_usd?: number | null; tokens?: number | null }
export type AskEvent =
  | { type: 'chat'; chat_id: number }
  | { type: 'session'; session_id: string }
  | { type: 'text'; text: string }
  | ({ type: 'tool' } & Step)
  | { type: 'done'; text: string; error: boolean; cost_usd: number | null; tokens: number }
  | { type: 'error'; text: string }
export type Usage = { usd: number; tokens: number; runs: number; daily_usd: number; max_usd_per_ask: number; model: string; effort: string }
export type GhRow = { title: string; url: string; number: number; repo: string; updated_at: string; draft: boolean; review: string | null; checks: string | null; comments: number; author: string | null }
export type GhRepo = { repo: string; url: string; pushed_at: string; stars: number; open_issues: number }
export type GitHubStatus = { error?: string; login?: string; prs?: GhRow[]; issues?: GhRow[]; reviews?: GhRow[]; shipped?: GhRow[]; repos?: GhRepo[] }
export type MemHit = { day: string; kind: string; text: string; ref: string }
export type MemDay = { day: string; things: number; chats: { id: number; title: string }[]; summary: string | null; facts: string[] }
export type Note = { id: number; name: string; text: string; created_at: string }
export type Doc = { id: number; name: string; kind: string; chars: number; created_at: string }
export type Question = { key: string; q: string; hint: string }
export type CompanionChoice = { species: string; label: string; blurb: string }

export type Mod = {
  id: string
  name: string
  icon: string
  every: string
  sources: ({ type: string } & Record<string, unknown>)[]
  interests: string[]
  actions: ('save' | 'skip' | 'open' | 'summarize' | 'todo' | 'done' | 'draft')[]
  new: number
  saved: number
  run: { last_run: string | null; last_error: string | null; added: number | null } | null
  workflows: { label: string; prompt: string }[]
  notify?: boolean
}
export type Template = { key: string; title: string; blurb: string; icon: string; params: Record<string, { label: string; default?: string; from?: 'interests' }> }
export type ModItem = {
  id: number
  module: string
  source: string
  title: string
  subtitle: string | null
  body: string | null
  url: string | null
  score: number
  why: string[]
  status: string
  published_at: string | null
  stage: Stage | null
  data: {
    summary?: { summary: string; why_you: string }
    discussion?: string
    topics?: string[]
    apply_url?: string
    email?: string
    email_source?: string
    company?: string
  }
}

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
  mail_drafts: number
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
  newGame: (about: Record<string, string>, companion: { species: string; name: string }, modules: { template: string; params: Record<string, string> }[] = []) =>
    post<{ ok: boolean }>('/onboarding', { about, companion, modules }),
  setAbout: (key: string, value: string) => post<Record<string, string>>('/about', { key, value }),
  modules: () => call<Mod[]>('/modules'),
  templates: () => call<Template[]>('/templates'),
  createModule: (template: string, params: Record<string, string>) => post<Mod>('/modules', { template, params }),
  moduleYaml: (id: string) => call<{ yaml: string }>(`/modules/${id}/yaml`),
  saveModuleYaml: (id: string, yaml: string) => call<Mod>(`/modules/${id}`, { method: 'PUT', body: JSON.stringify({ yaml }) }),
  deleteModule: (id: string) => call(`/modules/${id}`, { method: 'DELETE' }),
  runModule: (id: string) => post(`/modules/${id}/run`),
  dismissError: (id: string) => post(`/modules/${id}/dismiss`),
  items: (id: string, status: string, offset = 0) => call<{ items: ModItem[]; has_more: boolean }>(`/modules/${id}/items?status=${status}&offset=${offset}`),
  act: (itemId: number, action: 'save' | 'skip' | 'done' | 'undo', reason = '') => post<{ status: string; xp: number }>(`/items/${itemId}/${action}`, { reason }),
  itemTodo: (itemId: number) => post<{ todo_id: number }>(`/items/${itemId}/todo`),
  summarize: (itemId: number) => post<{ summary: string; why_you: string }>(`/items/${itemId}/summarize`),
  capture: (text: string) =>
    post<{ kind: 'todo' | 'reminder' | 'log'; id: number; text: string; due_at: string | null; xp: number; no_time: boolean }>('/capture', { text }),
  todo: (id: number, action: 'done' | 'undo' | 'drop') => post<{ ok: boolean; xp: number }>(`/todos/${id}/${action}`),
  dismiss: (id: number) => post<{ ok: boolean; xp: number }>(`/reminders/${id}/dismiss`),
  log: (offset: number) => call<{ items: LogEntry[]; has_more: boolean }>(`/log?offset=${offset}`),
  samples: () => call<Sample[]>('/samples'),
  addSample: (s: { kind: string; title: string; body: string }) => post<{ id: number }>('/samples', s),
  deleteSample: (id: number) => call(`/samples/${id}`, { method: 'DELETE' }),
  voice: () => call<VoiceView>('/voice'),
  editVoice: (v: Partial<Voice> & { rules?: string[] }) => call<VoiceView>('/voice', { method: 'PUT', body: JSON.stringify(v) }),
  buildVoice: () => post<Voice>('/voice/build'),
  mail: (status: 'draft' | 'sent') => call<MailBox>(`/mail?status=${status}`),
  newMail: (d: Partial<MailDraft>) => post<{ id: number }>('/mail', d),
  editMail: (id: number, d: { subject: string; body: string; to_name: string; to_email: string }) =>
    call(`/mail/${id}`, { method: 'PATCH', body: JSON.stringify(d) }),
  sendMail: (id: number, verified: boolean) => post<{ dry_run: boolean; to: string }>(`/mail/${id}/send`, { verified }),
  dropMail: (id: number) => post(`/mail/${id}/drop`),
  redraftMail: (id: number, note: string) => post<{ subject: string; body: string }>(`/mail/${id}/redraft`, { note }),
  followup: (id: number) => post<{ id: number }>(`/mail/${id}/followup`),
  noFollowup: (id: number) => post(`/mail/${id}/no-followup`),
  inboxCheck: () => post<{ found: number }>('/mail/inbox/check'),
  inboxDone: (id: number) => post(`/mail/inbox/${id}/done`),
  next: () => call<NextUp[]>('/next'),
  itemStage: (id: number, stage: Stage) => post<{ changed: boolean }>(`/items/${id}/stage`, { stage }),
  renameModule: (id: string, name: string) => call<Mod>(`/modules/${id}/name`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  mailSetup: (b: { address: string; from_name: string; app_password: string; dry_run: boolean; daily_cap: number }) =>
    call<{ ok: boolean; ready: boolean }>('/mail/setup', { method: 'PUT', body: JSON.stringify(b) }),
  stopAsk: (chatId: number) => post<{ stopped: boolean }>(`/ask/${chatId}/stop`),
  chats: () => call<{ id: number; title: string; updated_at: string }[]>('/chats'),
  chat: (id: number) => call<ChatMsg[]>(`/chats/${id}`),
  usage: () => call<Usage>('/usage'),
  memorySearch: (q: string) => call<MemHit[]>(`/memory/search?q=${encodeURIComponent(q)}`),
  memoryDays: (offset = 0) => call<{ days: MemDay[]; pending: string[] }>(`/memory/days?offset=${offset}`),
  memoryDay: (day: string) => call<{ day: string; summary: string | null; facts: string[]; raw: string }>(`/memory/day/${day}`),
  memoryDigest: () => post('/memory/digest'),
  github: (refresh = false) => call<GitHubStatus>(`/github${refresh ? '?refresh=true' : ''}`),
  docs: () => call<Doc[]>('/docs'),
  addDoc: (name: string, kind: string, data_b64: string) => post<{ id: number }>('/docs', { name, kind, data_b64 }),
  deleteDoc: (id: number) => call(`/docs/${id}`, { method: 'DELETE' }),
  notes: () => call<Note[]>('/notes'),
  saveNote: (id: number, name: string, text: string) => call(`/notes/${id}`, { method: 'PUT', body: JSON.stringify({ name, text }) }),
  recap: () => post<Recap>('/recap'),
  brainCheck: () => call<{ ok: boolean; name: string; detail: string }>('/brain/check'),
  settings: (s: { brain_kind?: string; brain_model?: string; recap_hour?: number; todo_goal?: number; assistant_model?: string; assistant_effort?: string; max_usd_per_ask?: number; daily_usd?: number }) =>
    call<{ ok: boolean }>('/settings', { method: 'PUT', body: JSON.stringify(s) }),
}

/** Ask the assistant; calls onEvent for each streamed step. Resolves when the run ends. */
export async function ask(text: string, chatId: number | null, onEvent: (e: AskEvent) => void): Promise<void> {
  const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, chat_id: chatId }) })
  if (!r.ok || !r.body) {
    const j = await r.json().catch(() => ({}))
    throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const l of lines) if (l.trim()) onEvent(JSON.parse(l) as AskEvent)
  }
}

/** Open the Ask box from anywhere (e.g. a lead's "draft" button), optionally sending right away. */
export const askBolt = (text: string, send = false, chat?: number) =>
  window.dispatchEvent(new CustomEvent('tamadesk:ask', { detail: { text, send, chat } }))

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
