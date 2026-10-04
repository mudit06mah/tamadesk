// Ask: the heart of tamadesk. Tell your companion what you want done; it works with your own
// Claude Code and the desk's tools, and you watch each step happen. "todo …", "remind me …" and
// "log …" are handled instantly on the desk itself and cost nothing.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ask, type ChatMsg, type Step, type Usage } from './api'
import { Companion, useCompanion, type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { Markdown } from './Markdown'
import { Bar } from './ui'
import type { Toast } from './util'

const POKES = ['hehe', 'that tickles!', "I'm awake, I'm awake", 'one thing at a time :)', '*happy wiggle*', 'boop']
const FREE = /^\s*(todo\b|t:|\[\s?\]|remind\s+me\b|log\b|>)/i

/** What each tool call looks like to a person. */
export function stepLabel(st: Step): string {
  const i = st.input as Record<string, string & Record<string, string>>
  const name = st.name.replace(/^mcp__\w+?__/, '')
  const q = i.params?.query ?? i.params?.url ?? i.query ?? ''
  const labels: Record<string, string> = {
    search: `searching ${i.source ?? 'the web'}${q ? `: ${q}` : ''}`,
    web_search_exa: `searching the web: ${i.query ?? ''}`,
    web_fetch_exa: 'reading pages',
    read_page: `reading ${String(i.url ?? '').replace(/^https?:\/\/(www\.)?/, '').split('/')[0]}`,
    WebFetch: `reading ${String(i.url ?? '').replace(/^https?:\/\/(www\.)?/, '').split('/')[0]}`,
    create_tab: `hatching a tab: ${i.name ?? ''}`,
    delete_tab: `removing tab ${i.tab ?? ''}`,
    add_to_tab: `filling ${i.tab ?? 'a tab'}`,
    list_tabs: 'looking at your tabs',
    tab_items: `reading ${i.tab ?? 'a tab'}`,
    draft_email: `drafting: ${i.subject ?? 'an email'}`,
    add_todo: `todo: ${i.title ?? ''}`,
    set_reminder: `reminder: ${i.text ?? ''}`,
    log: 'writing in your log',
  }
  return (labels[name] ?? name).slice(0, 90)
}

const GLYPH: Record<string, string> = { search: '⌕', web_search_exa: '⌕', create_tab: '✦', draft_email: '✉', add_todo: '✓', set_reminder: '⏰' }
const glyph = (st: Step) => GLYPH[st.name.replace(/^mcp__\w+?__/, '')] ?? '›'

function examples(interests: string): string[] {
  const topic = interests.split(',')[0]?.trim() || 'developer tools'
  return [
    `Keep an eye on new ${topic} projects on GitHub`,
    `Every morning, the best new papers and news on ${topic}`,
    'Find 15 small startups that might need what I offer, with a contact',
    'remind me to stretch in 30 min',
  ]
}

export function AskPanel({
  greeting,
  mood,
  interests,
  level,
  notify,
  onChange,
  cheer: outerCheer = 0,
  pending,
  clearPending,
}: {
  greeting: string
  mood: Mood
  interests: string
  level: { level: number; xp: number; into: number; need: number }
  notify: (t: string, k?: Toast['kind']) => void
  onChange: () => void
  cheer?: number
  pending?: { text: string; send: boolean } | null
  clearPending?: () => void
}) {
  const fx = useFx()
  const buddy = useCompanion()
  const [text, setText] = useState('')
  const [msgs, setMsgs] = useState<ChatMsg[]>([])
  const [live, setLive] = useState<{ text: string; steps: Step[] } | null>(null)
  const [chatId, setChatId] = useState<number | null>(null)
  const [chats, setChats] = useState<{ id: number; title: string }[]>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [poke, setPoke] = useState<string | null>(null)
  const [cheer, setCheer] = useState(0)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const running = live !== null

  const loadMeta = useCallback(() => {
    void api.usage().then(setUsage)
    void api.chats().then(setChats)
  }, [])
  useEffect(loadMeta, [loadMeta])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, live])

  const send = useCallback(
    async (raw: string) => {
      const t = raw.trim()
      if (!t || running) return
      setText('')
      if (FREE.test(t)) {
        // instant and free: handled by the desk, no AI involved
        const r = await api.capture(t.replace(/^\s*(log\b|>)\s*/i, ''))
        fx.sound('capture')
        fx.float(inputRef.current, r.kind === 'log' ? `+${r.xp} XP` : r.kind === 'todo' ? '+ todo' : '⏰ set')
        onChange()
        return
      }
      fx.sound('tap')
      setMsgs((m) => [...m, { role: 'user', text: t }])
      let liveText = ''
      const steps: Step[] = []
      setLive({ text: '', steps: [] })
      let final: ChatMsg = { role: 'assistant', text: '' }
      try {
        await ask(t, chatId, (e) => {
          if (e.type === 'chat') setChatId(e.chat_id)
          if (e.type === 'text') {
            liveText += e.text
            setLive({ text: liveText, steps: [...steps] })
          }
          if (e.type === 'tool') {
            fx.sound('poke')
            steps.push({ name: e.name, input: e.input })
            setLive({ text: liveText, steps: [...steps] })
          }
          if (e.type === 'done') final = { role: 'assistant', text: e.text, cost_usd: e.cost_usd, tokens: e.tokens }
          if (e.type === 'error') final = { role: 'assistant', text: `Something went wrong: ${e.text}` }
        })
      } catch (err) {
        notify((err as Error).message, 'err')
        final = { role: 'assistant', text: (err as Error).message }
      }
      setMsgs((m) => [...m, { ...final, steps, text: final.text || liveText }])
      setLive(null)
      fx.sound('send')
      setCheer((n) => n + 1)
      loadMeta()
      onChange()
    },
    [running, chatId, fx, onChange, loadMeta, notify],
  )

  // "ask Bolt" from anywhere: lead buttons, the new-tab dialog, the / key
  const take = useCallback(
    ({ text: t, send: now }: { text: string; send: boolean }) => {
      if (now) void send(t)
      else {
        setText(t)
        setTimeout(() => inputRef.current?.focus(), 50)
      }
    },
    [send],
  )
  useEffect(() => {
    const onAsk = (e: Event) => take((e as CustomEvent<{ text: string; send: boolean }>).detail)
    window.addEventListener('tamadesk:ask', onAsk)
    return () => window.removeEventListener('tamadesk:ask', onAsk)
  }, [take])
  useEffect(() => {
    if (!pending) return
    clearPending?.()
    take(pending)
  }, [pending, clearPending, take])

  const openChat = async (id: number | null) => {
    setChatId(id)
    setMsgs(id ? await api.chat(id) : [])
    fx.sound('tap')
  }

  const lastStep = live?.steps.at(-1)
  const say = poke ?? (running ? (lastStep ? `${stepLabel(lastStep)}…` : 'On it…') : msgs.length ? 'Anything else?' : greeting)
  const free = FREE.test(text)
  const spent = usage ? usage.usd / usage.daily_usd : 0

  return (
    <section className="ask">
      <div className="ask-head">
        <div className="ask-buddy">
          <Companion
            mood={running ? 'happy' : poke ? 'happy' : mood}
            size={104}
            cheer={cheer + outerCheer}
            onPoke={() => {
              fx.sound('poke')
              setPoke(POKES[Math.floor(Math.random() * POKES.length)])
              setTimeout(() => setPoke(null), 1800)
            }}
          />
          <div className="lv-mini" title={`${level.xp} XP · ${level.need - level.into} to next level`}>
            <b>LV {level.level}</b>
            <Bar value={level.into / Math.max(1, level.need)} label="XP to next level" />
          </div>
        </div>
        <div className="ask-main">
          <motion.div key={say} className={`bubble ask-bubble ${running ? 'working' : ''}`} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
            {say}
          </motion.div>
          <form
            className={`ask-box ${running ? 'busy' : ''}`}
            onSubmit={(e) => {
              e.preventDefault()
              void send(text)
            }}
          >
            <textarea
              ref={inputRef}
              rows={2}
              value={text}
              disabled={running}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send(text)
                }
              }}
              placeholder={`Ask ${buddy.name} to do anything. "Find…", "Keep an eye on…", "Email…", "Remind me…"`}
              aria-label={`Ask ${buddy.name}`}
            />
            <div className="ask-row">
              <span className={`ask-hint ${free ? 'free' : ''}`}>
                {free ? 'instant · free' : running ? `${buddy.name} is working…` : `↵ ask ${buddy.name}`}
              </span>
              {usage && (
                <span className="ask-budget" title={`${usage.model}, ${usage.effort} effort · max $${usage.max_usd_per_ask.toFixed(2)} per ask`}>
                  today ≈ ${usage.usd.toFixed(2)} / ${usage.daily_usd.toFixed(2)}
                  <i style={{ width: `${Math.min(100, spent * 100)}%` }} />
                </span>
              )}
              <motion.button className="btn solid" whileTap={{ scale: 0.9 }} disabled={running || !text.trim()}>
                {running ? <span className="blink">working</span> : 'Go ▶'}
              </motion.button>
            </div>
          </form>
          {!msgs.length && !running && (
            <div className="ask-examples">
              {examples(interests).map((ex) => (
                <motion.button key={ex} className="chip" whileTap={{ scale: 0.94 }} onClick={() => (setText(ex), inputRef.current?.focus())}>
                  {ex}
                </motion.button>
              ))}
            </div>
          )}
        </div>
      </div>

      {(msgs.length > 0 || running) && (
        <div className="convo">
          <div className="convo-bar">
            <select value={chatId ?? ''} onChange={(e) => void openChat(e.target.value ? Number(e.target.value) : null)}>
              <option value="">this conversation</option>
              {chats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title.slice(0, 60)}
                </option>
              ))}
            </select>
            <button className="btn tiny ghost" disabled={running} onClick={() => void openChat(null)}>
              + new chat
            </button>
          </div>
          <div className="convo-log" ref={logRef}>
            {msgs.map((m, i) => (
              <Message key={m.id ?? `m${i}`} m={m} />
            ))}
            {live && <Message m={{ role: 'assistant', text: live.text, steps: live.steps }} live />}
          </div>
        </div>
      )}
    </section>
  )

}

function Message({ m, live: isLive }: { m: ChatMsg; live?: boolean }) {
  const [open, setOpen] = useState(!!isLive)
  if (m.role === 'user') return <div className="msg user">{m.text}</div>
  const steps = m.steps ?? []
  return (
    <div className="msg bot">
      {steps.length > 0 && (
        <div className="steps">
          <button className="steps-toggle" onClick={() => setOpen(!open)}>
            {isLive ? <span className="blink">working</span> : `${steps.length} step${steps.length > 1 ? 's' : ''}`} {open ? '▾' : '▸'}
          </button>
          <AnimatePresence initial={false}>
            {(open || isLive) &&
              steps.map((st, i) => (
                <motion.div key={i} className="step" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}>
                  <span className="step-glyph">{glyph(st)}</span> {stepLabel(st)}
                </motion.div>
              ))}
          </AnimatePresence>
        </div>
      )}
      {m.text ? <Markdown text={m.text} /> : isLive && <p className="muted blink">thinking…</p>}
      {!isLive && m.cost_usd != null && (
        <div className="msg-cost">
          ≈ ${m.cost_usd.toFixed(3)} · {Math.round((m.tokens ?? 0) / 1000)}k tokens
        </div>
      )}
    </div>
  )
}
