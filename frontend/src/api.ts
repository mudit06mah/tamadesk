// Typed client for the tamadesk backend (/api, proxied to :6206 in dev).

type Todo = { id: number; title: string; due_at: string | null; status: string; done_at: string | null; created_at: string }
export type LogEntry = { id: number; body: string; mood: number | null; created_at: string }
type Reminder = { id: number; text: string; due_at: string; status: 'pending' | 'fired' | 'dismissed'; fired_at: string | null }
export type Activity = { kind: string; detail: string; xp: number; at: string }
/** Tomorrow's picks point at open todos (todo_id) so "+ todo" never duplicates one; status is where it stands now. */
type RecapPick = { text: string; todo_id: number | null; status?: string | null }
export type Recap = { headline: string; recap: string; tomorrow: (RecapPick | string)[]; so_far?: boolean; at?: string }
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
  suggestions?: Suggestion[]
  can_ask?: boolean
}
/** Something on a mail or draft only the user can do well. `required` ones gate sending. */
export type Suggestion = { id: number; rule: string; text: string; data: { due?: string; source?: string; company?: string }; required: boolean }
export type InboxKind = 'reply' | 'interview' | 'applied' | 'rejected' | 'bounce' | 'update'
export type NextUp = {
  kind: InboxKind | 'followup' | 'draft' | 'kept' | 'github'
  id: number
  key?: string
  url?: string
  title: string
  detail: string
  snippet?: string
  draft_id?: number | null
  module?: string
  from?: string
  action: 'answer' | 'seen' | 'followup' | 'mail' | 'tab' | 'open'
}
/** One row of the day: a meeting, reminder, todo, something done, or something waiting on you. */
export type DayEntry = {
  kind: 'todo' | 'reminder' | 'log' | 'did' | 'meeting' | 'recap' | 'next' | 'promise'
  key: string
  title: string
  at: string | null
  end: string | null
  detail: string
  link: string
  state: string
  ref: { todo?: number; reminder?: number; event?: number; item?: number | null; suggestion?: number; cal_key?: string }
  next?: NextUp
  meet_url?: string | null
  all_day?: boolean
  recap?: Recap
  suggestions?: Suggestion[]
  can_ask?: boolean
  target?: 'draft' | 'inbox'
  due?: string | null
  repeat?: string // 'weekdays', 'every Mon, Thu'
  chain?: number // habit chain: on-time completions in a row
  tags?: string[]
  waiting?: boolean
  who?: string | null
}
export type DayView = {
  date: string
  is_today: boolean
  needs_you: DayEntry[]
  timeline: DayEntry[]
  anytime: DayEntry[]
  progress: number
  pressure?: { id: number; stage: number; text: string } | null
  focus?: Focus | null
}
export type CalendarStatus = { feed_set: boolean; from_mail: boolean; remind_min: number; synced: string | null; error: string | null; events: number; deadline_feeds: { tag: string; host: string }[] }
export type Stage = 'emailed' | 'applied' | 'replied' | 'interview' | 'rejected' | 'done'
export type VoiceView = { voice: Voice | null; rules: string[] }
export type MailBox = { items: MailDraft[]; ready: boolean; address: string; provider: string; providers: string[]; dry_run: boolean; daily_cap: number; sent_today: number }
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
type GhRepo = { repo: string; url: string; pushed_at: string; stars: number; open_issues: number }
export type GitHubStatus = { error?: string; login?: string; prs?: GhRow[]; issues?: GhRow[]; reviews?: GhRow[]; shipped?: GhRow[]; repos?: GhRepo[] }
export type MemHit = { day: string; kind: string; text: string; ref: string }
export type MemDay = { day: string; things: number; chats: { id: number; title: string }[]; summary: string | null; facts: string[] }
export type Note = { id: number; name: string; text: string; created_at: string }
export type Doc = { id: number; name: string; kind: string; chars: number; created_at: string }
/** The profile card (memory/profile.md): written from the resume in the background, then yours to edit. */
export type ProfileCard = { text: string; has_resume: boolean; state: 'none' | 'building' | 'ready' | 'error'; error?: string; at?: string }
export type Question = { key: string; q: string; hint: string; options?: string[]; core?: boolean }
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
  passed: number
  /** what bookmarks and passes taught the tab: words it now ranks up (more) and down (less) */
  taste: { more: string[]; less: string[] }
  /** feed: ranked by taste; steps: a path in order (a learning roadmap) */
  layout: 'feed' | 'steps'
  run: { last_run: string | null; last_error: string | null; added: number | null; dropped?: number | null; left_out?: string | null } | null
  boards?: number // company job boards this tab learned from search results
  fit?: { level: string | null; roles: string[]; avoid: string[]; min: number } | null
  workflows: { label: string; prompt: string }[]
  fresh_at?: string | null // newest unseen item: a sparkle on the tab until you look
  notify?: boolean
}
export type Template = { key: string; title: string; blurb: string; icon: string; params: Record<string, { label: string; default?: string; from?: string }> }
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
    thumb?: string // a video's (or playlist's) picture
    step?: number // a steps tab (roadmap): which step, and its topic
    topic?: string
    duration?: number // seconds
    views?: number
    discussion?: string
    topics?: string[]
    apply_url?: string
    email?: string
    email_source?: string
    company?: string
    fit?: { score: number; why: string[] }
    deadline?: string // e.g. a CFP's closing day: '+ todo' makes it due then
    live?: 'open' | 'closed' | 'unknown'
    closed_at?: string // a kept posting that stopped taking applications
    screen?: string // why it suits the user's preferences
    board?: string
  }
}

