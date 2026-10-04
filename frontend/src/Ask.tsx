// Ask: the heart of tamadesk. Tell your companion what you want done; it works with your own
// Claude Code and the desk's tools, and you watch each step happen. "todo …", "remind me …" and
// "log …" are handled instantly on the desk itself and cost nothing.
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { type ChatMsg, type Step } from './api'
import { FREE, useAsk } from './AskStore'
import { Companion, useCompanion, type Mood } from './Companion'
import { useFx } from './fx/Fx'
import { FlameIcon } from './icons'
import { Markdown } from './Markdown'
import { Bar } from './ui'

const POKES = ['hehe', 'that tickles!', "I'm awake, I'm awake", 'one thing at a time :)', '*happy wiggle*', 'boop']

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

const GLYPH: Record<string, string> = { search: '⌕', web_search_exa: '⌕', create_tab: '✦', draft_email: '@', add_todo: '✓', set_reminder: '!' }
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
  stats,
  cheer: outerCheer = 0,
}: {
  greeting: string
  mood: Mood
  interests: string
  level: { level: number; xp: number; into: number; need: number }
  stats: { done: number; goal: number; streak: number }
  cheer?: number
}) {
  const fx = useFx()
  const buddy = useCompanion()
  const { text, setText, msgs, live, chatId, chats, usage, send, openChat, focusTick, doneTick } = useAsk()
  const [poke, setPoke] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const running = live !== null
  const cheer = doneTick + outerCheer

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, live])
  useEffect(() => {
    if (focusTick) inputRef.current?.focus()
  }, [focusTick])

  const lastStep = live?.steps.at(-1)
  const say = poke ?? (running ? (lastStep ? `${stepLabel(lastStep)}…` : 'On it…') : msgs.length ? 'Anything else?' : greeting)
  const free = FREE.test(text)
  const spent = usage ? usage.usd / usage.daily_usd : 0

  return (
    <section className="ask">
      <div className="ask-head">
        <div className="ask-buddy">
          <motion.div
            animate={running ? { y: [0, -3, 0] } : text ? { rotate: -7, y: -2 } : { rotate: 0, y: 0 }}
            transition={running ? { duration: 0.7, repeat: Infinity } : { type: 'spring', stiffness: 260, damping: 14 }}
            title={text && !running ? 'listening…' : undefined}
          >
          <Companion
            mood={running ? 'happy' : poke ? 'happy' : mood}
            size={104}
            cheer={cheer}
            onPoke={() => {
              fx.sound('poke')
              setPoke(POKES[Math.floor(Math.random() * POKES.length)])
              setTimeout(() => setPoke(null), 1800)
            }}
          />
          </motion.div>
          <div className="lv-mini" title={`${level.xp} XP · ${level.need - level.into} to next level`}>
            <b>LV {level.level}</b>
            <Bar value={level.into / Math.max(1, level.need)} label="XP to next level" />
          </div>
          <div className="ask-stats">
            <span className={`pill ${stats.done >= stats.goal ? 'hit' : ''}`} title="todos done today / daily goal">
              ✓ {stats.done}/{stats.goal}
            </span>
            {stats.streak > 0 && (
              <span className="pill" title="days in a row">
                <FlameIcon /> {stats.streak}d
              </span>
            )}
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
              onChange={(e) => {
                setText(e.target.value)
                fx.sound('key')
              }}
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
            <select value={chatId ?? ''} onChange={(e) => (fx.sound('tap'), void openChat(e.target.value ? Number(e.target.value) : null))}>
              <option value="">this conversation</option>
              {chats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title.slice(0, 60)}
                </option>
              ))}
            </select>
            <button className="btn tiny ghost" disabled={running} onClick={() => (fx.sound('tap'), void openChat(null))}>
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
