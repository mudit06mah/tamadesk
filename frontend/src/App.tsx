import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, askBolt, when, type Mod, type State } from './api'
import { Companion, CompanionCtx } from './Companion'
import { FxProvider, useFx } from './fx/Fx'
import { play, setSound, soundOn } from './fx/sound'
import { BookIcon, GearIcon, HomeIcon, MailIcon, ModIcon, MoonIcon, PlusIcon, SunIcon } from './icons'
import { Journal } from './Journal'
import { Mail } from './Mail'
import { ModulePage } from './ModulePage'
import { NewGame } from './NewGame'
import { Settings } from './Settings'
import { NewTabDialog } from './Templates'
import { Today } from './Today'
import { Dialog } from './ui'
import { isTyping, type Toast } from './util'

// fixed pages, plus one `m:<id>` page per module tab (between Today and Journal)
export type Page = string
type Theme = 'paper' | 'phosphor'
const pagesFor = (mods: Mod[]): Page[] => ['today', ...mods.map((m) => `m:${m.id}`), 'mail', 'journal', 'settings']

function initialTheme(): Theme {
  const q = new URLSearchParams(location.search).get('theme')
  if (q === 'paper' || q === 'phosphor') return q
  try {
    const saved = localStorage.getItem('theme')
    if (saved === 'paper' || saved === 'phosphor') return saved
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'phosphor' : 'paper'
}

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
      </FxProvider>
    </CompanionCtx.Provider>
  )
}

function Shell({ state, setState }: { state: State | null; setState: (s: State) => void }) {
  const fx = useFx()
  const [page, setPage] = useState<Page>(() => location.hash.slice(1) || 'today')
  const [mods, setMods] = useState<Mod[]>([])
  const [newTab, setNewTab] = useState(false)
  const pages = pagesFor(mods)
  // an "ask Bolt" from another page: switch to Today and hand the request over once Ask is mounted
  const [pendingAsk, setPendingAsk] = useState<{ text: string; send: boolean } | null>(null)
  const pageRef = useRef(page)
  pageRef.current = page
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [sound, setSoundState] = useState(soundOn())
  const [offline, setOffline] = useState(false)
  const [replay, setReplay] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)
  const toastTimer = useRef<number | undefined>(undefined)
  const rung = useRef(new Set<number>())

  useEffect(() => {
    if (location.hash.slice(1) !== page) history.pushState(null, '', `${location.pathname}${location.search}#${page}`)
  }, [page])

  useEffect(() => {
    const onAsk = (e: Event) => {
      if (pageRef.current === 'today') return
      setPendingAsk((e as CustomEvent<{ text: string; send: boolean }>).detail)
      setPage('today')
    }
    window.addEventListener('tamadesk:ask', onAsk)
    return () => window.removeEventListener('tamadesk:ask', onAsk)
  }, [])

  useEffect(() => {
    const onHash = () => setPage(location.hash.slice(1) || 'today')
    window.addEventListener('popstate', onHash)
    return () => window.removeEventListener('popstate', onHash)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
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
    play('tap')
    setPage(p)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === '/') {
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
  const mod = page.startsWith('m:') ? mods.find((m) => `m:${m.id}` === page) : undefined
  const tiles: { id: Page; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'today', label: 'Today', icon: <HomeIcon />, count: state.today.open.length },
    ...mods.map((m) => ({ id: `m:${m.id}`, label: m.name, icon: <ModIcon name={m.icon} />, count: m.new })),
    { id: 'mail', label: 'Mail', icon: <MailIcon /> },
    { id: 'journal', label: 'Journal', icon: <BookIcon /> },
    { id: 'settings', label: 'Settings', icon: <GearIcon /> },
  ]

  return (
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

        <nav className="tiles">
          {tiles.map((t, i) => (
            <motion.button
              layout
              key={t.id}
              id={`dock-${t.id}`}
              className={`tile ${page === t.id ? 'on' : ''}`}
              onClick={() => go(t.id)}
              initial={{ scale: 0.3, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 380, damping: 18 }}
            >
              <span className="tile-icon">{t.icon}</span>
              <span className="tile-label">{t.label}</span>
              {!!t.count && <span className="tile-count">{t.count}</span>}
              {i < 9 && <kbd className="tile-key">{i + 1}</kbd>}
              {page === t.id && <motion.span layoutId="tile-on" className="tile-glow" />}
            </motion.button>
          ))}
          <motion.button layout className="tile tile-add" onClick={() => setNewTab(true)} whileTap={{ scale: 0.9 }} title="Add a tab">
            <span className="tile-icon">
              <PlusIcon />
            </span>
            <span className="tile-label">New tab</span>
          </motion.button>
        </nav>

        <div className="dock-foot">
          <div className={`lamp ${offline ? 'off' : 'live'}`}>
            <i />
            {offline ? 'Backend offline' : `${state.brain.kind === 'ollama' ? 'Ollama' : 'Claude Code'} · ${state.brain.model}`}
          </div>
          <div className="toggles">
            <button className="mini" onClick={() => setTheme(theme === 'phosphor' ? 'paper' : 'phosphor')} title={theme === 'phosphor' ? 'Paper theme' : 'Phosphor theme'}>
              {theme === 'phosphor' ? <SunIcon /> : <MoonIcon />}
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
          </div>
        </div>
      </aside>

      <main className="screen">
        <AnimatePresence mode="wait">
          <motion.div key={page} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
            {(page === 'today' || (page.startsWith('m:') && !mod)) && <Today state={state} refresh={refresh} notify={notify} go={go} pendingAsk={pendingAsk} clearPending={() => setPendingAsk(null)} />}
            {mod && <ModulePage key={mod.id} mod={mod} notify={notify} onChange={refresh} onDeleted={() => (go('today'), void refresh())} />}
            {page === 'journal' && <Journal />}
            {page === 'mail' && <Mail notify={notify} onChange={refresh} />}
            {page === 'settings' && <Settings state={state} refresh={refresh} notify={notify} replay={() => setReplay(true)} />}
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
  )
}
