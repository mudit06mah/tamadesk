// Colour themes. Each is one palette applied as CSS variables on <html>, so a new theme is a few
// lines here and no CSS. `crt` adds scanlines and glow; `dark` flips the browser's color-scheme.

type Palette = {
  name: string
  dark?: boolean
  crt?: boolean
  r?: string
  desk: string
  dot: string
  win: string
  win2: string
  line: string
  ink: string
  text: string
  muted: string
  accent: string
  soft: string
  butter: string
  coral: string
  sage: string
  sageStrong: string
  paper: string
  blush: string
  invBg: string
  invFg: string
  good: string
  bad: string
  field: string
}

export const THEMES: Record<string, Palette> = {
  paper: { name: 'Lavender paper', desk: '#d9d3e6', dot: '#c9c1db', win: '#f7f2e7', win2: '#ebe3d3', line: '#2c2934', ink: '#2c2934', text: '#2c2934', muted: '#736d7d', accent: '#a48ed9', soft: '#d8ccf4', butter: '#f1d27e', coral: '#e98c7b', sage: '#cfe2d1', sageStrong: '#8dbd98', paper: '#fffaf0', blush: '#f3a9ba', invBg: '#2c2934', invFg: '#f7f2e7', good: '#3c8657', bad: '#c0463a', field: '#fffdf8' },
  sakura: { name: 'Sakura', desk: '#f6dfe3', dot: '#eccbd2', win: '#fff7f5', win2: '#fbe8e6', line: '#3b2a30', ink: '#3b2a30', text: '#3b2a30', muted: '#8a6d76', accent: '#e58aa5', soft: '#f9d3df', butter: '#f6d58b', coral: '#ef8f7f', sage: '#dcebd9', sageStrong: '#91c49a', paper: '#fffaf8', blush: '#f2a6bb', invBg: '#3b2a30', invFg: '#fff7f5', good: '#3d8a5a', bad: '#c2414f', field: '#fffdfc' },
  matcha: { name: 'Matcha', desk: '#d7e3c8', dot: '#c6d6b4', win: '#f8f6ea', win2: '#ebeedb', line: '#26301f', ink: '#26301f', text: '#26301f', muted: '#66735b', accent: '#7fae5c', soft: '#d6e9c3', butter: '#e8d27a', coral: '#e39a72', sage: '#d2e6c4', sageStrong: '#7fae5c', paper: '#fdfcf3', blush: '#efb0a0', invBg: '#26301f', invFg: '#f8f6ea', good: '#3f7d2c', bad: '#b94a35', field: '#fffff7' },
  peach: { name: 'Peach sunset', desk: '#f7d9c4', dot: '#efc8ad', win: '#fff6ee', win2: '#fbe6d6', line: '#3a2620', ink: '#3a2620', text: '#3a2620', muted: '#8c6a5c', accent: '#f08a5d', soft: '#fcd6c2', butter: '#f7c873', coral: '#e8705f', sage: '#e2ead3', sageStrong: '#99bc84', paper: '#fffaf5', blush: '#f4a7a0', invBg: '#3a2620', invFg: '#fff6ee', good: '#4b8a3e', bad: '#c43d32', field: '#fffcf8' },
  gameboy: { name: 'Game Boy', r: '4px', desk: '#9bbc0f', dot: '#8bac0f', win: '#c4d88a', win2: '#b2c97a', line: '#0f380f', ink: '#0f380f', text: '#0f380f', muted: '#306230', accent: '#306230', soft: '#a9c45a', butter: '#c4d88a', coral: '#8bac0f', sage: '#b2c97a', sageStrong: '#306230', paper: '#e0f0b0', blush: '#8bac0f', invBg: '#0f380f', invFg: '#c4d88a', good: '#0f380f', bad: '#0f380f', field: '#d6e8a0' },
  mono: { name: 'Newsprint', r: '4px', desk: '#e6e3dc', dot: '#d4d0c6', win: '#fbfaf6', win2: '#efece4', line: '#111111', ink: '#111111', text: '#111111', muted: '#6b6760', accent: '#111111', soft: '#e2ded4', butter: '#e8dfb0', coral: '#d26a5c', sage: '#e4e8de', sageStrong: '#7a8f6e', paper: '#ffffff', blush: '#e9b3a6', invBg: '#111111', invFg: '#fbfaf6', good: '#2e6b3a', bad: '#b3372b', field: '#ffffff' },
  phosphor: { name: 'Green CRT', dark: true, crt: true, r: '6px', desk: '#0f1512', dot: '#16201b', win: '#17211c', win2: '#1e2c25', line: '#5e8a6c', ink: '#050806', text: '#bfe3c8', muted: '#7ea68a', accent: '#8fd39f', soft: '#2a4234', butter: '#d6c273', coral: '#e2785f', sage: '#213229', sageStrong: '#8fd39f', paper: '#cfead6', blush: '#e2785f', invBg: '#8fd39f', invFg: '#0f1512', good: '#8fd39f', bad: '#ee8f7b', field: '#111a15' },
  amber: { name: 'Amber CRT', dark: true, crt: true, r: '6px', desk: '#140f08', dot: '#1f170c', win: '#1d150b', win2: '#2a1f10', line: '#9a6b2a', ink: '#050302', text: '#ffcf8a', muted: '#b8894a', accent: '#ffb347', soft: '#3d2b12', butter: '#ffd27a', coral: '#ff8a5c', sage: '#2a2414', sageStrong: '#e2b55a', paper: '#ffe2b8', blush: '#ff9a6b', invBg: '#ffb347', invFg: '#140f08', good: '#e2c25a', bad: '#ff7b5c', field: '#17110a' },
  midnight: { name: 'Midnight neon', dark: true, desk: '#16132a', dot: '#211d3b', win: '#211c3a', win2: '#2b2550', line: '#6e5fd1', ink: '#07060f', text: '#e8e3ff', muted: '#9a91c9', accent: '#ff79c6', soft: '#3d2f63', butter: '#f9e27d', coral: '#ff8f70', sage: '#25304a', sageStrong: '#7be0b5', paper: '#f3efff', blush: '#ff79c6', invBg: '#ff79c6', invFg: '#16132a', good: '#7be0b5', bad: '#ff6b81', field: '#1a1631' },
  ocean: { name: 'Deep sea', dark: true, desk: '#0c1d2b', dot: '#13293b', win: '#13283a', win2: '#1a3449', line: '#4f8fb8', ink: '#03080d', text: '#d9eefa', muted: '#86aac2', accent: '#5ec8e5', soft: '#1d4660', butter: '#f2d58a', coral: '#ff9b85', sage: '#173a3f', sageStrong: '#6fd3b3', paper: '#e8f6fd', blush: '#ffa3b5', invBg: '#5ec8e5', invFg: '#0c1d2b', good: '#6fd3b3', bad: '#ff7f7f', field: '#0f2333' },
  frost: { name: 'Frost', dark: true, desk: '#2e3440', dot: '#353c4a', win: '#3b4252', win2: '#434c5e', line: '#81a1c1', ink: '#191d24', text: '#eceff4', muted: '#a3adbf', accent: '#88c0d0', soft: '#4c566a', butter: '#ebcb8b', coral: '#d08770', sage: '#3f4a4a', sageStrong: '#a3be8c', paper: '#eceff4', blush: '#b48ead', invBg: '#88c0d0', invFg: '#2e3440', good: '#a3be8c', bad: '#bf616a', field: '#323946' },
  vampire: { name: 'Vampire', dark: true, desk: '#1e1f29', dot: '#282a36', win: '#282a36', win2: '#343746', line: '#bd93f9', ink: '#0d0e13', text: '#f8f8f2', muted: '#a4a8c4', accent: '#bd93f9', soft: '#44475a', butter: '#f1fa8c', coral: '#ffb86c', sage: '#2f3d3a', sageStrong: '#50fa7b', paper: '#f8f8f2', blush: '#ff79c6', invBg: '#bd93f9', invFg: '#1e1f29', good: '#50fa7b', bad: '#ff5555', field: '#21222c' },
}

