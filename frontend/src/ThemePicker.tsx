// A grid of theme swatches. Each swatch is a tiny window in that theme's own colours.
import { motion } from 'motion/react'
import { THEMES } from './themes'

export function ThemePicker({ value, onPick }: { value: string; onPick: (id: string) => void }) {
  return (
    <div className="themes">
      {Object.entries(THEMES).map(([id, t]) => (
        <motion.button
          key={id}
          className={`swatch ${value === id ? 'on' : ''}`}
          onClick={() => onPick(id)}
          whileHover={{ y: -2 }}
          whileTap={{ scale: 0.9 }}
          title={t.name}
          style={{ background: t.desk, borderColor: t.line }}
        >
          <span className="sw-win" style={{ background: t.win, borderColor: t.line }}>
            <i style={{ background: t.accent }} />
            <i style={{ background: t.butter }} />
            <i style={{ background: t.coral }} />
          </span>
          <span className="sw-name" style={{ color: t.text }}>
            {t.name}
          </span>
        </motion.button>
      ))}
    </div>
  )
}