export type Focus = { id: number; tag: string; minutes: number; started_at: string; ends_at: string; status: string }
export type WeekCard = {
  kind: 'week'
  from: string
  to: string
  xp: number
  done: number
  on_time: number
  waiting_closed: number
  focus_minutes: number
  focus_by_tag: Record<string, number>
  best_chain: number
  sent: number
  moves: number
  active_days: number
  best_day: string | null
  top_tags: string[]
  title: string
  title_why: string
  highlights: string[]
  markdown: string
}
export type Review = { kind: 'standup' | 'brag'; markdown: string } | WeekCard
export type Captured = {
  kind: 'todo' | 'reminder' | 'log' | 'done' | 'move' | 'waiting' | 'meeting' | 'focus' | 'next'
  id: number | null
  text: string
  due_at: string | null
  xp: number
  no_time: boolean
  message: string
  chain?: number
  milestone?: boolean
}
type Progress = {
  xp: number
  level: number
  level_xp: number
  level_need: number
  streak_days: number
  freezes: number // a missed day spends one instead of the streak
  frozen: string[]
  xp_rules: Record<string, number>
}

export type State = {
  onboarded: boolean
  about: Record<string, string>
  companion: { species: string; name: string } | null
  has_voice: boolean
  samples: number
  mail_drafts: number
  needs_you: number
  brain: { kind: 'claude_code' | 'ollama'; model: string }
  /** the user's day: it runs wake to bed ('HH:MM'), and `today` is the day it is for them now (still
   * yesterday's date at 12:30am if they haven't slept) */
  day: { wake: string; bed: string; today: string; todo_goal: number; quiet_start: number | null; quiet_end: number | null }
  focus: Focus | null
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
  newGame: (about: Record<string, string>, companion: { species: string; name: string }, modules: { template: string; params: Record<string, string> }[] = [], day?: { wake: string; bed: string }) =>
    post<{ ok: boolean }>('/onboarding', { about, companion, modules, day }),
  setAbout: (key: string, value: string) => post<Record<string, string>>('/about', { key, value }),
  modules: () => call<Mod[]>('/modules'),
  templates: () => call<Template[]>('/templates'),
  createModule: (template: string, params: Record<string, string>) => post<Mod>('/modules', { template, params }),
  moduleYaml: (id: string) => call<{ yaml: string }>(`/modules/${id}/yaml`),
  saveModuleYaml: (id: string, yaml: string) => call<Mod>(`/modules/${id}`, { method: 'PUT', body: JSON.stringify({ yaml }) }),
  deleteModule: (id: string) => call(`/modules/${id}`, { method: 'DELETE' }),
  runModule: (id: string) => post(`/modules/${id}/run`),
  dismissError: (id: string) => post(`/modules/${id}/dismiss`),
  items: (id: string, status: string, offset = 0, limit = 30) => call<{ items: ModItem[]; has_more: boolean }>(`/modules/${id}/items?status=${status}&offset=${offset}&limit=${limit}`),
  act: (itemId: number, action: 'save' | 'skip' | 'done' | 'undo', reason = '') => post<{ status: string; xp: number }>(`/items/${itemId}/${action}`, { reason }),
  itemTodo: (itemId: number) => post<{ todo_id: number; due_at: string | null }>(`/items/${itemId}/todo`),
  summarize: (itemId: number) => post<{ summary: string; why_you: string }>(`/items/${itemId}/summarize`),
  capture: (text: string) => post<Captured>('/capture', { text }),
  todo: (id: number, action: 'done' | 'undo' | 'drop', stop = false) => post<{ ok: boolean; xp: number; chain?: number; milestone?: boolean }>(`/todos/${id}/${action}${stop ? '?stop=true' : ''}`),
  todoRepeat: (id: number, repeat: string | null) => call(`/todos/${id}/repeat`, { method: 'PUT', body: JSON.stringify({ repeat }) }),
  focusStart: (minutes: number, tag = '') => post<Focus>('/focus', { minutes, tag }),
  focusEnd: (action: 'stop' | 'finish') => post<{ xp: number; finished?: boolean; stopped?: boolean }>(`/focus/${action}`),
  review: (kind: 'standup' | 'week' | 'brag') => call<Review>(`/review/${kind}`),
  tips: () => call<string[]>('/tips'),
  boards: (moduleId: string) => call<{ board: string; found_from: string | null; added_at: string }[]>(`/modules/${moduleId}/boards`),
  forgetBoard: (moduleId: string, board: string) => call(`/modules/${moduleId}/boards/${encodeURIComponent(board)}`, { method: 'DELETE' }),
  setCompanion: (species: string) => post<{ species: string; name: string }>('/companion', { species }),
  seen: (kind: 'gh', key: string) => post('/seen', { kind, key }),
  promises: (cal_key: string, lines: string[]) => post<{ todos: number[] }>('/meetings/promises', { cal_key, lines }),
  newNote: (name: string, text: string) => post<{ id: number }>('/notes', { name, text }),
  todoDue: (id: number, when: string) => call<{ due_at: string | null }>(`/todos/${id}/due`, { method: 'PUT', body: JSON.stringify({ when }) }),
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
  restoreMail: (id: number) => post(`/mail/${id}/restore`),
  redraftMail: (id: number, note: string) => post<{ subject: string; body: string }>(`/mail/${id}/redraft`, { note }),
  followup: (id: number) => post<{ id: number }>(`/mail/${id}/followup`),
  noFollowup: (id: number) => post(`/mail/${id}/no-followup`),
  inboxCheck: () => post<{ found: number }>('/mail/inbox/check'),
  inboxDone: (id: number) => post(`/mail/inbox/${id}/done`),
  next: () => call<NextUp[]>('/next'),
  today: (day = '') => call<DayView>(`/today${day ? `?day=${day}` : ''}`),
  item: (id: number) => call<{ item: ModItem; actions: Mod['actions']; module: string }>(`/items/${id}`),
  draft: (id: number) => call<{ draft: MailDraft; ready: boolean }>(`/mail/${id}`),
  suggestion: (id: number, action: 'done' | 'undo' | 'dismiss' | 'remind') => post<{ xp?: number; reminder_at?: string }>(`/suggestions/${id}/${action}`),
  askTips: (target: 'draft' | 'inbox', id: number) => post<Suggestion[]>('/suggestions/ask', { target, id }),
  calendar: () => call<CalendarStatus>('/calendar'),
  calendarSetup: (b: { feed?: string; from_mail?: boolean; remind_min?: number; add_deadline_feed?: { url: string; tag: string }; remove_deadline_feed?: string }) =>
    call<CalendarStatus>('/calendar', { method: 'PUT', body: JSON.stringify(b) }),
  calendarSync: () => post<CalendarStatus & { changed: number }>('/calendar/sync'),
  itemStage: (id: number, stage: Stage) => post<{ changed: boolean }>(`/items/${id}/stage`, { stage }),
  renameModule: (id: string, name: string) => call<Mod>(`/modules/${id}/name`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  mailSetup: (b: { address: string; from_name: string; app_password: string; dry_run: boolean; daily_cap: number; provider: string; imap_host: string; smtp_host: string; smtp_port: number }) =>
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
  profile: () => call<ProfileCard>('/profile'),
  saveProfile: (text: string) => call('/profile', { method: 'PUT', body: JSON.stringify({ text }) }),
  rebuildProfile: () => post<{ state: string }>('/profile/rebuild', {}),
  notes: () => call<Note[]>('/notes'),
  saveNote: (id: number, name: string, text: string) => call(`/notes/${id}`, { method: 'PUT', body: JSON.stringify({ name, text }) }),
  recap: () => post<Recap>('/recap'),
  brainCheck: () => call<{ ok: boolean; name: string; detail: string }>('/brain/check'),
  settings: (s: { quiet_start?: number; quiet_end?: number; brain_kind?: string; brain_model?: string; wake?: string; bed?: string; todo_goal?: number; assistant_model?: string; assistant_effort?: string; max_usd_per_ask?: number; daily_usd?: number }) =>
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

/** Two digits: 7 -> '07'. */
export const pad2 = (n: number) => String(n).padStart(2, '0')

/** 'YYYY-MM-DD' `offset` days from `from` (the user's day from the desk, which turns over mid-night). */
export function dayPlus(from: string, offset: number): string {
  const d = new Date(`${from}T12:00`)
  d.setDate(d.getDate() + offset)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/** Times of day every half hour, for wake and bed pickers. */
export const HALF_HOURS = Array.from({ length: 48 }, (_, i) => `${pad2(Math.floor(i / 2))}:${i % 2 ? '30' : '00'}`)

/** A local date and time the way the backend reads an exact time: 'YYYY-MM-DD HH:MM'. */
export const localMinute = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`

export function when(ts: string): string {
  const label = dayLabel(ts)
  return `${label === 'today' ? '' : label + ' '}${clock(ts)}`
}