export type ThemeId = keyof typeof THEMES

const VARS: [keyof Palette, string][] = [
  ['desk', 'desk'], ['dot', 'desk-dot'], ['win', 'win'], ['win2', 'win-2'], ['line', 'line'], ['ink', 'ink'],
  ['text', 'text'], ['muted', 'muted'], ['accent', 'accent'], ['soft', 'accent-soft'], ['butter', 'butter'],
  ['coral', 'coral'], ['sage', 'sage'], ['sageStrong', 'sage-strong'], ['paper', 'paper'], ['blush', 'blush'],
  ['invBg', 'inverse-bg'], ['invFg', 'inverse-fg'], ['good', 'good'], ['bad', 'bad'], ['field', 'field'],
]

export function applyTheme(id: string) {
  const t = THEMES[id] ?? THEMES.paper
  const root = document.documentElement
  for (const [k, v] of VARS) root.style.setProperty(`--${v}`, t[k] as string)
  root.style.setProperty('--r', t.r ?? '12px')
  root.style.colorScheme = t.dark ? 'dark' : 'light'
  root.toggleAttribute('data-crt', !!t.crt)
  root.toggleAttribute('data-dark', !!t.dark)
}

export function savedTheme(): string {
  const q = new URLSearchParams(location.search).get('theme')
  if (q && q in THEMES) return q
  try {
    const s = localStorage.getItem('theme')
    if (s && s in THEMES) return s
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'midnight' : 'paper'
}
