# tamadesk

An open-source (MIT) personal assistant with a pixel companion: ask it to do things (it runs on the user's own Claude Code with tamadesk's tools), plus tabs that watch the web, Mail, todos, reminders, a daily log and an evening recap, all gamified. `docs/plan.md` is the source of truth for scope, roadmap, and the art, motion and sound direction.

## Layout
- `src/tamadesk/`: Python package (FastAPI, Typer CLI).
  - `core/` holds config (platformdirs data folder), db, `clock` (every UTC/local conversion), `net` (the one HTTP helper) and usage.
  - `brain/` holds pluggable model backends.
  - `life/` holds the user's day: capture, todos, focus, mail, calendar, memory, the profile card, the game.
  - `modules/` holds tabs: specs, sources, ranking, fit, screening, YouTube.
  - `assistant/` holds Bolt: its prompt and runner, and its tools (an MCP server).
  - `api/` holds the routes and the scheduler.
- `frontend/`: Vite + React + TS. `npm run build` goes to `frontend/dist`, which the backend serves at `/`.
- User data lives in `~/.local/share/tamadesk` (or `TAMADESK_HOME`), never in the repo. Long-term memory is markdown in its `memory/` folder (source of truth); SQLite only indexes it.

## Commands
- `uv run tamadesk serve [--reload]`: runs on 127.0.0.1:6206
- `uv run tamadesk doctor`
- `tamadesk export` / `import` (move a desk), `tamadesk install-service` (start at login)
- `uv run pytest`, `uv run ruff check .`
- `cd frontend && npm run dev` (proxies /api to 6206), `npm run build`, `npx oxlint src`

