// The conversation lives here, above the pages, so switching tabs never loses it: an answer keeps
// streaming while you look elsewhere, and the last chat comes back after a reload.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, ask, type ChatMsg, type Step, type Usage } from './api'
import { useFx } from './fx/Fx'
import type { Toast } from './util'

export const FREE = /^\s*(todo\b|t:|\[\s?\]|remind\s+me\b|log\b|>)/i
const SAVED = 'tamadesk-chat'

type Ctx = {
  text: string
  setText: (t: string) => void
  msgs: ChatMsg[]
  live: { text: string; steps: Step[] } | null
  chatId: number | null
  chats: { id: number; title: string; updated_at: string }[]
  usage: Usage | null
  send: (t: string) => Promise<void>
  stop: () => void
  openChat: (id: number | null) => Promise<void>
  focusTick: number
  doneTick: number
}

const AskCtx = createContext<Ctx | null>(null)

export function useAsk(): Ctx {
  const v = useContext(AskCtx)
  if (!v) throw new Error('useAsk outside AskProvider')
  return v
}

export function AskProvider({ children, notify, onChange }: { children: ReactNode; notify: (t: string, k?: Toast['kind']) => void; onChange: () => void }) {
  const fx = useFx()
  const [text, setText] = useState('')
  const [msgs, setMsgs] = useState<ChatMsg[]>([])
  const [live, setLive] = useState<Ctx['live']>(null)
  const [chatId, setChatId] = useState<number | null>(null)
  const [chats, setChats] = useState<Ctx['chats']>([])
  const [usage, setUsage] = useState<Usage | null>(null)
  const [focusTick, setFocusTick] = useState(0)
  const [doneTick, setDoneTick] = useState(0)
  const busy = useRef(false)
  const runningChat = useRef<number | null>(null) // the chat whose answer is streaming (for stop)

  const loadMeta = useCallback(() => {
    void api.usage().then(setUsage)
    void api.chats().then(setChats)
  }, [])

  const openChat = useCallback(async (id: number | null) => {
    setChatId(id)
    try {
      if (id) localStorage.setItem(SAVED, String(id))
      else localStorage.removeItem(SAVED)
    } catch {
      /* storage unavailable */
    }
    setMsgs(id ? await api.chat(id).catch(() => []) : [])
  }, [])

  // restore the last conversation
  useEffect(() => {
    loadMeta()
    let saved: string | null = null
    try {
      saved = localStorage.getItem(SAVED)
    } catch {
      /* storage unavailable */
    }
    if (saved) void openChat(Number(saved))
  }, [loadMeta, openChat])

  const send = useCallback(
    async (raw: string) => {
      const t = raw.trim()
      if (!t || busy.current) return
      setText('')
      if (FREE.test(t)) {
        // instant and free: handled by the desk, no AI involved
        const r = await api.capture(t.replace(/^\s*(log\b\s*:?|>)\s*/i, ''))
        fx.sound('capture')
        fx.float(document.querySelector('.ask-box'), r.kind === 'log' ? `+${r.xp} XP` : r.kind === 'todo' ? '+ todo' : 'reminder set')
        if (r.no_time) notify("Couldn't find a time in that, so it's a todo. Try “in 10 minutes” or “at 6pm”.", 'err')
        onChange()
        return
      }
      busy.current = true
      fx.sound('tap')
      setMsgs((m) => [...m, { role: 'user', text: t }])
      let liveText = ''
      const steps: Step[] = []
      setLive({ text: '', steps: [] })
      let final: ChatMsg = { role: 'assistant', text: '' }
      try {
        await ask(t, chatId, (e) => {
          if (e.type === 'chat') {
            runningChat.current = e.chat_id
            setChatId(e.chat_id)
            try {
              localStorage.setItem(SAVED, String(e.chat_id))
            } catch {
              /* storage unavailable */
            }
          }
          if (e.type === 'text') {
            liveText += e.text
            setLive({ text: liveText, steps: [...steps] })
          }
          if (e.type === 'tool') {
            steps.push({ name: e.name, input: e.input })
            fx.sound('step', steps.length)
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
      busy.current = false
      runningChat.current = null
      fx.sound('arrive')
      setDoneTick((n) => n + 1)
      loadMeta()
      onChange()
    },
    [chatId, fx, onChange, loadMeta, notify],
  )

  const stop = useCallback(() => {
    if (runningChat.current) void api.stopAsk(runningChat.current).then(() => fx.sound('undo'))
  }, [fx])

  // "ask Bolt" from anywhere: lead buttons, the new-tab dialog, the / key, Memory
  useEffect(() => {
    const onAsk = (e: Event) => {
      const d = (e as CustomEvent<{ text: string; send: boolean; chat?: number }>).detail
      if (d.chat) void openChat(d.chat)
      if (d.send) void send(d.text)
      else if (d.text || !d.chat) {
        setText(d.text)
        setFocusTick((n) => n + 1)
      }
    }
    window.addEventListener('tamadesk:ask', onAsk)
    return () => window.removeEventListener('tamadesk:ask', onAsk)
  }, [send, openChat])

  return (
    <AskCtx.Provider value={{ text, setText, msgs, live, chatId, chats, usage, send, stop, openChat, focusTick, doneTick }}>{children}</AskCtx.Provider>
  )
}
