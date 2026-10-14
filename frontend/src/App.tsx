// The desk shell: the sidebar of pages and tabs, the companion, hotkeys (/ or t to ask, 1-9 to jump, Esc to
// leave a text box), toasts, and whichever page is open.
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, askBolt, when, type Mod, type State } from './api'
import { Companion, CompanionCtx } from './Companion'
import { FxProvider, useFx } from './fx/Fx'
import { play, setSound, soundOn } from './fx/sound'
import { BrainIcon, CodeIcon, PenIcon, GearIcon, HomeIcon, MailIcon, ModIcon, PaletteIcon, PlusIcon } from './icons'
import { GitHub } from './GitHub'
import { applyTheme, savedTheme } from './themes'
import { ThemePicker } from './ThemePicker'
import { AskProvider } from './AskStore'
import { Memory } from './Memory'
import { Notes } from './Notes'
import { Mail } from './Mail'
import { ModulePage } from './ModulePage'
import { NewGame } from './NewGame'
import { Settings } from './Settings'
import { NewTabDialog } from './Templates'
import { Tips } from './Tips'
import { Today } from './Today'
import { Dialog } from './ui'
import { isTyping, type Toast } from './util'

// fixed pages, then one `m:<id>` page per tab, then Settings (keys 1-9 jump to them). A page can carry a
// focus after a slash: `mail/d12` opens draft 12, `m:jobs/i4` opens item 4 (links from Today use these).
type Page = string
const CORE: Page[] = ['today', 'mail', 'notes', 'github', 'memory']
const pagesFor = (mods: Mod[]): Page[] => [...CORE, ...mods.map((m) => `m:${m.id}`), 'settings']

function remembered(key: string): number | null {
  try {
    const v = localStorage.getItem(key)
    return v === null ? null : Number(v)
  } catch {
    return null
  }
}

function remember(key: string, v: number) {
  try {
    localStorage.setItem(key, String(v))
  } catch {
    /* ignore */
  }
}

export default function App() {
  const [state, setState] = useState<State | null>(null)
  const companion = state?.companion ?? { species: 'blob', name: 'buddy' }
  return (
    <CompanionCtx.Provider value={companion}>
      <FxProvider>
        <Shell state={state} setState={setState} />
        <Tips />
      </FxProvider>
    </CompanionCtx.Provider>
  )
}