## Rules
- **Public repo: no personal data.** No real names, emails, resumes, profile files or sample writing from any real person in code, tests, fixtures or docs.
- **Brains:** Claude only via the user's own `claude` CLI login (never `--bare`, never an API key in code, strip `ANTHROPIC_API_KEY`, always `--tools ""`), or Ollama. An API-key brain is roadmap-only and must use the OS keychain. Every `claude -p` runs lean (`brain/claude_code.LEAN`): our own `--system-prompt`, `--strict-mcp-config`, no skills and no user settings. This loads none of the user's connectors, skills or hooks, and halves Bolt's tokens.
- **Schema changes:** append to `MIGRATIONS` in `core/db.py`. Never edit an applied migration.
- **XP only for real progress.** Every XP change is an `events` row, and undo must reverse it.
- **Nothing is sent anywhere** (mail, network) without an explicit user click.
- **Sources:** only free, login-free channels: official public APIs, RSS/Atom (news topics: the `news` source, Bing News RSS, links unwrapped to the publisher), and agent-reach's login-free channels (Exa via mcporter, Jina Reader). Never cookie/login channels (LinkedIn, X, Reddit, Instagram) or scraping-hostile sites.
- **Know the user, don't invent them:** the profile card (`life/profile.py`, `memory/profile.md`) is the one page every ask reads. It's written from the resume in the background (light). Links come by regex, and numbers must appear in the resume. The user's own words win, and `remember` notes land in it.
- **On topic before ranking:** a tab about a person, company or story sets `match` (`engine.on_topic`); off-topic items are dropped, and `tools._broken` rejects sources that are mostly off topic when a tab is created.
- **Fit before ranking:** searches for things with a level (jobs) declare `fit` (`modules/fit.py`); a poor match is dropped, not ranked low.
- **Job search learns, then verifies** (`modules/postings.py`, `sources.job_search`, `engine.run`): several narrow posting-shaped queries, originals only (`postings.original`: company job systems or careers pages, never boards), the company job boards they came from are watched (`boards` table), postings are checked open (`verify`) and fresh (`max_age_days`), and companies are screened against the user's `avoid`/`wants` (`modules/screen.py`: rules first, one light batched call per new company, cached). Measure retrieval changes against live searches before trusting them.
- **Free first:** everyday actions are capture shortcuts (`life/capture.py`: todo, every…, done, move, waiting on, meeting, focus, next), answered on the desk with no AI. Keep `VERBS` and the Ask box's `FREE` in sync (a test checks it).
- **Game feel, not game chores:** banners, chains and sounds celebrate real progress; no unlockables or checklists to make people try features (the Ask box's example chips suggest untried shortcuts instead, `life/tips.py`). XP only for real progress, and stopping a focus session early pays nothing.
- **Whatever Bolt can create, it can remove:** pair every create tool with a remove/cancel one (`drop_todo`, `cancel_reminder`, …); never mark something done to make it disappear. A repeating todo is one series with at most one open copy.
- **The user's day, not the calendar's:** a day runs from their wake time to their bedtime (`settings.day.wake`/`bed`, asked in New Game), the recap is written at bedtime, and the day turns over halfway through their night. Use `clock.today()`, `clock.day_bounds()` and `clock.day_of()`; never take "today" from the calendar date.
- **Notifications go through `life/notify.ping`** with a kind; only urgent kinds ring during quiet hours or focus.
- **Only you:** suggestions on mail and drafts (`life/suggest.py`) are regex rules first; Claude only on the user's click, `light=True`. XP only when the data proves it happened.
- **Assistant first:** the Ask box (`assistant/`) is the main way to use the app; buttons and the template gallery are the manual fallback. New capabilities should be a tool in `assistant/tools.py` (reusing existing code) before they're a page.
- **Tokens and compute:** every Claude call is capped (`--max-budget-usd`), recorded in `usage`, and checked against the daily budget. Fetching, ranking and rendering cost zero tokens. Background jobs use `light=True`. Keep jobs on the 2-thread scheduler and prune data.
- **Assistant safety:** only `--tools WebFetch` plus the tamadesk and allowed agent-reach MCP servers. Never a shell or file-edit tool. Tools that change things outside the desk (sending mail) don't exist: Bolt drafts, the user sends.
- **Think in the user's next step:** every template carries 1-3 `workflows` (what you'd do with kept items), and items carry the data their next action needs (`apply_url`, published `email`). Sources go to the original (company pages, ATS boards), never aggregators or login walls (`sources.WALLED`).
- **Journeys, not features:** see `docs/journeys.md`. A draft links its item (`item_id`), follow-ups and replies link their thread (`parent_id`), stages move through `life/pipeline.set_stage` (forward-only unless manual), anything waiting on the user surfaces in `life/upnext.py`, and Today (`life/today.py`) is the one ordered list every page drills down from. Inbox reading is read-only and stores only mail matched to something the user started; the one exception is a calendar invite addressed to the user, of which only the event fields are kept (`life/calendar.py`).
- **Modules, not custom pages:** a new kind of tab is a template YAML plus, if needed, one `@source` function. New views are rare and must work for any module: there are two layouts, `feed` (ranked by taste) and `steps` (a path in order: items carry `data.step` and `data.topic`, like the roadmap).
- **Learning is a path, not a list:** "videos to learn X" or a syllabus becomes a `steps` tab with a `roadmap` source (`modules/youtube.py`: yt-dlp, no login, zero tokens). Video cards carry `thumb`, `duration` and `views`, and descriptions go through `youtube.blurb` (no promo).
- **DRY:** one HTTP helper (`core/net.py`), one item card plus action hook (`ItemCard.tsx`), and one template card for the gallery and New Game.
- **Motion and sound:** follow the tables in `docs/plan.md`. Respect reduced motion and the mute toggle.
- **Style:** match the surrounding code, keep it small and typed, and add tests for state logic. A short docstring on anything whose behavior isn't obvious from its name; shared helpers live in one place (`core/clock.py` for time, `pad2`/`localMinute` in `api.ts`, the `conn` fixture in `tests/conftest.py`).
