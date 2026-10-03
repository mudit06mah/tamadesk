// Small stroke icons (24px grid), inherit currentColor.
const base = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

export const HomeIcon = () => (
  <svg {...base} aria-hidden><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /></svg>
)
export const BookIcon = () => (
  <svg {...base} aria-hidden><path d="M4 4h7a2 2 0 012 2v14a2 2 0 00-2-2H4z" /><path d="M20 4h-5a2 2 0 00-2 2v14a2 2 0 012-2h5z" /></svg>
)
export const PenIcon = () => (
  <svg {...base} aria-hidden><path d="M4 20l4-1 11-11-3-3L5 16z" /><path d="M14 6l3 3" /></svg>
)
export const GearIcon = () => (
  <svg {...base} aria-hidden><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></svg>
)
export const SunIcon = () => (
  <svg {...base} aria-hidden><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" /></svg>
)
export const MoonIcon = () => (
  <svg {...base} aria-hidden><path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z" /></svg>
)
export const FlameIcon = () => (
  <svg {...base} aria-hidden><path d="M12 3c1 4 5 5 5 10a5 5 0 01-10 0c0-3 2-4 2-7 1 1 2 2 3 3 0-2 0-4 0-6z" /></svg>
)
