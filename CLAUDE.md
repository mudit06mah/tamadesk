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
- `uv run tamadesk serve [--reload]`: runs on 127.0.0.1:7778
- `uv run tamadesk doctor`
- `uv run pytest`, `uv run ruff check .`
- `cd frontend && npm run dev` (proxies /api to 7778), `npm run build`, `npx oxlint src`

## Rules
- **Public repo: no personal data.** No real names, emails, resumes, profile files or sample writing from any real person in code, tests, fixtures or docs.
- **Brains:** Claude only via the user's own `claude` CLI login (never `--bare`, never an API key in code, strip `ANTHROPIC_API_KEY`, always `--tools ""`), or Ollama. An API-key brain is roadmap-only and must use the OS keychain.
- **Schema changes:** append to `MIGRATIONS` in `core/db.py`. Never edit an applied migration.
- **XP only for real progress.** Every XP change is an `events` row, and undo must reverse it.
- **Nothing is sent anywhere** (mail, network) without an explicit user click.
- **Motion and sound:** follow the tables in `docs/plan.md`. Respect reduced motion and the mute toggle.
- **Style:** match the surrounding code, keep it small and typed, and add tests for state logic.
