// GitHub: the work you still owe. Your open PRs (review decision, CI), issues assigned to you and
// PRs waiting for your review, straight from your own `gh` login.
import { motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, askBolt, utc, type GhRow, type GitHubStatus } from './api'
import { useCompanion } from './Companion'
import { useFx } from './fx/Fx'
import { Win } from './ui'
import type { Toast } from './util'

const ago = (iso: string) => {
  const d = Math.round((Date.now() - utc(iso).getTime()) / 86_400_000)
  return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d}d ago`
}

const stale = (iso: string) => Date.now() - utc(iso).getTime() > 60 * 86_400_000

function badges(r: GhRow) {
  const out: [string, string][] = []
  if (r.draft) out.push(['draft', 'muted'])
  if (r.review === 'CHANGES_REQUESTED') out.push(['changes requested', 'bad'])
  if (r.review === 'APPROVED') out.push(['approved', 'good'])
  if (r.review === 'REVIEW_REQUIRED') out.push(['needs review', 'warn'])
  if (r.checks === 'FAILURE' || r.checks === 'ERROR') out.push(['CI failing', 'bad'])
  if (r.checks === 'SUCCESS') out.push(['CI ✓', 'good'])
  if (r.checks === 'PENDING') out.push(['CI running', 'warn'])
  return out
}

function Rows({ rows, empty }: { rows: GhRow[]; empty: string }) {
  if (!rows.length) return <p className="muted small">{empty}</p>
  return (
    <ul className="gh-rows">
      {rows.map((r) => (
        <motion.li key={r.url} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}>
          <a href={r.url} target="_blank" rel="noreferrer" className="gh-title">
            {r.title}
          </a>
          <div className="gh-meta">
            <span className="muted small">
              {r.repo}#{r.number} · {ago(r.updated_at)}
              {r.author ? ` · by ${r.author}` : ''}
              {r.comments ? ` · ${r.comments} comments` : ''}
            </span>
            {badges(r).map(([t, k]) => (
              <span key={t} className={`gh-badge ${k}`}>
                {t}
              </span>
            ))}
          </div>
        </motion.li>
      ))}
    </ul>
  )
}

export function GitHub({ notify }: { notify: (t: string, k?: Toast['kind']) => void }) {
  const fx = useFx()
  const buddy = useCompanion()
  const [gh, setGh] = useState<GitHubStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(
    async (refresh = false) => {
      setBusy(true)
      try {
        setGh(await api.github(refresh))
        if (refresh) fx.sound('tap')
      } catch (e) {
        notify((e as Error).message, 'err')
      } finally {
        setBusy(false)
      }
    },
    [fx, notify],
  )
  useEffect(() => {
    void load()
  }, [load])

  const prs = gh?.prs ?? []
  const stuck = prs.filter((p) => p.review === 'CHANGES_REQUESTED' || p.checks === 'FAILURE').length
  return (
    <div className="gh">
      <header className="screen-head">
        <h1>GitHub</h1>
        <div className="mod-tools">
          {gh?.login && <span className="muted small">@{gh.login}</span>}
          <button className="btn tiny ghost" disabled={busy} onClick={() => load(true)}>
            {busy ? <span className="blink">checking…</span> : '↻ refresh'}
          </button>
        </div>
      </header>
      {gh?.error ? (
        <Win title="gh.cfg" className="empty-win">
          <p>{gh.error}</p>
          <p className="muted small">tamadesk uses your own GitHub CLI login, so no token is stored here.</p>
        </Win>
      ) : (
        <>
          <div className="mail-ask">
            <span className="muted">Ask {buddy.name}:</span>
            {[
              stuck ? `Which of my ${stuck} stuck PRs should I fix first, and what's blocking each?` : 'Summarize where my open PRs stand',
              'Remind me to follow up on PRs with no review by Friday',
              'Find good first issues in projects like the ones I contribute to',
              'Which of my repos should I revive, finish or archive?',
            ].map((t) => (
              <motion.button key={t} className="chip" whileTap={{ scale: 0.94 }} onClick={() => askBolt(t)}>
                {t}
              </motion.button>
            ))}
          </div>
          {!gh ? (
            <p className="loading">asking GitHub…</p>
          ) : (
          <div className="gh-grid">
            <Win title={`my_prs (${prs.length})`} className="gh-prs">
              <Rows rows={prs} empty="No open pull requests. Ship something!" />
            </Win>
            <Win title={`assigned (${gh?.issues?.length ?? 0})`}>
              <Rows rows={gh?.issues ?? []} empty="No issues assigned to you." />
            </Win>
            <Win title={`to_review (${gh?.reviews?.length ?? 0})`}>
              <Rows rows={gh?.reviews ?? []} empty="Nobody is waiting on your review." />
            </Win>
            <Win title={`shipped_this_week (${gh?.shipped?.length ?? 0})`}>
              <Rows rows={gh?.shipped ?? []} empty="Nothing merged in the last 7 days." />
            </Win>
            <Win title="your_repos" className="gh-repos">
              {gh?.repos?.length ? (
                <ul className="gh-rows">
                  {gh.repos.map((r) => (
                    <li key={r.repo} className={stale(r.pushed_at) ? 'stale' : ''}>
                      <a href={r.url} target="_blank" rel="noreferrer" className="gh-title">
                        {r.repo.split('/')[1]}
                      </a>
                      <div className="gh-meta">
                        <span className="muted small">
                          pushed {ago(r.pushed_at)} · ★ {r.stars}
                          {r.open_issues ? ` · ${r.open_issues} open issues` : ''}
                        </span>
                        {stale(r.pushed_at) && <span className="gh-badge warn">gathering dust</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">No repos of your own yet.</p>
              )}
            </Win>
          </div>
          )}
        </>
      )}
    </div>
  )
}