function Shell({ state, setState }: { state: State | null; setState: (s: State) => void }) {
  const fx = useFx()
  const [page, setPage] = useState<Page>(() => location.hash.slice(1) || 'today')
  const [mods, setMods] = useState<Mod[]>([])
  const [newTab, setNewTab] = useState(false)
  const [seenTabs, setSeenTabs] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem('seen-tabs') ?? '{}') as Record<string, string>
    } catch {
      return {}
    }
  })
  const pages = pagesFor(mods)
  const [base, focus = ''] = page.split('/')
  // an "ask Bolt" from another page: switch to Today (the conversation itself lives in AskProvider)
  const pageRef = useRef(page)
  pageRef.current = page
  const [theme, setTheme] = useState(savedTheme)
  const [picker, setPicker] = useState(false)
  useEffect(() => {
    if (!picker) return
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !(e.target as Element).closest('.theme-pop, .mini')) setPicker(false)
    }
    window.addEventListener('keydown', close)
    window.addEventListener('mousedown', close)
    return () => {
      window.removeEventListener('keydown', close)
      window.removeEventListener('mousedown', close)
    }
  }, [picker])
  const [sound, setSoundState] = useState(soundOn())
  const [offline, setOffline] = useState(false)
  const [replay, setReplay] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)
  const toastTimer = useRef<number | undefined>(undefined)
  const rung = useRef(new Set<number>())

  // looking at a tab clears its sparkle (a per-browser convenience, so localStorage is fine)
  useEffect(() => {
    const id = page.split('/')[0]
    if (!id.startsWith('m:')) return
    const stamp = new Date().toISOString().replace('T', ' ').slice(0, 19)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mark the tab seen when you open it
    setSeenTabs((m) => {
      const next = { ...m, [id.slice(2)]: stamp }
      try {
        localStorage.setItem('seen-tabs', JSON.stringify(next))
      } catch {
        /* storage unavailable */
      }
      return next
    })
  }, [page])

  useEffect(() => {
    if (location.hash.slice(1) !== page) history.pushState(null, '', `${location.pathname}${location.search}#${page}`)
  }, [page])

  useEffect(() => {
    const onAsk = () => {
      if (pageRef.current.split('/')[0] !== 'today') setPage('today')
    }
    const onNewTab = () => setNewTab(true)
    window.addEventListener('tamadesk:ask', onAsk)
    window.addEventListener('tamadesk:newtab', onNewTab)
    return () => {
      window.removeEventListener('tamadesk:ask', onAsk)
      window.removeEventListener('tamadesk:newtab', onNewTab)
    }
  }, [])

  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || 'today')
    window.addEventListener('popstate', onHash)
    return () => window.removeEventListener('popstate', onHash)
  }, [])

  useEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const refresh = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([api.state(), api.modules()])
      setState(s)
      setMods(m)
      setOffline(false)
      const lastLevel = remembered('seen-level')
      if (lastLevel !== null && s.progress.level > lastLevel) {
        fx.banner({ kind: 'level', title: `LEVEL ${s.progress.level}!`, sub: 'Every little thing you finish counts. Keep going!' })
      }
      remember('seen-level', s.progress.level)
      // ring each newly fired reminder once per session
      for (const r of s.reminders) {
        if (r.status === 'fired' && !rung.current.has(r.id)) {
          rung.current.add(r.id)
          play('ring')
        }
      }
    } catch {
      setOffline(true)
    }
  }, [fx, setState])

  useEffect(() => {
    const now = () => void refresh() // e.g. right after switching companions
    window.addEventListener('tamadesk:refresh', now)
    return () => window.removeEventListener('tamadesk:refresh', now)
  }, [refresh])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch + polling
    void refresh()
    const t = setInterval(refresh, 10000)
    return () => clearInterval(t)
  }, [refresh])

  const notify = useCallback((text: string, kind: Toast['kind'] = 'ok') => {
    setToast({ text, kind })
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 3800)
  }, [])

  const go = useCallback((p: Page) => {
    play('click')
    setPage(p)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Escape leaves a text box (after its own handlers ran), so / or t (back to typing) and 1-9 work again
      if (e.key === 'Escape' && isTyping(e)) {
        ;(e.target as HTMLElement).blur()
        return
      }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === '/' || e.key === 't') {
        e.preventDefault()
        askBolt('')
        return
      }
      const n = Number(e.key)
      if (n >= 1 && n <= Math.min(9, pages.length)) go(pages[n - 1])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, pages])

  if (!state) {
    return <p className="loading">{offline ? 'tamadesk backend is offline. Run `uv run tamadesk serve`.' : 'booting tamadesk…'}</p>
  }

  if (!state.onboarded || replay) {
    return (
      <NewGame
        replay={replay}
        onReady={() => {
          setReplay(false)
          void refresh()
        }}
      />
    )
  }

  const ringing = state.reminders.filter((r) => r.status === 'fired')
  const name = state.companion?.name ?? 'buddy'
  const mod = base.startsWith('m:') ? mods.find((m) => `m:${m.id}` === base) : undefined
  const core: { id: Page; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'today', label: 'Today', icon: <HomeIcon />, count: state.needs_you },
    { id: 'mail', label: 'Mail', icon: <MailIcon />, count: state.mail_drafts },
    { id: 'notes', label: 'Notes', icon: <PenIcon /> },
    { id: 'github', label: 'GitHub', icon: <CodeIcon /> },
    { id: 'memory', label: 'Memory', icon: <BrainIcon /> },
  ]
  const navRow = (t: { id: Page; label: string; icon: React.ReactNode; count?: number; fresh?: boolean }, big = false) => {
    const key = pages.indexOf(t.id) + 1
    return (
      <motion.button
        layout="position"
        key={t.id}
        id={`dock-${t.id}`}
        className={`nav-row ${big ? 'big' : ''} ${base === t.id ? 'on' : ''}`}
        onClick={() => go(t.id)}
        whileTap={{ scale: 0.95 }}
        initial={{ opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
      >
        {base === t.id && <motion.span layoutId="nav-on" className="nav-glow" transition={{ type: 'spring', stiffness: 500, damping: 34 }} />}
        <span className="nav-icon">{t.icon}</span>
        <span className="nav-label">{t.label}</span>
        {!!t.count && (
          <motion.span key={t.count} className="nav-count" initial={{ scale: 1.6 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 600, damping: 14 }}>
            {t.count}
          </motion.span>
        )}
        {t.fresh && base !== t.id && (
          <motion.span className="nav-fresh" title="something new since you last looked" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 12 }}>
            ✦
          </motion.span>
        )}
        {key > 0 && key < 10 && <kbd className="nav-key">{key}</kbd>}
      </motion.button>
    )
  }

  return (
    <AskProvider notify={notify} onChange={refresh}>
    <div className="desk">
      <aside className="dock">
        <div className="logo">
          <span className="logo-buddy">
            <Companion size={34} />
          </span>
          <span className="logo-text">
            TAMADESK<small>v0.3 · {name}</small>
          </span>
        </div>

        <nav className="nav-core">{core.map((t) => navRow(t, true))}</nav>

        <div className="nav-head">
          <span>your tabs</span>
          <motion.button className="nav-add" whileTap={{ scale: 0.85, rotate: 90 }} onClick={() => setNewTab(true)} title="Add a tab" aria-label="Add a tab">
            <PlusIcon />
          </motion.button>
        </div>
        <nav className="nav-tabs">
          {mods.length === 0 ? (
            <button className="nav-empty" onClick={() => askBolt('Keep an eye on ')}>
              Ask {name} to keep an eye on something, or press +
            </button>
          ) : (
            // a sparkle for "new since you looked", not a count of everything unread: tabs shouldn't feel like debt
            mods.map((m) => navRow({ id: `m:${m.id}`, label: m.name, icon: <ModIcon name={m.icon} />, fresh: !!m.fresh_at && m.fresh_at > (seenTabs[m.id] ?? '') }))
          )}
        </nav>

        <div className="dock-foot">
          <div className={`lamp ${offline ? 'off' : 'live'}`}>
            <i />
            {offline ? 'Backend offline' : `${state.brain.kind === 'ollama' ? 'Ollama' : 'Claude Code'} · ${state.brain.model}`}
          </div>
          <div className="toggles">
            <button className="mini" onClick={() => setPicker(!picker)} title="Theme" aria-label="Theme">
              <PaletteIcon />
            </button>
            <button
              className={`mini ${sound ? '' : 'muted-btn'}`}
              onClick={() => {
                setSound(!sound)
                setSoundState(!sound)
                if (!sound) play('tap')
              }}
              title={sound ? 'Mute sounds' : 'Unmute sounds'}
            >
              {sound ? '♪' : '×'}
            </button>
            <button className={`mini ${base === 'settings' ? 'on' : ''}`} onClick={() => go('settings')} title="Settings" aria-label="Settings">
              <GearIcon />
            </button>
          </div>
          <AnimatePresence>
            {picker && (
              <motion.div className="theme-pop" initial={{ opacity: 0, y: 10, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6 }}>
                <ThemePicker
                  value={theme}
                  onPick={(t) => {
                    play('sparkle')
                    setTheme(t)
                  }}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </aside>

      <main className="screen">
        <AnimatePresence mode="wait">
          <motion.div
            key={base}
            initial={{ opacity: 0, x: 18, scale: 0.995 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ type: 'spring', stiffness: 420, damping: 34, opacity: { duration: 0.15 } }}
          >
            {(base === 'today' || (base.startsWith('m:') && !mod)) && <Today state={state} refresh={refresh} notify={notify} />}
            {mod && <ModulePage key={mod.id} mod={mod} focus={focus} notify={notify} onChange={refresh} onDeleted={() => (go('today'), void refresh())} />}
            {base === 'memory' && <Memory notify={notify} />}
            {base === 'notes' && <Notes notify={notify} />}
            {base === 'mail' && <Mail focus={focus} notify={notify} onChange={refresh} />}
            {base === 'github' && <GitHub notify={notify} />}
            {base === 'settings' && <Settings state={state} refresh={refresh} notify={notify} replay={() => setReplay(true)} theme={theme} setTheme={setTheme} />}
          </motion.div>
        </AnimatePresence>
      </main>

      <NewTabDialog
        open={newTab}
        interests={state.about.interests ?? ''}
        onClose={() => setNewTab(false)}
        notify={notify}
        onCreated={(m) => {
          setNewTab(false)
          void refresh().then(() => setPage(`m:${m.id}`))
        }}
      />

      <Dialog open={ringing.length > 0} title="alarm.clk" onClose={() => undefined}>
        <div className="ring">
          <motion.div animate={{ rotate: [0, -8, 8, -8, 8, 0] }} transition={{ duration: 0.6, repeat: Infinity, repeatDelay: 1 }}>
            <Companion mood="happy" size={84} />
          </motion.div>
          <div className="ring-list">
            <div className="ring-head">{name} says:</div>
            {ringing.map((r) => (
              <div key={r.id} className="ring-item">
                <span>
                  <b>{r.text}</b>
                  <span className="muted small"> · {when(r.due_at)}</span>
                </span>
                <button
                  data-autofocus
                  className="btn solid"
                  onClick={async (e) => {
                    const el = e.currentTarget
                    const res = await api.dismiss(r.id)
                    fx.sound('check')
                    fx.burstAt(el)
                    if (res.xp) fx.float(el, `+${res.xp} XP`)
                    await refresh()
                  }}
                >
                  Got it
                </button>
              </div>
            ))}
          </div>
        </div>
      </Dialog>

      <AnimatePresence>
        {toast && (
          <motion.div className={`toast ${toast.kind}`} initial={{ opacity: 0, y: 30, x: '-50%' }} animate={{ opacity: 1, y: 0, x: '-50%' }} exit={{ opacity: 0, y: 20, x: '-50%' }}>
            {toast.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </AskProvider>
  )
}
