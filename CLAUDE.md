# tamadesk

An open-source (MIT) desk companion: daily log, todos, reminders, drafting in the user's own voice, and an evening recap, all gamified with a pixel companion. `docs/plan.md` is the source of truth for scope, roadmap, and the art, motion and sound direction.

## Layout
- `src/tamadesk/`: Python package (FastAPI, Typer CLI).
  - `core/` holds config (platformdirs data folder) and db.
  - `brain/` holds pluggable model backends.
  - `life/` holds capture, game, onboarding and writer.
  - `api/` holds the routes and the scheduler.
- `frontend/`: Vite + React + TS. `npm run build` goes to `frontend/dist`, which the backend serves at `/`.
- User data lives in `~/.local/share/tamadesk` (or `TAMADESK_HOME`), never in the repo.

## Commands
- `uv run tamadesk serve [--reload]`: runs on 127.0.0.1:6206
- `uv run tamadesk doctor`
- `uv run pytest`, `uv run ruff check .`
- `cd frontend && npm run dev` (proxies /api to 6206), `npm run build`, `npx oxlint src`

## Rules
- **Public repo: no personal data.** No real names, emails, resumes, profile files or sample writing from any real person in code, tests, fixtures or docs.
- **Brains:** Claude only via the user's own `claude` CLI login (never `--bare`, never an API key in code, strip `ANTHROPIC_API_KEY`, always `--tools ""`), or Ollama. An API-key brain is roadmap-only and must use the OS keychain.
- **Schema changes:** append to `MIGRATIONS` in `core/db.py`. Never edit an applied migration.
- **XP only for real progress.** Every XP change is an `events` row, and undo must reverse it.
- **Nothing is sent anywhere** (mail, network) without an explicit user click.
- **Sources:** only free, login-free channels: official public APIs, RSS/Atom, and agent-reach's login-free channels (Exa via mcporter, Jina Reader). Never cookie/login channels (LinkedIn, X, Reddit, Instagram) or scraping-hostile sites.
- **Tokens and compute:** fetching, ranking and rendering cost zero tokens. Brain calls are short text only, on demand, using `light=True` (haiku) unless the user is drafting. Keep jobs on the 2-thread scheduler and prune data.
- **Modules, not custom pages:** a new kind of tab is a template YAML plus, if needed, one `@source` function. New views are rare and must work for any module.
- **DRY:** one HTTP helper (`core/net.py`), one item card plus action hook (`ItemCard.tsx`), and one template card for the gallery and New Game.
- **Motion and sound:** follow the tables in `docs/plan.md`. Respect reduced motion and the mute toggle.
- **Style:** match the surrounding code, keep it small and typed, and add tests for state logic.
